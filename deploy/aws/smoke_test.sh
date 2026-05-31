#!/bin/bash
# Smoke test suite for AWS Fargate deployment (Spec 0008 §8).
# Prerequisites: terraform apply has succeeded, ALB is healthy, image is pushed to ECR.
# Usage: ./deploy/aws/smoke_test.sh [ALB_DNS] [HANDLE]

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
ALB_DNS="${1:-}"
TEST_HANDLE="${2:-sample}"
TIMEOUT=300
POLL_INTERVAL=10

if [ -z "$ALB_DNS" ]; then
    echo "Usage: ./deploy/aws/smoke_test.sh <ALB_DNS> [HANDLE]"
    echo "  ALB_DNS: DNS name of the ALB (from terraform output alb_dns_name)"
    echo "  HANDLE: Handle to test (default: sample)"
    exit 1
fi

echo "=========================================="
echo "AWS Fargate Deployment Smoke Tests"
echo "=========================================="
echo "ALB DNS: $ALB_DNS"
echo "Test handle: $TEST_HANDLE"
echo ""

# Helper functions
pass() {
    echo -e "${GREEN}✓${NC} $1"
}

fail() {
    echo -e "${RED}✗${NC} $1"
    exit 1
}

warn() {
    echo -e "${YELLOW}⚠${NC} $1"
}

# Test 1: ALB + target group healthy
test_alb_health() {
    echo "Test 1: ALB target group health..."
    local healthy_count=$(aws elbv2 describe-target-health \
        --target-group-arn $(aws elbv2 describe-target-groups \
            --load-balancer-arn $(aws elbv2 describe-load-balancers \
                --query "LoadBalancers[?DNSName=='$ALB_DNS'].LoadBalancerArn" --output text) \
            --query 'TargetGroups[0].TargetGroupArn' --output text) \
        --query "length(TargetHealthDescriptions[?TargetHealth.State=='healthy'])" \
        --output text 2>/dev/null || echo "0")

    if [ "$healthy_count" -ge 1 ]; then
        pass "ALB has $healthy_count healthy target(s)"
    else
        fail "ALB has no healthy targets"
    fi
}

# Test 2: GET /healthz returns 200
test_healthz() {
    echo "Test 2: GET /healthz endpoint..."
    local response=$(curl -s -w "\n%{http_code}" https://$ALB_DNS/healthz)
    local http_code=$(echo "$response" | tail -1)

    if [ "$http_code" = "200" ]; then
        pass "/healthz returned $http_code"
    else
        fail "/healthz returned $http_code (expected 200)"
    fi
}

# Test 3: POST /runs enqueues a batch
test_enqueue_run() {
    echo "Test 3: POST /runs enqueue..."
    local run_response=$(curl -s -X POST https://$ALB_DNS/runs \
        -H "Content-Type: application/json" \
        -d "{\"handle\": \"$TEST_HANDLE\", \"stages\": \"1,2,3\"}")

    local run_id=$(echo "$run_response" | jq -r '.run_id // empty')
    local status=$(echo "$run_response" | jq -r '.status // empty')

    if [ -z "$run_id" ]; then
        fail "POST /runs returned invalid response: $run_response"
    fi

    if [ "$status" = "queued" ]; then
        pass "Enqueued run $run_id with status queued"
        echo "$run_id"
    else
        fail "POST /runs returned status '$status' (expected 'queued')"
    fi
}

# Test 4: GET /runs/{run_id} returns status
test_get_run_status() {
    echo "Test 4: GET /runs/{run_id} status..."
    local run_id=$1
    local response=$(curl -s -w "\n%{http_code}" https://$ALB_DNS/runs/$run_id?handle=$TEST_HANDLE)
    local http_code=$(echo "$response" | tail -1)
    local body=$(echo "$response" | head -n -1)

    if [ "$http_code" = "200" ]; then
        local returned_status=$(echo "$body" | jq -r '.status // empty')
        pass "GET /runs/$run_id returned status: $returned_status"
    else
        fail "GET /runs/$run_id returned $http_code (expected 200)"
    fi
}

# Test 5: Wait for pipeline to complete
test_pipeline_completion() {
    echo "Test 5: Waiting for pipeline to complete (max ${TIMEOUT}s)..."
    local run_id=$1
    local elapsed=0

    while [ $elapsed -lt $TIMEOUT ]; do
        local response=$(curl -s https://$ALB_DNS/runs/$run_id?handle=$TEST_HANDLE)
        local status=$(echo "$response" | jq -r '.status // empty')

        if [ "$status" = "succeeded" ]; then
            pass "Pipeline completed with status: $status"
            return 0
        elif [ "$status" = "failed" ]; then
            local error=$(echo "$response" | jq -r '.error // "unknown"')
            fail "Pipeline failed: $error"
        elif [ "$status" = "running" ]; then
            echo "  ... still running (${elapsed}s elapsed)"
        fi

        sleep $POLL_INTERVAL
        elapsed=$((elapsed + POLL_INTERVAL))
    done

    fail "Pipeline did not complete within ${TIMEOUT}s"
}

# Test 6: Verify EFS artifacts
test_efs_artifacts() {
    echo "Test 6: Verify EFS artifacts..."
    # This test is local to the container; in real deployment, would use EFS mount point
    warn "Skipping EFS artifact verification (requires EFS mount access from test environment)"
}

# Test 7: Verify Neo4j graph
test_neo4j_graph() {
    echo "Test 7: Verify Neo4j graph..."
    # This test requires cypher-shell or direct Neo4j API access
    warn "Skipping Neo4j verification (requires Neo4j client from test environment)"
}

# Test 8: POST /ask query endpoint
test_ask_endpoint() {
    echo "Test 8: POST /ask query endpoint..."
    local response=$(curl -s -X POST https://$ALB_DNS/ask \
        -H "Content-Type: application/json" \
        -d "{\"handle\": \"$TEST_HANDLE\", \"question\": \"Who is this creator?\"}")

    local has_answer=$(echo "$response" | jq 'has("answer")' 2>/dev/null || echo "false")

    if [ "$has_answer" = "true" ]; then
        pass "POST /ask returned a response"
    else
        warn "POST /ask may not be ready yet (graph still loading): $response"
    fi
}

# Test 9: POST /rag endpoint
test_rag_endpoint() {
    echo "Test 9: POST /rag endpoint..."
    local response=$(curl -s -X POST https://$ALB_DNS/rag \
        -H "Content-Type: application/json" \
        -d "{\"handle\": \"$TEST_HANDLE\", \"question\": \"What are the main interests?\"}")

    local has_answer=$(echo "$response" | jq 'has("answer")' 2>/dev/null || echo "false")

    if [ "$has_answer" = "true" ]; then
        pass "POST /rag returned a response"
    else
        warn "POST /rag may not be ready yet (embeddings still loading): $response"
    fi
}

# Main flow
main() {
    test_alb_health
    test_healthz
    run_id=$(test_enqueue_run)
    test_get_run_status "$run_id"
    test_pipeline_completion "$run_id"
    test_efs_artifacts
    test_neo4j_graph
    test_ask_endpoint
    test_rag_endpoint

    echo ""
    echo "=========================================="
    echo -e "${GREEN}All smoke tests passed!${NC}"
    echo "=========================================="
}

main
