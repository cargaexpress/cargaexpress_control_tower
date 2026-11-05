# ==============================================================================
# CargaExpress Infrastructure - Networking Module Outputs
# File: infrastructure/terraform/modules/networking/outputs.tf
# ==============================================================================

output "vpc_id" {
  value       = aws_vpc.main.id
  description = "The ID of the provisioned VPC"
}

output "vpc_cidr_block" {
  value       = aws_vpc.main.cidr_block
  description = "The CIDR block of the VPC"
}

output "public_subnet_ids" {
  value       = aws_subnet.public[*].id
  description = "List of IDs of the public subnets (ALB, NAT)"
}

output "private_app_subnet_ids" {
  value       = aws_subnet.private_app[*].id
  description = "List of IDs of the private application subnets (ECS, Airflow, RabbitMQ)"
}

output "private_db_subnet_ids" {
  value       = aws_subnet.private_db[*].id
  description = "List of IDs of the private database subnets (RDS PostgreSQL)"
}

output "nat_gateway_id" {
  value       = aws_nat_gateway.main.id
  description = "The ID of the NAT Gateway"
}

output "nat_public_ip" {
  value       = aws_eip.nat.public_ip
  description = "The elastic public IP of the NAT Gateway"
}

output "alb_security_group_id" {
  value       = aws_security_group.alb.id
  description = "The ID of the ALB security group"
}

output "ecs_security_group_id" {
  value       = aws_security_group.ecs.id
  description = "The ID of the ECS tasks security group"
}

output "airflow_security_group_id" {
  value       = aws_security_group.airflow.id
  description = "The ID of the Airflow security group"
}

output "rabbitmq_security_group_id" {
  value       = aws_security_group.rabbitmq.id
  description = "The ID of the RabbitMQ security group"
}

output "rds_security_group_id" {
  value       = aws_security_group.rds.id
  description = "The ID of the RDS PostgreSQL security group"
}

output "s3_vpc_endpoint_id" {
  value       = aws_vpc_endpoint.s3.id
  description = "The ID of the S3 VPC Gateway Endpoint (direct zero-cost S3 routing)"
}
