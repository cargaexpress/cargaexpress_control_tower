import subprocess
import json
import time

region = "us-east-2"
instance_id = "i-0ab95d8c9ecd34970"

# Read local migrate_and_populate_gold.py
with open("scripts/migrate_and_populate_gold.py", "r", encoding="utf-8") as f:
    script_content = f.read()

bash_commands = f"""cat << 'EOF' > /tmp/build/scripts/migrate_and_populate_gold.py
{script_content}
EOF

docker run --rm -u root \\
  -v /tmp/build:/app_code \\
  -w /app_code \\
  -e DATABASE_URL="postgresql+asyncpg://cargaexpress_admin:IYUMOYnnHnk%7B%24j%284S%5DQx%7BzLx@cargaexpress-staging-postgres.cnmosmsqi0oq.us-east-2.rds.amazonaws.com:5432/cargaexpress_staging" \\
  -e APP_ENV="staging" \\
  -e AWS_DEFAULT_REGION="us-east-2" \\
  cargaexpress-backend:staging \\
  bash -c "pip install --no-cache-dir --break-system-packages pandas pyarrow boto3 && PYTHONPATH=/root/.local/lib/python3.12/site-packages:/usr/local/lib/python3.12/site-packages:/app/.venv/lib/python3.12/site-packages:/app_code/backend python3 scripts/migrate_and_populate_gold.py"
"""

print("=== Sending Seeding & Analytical ETL SSM Command ===")
res = subprocess.run([
    "aws", "ssm", "send-command",
    "--instance-ids", instance_id,
    "--document-name", "AWS-RunShellScript",
    "--parameters", json.dumps({"commands": [bash_commands]}),
    "--region", region,
    "--query", "Command.CommandId",
    "--output", "text"
], capture_output=True, text=True, check=True)

cmd_id = res.stdout.strip()
print(f"[OK] SSM Command launched with ID: {cmd_id}")
print("Waiting for Seeding and Analytical ETL to finish...")

while True:
    time.sleep(8)
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
