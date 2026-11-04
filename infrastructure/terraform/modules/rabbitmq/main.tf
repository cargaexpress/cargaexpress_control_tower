# ==============================================================================
# CargaExpress Infrastructure - RabbitMQ EC2 Module
# File: infrastructure/terraform/modules/rabbitmq/main.tf
# ==============================================================================

# ------------------------------------------------------------------------------
# 1. AMI Data Source (Amazon Linux 2023 Minimal)
# ------------------------------------------------------------------------------
data "aws_ami" "al2023" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-2023.*-x86_64"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

# ------------------------------------------------------------------------------
# 2. IAM Role & Instance Profile for RabbitMQ EC2 Instance
# ------------------------------------------------------------------------------
resource "aws_iam_role" "rabbitmq" {
  name = "${var.project_name}-${var.environment}-rabbitmq-ec2-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "ec2.amazonaws.com"
        }
      }
    ]
  })

  tags = var.tags
}

resource "aws_iam_role_policy_attachment" "ssm_core" {
  role       = aws_iam_role.rabbitmq.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "rabbitmq" {
  name = "${var.project_name}-${var.environment}-rabbitmq-profile"
  role = aws_iam_role.rabbitmq.name

  tags = var.tags
}

# ------------------------------------------------------------------------------
# 3. RabbitMQ EC2 Broker Instance
# ------------------------------------------------------------------------------
resource "aws_instance" "rabbitmq" {
  ami                    = data.aws_ami.al2023.id
  instance_type          = var.instance_type
  subnet_id              = var.private_app_subnet_id
  vpc_security_group_ids = [var.rabbitmq_security_group_id]
  iam_instance_profile   = aws_iam_instance_profile.rabbitmq.name

  root_block_device {
    volume_size           = var.volume_size
    volume_type           = "gp3"
    encrypted             = true
    kms_key_id            = var.kms_key_arn
    delete_on_termination = true

    tags = merge(
      var.tags,
      {
        Name = "${var.project_name}-${var.environment}-rabbitmq-disk"
      }
    )
  }

  user_data = <<-EOF
              #!/bin/bash
              set -e
              yum update -y
              yum install -y docker
              systemctl enable --now docker

              mkdir -p /opt/rabbitmq/data

              cat << 'DOCKER_COMPOSE' > /opt/rabbitmq/docker-compose.yml
              services:
                rabbitmq:
                  image: rabbitmq:3.13-management-alpine
                  container_name: rabbitmq-broker
                  restart: always
                  ports:
                    - "5672:5672"
                    - "15672:15672"
                  environment:
                    RABBITMQ_DEFAULT_USER: "${var.rabbitmq_username}"
                    RABBITMQ_DEFAULT_PASS: "${var.rabbitmq_password}"
                  volumes:
                    - /opt/rabbitmq/data:/var/lib/rabbitmq/mnesia
              DOCKER_COMPOSE

              curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
              chmod +x /usr/local/bin/docker-compose
              cd /opt/rabbitmq
              /usr/local/bin/docker-compose up -d

              # Wait for broker readiness and initialize canonical queues and dead-letter queues
              sleep 20
              docker exec rabbitmq-broker rabbitmqadmin -u "${var.rabbitmq_username}" -p "${var.rabbitmq_password}" declare exchange name=eventos_exchange type=direct durable=true || true
              docker exec rabbitmq-broker rabbitmqadmin -u "${var.rabbitmq_username}" -p "${var.rabbitmq_password}" declare queue name=eventos_transportadora durable=true || true
              docker exec rabbitmq-broker rabbitmqadmin -u "${var.rabbitmq_username}" -p "${var.rabbitmq_password}" declare queue name=eventos_transportadora.retry durable=true || true
              docker exec rabbitmq-broker rabbitmqadmin -u "${var.rabbitmq_username}" -p "${var.rabbitmq_password}" declare queue name=eventos_transportadora.dlq durable=true || true
              docker exec rabbitmq-broker rabbitmqadmin -u "${var.rabbitmq_username}" -p "${var.rabbitmq_password}" declare binding source=eventos_exchange destination=eventos_transportadora routing_key=evento.recibido || true
              EOF

  tags = merge(
    var.tags,
    {
      Name = "${var.project_name}-${var.environment}-rabbitmq-broker"
      Role = "MessageBroker"
    }
  )

  lifecycle {
    ignore_changes = [ami]
  }
}
