import subprocess
import json
import time

region = 'us-east-2'
instance_id = 'i-004830098afc09efb'

# Check socket to RDS 5432
commands = [
    "python3 -c \"import socket; s = socket.create_connection(('cargaexpress-staging-postgres.cnmosmsqi0oq.us-east-2.rds.amazonaws.com', 5432), 5); print('RDS_PORT_5432_CONNECTED')\""
]

res = subprocess.run([
    'aws', 'ssm', 'send-command',
    '--instance-ids', instance_id,
    '--document-name', 'AWS-RunShellScript',
    '--parameters', json.dumps({'commands': commands}),
    '--region', region,
    '--query', 'Command.CommandId',
    '--output', 'text'
], capture_output=True, text=True)

cmd_id = res.stdout.strip()
print('Command ID:', cmd_id)

time.sleep(3)

inv = subprocess.run([
    'aws', 'ssm', 'get-command-invocation',
    '--command-id', cmd_id,
    '--instance-id', instance_id,
    '--region', region,
    '--query', '{Status:Status,Output:StandardOutputContent,Error:StandardErrorContent}',
    '--output', 'json'
], capture_output=True, text=True)

print('Invocation result:', inv.stdout)
