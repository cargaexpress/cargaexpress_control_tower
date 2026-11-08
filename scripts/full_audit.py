import subprocess
import json

def run_json(cmd):
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return json.loads(res.stdout)
    except Exception as e:
        return {"error": str(e), "stderr": getattr(e, "stderr", None)}

print("================================================================================")
print("              CARGAEXPRESS STAGING - COMPREHENSIVE SYSTEM AUDIT                 ")
print("================================================================================")

# 1. IAM Roles Audit
print("\n[1] IAM ROLES & POLICIES AUDIT:")
roles_to_check = [
    "cargaexpress-staging-ecs-execution-role",
    "cargaexpress-staging-ecs-task-role",
    "cargaexpress-staging-rabbitmq-ec2-role",
    "cargaexpress-staging-github-actions-role"
]
for role in roles_to_check:
    print(f"\n* Role: {role}")
    attached = run_json(["aws", "iam", "list-attached-role-policies", "--role-name", role])
    inline = run_json(["aws", "iam", "list-role-policies", "--role-name", role])
    att_policies = [p["PolicyName"] for p in attached.get("AttachedPolicies", [])]
    inl_policies = inline.get("PolicyNames", [])
    print(f"  Attached Managed Policies: {att_policies}")
    print(f"  Inline Policies: {inl_policies}")

# 2. Secrets Manager Audit
print("\n[2] SECRETS MANAGER AUDIT:")
secrets = [
    "cargaexpress/staging/database",
    "cargaexpress/staging/rabbitmq",
    "cargaexpress/staging/airflow",
    "cargaexpress/staging/app_secrets"
]
for s in secrets:
    val = run_json(["aws", "secretsmanager", "get-secret-value", "--secret-id", s, "--region", "us-east-2"])
    if "error" in val:
        print(f"  [FAIL] {s}: {val['error']}")
    else:
        sec_dict = json.loads(val.get("SecretString", "{}"))
        masked_keys = list(sec_dict.keys())
        print(f"  [PASS] {s}: {len(masked_keys)} keys found -> {masked_keys}")

# 3. EC2 Bastion & SSM Status
print("\n[3] EC2 BASTION & SSM TUNNEL PERMISSIONS AUDIT:")
ssm_inst = run_json(["aws", "ssm", "describe-instance-information", "--region", "us-east-2"])
instances = ssm_inst.get("InstanceInformationList", [])
for inst in instances:
    print(f"  Instance ID: {inst.get('InstanceId')}")
    print(f"  Ping Status: {inst.get('PingStatus')}")
    print(f"  Agent Version: {inst.get('AgentVersion')}")
    print(f"  Platform: {inst.get('PlatformName')} {inst.get('PlatformVersion')}")

# Check RDS Security Group Ingress Rules
rds_sg = run_json(["aws", "ec2", "describe-security-groups", "--group-names", "cargaexpress-staging-rds-sg", "--region", "us-east-2"])
if "SecurityGroups" in rds_sg and rds_sg["SecurityGroups"]:
    sg = rds_sg["SecurityGroups"][0]
    print(f"\n* RDS Security Group ({sg['GroupId']}) Ingress Rules:")
    for rule in sg.get("IpPermissions", []):
        port = rule.get("FromPort")
        sg_pairs = [p.get("GroupId") for p in rule.get("UserIdGroupPairs", [])]
        cidrs = [c.get("CidrIp") for c in rule.get("IpRanges", [])]
        print(f"  - Port {port}: SGs={sg_pairs}, CIDRs={cidrs}")

# 4. Airflow & ECS Services Audit
print("\n[4] ECS SERVICES & AIRFLOW STATUS AUDIT:")
cluster_name = "cargaexpress-staging-cluster"
services_to_check = [
    "cargaexpress-staging-airflow-webserver-svc",
    "cargaexpress-staging-airflow-scheduler-svc",
    "cargaexpress-staging-airflow-worker-svc",
    "cargaexpress-staging-api-svc",
    "cargaexpress-staging-receiver-svc",
    "cargaexpress-staging-worker-svc"
]
svcs_data = run_json(["aws", "ecs", "describe-services", "--cluster", cluster_name, "--services"] + services_to_check + ["--region", "us-east-2"])
for svc in svcs_data.get("services", []):
    name = svc.get("serviceName")
    desired = svc.get("desiredCount")
    running = svc.get("runningCount")
    pending = svc.get("pendingCount")
    status = svc.get("status")
    print(f"\n* Service: {name}")
    print(f"  Status: {status} | Desired: {desired} | Running: {running} | Pending: {pending}")
    events = svc.get("events", [])
    if events:
        print(f"  Latest Event: {events[0].get('message')}")

# 5. Check Active ECS Tasks
print("\n[5] ACTIVE ECS TASKS IN CLUSTER:")
tasks = run_json(["aws", "ecs", "list-tasks", "--cluster", cluster_name, "--region", "us-east-2"])
task_arns = tasks.get("taskArns", [])
print(f"  Total running/pending tasks in cluster: {len(task_arns)}")
if task_arns:
    task_details = run_json(["aws", "ecs", "describe-tasks", "--cluster", cluster_name, "--tasks"] + task_arns[:10] + ["--region", "us-east-2"])
    for t in task_details.get("tasks", []):
        t_def = t.get("taskDefinitionArn").split("/")[-1]
        last_status = t.get("lastStatus")
        desired_status = t.get("desiredStatus")
        containers = [c.get("name") + ":" + c.get("lastStatus") for c in t.get("containers", [])]
        print(f"  - Task {t.get('taskArn').split('/')[-1]}: Def={t_def}, Status={last_status}/{desired_status}, Containers={containers}")

print("\n================================================================================")
print("                              AUDIT FINISHED                                    ")
print("================================================================================")
