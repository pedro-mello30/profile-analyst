# VPC
resource "aws_vpc" "main" {
  cidr_block           = var.vpc_cidr
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = {
    Name = "${local.cluster_name}-vpc"
  }
}

# Internet Gateway
resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id

  tags = {
    Name = "${local.cluster_name}-igw"
  }
}

# Get available AZs
data "aws_availability_zones" "available" {
  state = "available"
}

# Public Subnets (for ALB + NAT)
resource "aws_subnet" "public" {
  count                   = var.availability_zones
  vpc_id                  = aws_vpc.main.id
  cidr_block              = "10.0.${count.index + 1}.0/24"
  availability_zone       = data.aws_availability_zones.available.names[count.index]
  map_public_ip_on_launch = true

  tags = {
    Name = "${local.cluster_name}-public-${count.index + 1}"
    Type = "Public"
  }
}

# Private Subnets (for ECS tasks, databases)
resource "aws_subnet" "private" {
  count             = var.availability_zones * var.private_subnet_count
  vpc_id            = aws_vpc.main.id
  cidr_block        = "10.0.${100 + count.index + 1}.0/24"
  availability_zone = data.aws_availability_zones.available.names[count.index % var.availability_zones]

  tags = {
    Name = "${local.cluster_name}-private-${count.index + 1}"
    Type = "Private"
  }
}

# Elastic IPs for NAT Gateways
resource "aws_eip" "nat" {
  count  = var.availability_zones
  domain = "vpc"

  depends_on = [aws_internet_gateway.main]

  tags = {
    Name = "${local.cluster_name}-nat-eip-${count.index + 1}"
  }
}

# NAT Gateways (one per AZ for HA)
resource "aws_nat_gateway" "main" {
  count         = var.availability_zones
  allocation_id = aws_eip.nat[count.index].id
  subnet_id     = aws_subnet.public[count.index].id

  depends_on = [aws_internet_gateway.main]

  tags = {
    Name = "${local.cluster_name}-nat-${count.index + 1}"
  }
}

# Route Table - Public
resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block      = "0.0.0.0/0"
    gateway_id      = aws_internet_gateway.main.id
  }

  tags = {
    Name = "${local.cluster_name}-rt-public"
  }
}

# Public Route Table Associations
resource "aws_route_table_association" "public" {
  count          = var.availability_zones
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

# Route Tables - Private (one per AZ, each with NAT in same AZ)
resource "aws_route_table" "private" {
  count  = var.availability_zones
  vpc_id = aws_vpc.main.id

  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = aws_nat_gateway.main[count.index].id
  }

  tags = {
    Name = "${local.cluster_name}-rt-private-${count.index + 1}"
  }
}

# Private Route Table Associations
resource "aws_route_table_association" "private" {
  count          = length(aws_subnet.private)
  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private[count.index % var.availability_zones].id
}

# VPC Endpoints
# S3 Gateway Endpoint
resource "aws_vpc_endpoint" "s3" {
  vpc_id              = aws_vpc.main.id
  service_name        = "com.amazonaws.${local.region}.s3"
  vpc_endpoint_type   = "Gateway"
  route_table_ids     = concat(aws_route_table.private[*].id, [aws_route_table.public.id])

  tags = {
    Name = "${local.cluster_name}-s3-endpoint"
  }
}

# Secrets Manager VPC Endpoint
resource "aws_vpc_endpoint" "secrets_manager" {
  vpc_id              = aws_vpc.main.id
  service_name        = "com.amazonaws.${local.region}.secretsmanager"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = aws_subnet.private[*].id
  security_group_ids  = [aws_security_group.vpc_endpoints.id]
  private_dns_enabled = true

  tags = {
    Name = "${local.cluster_name}-secrets-endpoint"
  }
}

# Security Group for VPC Endpoints
resource "aws_security_group" "vpc_endpoints" {
  name        = "${local.cluster_name}-vpc-endpoints-sg"
  description = "Security group for VPC endpoints"
  vpc_id      = aws_vpc.main.id

  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${local.cluster_name}-vpc-endpoints-sg"
  }
}

# Security Group for ALB
resource "aws_security_group" "alb" {
  name        = "${local.cluster_name}-alb-sg"
  description = "Security group for ALB"
  vpc_id      = aws_vpc.main.id

  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${local.cluster_name}-alb-sg"
  }
}

# Security Group for ECS tasks
resource "aws_security_group" "ecs_tasks" {
  name        = "${local.cluster_name}-ecs-tasks-sg"
  description = "Security group for ECS tasks"
  vpc_id      = aws_vpc.main.id

  ingress {
    from_port       = 0
    to_port         = 65535
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }

  ingress {
    from_port   = 0
    to_port     = 65535
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${local.cluster_name}-ecs-tasks-sg"
  }
}

# Security Group for RDS
resource "aws_security_group" "rds" {
  name        = "${local.cluster_name}-rds-sg"
  description = "Security group for RDS"
  vpc_id      = aws_vpc.main.id

  ingress {
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.ecs_tasks.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${local.cluster_name}-rds-sg"
  }
}
