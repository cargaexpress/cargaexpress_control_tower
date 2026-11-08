import subprocess
import json
import time

region = 'us-east-2'
instance_id = 'i-004830098afc09efb'

# Script to patch env.py, build and push to ECR
script = """
cat << 'EOF' > /tmp/build/backend/alembic/env.py
import asyncio
from logging.config import fileConfig

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

import app.models  # noqa: F401
from alembic import context
from app.config import settings
from app.database import Base

config = context.config
config.set_main_option("sqlalchemy.url", settings.database_url.replace("%", "%%"))

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

def run_migrations_offline() -> None:
    url = settings.database_url
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()

def do_run_migrations(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()

async def run_migrations_online() -> None:
    connectable: AsyncEngine = create_async_engine(settings.database_url)
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()

if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
EOF

cd /tmp/build
echo "=== Building Docker image ==="
docker build -t 326204936524.dkr.ecr.us-east-2.amazonaws.com/cargaexpress-backend:staging -f backend/Dockerfile .

echo "=== Tagging worker image ==="
docker tag 326204936524.dkr.ecr.us-east-2.amazonaws.com/cargaexpress-backend:staging 326204936524.dkr.ecr.us-east-2.amazonaws.com/cargaexpress-worker:staging

echo "=== Logging into ECR ==="
aws ecr get-login-password --region us-east-2 | docker login --username AWS --password-stdin 326204936524.dkr.ecr.us-east-2.amazonaws.com

echo "=== Pushing to ECR ==="
docker push 326204936524.dkr.ecr.us-east-2.amazonaws.com/cargaexpress-backend:staging
docker push 326204936524.dkr.ecr.us-east-2.amazonaws.com/cargaexpress-worker:staging

echo "=== PUSH_COMPLETE ==="
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
print('Command ID:', cmd_id)
