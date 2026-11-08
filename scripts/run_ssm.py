import subprocess
import json
import time
import sys

def run_remote_command(commands, wait_seconds=5):
    region = 'us-east-2'
    instance_id = 'i-004830098afc09efb'
    
    if isinstance(commands, str):
        commands = [commands]
        
    res = subprocess.run([
        'aws', 'ssm', 'send-command',
        '--instance-ids', instance_id,
        '--document-name', 'AWS-RunShellScript',
        '--parameters', json.dumps({'commands': commands}),
        '--region', region,
        '--query', 'Command.CommandId',
        '--output', 'text'
    ], capture_output=True, text=True, encoding='utf-8', errors='replace')
    
    cmd_id = res.stdout.strip()
    if not cmd_id:
        print("Failed to send command:", res.stderr)
        return None
        
    print(f"Command ID: {cmd_id}")
    
    # Poll until command finishes or timeouts
    for _ in range(wait_seconds * 2):
        time.sleep(1)
        inv = subprocess.run([
            'aws', 'ssm', 'get-command-invocation',
            '--command-id', cmd_id,
            '--instance-id', instance_id,
            '--region', region,
            '--query', '{Status:Status,Output:StandardOutputContent,Error:StandardErrorContent}',
            '--output', 'json'
        ], capture_output=True, text=True, encoding='utf-8', errors='replace')
        
        try:
            data = json.loads(inv.stdout)
            status = data.get('Status')
            if status in ['Success', 'Failed', 'Cancelled', 'TimedOut']:
                print(f"Status: {status}")
                print("--- STDOUT ---")
                print(data.get('Output'))
                if data.get('Error'):
                    print("--- STDERR ---")
                    print(data.get('Error'))
                return data
        except Exception as e:
            pass
            
    print("Timed out waiting for command execution")
    return None

if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'echo Hello from SSM'
    run_remote_command(cmd, wait_seconds=15)
