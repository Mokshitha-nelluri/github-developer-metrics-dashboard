#!/usr/bin/env python3
"""
GitHub OAuth Setup Helper
Helps configure GitHub OAuth for the GitHub Metrics Dashboard
"""

import os
import sys
import webbrowser
from pathlib import Path

def main():
    print("GitHub OAuth Setup Helper")
    print("=" * 40)
    
    # Check current configuration
    print("\nCurrent Configuration:")
    client_id = os.getenv("GITHUB_CLIENT_ID")
    client_secret = os.getenv("GITHUB_CLIENT_SECRET")
    redirect_uri = os.getenv("OAUTH_REDIRECT_URI", "http://localhost:5000/auth/callback")
    
    print(f"   GITHUB_CLIENT_ID: {'Set' if client_id else 'Not set'}")
    print(f"   GITHUB_CLIENT_SECRET: {'Set' if client_secret else 'Not set'}")
    print(f"   OAUTH_REDIRECT_URI: {redirect_uri}")
    
    if client_id and client_secret:
        print("\nOAuth is already configured!")
        
        if input("\nWould you like to test the OAuth flow? (y/n): ").lower().startswith('y'):
            test_oauth_flow(client_id, redirect_uri)
        return
    
    print("\nOAuth is not configured. Let's set it up!")
    
    # Guide user through setup
    print("\nStep 1: Create GitHub OAuth App")
    print("   1. Go to GitHub Settings → Developer settings → OAuth Apps")
    print("   2. Click 'New OAuth App'")
    print("   3. Use these settings:")
    print(f"      - Application name: GitHub Metrics Dashboard")
    print(f"      - Homepage URL: http://localhost:8501")
    print(f"      - Authorization callback URL: {redirect_uri}")
    print("   4. Click 'Register application'")
    
    if input("\nOpen GitHub OAuth Apps page? (y/n): ").lower().startswith('y'):
        webbrowser.open("https://github.com/settings/developers")
    
    print("\nStep 2: Get Your OAuth Credentials")
    client_id = input("   Enter your GitHub Client ID: ").strip()
    client_secret = input("   Enter your GitHub Client Secret: ").strip()
    
    if not client_id or not client_secret:
        print("ERROR: Client ID and Secret are required!")
        return
    
    # Update .env file
    env_file = Path(".env")
    
    env_content = []
    if env_file.exists():
        with open(env_file, "r") as f:
            env_content = f.readlines()
    
    # Remove existing OAuth lines
    env_content = [line for line in env_content if not any(key in line for key in ["GITHUB_CLIENT_ID", "GITHUB_CLIENT_SECRET", "OAUTH_REDIRECT_URI"])]
    
    # Add new OAuth configuration
    env_content.extend([
        "\n# GitHub OAuth Configuration\n",
        f"GITHUB_CLIENT_ID={client_id}\n",
        f"GITHUB_CLIENT_SECRET={client_secret}\n",
        f"OAUTH_REDIRECT_URI={redirect_uri}\n"
    ])
    
    # Write updated .env file
    with open(env_file, "w") as f:
        f.writelines(env_content)
    
    print(f"\nSUCCESS: OAuth configuration saved to {env_file}")
    print("\nPlease restart the application to load the new configuration.")
    
    if input("\nWould you like to test the OAuth flow now? (y/n): ").lower().startswith('y'):
        # Reload environment
        from dotenv import load_dotenv
        load_dotenv(override=True)
        test_oauth_flow(client_id, redirect_uri)

def test_oauth_flow(client_id: str, redirect_uri: str):
    """Test the OAuth flow"""
    print("\n🧪 Testing OAuth Flow...")
    
    # Construct OAuth URL
    oauth_url = (
        f"https://github.com/login/oauth/authorize"
        f"?client_id={client_id}"
        f"&redirect_uri={redirect_uri}"
        f"&scope=repo,user:email,read:org"
        f"&state=test_oauth"
    )
    
    print(f"\nOAuth URL: {oauth_url}")
    
    if input("\nOpen OAuth URL in browser? (y/n): ").lower().startswith('y'):
        webbrowser.open(oauth_url)
        print("\nWhat to expect:")
        print("   1. Browser opens to GitHub authorization page")
        print("   2. Click 'Authorize' to grant permissions")
        print("   3. You'll be redirected to the callback URL")
        print("   4. The callback server should handle the response")
        print("\nNOTE: Make sure the dashboard is running on http://localhost:8501")
        print("NOTE: Make sure the OAuth callback server is running on port 5000")
    
    print("\nSUCCESS: OAuth test initiated!")
    print("   If you see any errors, check the OAUTH_SETUP.md file for troubleshooting.")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nSetup cancelled by user")
    except Exception as e:
        print(f"\nERROR: {e}")
        sys.exit(1)
