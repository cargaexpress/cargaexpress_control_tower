import subprocess
import json
import time

region = 'us-east-2'
instance_id = 'i-004830098afc09efb'

script = """
cat << 'EOF' > /tmp/build/migrate.sh
#!/bin/bash
set -e
cd /tmp/build

echo "=== 1. Building Docker image ==="
docker build -t cargaexpress-backend:staging -f backend/Dockerfile .

echo "=== 2. Running Alembic Migrations ==="
docker run --rm \
  -e DATABASE_URL="postgresql+asyncpg://cargaexpress_admin:edK%25ER08hzu9q%23%5DPZMlQNw%7Bv@cargaexpress-staging-postgres.cnmosmsqi0oq.us-east-2.rds.amazonaws.com:5432/cargaexpress_staging" \
  -e APP_ENV="staging" \
  cargaexpress-backend:staging \
  alembic upgrade head

echo "=== 3. Logging into ECR ==="
aws ecr get-login-password --region us-east-2 | docker login --username AWS --password-stdin 326204936524.dkr.ecr.us-east-2.amazonaws.com

echo "=== 4. Tagging and Pushing Images ==="
docker tag cargaexpress-backend:staging 326204936524.dkr.ecr.us-east-2.amazonaws.com/cargaexpress-backend:staging
docker tag cargaexpress-backend:staging 326204936524.dkr.ecr.us-east-2.amazonaws.com/cargaexpress-worker:staging
docker tag cargaexpress-backend:staging 326204936524.dkr.ecr.us-east-2.amazonaws.com/cargaexpress-backend:latest
docker tag cargaexpress-backend:staging 326204936524.dkr.ecr.us-east-2.amazonaws.com/cargaexpress-worker:latest

docker push 326204936524.dkr.ecr.us-east-2.amazonaws.com/cargaexpress-backend:staging
docker push 326204936524.dkr.ecr.us-east-2.amazonaws.com/cargaexpress-worker:staging

echo "=== 5. Verification: Check Tables ==="
docker run --rm -e PGPASSWORD='edK%ER08hzu9q#]PZMlQNw{v' postgres:16-alpine psql -h cargaexpress-staging-postgres.cnmosmsqi0oq.us-east-2.rds.amazonaws.com -U cargaexpress_admin -d cargaexpress_staging -c '\dt'

EOF
chmod +x /tmp/build/migrate.sh
/tmp/build/migrate.sh > /tmp/migrate.log 2>&1 &
echo "MIGRATION_JOB_STARTED_PID=$!"
"""

res = subprocess.run([
    'aws', 'ssm', 'send-command',
    '--instance-ids', instance_id,
    '--document-name', 'AWS-RunShellScript',
    '--parameters', json.dumps({'commands': [script]}),
    '--region', region,
    '--query', 'Command.CommandId',
    '--output', 'text'
], capture_output=True, text=True)

cmd_id = res.stdout.strip()
print('Started Command ID:', cmd_id)
