# ==============================================================================
# CargaExpress Infrastructure - AWS Cost Budget & Alerts
# File: infrastructure/terraform/modules/monitoring/budget.tf
# ==============================================================================
# Creates an AWS Cost Budget with SNS and email alerts when approved by business.
# If monthly_budget_limit is null or 0, this budget is skipped.
# ==============================================================================

variable "monthly_budget_limit" {
  type        = number
  description = "Approved monthly AWS budget limit in USD (set null until approved by management)"
  default     = null
}

resource "aws_budgets_budget" "cost_budget" {
  count             = var.monthly_budget_limit != null && var.monthly_budget_limit > 0 ? 1 : 0
  name              = "${var.project_name}-${var.environment}-monthly-budget"
  budget_type       = "COST"
  limit_amount      = tostring(var.monthly_budget_limit)
  limit_unit        = "USD"
  time_unit         = "MONTHLY"
  time_period_start = "2026-01-01_00:00"

  cost_filter {
    name = "TagKeyValue"
    values = [
      "user:Project$${var.project_name}",
      "user:Environment$${var.environment}"
    ]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.alert_email]
    subscriber_sns_topic_arns  = [aws_sns_topic.alerts.arn]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = [var.alert_email]
    subscriber_sns_topic_arns  = [aws_sns_topic.alerts.arn]
  }

  tags = var.tags
}
