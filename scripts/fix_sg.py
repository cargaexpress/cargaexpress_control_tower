import os

path = os.path.join('infrastructure', 'terraform', 'modules', 'networking', 'main.tf')
with open(path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

new_lines = []
skip = False
in_rabbitmq = False
for i, line in enumerate(lines):
    if 'resource "aws_security_group" "rabbitmq"' in line:
        in_rabbitmq = True
    elif 'resource "aws_security_group" "rds"' in line:
        in_rabbitmq = False

    if in_rabbitmq and 'PostgreSQL port 5432 from EC2 management host' in line:
        # We need to remove the ingress { ... } block around this
        # The block started at the preceding line (which is '  ingress {')
        if new_lines and 'ingress {' in new_lines[-1]:
            new_lines.pop()
        skip = True
        continue
    
    if skip:
        if '}' in line:
            skip = False
            continue
        else:
            continue
    new_lines.append(line)

with open(path, 'w', encoding='utf-8') as f:
    f.writelines(new_lines)

print("Successfully cleaned up rabbitmq security group.")
