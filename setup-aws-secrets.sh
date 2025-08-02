#!/bin/bash

# AWS Secrets Manager Setup Script
# This script creates all the required secrets for the GitHub Metrics Dashboard

set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}🔐 Setting up AWS Secrets Manager secrets${NC}"
echo -e "${BLUE}===========================================${NC}"

# Load environment variables from .env file
if [ -f .env ]; then
    export $(cat .env | grep -v '^#' | xargs)
    echo -e "${GREEN}✅ Loaded environment variables from .env${NC}"
else
    echo -e "${RED}❌ .env file not found${NC}"
    exit 1
fi

# AWS Region
AWS_REGION=${AWS_REGION:-us-east-1}

# Function to create secret
create_secret() {
    local secret_name="$1"
    local secret_value="$2"
    local description="$3"
    
    echo -e "${YELLOW}Creating secret: ${secret_name}${NC}"
    
    # Check if secret already exists
    if aws secretsmanager describe-secret --secret-id "$secret_name" --region "$AWS_REGION" >/dev/null 2>&1; then
        echo -e "${YELLOW}Secret ${secret_name} already exists, updating...${NC}"
        aws secretsmanager update-secret \
            --secret-id "$secret_name" \
            --secret-string "$secret_value" \
            --region "$AWS_REGION" \
            --description "$description" >/dev/null
    else
        echo -e "${GREEN}Creating new secret: ${secret_name}${NC}"
        aws secretsmanager create-secret \
            --name "$secret_name" \
            --secret-string "$secret_value" \
            --region "$AWS_REGION" \
            --description "$description" >/dev/null
    fi
    
    echo -e "${GREEN}✅ Secret ${secret_name} configured${NC}"
}

# Create all required secrets
echo -e "${BLUE}Creating secrets...${NC}"

create_secret "github-metrics/github-token" "$GITHUB_TOKEN" "GitHub Personal Access Token for API access"
create_secret "github-metrics/github-client-id" "$GITHUB_CLIENT_ID" "GitHub OAuth Client ID"  
create_secret "github-metrics/github-client-secret" "$GITHUB_CLIENT_SECRET" "GitHub OAuth Client Secret"
create_secret "github-metrics/gemini-api-key" "$GEMINI_API_KEY" "Google Gemini API Key for AI analysis"
create_secret "github-metrics/database-url" "$DATABASE_URL" "PostgreSQL database connection URL"

echo -e "${GREEN}🎉 All secrets configured successfully!${NC}"
echo -e "${BLUE}Next steps:${NC}"
echo -e "1. Create ECR repository: aws ecr create-repository --repository-name github-metrics --region $AWS_REGION"
echo -e "2. Build and push Docker image"
echo -e "3. Deploy ECS service"
