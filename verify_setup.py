#!/usr/bin/env python3
"""
Setup Verification Script for GitHub Metrics Dashboard
Validates that all required components are properly configured
"""
import os
import sys
import importlib.util
from pathlib import Path

def check_file_exists(filepath, description):
    """Check if a file exists"""
    if os.path.exists(filepath):
        print(f"SUCCESS: {description}: {filepath}")
        return True
    else:
        print(f"ERROR: {description}: {filepath} - NOT FOUND")
        return False

def check_python_import(module_name, description):
    """Check if a Python module can be imported"""
    try:
        __import__(module_name)
        print(f"SUCCESS: {description}: {module_name}")
        return True
    except ImportError as e:
        print(f"ERROR: {description}: {module_name} - IMPORT ERROR: {e}")
        return False

def check_env_var(var_name, required=True):
    """Check if environment variable is set"""
    value = os.getenv(var_name)
    if value:
        masked_value = f"{value[:8]}...{value[-4:]}" if len(value) > 12 else "***"
        print(f"SUCCESS Environment: {var_name} = {masked_value}")
        return True
    else:
        status = "ERROR: MISSING" if required else "WARNING: NOT SET"
        print(f"{status} Environment: {var_name}")
        return not required

def main():
    """Run all verification checks"""
    print("=" * 60)
    print("GitHub Metrics Dashboard - Setup Verification")
    print("=" * 60)
    
    checks_passed = 0
    total_checks = 0
    
    # Check core application files
    core_files = [
        ("app.py", "Main application launcher"),
        ("config.py", "Configuration file"),
        ("requirements.txt", "Python dependencies"),
        ("Dockerfile", "Docker configuration"),
        ("frontend/dashboard.py", "Streamlit dashboard"),
        ("backend/data_store.py", "Data store module"),
        ("backend/github_api.py", "GitHub API module"),
        ("backend/metrics_calculator.py", "Metrics calculator"),
        ("backend/ml_analyzer.py", "ML analyzer"),
        ("backend/summary_bot.py", "AI summary bot"),
    ]
    
    print("\nChecking Core Files:")
    for filepath, description in core_files:
        if check_file_exists(filepath, description):
            checks_passed += 1
        total_checks += 1
    
    # Check AWS deployment files
    aws_files = [
        (".aws/cloudformation-infrastructure.yml", "CloudFormation template"),
        (".aws/task-definition.json", "ECS task definition"),
        (".github/workflows/aws-deploy.yml", "GitHub Actions workflow"),
        ("deploy-aws.sh", "AWS deployment script"),
    ]
    
    print("\nChecking AWS Deployment Files:")
    for filepath, description in aws_files:
        if check_file_exists(filepath, description):
            checks_passed += 1
        total_checks += 1
    
    # Check Python dependencies
    required_modules = [
        ("streamlit", "Streamlit web framework"),
        ("pandas", "Data analysis library"),
        ("numpy", "Numerical computing"),
        ("plotly", "Interactive plotting"),
        ("requests", "HTTP library"),
        ("psycopg2", "PostgreSQL adapter"),
        ("boto3", "AWS SDK"),
    ]
    
    print("\nChecking Python Dependencies:")
    for module, description in required_modules:
        if check_python_import(module, description):
            checks_passed += 1
        total_checks += 1
    
    # Check environment variables
    print("\nChecking Environment Variables:")
    env_vars = [
        ("GITHUB_TOKEN", True),
        ("DATABASE_URL", True),
        ("GITHUB_CLIENT_ID", True),
        ("GITHUB_CLIENT_SECRET", True),
        ("GEMINI_API_KEY", False),  # Optional due to fallback
        ("AWS_DEPLOYMENT", False),
        ("AWS_REGION", False),
    ]
    
    for var_name, required in env_vars:
        if check_env_var(var_name, required):
            checks_passed += 1
        total_checks += 1
    
    # Summary
    print("\n" + "=" * 60)
    print(f"Verification Results: {checks_passed}/{total_checks} checks passed")
    
    if checks_passed == total_checks:
        print("SUCCESS: All checks passed! Ready for deployment.")
        return 0
    elif checks_passed >= total_checks * 0.8:  # 80% pass rate
        print("WARNING: Most checks passed. Review warnings above.")
        return 0
    else:
        print("ERROR: Several checks failed. Please resolve issues before deployment.")
        return 1

if __name__ == "__main__":
    sys.exit(main())
