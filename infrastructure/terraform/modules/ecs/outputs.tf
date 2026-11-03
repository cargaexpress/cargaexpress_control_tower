# ==============================================================================
# CargaExpress Infrastructure - ECS Fargate Module Outputs
# File: infrastructure/terraform/modules/ecs/outputs.tf
# ==============================================================================

output "cluster_id" {
  value       = aws_ecs_cluster.main.id
  description = "The ECS Cluster ID"
}

output "cluster_name" {
  value       = aws_ecs_cluster.main.name
  description = "The ECS Cluster name"
}

output "alb_dns_name" {
  value       = aws_lb.main.dns_name
  description = "The external DNS name of the Application Load Balancer"
}

output "alb_zone_id" {
  value       = aws_lb.main.zone_id
  description = "The canonical hosted zone ID of the ALB"
}

output "alb_arn" {
  value       = aws_lb.main.arn
  description = "The ARN of the Application Load Balancer"
}

output "receiver_service_name" {
  value       = aws_ecs_service.receiver.name
  description = "Name of the ECS Webhook Receiver service"
}

output "api_service_name" {
  value       = aws_ecs_service.api.name
  description = "Name of the ECS Query APIs service"
}

output "worker_service_name" {
  value       = aws_ecs_service.worker.name
  description = "Name of the ECS Background Worker service"
}

output "api_target_group_arn" {
  value       = aws_lb_target_group.api.arn
  description = "Target group ARN for Query APIs"
}

output "receiver_target_group_arn" {
  value       = aws_lb_target_group.receiver.arn
  description = "Target group ARN for Webhook Receiver"
}
