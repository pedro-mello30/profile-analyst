# ── Frontend Dashboard (Spec 0009) ─────────────────────────────────────────────
# S3 bucket + CloudFront + ALB auth rules for the React SPA.
# Depends on: aws_lb.main, aws_lb_listener.http/https, aws_lb_target_group.api

# ── S3 bucket ──────────────────────────────────────────────────────────────────
resource "aws_s3_bucket" "frontend" {
  bucket = "${local.cluster_name}-frontend"

  tags = {
    Name = "${local.cluster_name}-frontend"
  }
}

resource "aws_s3_bucket_versioning" "frontend" {
  bucket = aws_s3_bucket.frontend.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_public_access_block" "frontend" {
  bucket                  = aws_s3_bucket.frontend.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "frontend" {
  bucket = aws_s3_bucket.frontend.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# ── CloudFront OAC ─────────────────────────────────────────────────────────────
resource "aws_cloudfront_origin_access_control" "frontend" {
  name                              = "${local.cluster_name}-frontend-oac"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

# Allow CloudFront OAC principal to read S3 objects
resource "aws_s3_bucket_policy" "frontend" {
  bucket = aws_s3_bucket.frontend.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "AllowCloudFrontServicePrincipal"
      Effect    = "Allow"
      Principal = { Service = "cloudfront.amazonaws.com" }
      Action    = "s3:GetObject"
      Resource  = "${aws_s3_bucket.frontend.arn}/*"
      Condition = {
        StringEquals = {
          "AWS:SourceArn" = aws_cloudfront_distribution.frontend.arn
        }
      }
    }]
  })
}

# ── CloudFront Function — strip /api prefix before forwarding to ALB ───────────
resource "aws_cloudfront_function" "strip_api_prefix" {
  name    = "${local.cluster_name}-strip-api-prefix"
  runtime = "cloudfront-js-2.0"
  publish = true
  code    = <<-EOT
    function handler(event) {
      var request = event.request;
      request.uri = request.uri.replace(/^\/api/, '') || '/';
      return request;
    }
  EOT
}

# ── CloudFront distribution ────────────────────────────────────────────────────
locals {
  s3_origin_id  = "S3FrontendOrigin"
  alb_origin_id = "ALBApiOrigin"

  # Use HTTPS to ALB when a cert is configured, HTTP otherwise.
  alb_origin_protocol = var.acm_certificate_arn != "" ? "https-only" : "http-only"
  alb_origin_port     = var.acm_certificate_arn != "" ? 443 : 80
}

resource "aws_cloudfront_distribution" "frontend" {
  enabled             = true
  default_root_object = "index.html"
  comment             = "${local.cluster_name} frontend dashboard (spec 0009)"
  price_class         = "PriceClass_100"

  # Origin 1 — S3 static assets (default behaviour)
  origin {
    domain_name              = aws_s3_bucket.frontend.bucket_regional_domain_name
    origin_id                = local.s3_origin_id
    origin_access_control_id = aws_cloudfront_origin_access_control.frontend.id
  }

  # Origin 2 — ALB for API calls (/api/*)
  origin {
    domain_name = aws_lb.main.dns_name
    origin_id   = local.alb_origin_id
    custom_origin_config {
      http_port              = 80
      https_port             = 443
      origin_protocol_policy = local.alb_origin_protocol
      origin_ssl_protocols   = ["TLSv1.2"]
    }
  }

  # Default behaviour — serve static assets from S3
  default_cache_behavior {
    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]
    target_origin_id       = local.s3_origin_id
    viewer_protocol_policy = "redirect-to-https"
    compress               = true

    # CachingOptimized managed policy
    cache_policy_id = "658327ea-f89d-4fab-a63d-7e88639e58f6"
  }

  # /api/* — proxy to ALB, no caching, strip prefix via CloudFront Function
  ordered_cache_behavior {
    path_pattern           = "/api/*"
    allowed_methods        = ["DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"]
    cached_methods         = ["GET", "HEAD"]
    target_origin_id       = local.alb_origin_id
    viewer_protocol_policy = "redirect-to-https"
    compress               = false

    # CachingDisabled managed policy
    cache_policy_id = "4135ea2d-6df8-44a3-9df3-4b5a84be39ad"

    # Forward all viewer headers (including Authorization) except Host
    # AllViewerExceptHostHeader managed policy
    origin_request_policy_id = "b689b0a8-53d0-40ab-baf2-68738e2966ac"

    function_association {
      event_type   = "viewer-request"
      function_arn = aws_cloudfront_function.strip_api_prefix.arn
    }
  }

  # SPA routing — 404 from S3 → serve index.html (React Router handles client-side routing)
  custom_error_response {
    error_code         = 404
    response_code      = 200
    response_page_path = "/index.html"
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  # Use default CloudFront certificate for v1 (custom domain is Future Work)
  viewer_certificate {
    cloudfront_default_certificate = true
  }
}

# ── Secrets Manager — frontend API token ───────────────────────────────────────
resource "aws_secretsmanager_secret" "frontend_api_token" {
  name                    = "analyst/frontend_api_token"
  description             = "Shared Bearer token for the profile-analyst frontend dashboard"
  recovery_window_in_days = 7

  tags = {
    Name = "${local.cluster_name}-frontend-token"
  }
}

resource "aws_secretsmanager_secret_version" "frontend_api_token" {
  secret_id     = aws_secretsmanager_secret.frontend_api_token.id
  secret_string = var.frontend_api_token
}

# ── ALB listener rules — enforce Bearer token on all /api/* requests ───────────
#
# Two rules on each active listener:
#   Priority 1: /api/* AND Authorization matches → forward to API target group
#   Priority 2: /api/* (catch-all) → fixed 401 unauthorized
#
# NOTE: This protects ALL /api/* traffic arriving at the ALB, including direct
# access that bypasses CloudFront. Update smoke_test.sh to include the token.

# HTTP listener rules (always present — HTTP listener always exists)
resource "aws_lb_listener_rule" "frontend_auth_allow_http" {
  listener_arn = aws_lb_listener.http.arn
  priority     = 10

  condition {
    path_pattern {
      values = ["/api/*"]
    }
  }

  condition {
    http_header {
      http_header_name = "Authorization"
      values           = ["Bearer ${var.frontend_api_token}"]
    }
  }

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
  }
}

resource "aws_lb_listener_rule" "frontend_auth_reject_http" {
  listener_arn = aws_lb_listener.http.arn
  priority     = 11

  condition {
    path_pattern {
      values = ["/api/*"]
    }
  }

  action {
    type = "fixed-response"
    fixed_response {
      content_type = "application/json"
      message_body = "{\"error\":\"unauthorized\"}"
      status_code  = "401"
    }
  }
}

# HTTPS listener rules (only when ACM cert is configured)
resource "aws_lb_listener_rule" "frontend_auth_allow_https" {
  count        = var.acm_certificate_arn != "" ? 1 : 0
  listener_arn = aws_lb_listener.https[0].arn
  priority     = 10

  condition {
    path_pattern {
      values = ["/api/*"]
    }
  }

  condition {
    http_header {
      http_header_name = "Authorization"
      values           = ["Bearer ${var.frontend_api_token}"]
    }
  }

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
  }
}

resource "aws_lb_listener_rule" "frontend_auth_reject_https" {
  count        = var.acm_certificate_arn != "" ? 1 : 0
  listener_arn = aws_lb_listener.https[0].arn
  priority     = 11

  condition {
    path_pattern {
      values = ["/api/*"]
    }
  }

  action {
    type = "fixed-response"
    fixed_response {
      content_type = "application/json"
      message_body = "{\"error\":\"unauthorized\"}"
      status_code  = "401"
    }
  }
}
