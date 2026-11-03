# ==============================================================================
# CargaExpress Infrastructure - RabbitMQ EC2 Module Outputs
# File: infrastructure/terraform/modules/rabbitmq/outputs.tf
# ==============================================================================

output "instance_id" {
  value       = aws_instance.rabbitmq.id
  description = "The EC2 instance ID running RabbitMQ"
}

output "private_ip" {
  value       = aws_instance.rabbitmq.private_ip
  description = "The internal private IP of the RabbitMQ broker"
}

output "amqp_url" {
  value       = "amqp://${var.rabbitmq_username}:${var.rabbitmq_password}@${aws_instance.rabbitmq.private_ip}:5672/"
  description = "Connection AMQP URL for consumers and producers"
  sensitive   = true
}

output "management_url" {
  value       = "http://${aws_instance.rabbitmq.private_ip}:15672/"
  description = "Private URL for RabbitMQ management console"
}
