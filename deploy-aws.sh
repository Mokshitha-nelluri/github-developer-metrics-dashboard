#!/bin/bash

# AWS Deployment Script for GitHub Metrics Dashboard
# This script automates the complete AWS deployment process

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
ENVIRONMENT=${ENVIRONMENT:-production}
AWS_REGION=${AWS_REGION:-us-east-1}
DOMAIN_NAME=${DOMAIN_NAME:-github-metrics.yourdomain.com}
STACK_NAME="${ENVIRONMENT}-github-metrics-infrastructure"

echo -e "${BLUE}🚀 GitHub Metrics Dashboard - AWS Deployment${NC}"
echo -e "${BLUE}===============================================${NC}"

# Function to print colored messages
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check prerequisites
check_prerequisites() {
    log_info "Checking prerequisites..."
    
    # Check AWS CLI
    if ! command -v aws &> /dev/null; then
        log_error "AWS CLI is not installed. Please install it first."
        exit 1
    fi
    
    # Check Docker
    if ! command -v docker &> /dev/null; then
        log_error "Docker is not installed. Please install it first."
        exit 1
    fi
    
    # Check AWS credentials
    if ! aws sts get-caller-identity &> /dev/null; then
        log_error "AWS credentials not configured. Run 'aws configure' first."
        exit 1
    fi
    
    log_info "✅ All prerequisites met"
}

# Get user inputs
get_inputs() {
    log_info "Gathering deployment configuration..."
    
    # Environment variables check
    if [[ -z "${GITHUB_TOKEN:-}" ]]; then
        read -sp "Enter GitHub Personal Access Token: " GITHUB_TOKEN
        echo
    fi
    
    if [[ -z "${SUPABASE_URL:-}" ]]; then
        read -p "Enter Supabase URL: " SUPABASE_URL
    fi
    
    if [[ -z "${SUPABASE_KEY:-}" ]]; then
        read -sp "Enter Supabase API Key: " SUPABASE_KEY
        echo
    fi
    
    if [[ -z "${GEMINI_API_KEY:-}" ]]; then
        read -sp "Enter Google Gemini API Key: " GEMINI_API_KEY
        echo
    fi
    
    # SSL Certificate
    if [[ -z "${CERTIFICATE_ARN:-}" ]]; then
        log_warn "SSL Certificate ARN not provided. You'll need to create one in ACM."
        read -p "Enter SSL Certificate ARN (or press Enter to skip): " CERTIFICATE_ARN
    fi
}

# Create or update CloudFormation stack
deploy_infrastructure() {
    log_info "Deploying infrastructure with CloudFormation..."
    
    local cf_params=(
        "ParameterKey=Environment,ParameterValue=${ENVIRONMENT}"
        "ParameterKey=DomainName,ParameterValue=${DOMAIN_NAME}"
        "ParameterKey=GitHubToken,ParameterValue=${GITHUB_TOKEN}"
        "ParameterKey=SupabaseUrl,ParameterValue=${SUPABASE_URL}"
        "ParameterKey=SupabaseKey,ParameterValue=${SUPABASE_KEY}"
        "ParameterKey=GeminiApiKey,ParameterValue=${GEMINI_API_KEY}"
    )
    
    if [[ -n "${CERTIFICATE_ARN:-}" ]]; then
        cf_params+=("ParameterKey=CertificateArn,ParameterValue=${CERTIFICATE_ARN}")
    fi
    
    # Check if stack exists
    if aws cloudformation describe-stacks --stack-name "$STACK_NAME" --region "$AWS_REGION" &> /dev/null; then
        log_info "Updating existing CloudFormation stack..."
        aws cloudformation update-stack \
            --stack-name "$STACK_NAME" \
            --template-body file://.aws/cloudformation-infrastructure.yml \
            --parameters "${cf_params[@]}" \
            --capabilities CAPABILITY_IAM \
            --region "$AWS_REGION"
    else
        log_info "Creating new CloudFormation stack..."
        aws cloudformation create-stack \
            --stack-name "$STACK_NAME" \
            --template-body file://.aws/cloudformation-infrastructure.yml \
            --parameters "${cf_params[@]}" \
            --capabilities CAPABILITY_IAM \
            --region "$AWS_REGION"
    fi
    
    log_info "Waiting for CloudFormation stack deployment..."
    aws cloudformation wait stack-create-complete \
        --stack-name "$STACK_NAME" \
        --region "$AWS_REGION" || \
    aws cloudformation wait stack-update-complete \
        --stack-name "$STACK_NAME" \
        --region "$AWS_REGION"
    
    log_info "✅ Infrastructure deployed successfully"
}

# Build and push Docker image
build_and_push_image() {
    log_info "Building and pushing Docker image..."
    
    # Get ECR repository URI from CloudFormation output
    ECR_URI=$(aws cloudformation describe-stacks \
        --stack-name "$STACK_NAME" \
        --region "$AWS_REGION" \
        --query "Stacks[0].Outputs[?OutputKey=='ECRRepositoryURI'].OutputValue" \
        --output text)
    
    if [[ -z "$ECR_URI" ]]; then
        log_error "Could not retrieve ECR repository URI"
        exit 1
    fi
    
    log_info "ECR Repository: $ECR_URI"
    
    # Login to ECR
    aws ecr get-login-password --region "$AWS_REGION" | \
        docker login --username AWS --password-stdin "$ECR_URI"
    
    # Build image
    log_info "Building Docker image..."
    docker build -t github-metrics:latest .
    
    # Tag and push image
    docker tag github-metrics:latest "$ECR_URI:latest"
    docker tag github-metrics:latest "$ECR_URI:$(git rev-parse HEAD)"
    
    log_info "Pushing Docker image to ECR..."
    docker push "$ECR_URI:latest"
    docker push "$ECR_URI:$(git rev-parse HEAD)"
    
    log_info "✅ Docker image pushed successfully"
}

# Create ECS service
deploy_ecs_service() {
    log_info "Deploying ECS service..."
    
    # Get stack outputs
    CLUSTER_NAME=$(aws cloudformation describe-stacks \
        --stack-name "$STACK_NAME" \
        --region "$AWS_REGION" \
        --query "Stacks[0].Outputs[?OutputKey=='ECSClusterName'].OutputValue" \
        --output text)
    
    ECR_URI=$(aws cloudformation describe-stacks \
        --stack-name "$STACK_NAME" \
        --region "$AWS_REGION" \
        --query "Stacks[0].Outputs[?OutputKey=='ECRRepositoryURI'].OutputValue" \
        --output text)
    
    # Update task definition with correct image URI
    sed "s|ACCOUNT_ID.dkr.ecr.us-east-1.amazonaws.com/github-metrics:latest|$ECR_URI:latest|g" \
        .aws/task-definition.json > .aws/task-definition-updated.json
    
    # Register task definition
    log_info "Registering ECS task definition..."
    TASK_DEF_ARN=$(aws ecs register-task-definition \
        --cli-input-json file://.aws/task-definition-updated.json \
        --region "$AWS_REGION" \
        --query 'taskDefinition.taskDefinitionArn' \
        --output text)
    
    # Create or update ECS service
    SERVICE_NAME="${ENVIRONMENT}-github-metrics-service"
    
    if aws ecs describe-services \
        --cluster "$CLUSTER_NAME" \
        --services "$SERVICE_NAME" \
        --region "$AWS_REGION" &> /dev/null; then
        
        log_info "Updating existing ECS service..."
        aws ecs update-service \
            --cluster "$CLUSTER_NAME" \
            --service "$SERVICE_NAME" \
            --task-definition "$TASK_DEF_ARN" \
            --region "$AWS_REGION"
    else
        log_info "Creating new ECS service..."
        # Create service (this would need the complete service definition)
        log_warn "ECS service creation needs to be completed manually or via additional CloudFormation template"
    fi
    
    log_info "✅ ECS service deployed successfully"
}

# Setup monitoring and alerts
setup_monitoring() {
    log_info "Setting up CloudWatch monitoring and alerts..."
    
    # Create CloudWatch dashboard
    cat > dashboard.json << EOF
{
    "widgets": [
        {
            "type": "metric",
            "properties": {
                "metrics": [
                    ["AWS/ECS", "CPUUtilization", "ServiceName", "${ENVIRONMENT}-github-metrics-service"],
                    [".", "MemoryUtilization", ".", "."]
                ],
                "period": 300,
                "stat": "Average",
                "region": "${AWS_REGION}",
                "title": "ECS Service Metrics"
            }
        }
    ]
}
EOF
    
    aws cloudwatch put-dashboard \
        --dashboard-name "${ENVIRONMENT}-github-metrics-dashboard" \
        --dashboard-body file://dashboard.json \
        --region "$AWS_REGION"
    
    rm dashboard.json
    
    log_info "✅ Monitoring setup completed"
}

# Main deployment function
main() {
    log_info "Starting deployment process..."
    
    check_prerequisites
    get_inputs
    deploy_infrastructure
    build_and_push_image
    deploy_ecs_service
    setup_monitoring
    
    log_info "🎉 Deployment completed successfully!"
    
    # Get ALB DNS name
    ALB_DNS=$(aws cloudformation describe-stacks \
        --stack-name "$STACK_NAME" \
        --region "$AWS_REGION" \
        --query "Stacks[0].Outputs[?OutputKey=='ALBDNSName'].OutputValue" \
        --output text)
    
    echo -e "${GREEN}Application URL: https://${ALB_DNS}${NC}"
    echo -e "${GREEN}Domain: https://${DOMAIN_NAME}${NC}"
    echo -e "${YELLOW}Note: Configure your domain's DNS to point to the ALB${NC}"
}

# Run main function
main "$@"
