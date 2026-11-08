import os
import re

dag_files = [f for f in os.listdir('dags') if f.startswith('dag_') and f.endswith('.py')]
for df in dag_files:
    p = os.path.join('dags', df)
    print("=" * 70)
    print(f"ARCHIVO: dags/{df}")
    with open(p, encoding='utf-8') as f:
        content = f.read()
        
    sched = re.findall(r'schedule(?:_interval)?\s*=\s*([^\n,\)]+)', content)
    dag_id = re.findall(r'dag_id\s*=\s*[\'"]([^\'"]+)[\'"]', content)
    tasks = re.findall(r'@task[^\n]*\ndef\s+([a-zA-Z0-9_]+)', content)
    if not tasks:
        tasks = re.findall(r'task_id\s*=\s*[\'"]([^\'"]+)[\'"]', content)
        
    print(f"DAG ID:       {dag_id[0] if dag_id else 'Derived'}")
    print(f"Periodicidad: {sched[0].strip() if sched else 'No definida / None'}")
    print(f"Tareas:       {tasks}")
    
    # Check retries and catchup
    catchup = re.findall(r'catchup\s*=\s*([^\n,\)]+)', content)
    if catchup:
        print(f"Catchup:      {catchup[0].strip()}")
