path = 'infrastructure/terraform/modules/networking/main.tf'
with open(path, 'r', encoding='utf-8') as f:
    text = f.read()

target = 'security_groups = [aws_security_group.airflow.id]\n  }'
new_block = 'security_groups = [aws_security_group.airflow.id]\n  }\n\n  ingress {\n    description     = "PostgreSQL port 5432 from EC2 management host"\n    from_port       = 5432\n    to_port         = 5432\n    protocol        = "tcp"\n    security_groups = [aws_security_group.rabbitmq.id]\n  }'

if target in text:
    text = text.replace(target, new_block)
    print('Replaced LF')
elif target.replace('\n', '\r\n') in text:
    text = text.replace(target.replace('\n', '\r\n'), new_block.replace('\n', '\r\n'))
    print('Replaced CRLF')
else:
    print('Target not found')

with open(path, 'w', encoding='utf-8') as f:
    f.write(text)
