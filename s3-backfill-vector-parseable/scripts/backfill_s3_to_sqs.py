#!/usr/bin/env python3
import argparse
import json
from datetime import datetime, timezone
from urllib.parse import quote

import boto3


def parse_args():
    parser = argparse.ArgumentParser(
        description="Replay existing S3 objects by sending S3 event messages to SQS."
    )
    parser.add_argument("--bucket", required=True, help="S3 bucket to list.")
    parser.add_argument("--queue-url", required=True, help="SQS queue URL to send events to.")
    parser.add_argument("--prefix", default="", help="Only list objects under this prefix.")
    parser.add_argument("--region", default="us-east-1", help="AWS region.")
    parser.add_argument("--s3-endpoint-url", help="Custom S3 endpoint, for LocalStack/MinIO.")
    parser.add_argument("--sqs-endpoint-url", help="Custom SQS endpoint, for LocalStack.")
    parser.add_argument("--limit", type=int, help="Maximum number of objects to replay.")
    parser.add_argument("--dry-run", action="store_true", help="Print events without sending them.")
    return parser.parse_args()


def s3_event(bucket, key, size, etag, region):
    event_time = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return {
        "Records": [
            {
                "eventVersion": "2.0",
                "eventSource": "aws:s3",
                "awsRegion": region,
                "eventTime": event_time,
                "eventName": "ObjectCreated:Put",
                "userIdentity": {"principalId": "backfill"},
                "requestParameters": {"sourceIPAddress": "backfill"},
                "responseElements": {
                    "x-amz-request-id": "backfill",
                    "x-amz-id-2": "backfill",
                },
                "s3": {
                    "s3SchemaVersion": "1.0",
                    "configurationId": "backfill",
                    "bucket": {
                        "name": bucket,
                        "ownerIdentity": {"principalId": "backfill"},
                        "arn": f"arn:aws:s3:::{bucket}",
                    },
                    "object": {
                        "key": quote(key, safe="/"),
                        "size": size,
                        "eTag": etag.strip('"') if etag else "",
                        "sequencer": "backfill",
                    },
                },
            }
        ]
    }


def iter_objects(s3_client, bucket, prefix):
    paginator = s3_client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if key.endswith("/"):
                continue
            yield key, obj.get("Size", 0), obj.get("ETag", "")


def main():
    args = parse_args()
    s3_client = boto3.client(
        "s3",
        region_name=args.region,
        endpoint_url=args.s3_endpoint_url,
    )
    sqs_client = boto3.client(
        "sqs",
        region_name=args.region,
        endpoint_url=args.sqs_endpoint_url,
    )

    sent = 0
    for key, size, etag in iter_objects(s3_client, args.bucket, args.prefix):
        event = s3_event(args.bucket, key, size, etag, args.region)
        body = json.dumps(event, separators=(",", ":"))

        if args.dry_run:
            print(body)
        else:
            sqs_client.send_message(QueueUrl=args.queue_url, MessageBody=body)
            print(f"sent s3://{args.bucket}/{key}")

        sent += 1
        if args.limit and sent >= args.limit:
            break

    print(f"objects_replayed={sent}")


if __name__ == "__main__":
    main()
