import json
import logging
import os
import time
from copy import deepcopy
from urllib.parse import unquote_plus

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError, EndpointConnectionError
from flask import Flask, jsonify, request


logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("minio-sqs-bridge")

AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
LOCALSTACK_ENDPOINT = os.getenv("LOCALSTACK_ENDPOINT", "http://localstack:4566")
SQS_QUEUE_NAME = os.getenv("SQS_QUEUE_NAME", "s3-events")

app = Flask(__name__)
sqs_client = boto3.client(
    "sqs",
    region_name=AWS_REGION,
    endpoint_url=LOCALSTACK_ENDPOINT,
    config=Config(retries={"max_attempts": 3, "mode": "standard"}),
)
queue_url = None


def get_queue_url():
    global queue_url
    if queue_url:
        return queue_url

    for attempt in range(1, 6):
        try:
            queue_url = sqs_client.get_queue_url(QueueName=SQS_QUEUE_NAME)["QueueUrl"]
            logger.info("resolved queue %s at %s", SQS_QUEUE_NAME, queue_url)
            return queue_url
        except ClientError as error:
            code = error.response.get("Error", {}).get("Code", "")
            if code in {"AWS.SimpleQueueService.NonExistentQueue", "QueueDoesNotExist"}:
                queue_url = sqs_client.create_queue(QueueName=SQS_QUEUE_NAME)["QueueUrl"]
                logger.info("created queue %s at %s", SQS_QUEUE_NAME, queue_url)
                return queue_url
            logger.warning("queue lookup failed on attempt %s: %s", attempt, error)
        except EndpointConnectionError as error:
            logger.warning("localstack not ready on attempt %s: %s", attempt, error)

        time.sleep(1)

    raise RuntimeError(f"could not resolve or create SQS queue {SQS_QUEUE_NAME}")


def normalize_record(record):
    normalized = deepcopy(record)
    normalized["eventSource"] = "aws:s3"
    normalized["eventName"] = "ObjectCreated:Put"
    normalized["awsRegion"] = normalized.get("awsRegion") or AWS_REGION

    s3 = normalized.get("s3", {})
    bucket = s3.get("bucket", {}).get("name")
    key = s3.get("object", {}).get("key")
    if key:
        s3["object"]["key"] = unquote_plus(key)

    if not bucket or not key:
        raise ValueError("record missing s3.bucket.name or s3.object.key")

    return normalized


def publish_records(records):
    normalized_records = [normalize_record(record) for record in records]
    message_body = json.dumps({"Records": normalized_records}, separators=(",", ":"))
    response = sqs_client.send_message(
        QueueUrl=get_queue_url(),
        MessageBody=message_body,
    )

    for record in normalized_records:
        bucket = record["s3"]["bucket"]["name"]
        key = record["s3"]["object"]["key"]
        logger.info("sent SQS notification for s3://%s/%s", bucket, key)

    return response["MessageId"], len(normalized_records)


@app.get("/health")
def health():
    return jsonify({"status": "ok"})


@app.post("/")
@app.post("/minio-event")
def minio_event():
    payload = request.get_json(silent=True)
    if not payload:
        return jsonify({"error": "expected JSON body"}), 400

    records = payload.get("Records")
    if not isinstance(records, list) or not records:
        return jsonify({"error": "expected non-empty Records array"}), 400

    try:
        message_id, record_count = publish_records(records)
    except Exception as error:
        logger.exception("failed to publish MinIO event")
        return jsonify({"error": str(error)}), 500

    return jsonify({"message_id": message_id, "records": record_count})


if __name__ == "__main__":
    logger.info("starting bridge on :8080")
    logger.info("localstack endpoint: %s", LOCALSTACK_ENDPOINT)
    logger.info("sqs queue name: %s", SQS_QUEUE_NAME)
    app.run(host="0.0.0.0", port=8080)
