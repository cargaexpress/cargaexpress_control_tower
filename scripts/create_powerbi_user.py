import subprocess
import json
import time

region = 'us-east-2'
instance_id = 'i-004830098afc09efb'

sql_content = """
DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'powerbi_user') THEN
    CREATE USER powerbi_user WITH PASSWORD 'PowerBI2026!';
  ELSE
    ALTER USER powerbi_user WITH PASSWORD 'PowerBI2026!';
  END IF;
END
$$;
GRANT CONNECT ON DATABASE cargaexpress_staging TO powerbi_user;
GRANT USAGE ON SCHEMA public TO powerbi_user;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO powerbi_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO powerbi_user;
"""

cmd = f"""
cat << 'EOF' > /tmp/create_user.sql
{sql_content}
EOF
docker run --rm -i -e PGPASSWORD='CargaExpress2026StagingAdmin!' postgres:16-alpine psql -h cargaexpress-staging-postgres.cnmosmsqi0oq.us-east-2.rds.amazonaws.com -U cargaexpress_admin -d cargaexpress_staging < /tmp/create_user.sql
"""

res = subprocess.run([
    'aws', 'ssm', 'send-command',
    '--instance-ids', instance_id,
    '--document-name', 'AWS-RunShellScript',
    '--parameters', json.dumps({'commands': [cmd]}),
    '--region', region,
    '--query', 'Command.CommandId',
    '--output', 'text'
], capture_output=True, text=True)

cmd_id = res.stdout.strip()
print('Command ID:', cmd_id)

time.sleep(5)

inv = subprocess.run([
    'aws', 'ssm', 'get-command-invocation',
    '--command-id', cmd_id,
    '--instance-id', instance_id,
    '--region', region,
    '--query', '{Status:Status,Output:StandardOutputContent,Error:StandardErrorContent}',
    '--output', 'json'
], capture_output=True, text=True, encoding='utf-8', errors='replace')

print(inv.stdout)
