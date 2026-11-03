# ==============================================================================
# CargaExpress Infrastructure - ECS Fargate Module
# File: infrastructure/terraform/modules/ecs/main.tf
# ==============================================================================

# ------------------------------------------------------------------------------
# 1. ECS Cluster & Capacity Providers
# ------------------------------------------------------------------------------
resource "aws_ecs_cluster" "main" {
  name = "${var.project_name}-${var.environment}-cluster"

  setting {
    name  = "containerInsights"
    value = "enabled"
  }

  tags = var.tags
}

resource "aws_ecs_cluster_capacity_providers" "main" {
  cluster_name = aws_ecs_cluster.main.name

  capacity_providers = ["FARGATE", "FARGATE_SPOT"]

  default_capacity_provider_strategy {
    capacity_provider = "FARGATE"
    weight            = 1
    base              = 1
  }
}

# ------------------------------------------------------------------------------
# 2. CloudWatch Log Groups for ECS Tasks
# ------------------------------------------------------------------------------
resource "aws_cloudwatch_log_group" "receiver" {
  name              = "/ecs/${var.project_name}-${var.environment}-receiver"
  retention_in_days = 30
  kms_key_id        = var.kms_key_arn

  tags = var.tags
}

resource "aws_cloudwatch_log_group" "api" {
  name              = "/ecs/${var.project_name}-${var.environment}-api"
  retention_in_days = 30
  kms_key_id        = var.kms_key_arn

  tags = var.tags
}

resource "aws_cloudwatch_log_group" "worker" {
  name              = "/ecs/${var.project_name}-${var.environment}-worker"
  retention_in_days = 30
  kms_key_id        = var.kms_key_arn

  tags = var.tags
}

# ------------------------------------------------------------------------------
# 3. Application Load Balancer (ALB) & Routing
# ------------------------------------------------------------------------------
resource "aws_lb" "main" {
  name               = "${var.project_name}-${var.environment}-alb"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [var.alb_security_group_id]
  subnets            = var.public_subnet_ids

  enable_deletion_protection = false

  tags = merge(
    var.tags,
    {
      Name = "${var.project_name}-${var.environment}-alb"
    }
  )
}

# Target Group: Brand & Carrier Query APIs (Default service)
resource "aws_lb_target_group" "api" {
  name        = "${var.project_name}-${var.environment}-api-tg"
  port        = 8000
  protocol    = "HTTP"
  vpc_id      = var.vpc_id
  target_type = "ip"

  health_check {
    enabled             = true
    path                = "/health"
    port                = "8000"
    protocol            = "HTTP"
    interval            = 30
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
    matcher             = "200"
  }

  deregistration_delay = 15

  tags = var.tags
}

# Target Group: Type A Webhook Receiver
resource "aws_lb_target_group" "receiver" {
  name        = "${var.project_name}-${var.environment}-rcv-tg"
  port        = 8000
  protocol    = "HTTP"
  vpc_id      = var.vpc_id
  target_type = "ip"

  health_check {
    enabled             = true
    path                = "/health"
    port                = "8000"
    protocol            = "HTTP"
    interval            = 15
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
    matcher             = "200"
  }

  deregistration_delay = 15

  tags = var.tags
}

# ALB HTTP Listener
resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.main.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
  }
}

# Listener Rule: Route Webhook traffic strictly to Webhook Receiver Target Group
resource "aws_lb_listener_rule" "receiver_rule" {
  listener_arn = aws_lb_listener.http.arn
  priority     = 10

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.receiver.arn
  }

  condition {
    path_pattern {
      values = ["/api/v1/webhooks/*"]
    }
  }
}

# ------------------------------------------------------------------------------
# 4. ECS Task Definitions
# ------------------------------------------------------------------------------

# Common Database URL string
locals {
  async_db_url = "postgresql+asyncpg://${var.db_user}:${var.db_password}@${var.db_host}:${var.db_port}/${var.db_name}"
}

# 4.1 Webhook Receiver Task Definition
resource "aws_ecs_task_definition" "receiver" {
  family                   = "${var.project_name}-${var.environment}-receiver"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "512"  # 0.5 vCPU
  memory                   = "1024" # 1 GB RAM
  execution_role_arn       = var.ecs_execution_role_arn
  task_role_arn            = var.ecs_task_role_arn

  container_definitions = jsonencode([
    {
      name      = "receiver"
      image     = var.backend_image
      essential = true
      portMappings = [
        {
          containerPort = 8000
          hostPort      = 8000
          protocol      = "tcp"
        }
      ]
      environment = [
        { name = "APP_ENV", value = var.environment },
        { name = "DATABASE_URL", value = local.async_db_url },
        { name = "RABBITMQ_URL", value = var.rabbitmq_url },
        { name = "LOG_LEVEL", value = "INFO" }
      ]
      secrets = [
        { name = "ADMIN_API_KEY", valueFrom = "${var.secretsmanager_app_secrets_arn}:ADMIN_API_KEY::" },
        { name = "API_KEY", valueFrom = "${var.secretsmanager_app_secrets_arn}:API_KEY::" },
        { name = "WEBHOOK_SECRET", valueFrom = "${var.secretsmanager_app_secrets_arn}:WEBHOOK_SECRET::" }
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.receiver.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "receiver"
        }
      }
    }
  ])

  tags = var.tags
}

# 4.2 FastAPI Query APIs Task Definition (Brands, Carriers, Analytics)
resource "aws_ecs_task_definition" "api" {
  family                   = "${var.project_name}-${var.environment}-api"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "512"  # 0.5 vCPU
  memory                   = "1024" # 1 GB RAM
  execution_role_arn       = var.ecs_execution_role_arn
  task_role_arn            = var.ecs_task_role_arn

  container_definitions = jsonencode([
    {
      name      = "api"
      image     = var.backend_image
      essential = true
      portMappings = [
        {
          containerPort = 8000
          hostPort      = 8000
          protocol      = "tcp"
        }
      ]
      environment = [
        { name = "APP_ENV", value = var.environment },
        { name = "DATABASE_URL", value = local.async_db_url },
        { name = "RABBITMQ_URL", value = var.rabbitmq_url },
        { name = "LOG_LEVEL", value = "INFO" }
      ]
      secrets = [
        { name = "ADMIN_API_KEY", valueFrom = "${var.secretsmanager_app_secrets_arn}:ADMIN_API_KEY::" },
        { name = "API_KEY", valueFrom = "${var.secretsmanager_app_secrets_arn}:API_KEY::" },
        { name = "BRAND_API_KEYS", valueFrom = "${var.secretsmanager_app_secrets_arn}:BRAND_API_KEYS::" },
        { name = "CARRIER_API_KEYS", valueFrom = "${var.secretsmanager_app_secrets_arn}:CARRIER_API_KEYS::" }
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.api.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "api"
        }
      }
    }
  ])

  tags = var.tags
}

# 4.3 Background Worker Consumer Task Definition (Consumes RabbitMQ & writes to RDS)
resource "aws_ecs_task_definition" "worker" {
  family                   = "${var.project_name}-${var.environment}-worker"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "512"  # 0.5 vCPU
  memory                   = "1024" # 1 GB RAM
  execution_role_arn       = var.ecs_execution_role_arn
  task_role_arn            = var.ecs_task_role_arn

  container_definitions = jsonencode([
    {
      name      = "worker"
      image     = var.worker_image
      essential = true
      command   = ["python", "-m", "app.worker"]
      environment = [
        { name = "APP_ENV", value = var.environment },
        { name = "DATABASE_URL", value = local.async_db_url },
        { name = "RABBITMQ_URL", value = var.rabbitmq_url },
        { name = "LOG_LEVEL", value = "INFO" }
      ]
      secrets = [
        { name = "ADMIN_API_KEY", valueFrom = "${var.secretsmanager_app_secrets_arn}:ADMIN_API_KEY::" }
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.worker.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "worker"
        }
      }
    }
  ])

  tags = var.tags
}

# ------------------------------------------------------------------------------
# 5. ECS Fargate Services (Running in Private App Subnets)
# ------------------------------------------------------------------------------

# 5.1 Webhook Receiver Service
resource "aws_ecs_service" "receiver" {
  name            = "${var.project_name}-${var.environment}-receiver-svc"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.receiver.arn
  desired_count   = 2
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = var.private_app_subnet_ids
    security_groups  = [var.ecs_security_group_id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.receiver.arn
    container_name   = "receiver"
    container_port   = 8000
  }

  deployment_controller {
    type = "ECS"
  }

  tags = var.tags
}

# 5.2 FastAPI Query APIs Service
resource "aws_ecs_service" "api" {
  name            = "${var.project_name}-${var.environment}-api-svc"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.api.arn
  desired_count   = 2
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = var.private_app_subnet_ids
    security_groups  = [var.ecs_security_group_id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.api.arn
    container_name   = "api"
    container_port   = 8000
  }

  deployment_controller {
    type = "ECS"
  }

  tags = var.tags
}

# 5.3 Background Worker Consumer Service
resource "aws_ecs_service" "worker" {
  name            = "${var.project_name}-${var.environment}-worker-svc"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.worker.arn
  desired_count   = 2
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = var.private_app_subnet_ids
    security_groups  = [var.ecs_security_group_id]
    assign_public_ip = false
  }

  deployment_controller {
    type = "ECS"
  }

  tags = var.tags
}

# ------------------------------------------------------------------------------
# 6. Target Tracking Auto-Scaling
# ------------------------------------------------------------------------------

# Auto-scaling for Receiver Service
resource "aws_appautoscaling_target" "receiver" {
  max_capacity       = 5
  min_capacity       = 1
  resource_id        = "service/${aws_ecs_cluster.main.name}/${aws_ecs_service.receiver.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"
}

resource "aws_appautoscaling_policy" "receiver_cpu" {
  name               = "${var.project_name}-${var.environment}-rcv-cpu-scaling"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.receiver.resource_id
  scalable_dimension = aws_appautoscaling_target.receiver.scalable_dimension
  service_namespace  = aws_appautoscaling_target.receiver.service_namespace

  target_tracking_scaling_policy_configuration {
    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
    target_value       = 70.0
    scale_in_cooldown  = 300
    scale_out_cooldown = 60
  }
}

# Auto-scaling for API Service
resource "aws_appautoscaling_target" "api" {
  max_capacity       = 5
  min_capacity       = 1
  resource_id        = "service/${aws_ecs_cluster.main.name}/${aws_ecs_service.api.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"
}

resource "aws_appautoscaling_policy" "api_cpu" {
  name               = "${var.project_name}-${var.environment}-api-cpu-scaling"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.api.resource_id
  scalable_dimension = aws_appautoscaling_target.api.scalable_dimension
  service_namespace  = aws_appautoscaling_target.api.service_namespace

  target_tracking_scaling_policy_configuration {
    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
    target_value       = 70.0
    scale_in_cooldown  = 300
    scale_out_cooldown = 60
  }
}
