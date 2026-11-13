import subprocess
import json
import time
import urllib.parse

region = "us-east-2"
instance_id = "i-0ab95d8c9ecd34970"

db_user = "cargaexpress_admin"
db_raw_pass = "IYUMOYnnHnk{$j(4S]Qx{zLx"
db_enc_pass = urllib.parse.quote_plus(db_raw_pass)
db_host = "cargaexpress-staging-postgres.cnmosmsqi0oq.us-east-2.rds.amazonaws.com"
db_name = "cargaexpress_staging"
db_url = f"postgresql+asyncpg://{db_user}:{db_enc_pass}@{db_host}:5432/{db_name}"

rmq_user = "cargaexpress"
rmq_pass = "hcQogrFHcvXavGKtwXWUy003"
rmq_host = "10.1.10.54"
rmq_url = f"amqp://{rmq_user}:{rmq_pass}@{rmq_host}:5672/"

print("=== 1. Updating AWS Secrets Manager ===")
db_secret = {
    "username": db_user,
    "password": db_raw_pass,
    "engine": "postgres",
    "port": 5432,
    "database": db_name,
    "DATABASE_URL": db_url
}
subprocess.run([
    "aws", "secretsmanager", "put-secret-value",
    "--secret-id", "cargaexpress/staging/database",
    "--secret-string", json.dumps(db_secret),
    "--region", region
], check=True)
print("[OK] cargaexpress/staging/database updated.")

rmq_secret = {
    "username": rmq_user,
    "password": rmq_pass,
    "port": 5672,
    "RABBITMQ_URL": rmq_url
}
subprocess.run([
    "aws", "secretsmanager", "put-secret-value",
    "--secret-id", "cargaexpress/staging/rabbitmq",
    "--secret-string", json.dumps(rmq_secret),
    "--region", region
], check=True)
print("[OK] cargaexpress/staging/rabbitmq updated.")

print("\n=== 2. Preparing Build & Migration Script on EC2 ===")
bash_script = f"""#!/bin/bash
set -e
echo "=== STEP A: Setup build directory ==="
rm -rf /tmp/build
mkdir -p /tmp/build
cd /tmp/build

echo "=== STEP B: Download source bundle from S3 ==="
aws s3 cp s3://cargaexpress-datalake-staging-326204936524/landing/build_bundle.tar.gz .
tar -xzf build_bundle.tar.gz

echo "=== STEP C: Building Docker image ==="
docker build -t cargaexpress-backend:staging -f backend/Dockerfile .

echo "=== STEP D: Running Alembic Migrations on RDS ==="
docker run --rm \\
  -e DATABASE_URL="{db_url}" \\
  -e APP_ENV="staging" \\
  cargaexpress-backend:staging \\
  alembic upgrade head

echo "=== STEP E: ECR Login & Push ==="
aws ecr get-login-password --region us-east-2 | docker login --username AWS --password-stdin 326204936524.dkr.ecr.us-east-2.amazonaws.com

docker tag cargaexpress-backend:staging 326204936524.dkr.ecr.us-east-2.amazonaws.com/cargaexpress-backend:staging
docker tag cargaexpress-backend:staging 326204936524.dkr.ecr.us-east-2.amazonaws.com/cargaexpress-worker:staging
docker tag cargaexpress-backend:staging 326204936524.dkr.ecr.us-east-2.amazonaws.com/cargaexpress-backend:latest
docker tag cargaexpress-backend:staging 326204936524.dkr.ecr.us-east-2.amazonaws.com/cargaexpress-worker:latest

docker push 326204936524.dkr.ecr.us-east-2.amazonaws.com/cargaexpress-backend:staging
docker push 326204936524.dkr.ecr.us-east-2.amazonaws.com/cargaexpress-worker:staging

echo "=== STEP F: Verify Database Tables ==="
docker run --rm -e PGPASSWORD='{db_raw_pass}' postgres:16-alpine psql -h {db_host} -U {db_user} -d {db_name} -c '\\dt'

echo "=== BUILD_AND_MIGRATION_COMPLETE ==="
"""

res = subprocess.run([
    "aws", "ssm", "send-command",
    "--instance-ids", instance_id,
    "--document-name", "AWS-RunShellScript",
    "--parameters", json.dumps({"commands": [bash_script]}),
    "--region", region,
    "--query", "Command.CommandId",
    "--output", "text"
], capture_output=True, text=True, check=True)

cmd_id = res.stdout.strip()
print(f"[OK] SSM Command launched with ID: {cmd_id}")
print("Waiting for build, migration, and push to complete...")

while True:
    time.sleep(10)
    inv = subprocess.run([
        "aws", "ssm", "get-command-invocation",
        "--command-id", cmd_id,
        "--instance-id", instance_id,
        "--region", region,
        "--query", "{Status:Status,Output:StandardOutputContent,Error:StandardErrorContent}",
        "--output", "json"
    ], capture_output=True, text=True, encoding="utf-8", errors="replace")
    
    data = json.loads(inv.stdout)
    status = data.get("Status")
    print(f"Current SSM Status: {status}")
    
    if status in ["Success", "Failed", "Cancelled", "TimedOut"]:
        print("\n=== Command Output ===")
        print(data.get("Output", ""))
        if data.get("Error"):
            print("\n=== Command Error ===")
            print(data.get("Error", ""))
        break
