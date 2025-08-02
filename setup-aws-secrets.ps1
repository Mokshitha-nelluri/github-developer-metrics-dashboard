# AWS Secrets Manager Setup Script for Windows PowerShell
# This script creates all the required secrets for the GitHub Metrics Dashboard

Write-Host "🔐 Setting up AWS Secrets Manager secrets" -ForegroundColor Blue
Write-Host "==========================================" -ForegroundColor Blue

# Load environment variables from .env file
if (Test-Path ".env") {
    Get-Content ".env" | ForEach-Object {
        if ($_ -match "^([^#].*?)=(.*)$") {
            $name = $matches[1]
            $value = $matches[2]
            [Environment]::SetEnvironmentVariable($name, $value, "Process")
        }
    }
    Write-Host "✅ Loaded environment variables from .env" -ForegroundColor Green
} else {
    Write-Host "❌ .env file not found" -ForegroundColor Red
    exit 1
}

# AWS Region
$AWS_REGION = if ($env:AWS_REGION) { $env:AWS_REGION } else { "us-east-1" }

# Function to create secret
function Create-Secret {
    param(
        [string]$SecretName,
        [string]$SecretValue,
        [string]$Description
    )
    
    Write-Host "Creating secret: $SecretName" -ForegroundColor Yellow
    
    # Check if secret already exists
    try {
        aws secretsmanager describe-secret --secret-id $SecretName --region $AWS_REGION --output none 2>$null
        Write-Host "Secret $SecretName already exists, updating..." -ForegroundColor Yellow
        aws secretsmanager update-secret --secret-id $SecretName --secret-string $SecretValue --region $AWS_REGION --description $Description --output none
    } catch {
        Write-Host "Creating new secret: $SecretName" -ForegroundColor Green
        aws secretsmanager create-secret --name $SecretName --secret-string $SecretValue --region $AWS_REGION --description $Description --output none
    }
    
    Write-Host "✅ Secret $SecretName configured" -ForegroundColor Green
}

# Create all required secrets
Write-Host "Creating secrets..." -ForegroundColor Blue

Create-Secret "github-metrics/github-token" $env:GITHUB_TOKEN "GitHub Personal Access Token for API access"
Create-Secret "github-metrics/github-client-id" $env:GITHUB_CLIENT_ID "GitHub OAuth Client ID"
Create-Secret "github-metrics/github-client-secret" $env:GITHUB_CLIENT_SECRET "GitHub OAuth Client Secret"  
Create-Secret "github-metrics/gemini-api-key" $env:GEMINI_API_KEY "Google Gemini API Key for AI analysis"
Create-Secret "github-metrics/database-url" $env:DATABASE_URL "PostgreSQL database connection URL"

Write-Host "🎉 All secrets configured successfully!" -ForegroundColor Green
Write-Host "Next steps:" -ForegroundColor Blue
Write-Host "1. Create ECR repository: aws ecr create-repository --repository-name github-metrics --region $AWS_REGION"
Write-Host "2. Build and push Docker image"
Write-Host "3. Deploy ECS service"
