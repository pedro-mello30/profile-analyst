# SQS Queue for batch runs
resource "aws_sqs_queue" "runs" {
  name                      = "${local.cluster_name}-runs"
  visibility_timeout_seconds = 300
  message_retention_seconds  = 1209600  # 14 days
  receive_wait_time_seconds  = 20

  tags = {
    Name = "${local.cluster_name}-runs"
  }
}

# SQS DLQ for poison messages
resource "aws_sqs_queue" "runs_dlq" {
  name                      = "${local.cluster_name}-runs-dlq"
  message_retention_seconds  = 1209600  # 14 days

  tags = {
    Name = "${local.cluster_name}-runs-dlq"
  }
}

# Update main queue with DLQ redrive policy
resource "aws_sqs_queue_redrive_policy" "runs" {
  queue_url = aws_sqs_queue.runs.url
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.runs_dlq.arn
    maxReceiveCount     = 3
  })
}
