import os

path_airflow = 'infrastructure/terraform/modules/airflow/main.tf'
with open(path_airflow, 'r', encoding='utf-8') as f:
    text = f.read()

# Replace Airflow task sizes
text = text.replace('cpu                      = "1024" # 1 vCPU', 'cpu                      = "256"  # 0.25 vCPU')
text = text.replace('memory                   = "2048" # 2 GB RAM', 'memory                   = "512"  # 512 MB RAM')

with open(path_airflow, 'w', encoding='utf-8') as f:
    f.write(text)

path_ecs = 'infrastructure/terraform/modules/ecs/main.tf'
with open(path_ecs, 'r', encoding='utf-8') as f:
    text = f.read()

# Replace ECS task sizes
text = text.replace('cpu                      = "512"  # 0.5 vCPU', 'cpu                      = "256"  # 0.25 vCPU')
text = text.replace('memory                   = "1024" # 1 GB RAM', 'memory                   = "512"  # 512 MB RAM')

with open(path_ecs, 'w', encoding='utf-8') as f:
    f.write(text)

print('Task sizes updated to 256 CPU and 512 Memory successfully!')
