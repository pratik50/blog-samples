# Backfill S3 Logs Into Parseable With Vector

This sample shows how to ingest raw log files from S3-compatible storage into Parseable with Vector.

It supports two local flows:

- **End-to-end ingest:** LocalStack S3 -> LocalStack SQS -> Vector -> Parseable
- **MinIO notification demo:** MinIO webhook -> bridge -> LocalStack SQS

For real AWS, the bridge is not required. AWS S3 can send object-created notifications directly to AWS SQS.

## Architecture

```text
New uploads:
S3 object created -> SQS notification -> Vector aws_s3 source -> Parseable HTTP ingest

Existing objects:
Backfill script -> SQS notification -> Vector aws_s3 source -> Parseable HTTP ingest
```

## Prerequisites

- Docker and Docker Compose
- Python 3, only for the backfill script
- Parseable running on `http://localhost:8000`

Default Parseable values used by this sample:

```text
stream: s3_import
user: admin
password: admin
```

Override these in `.env` if your local Parseable setup is different.

## Files

```text
docker-compose.yml              local MinIO, LocalStack, Vector, bridge
vector.toml                     Vector aws_s3 source and Parseable HTTP sink
samples/app.ndjson              120 sample log events
bridge/bridge.py                local-only MinIO webhook to SQS adapter
scripts/backfill_s3_to_sqs.py   replay existing S3 objects by sending S3 event messages
```

## Start Services

```sh
cp .env.example .env
docker compose up -d minio localstack
docker compose --profile pipeline up -d bridge
```

Validate containers:

```sh
docker compose ps
curl http://localhost:8080/health
```

Useful local endpoints:

```text
MinIO S3 API:       http://localhost:9000
MinIO console:      http://localhost:9001
LocalStack edge:    http://localhost:4566
Bridge health:      http://localhost:8080/health
```

## Create Queue

```sh
docker compose exec -T localstack awslocal sqs create-queue \
  --queue-name s3-events
```

## Recommended Local End-To-End Test

Use LocalStack for both S3 and SQS. This avoids endpoint mismatch issues and gives Vector one AWS-compatible endpoint for object reads and queue polling.

Create the bucket:

```sh
docker compose exec -T localstack awslocal s3 mb s3://raw-logs
```

Copy the sample file into the LocalStack container:

```sh
docker cp samples/app.ndjson vector-s3-localstack:/tmp/app.ndjson
```

Upload the sample file to LocalStack S3:

```sh
docker compose exec -T localstack awslocal s3 cp \
  /tmp/app.ndjson s3://raw-logs/logs/app.ndjson
```

Send an S3-style notification to SQS:

```sh
docker compose exec -T localstack awslocal sqs send-message \
  --queue-url http://sqs.us-east-1.localhost.localstack.cloud:4566/000000000000/s3-events \
  --message-body '{
    "Records": [{
      "eventVersion": "2.0",
      "eventSource": "aws:s3",
      "awsRegion": "us-east-1",
      "eventTime": "2026-06-09T10:00:00Z",
      "eventName": "ObjectCreated:Put",
      "s3": {
        "s3SchemaVersion": "1.0",
        "bucket": { "name": "raw-logs" },
        "object": { "key": "logs/app.ndjson", "size": 1 }
      }
    }]
  }'
```

Start Vector:

```sh
docker compose --profile pipeline up -d vector
```

Watch Vector:

```sh
docker compose logs --no-color --tail=80 vector
```

Open Parseable and query the `s3_import` stream:

```sql
select level, service, host, msg, duration_ms
from s3_import
order by p_timestamp desc
limit 20;
```

Count imported rows:

```sql
select count(*) as rows
from s3_import;
```

With the provided sample file, one successful import should add 120 events.

## Backfill Existing Objects

S3 notifications fire for new object events. Existing objects already present in a bucket do not automatically generate SQS messages.

Use the backfill script to list existing objects and send S3-style notifications to SQS:

```sh
python3 -m pip install -r scripts/requirements.txt
```

Dry run:

```sh
AWS_ACCESS_KEY_ID=minioadmin \
AWS_SECRET_ACCESS_KEY=minioadmin \
python3 scripts/backfill_s3_to_sqs.py \
  --bucket raw-logs \
  --prefix logs/ \
  --queue-url http://localhost:4566/000000000000/s3-events \
  --region us-east-1 \
  --s3-endpoint-url http://localhost:4566 \
  --sqs-endpoint-url http://localhost:4566 \
  --limit 5 \
  --dry-run
```

Replay existing objects:

```sh
AWS_ACCESS_KEY_ID=minioadmin \
AWS_SECRET_ACCESS_KEY=minioadmin \
python3 scripts/backfill_s3_to_sqs.py \
  --bucket raw-logs \
  --prefix logs/ \
  --queue-url http://localhost:4566/000000000000/s3-events \
  --region us-east-1 \
  --s3-endpoint-url http://localhost:4566 \
  --sqs-endpoint-url http://localhost:4566 \
  --limit 5
```

If Vector is running, it will poll the replayed SQS messages, fetch the existing object, and send the log events to Parseable.

For real AWS, remove the local endpoint flags and use the real queue URL:

```sh
python3 scripts/backfill_s3_to_sqs.py \
  --bucket customer-logs \
  --prefix raw/2024/ \
  --queue-url https://sqs.us-east-1.amazonaws.com/123456789012/customer-log-events \
  --region us-east-1 \
  --dry-run
```

## Optional MinIO Notification Demo

This part proves MinIO can emit webhook notifications locally. It is useful for understanding the MinIO path, but it is not required for the recommended LocalStack S3/SQS end-to-end test.

Create a MinIO bucket:

```sh
docker run --rm --network vector-s3-pipeline \
  -e MC_HOST_local=http://minioadmin:minioadmin@minio:9000 \
  minio/mc \
  mb --ignore-existing local/raw-logs
```

Connect MinIO events to the bridge webhook:

```sh
docker run --rm --network vector-s3-pipeline \
  -e MC_HOST_local=http://minioadmin:minioadmin@minio:9000 \
  minio/mc \
  event add --ignore-existing --event put \
  local/raw-logs arn:minio:sqs::primary:webhook
```

Upload the sample file:

```sh
docker run --rm --network vector-s3-pipeline \
  -e MC_HOST_local=http://minioadmin:minioadmin@minio:9000 \
  -v "$PWD/samples:/samples:ro" \
  minio/mc cp /samples/app.ndjson local/raw-logs/logs/app.ndjson
```

Check bridge logs:

```sh
docker compose logs --no-color --tail=40 bridge
```

Check SQS:

```sh
docker compose exec -T localstack awslocal sqs receive-message \
  --queue-url http://sqs.us-east-1.localhost.localstack.cloud:4566/000000000000/s3-events \
  --max-number-of-messages 1 \
  --visibility-timeout 0
```

## Cleanup

```sh
docker compose --profile pipeline down -v
```

## Notes

- The bridge is local-only. Production AWS uses S3 -> SQS directly.
- The backfill script sends notifications; it does not download or parse object contents.
- Replaying the same object more than once can create duplicate events in Parseable.
- `vector.toml` deletes SQS messages after Vector processes them successfully.
