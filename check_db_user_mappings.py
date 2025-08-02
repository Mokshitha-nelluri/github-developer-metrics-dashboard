#!/usr/bin/env python3
"""
Check database values for GitHub username and email associations
Using the credentials from start_dashboard.py
"""

import os
import sys

"""
Database User Mappings Checker

This script checks the user mappings in the database.
Before running, update the environment variables below with your actual values:
- DATABASE_URL: Your PostgreSQL connection string
- GITHUB_TOKEN: Your GitHub personal access token
"""

import os
import sys

# Set up environment like start_dashboard.py does
# IMPORTANT: Replace these with your actual values before running!
os.environ['AWS_DEPLOYMENT'] = 'true'
os.environ['DATABASE_URL'] = 'postgresql://username:password@your-rds-endpoint:5432/database_name'
os.environ['GITHUB_TOKEN'] = 'your-github-token-here'
# GEMINI_API_KEY should be loaded from .env file - removed hardcoded version
os.environ['AWS_REGION'] = 'us-east-1'

# Now import our modules
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from backend.aws_data_store import DataStore
from backend.github_api import GitHubAPI
import json
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def check_database_user_mappings():
    """Check what GitHub usernames and emails are stored in the database"""
    
    print("🔍 CHECKING DATABASE USER MAPPINGS")
    print("=" * 60)
    
    try:
        # Initialize DataStore with AWS credentials
        datastore = DataStore()
        print("✅ Connected to AWS DataStore")
        
        # Check what the current GitHub token returns
        github_api = GitHubAPI(os.environ['GITHUB_TOKEN'])
        token_user = github_api.get_authenticated_user()
        
        print(f"\n🔑 CURRENT TOKEN BELONGS TO:")
        print("-" * 35)
        if token_user:
            print(f"👤 Username: {token_user.get('login')}")
            print(f"📧 Email: {token_user.get('email')}")
            print(f"📝 Name: {token_user.get('name')}")
        
        # Test specific email addresses
        test_emails = [
            'akhil@brynklabs.dev',
            'mokshi.nelluri@gmail.com',
            'mokshitha-nelluri@users.noreply.github.com',
            '149896215+Mokshitha-nelluri@users.noreply.github.com'
        ]
        
        print(f"\n📊 DATABASE LOOKUPS:")
        print("-" * 25)
        
        for email in test_emails:
            try:
                print(f"\n🔍 Checking email: {email}")
                
                # First, get user info to see what's stored in users table
                user_info = datastore.get_user_by_email(email)
                if user_info:
                    print(f"   ✅ USER RECORD FOUND:")
                    print(f"   🆔 User ID: {user_info.get('id')}")
                    print(f"   👤 GitHub Username: {user_info.get('github_username', 'NOT_SET')}")
                    print(f"   � Email: {user_info.get('email')}")
                    print(f"   � Has GitHub Token: {'Yes' if user_info.get('github_token') else 'No'}")
                    print(f"   � Created: {user_info.get('created_at')}")
                    print(f"   🔄 Updated: {user_info.get('updated_at')}")
                    
                    # Now try to get metrics using the user_id
                    user_id = user_info.get('id')
                    if user_id:
                        try:
                            metrics_list = datastore.get_user_metrics(user_id, limit=1)
                            if metrics_list and len(metrics_list) > 0:
                                metrics = metrics_list[0]
                                print(f"   📊 METRICS FOUND:")
                                print(f"   📝 Total Commits: {metrics.get('total_commits', 0)}")
                                print(f"   🔀 Total PRs: {metrics.get('total_prs', 0)}")
                                print(f"   📂 Repos Contributed: {metrics.get('repos_contributed', 0)}")
                                print(f"   🎯 Activity Score: {metrics.get('activity_score', 0)}")
                            else:
                                print(f"   📊 No metrics data found for user_id: {user_id}")
                        except Exception as e:
                            print(f"   ❌ Error getting metrics: {e}")
                else:
                    print(f"   ❌ No user record found")
                    
            except Exception as e:
                print(f"   ❌ Error: {e}")
        
        # Try to get user by attempting save operation to see what gets stored
        print(f"\n🧪 TESTING DATA STORAGE:")
        print("-" * 25)
        
        test_email = 'akhil@brynklabs.dev'
        print(f"Testing with email: {test_email}")
        
        # Create minimal test metrics to see what username gets associated
        test_metrics = {
            'email': test_email,
            'total_repositories': 999,  # Distinctive number for testing
            'total_commits': 777,       # Distinctive number for testing
            'total_prs': 555,          # Distinctive number for testing
            'github_username': 'TEST_USER',  # We'll see if this gets overridden
            'test_timestamp': '2025-08-01_debug_run'
        }
        
        try:
            # This should reveal what username gets stored
            result = datastore.save_user_metrics(test_email, test_metrics)
            print(f"   ✅ Test save completed")
            
            # Now retrieve to see what was actually stored
            retrieved = datastore.get_user_metrics(test_email)
            if retrieved:
                print(f"   📤 Retrieved data:")
                print(f"   👤 Stored GitHub Username: {retrieved.get('github_username', 'NOT_SET')}")
                print(f"   📧 Stored Email: {retrieved.get('email', 'NOT_SET')}")
                print(f"   🔍 Test markers: repos={retrieved.get('total_repositories')}, commits={retrieved.get('total_commits')}")
            
        except Exception as e:
            print(f"   ❌ Test save failed: {e}")
        
        print(f"\n🎯 ANALYSIS:")
        print("=" * 15)
        print("1. The GitHub token belongs to 'Mokshitha-nelluri'")
        print("2. But users are logging in with different emails (like akhil@brynklabs.dev)")
        print("3. The system might be storing the token owner's username regardless of login email")
        print("4. This creates a mismatch: user email ≠ GitHub username")
        print("\n💡 SOLUTION NEEDED:")
        print("   - Use user-specific GitHub tokens (OAuth)")
        print("   - OR fix the username resolution logic")
        print("   - OR ensure the token belongs to the correct user")
        
    except Exception as e:
        print(f"❌ Database check failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    check_database_user_mappings()
