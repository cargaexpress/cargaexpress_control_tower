import subprocess
import json
import time

region = 'us-east-2'
instance_id = 'i-004830098afc09efb'

# Run psql inside docker or python script on EC2
script = """
cat << 'EOF' > /tmp/check_db.py
import urllib.parse
try:
    import psycopg2
except ImportError:
    import subprocess, sys
    subprocess.check_call([sys.executable, "-m", "pip", "install", "psycopg2-binary"])
    import psycopg2

conn = psycopg2.connect('postgresql://cargaexpress_admin:edK%25ER08hzu9q%23%5DPZMlQNw%7Bv@cargaexpress-staging-postgres.cnmosmsqi0oq.us-east-2.rds.amazonaws.com:5432/cargaexpress_staging')
cur = conn.cursor()
cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' ORDER BY table_name;")
rows = cur.fetchall()
print(f"TABLES_FOUND: {len(rows)}")
for r in rows:
    print(f"  - {r[0]}")
EOF
python3 /tmp/check_db.py
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

time.sleep(6)

inv = subprocess.run([
    'aws', 'ssm', 'get-command-invocation',
    '--command-id', cmd_id,
    '--instance-id', instance_id,
    '--region', region,
    '--query', '{Status:Status,Output:StandardOutputContent,Error:StandardErrorContent}',
    '--output', 'json'
], capture_output=True, text=True, encoding='utf-8', errors='replace')

print(inv.stdout)
