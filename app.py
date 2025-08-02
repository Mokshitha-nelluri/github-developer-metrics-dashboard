#!/usr/bin/env python3
"""
GitHub Metrics Dashboard - Main Application Entry Point
Unified launcher for local development and production deployment
"""
import os
import sys
import subprocess
import threading
import time
from pathlib import Path

def setup_environment(mode='production'):
    """Set up environment variables based on deployment mode"""
    
    # Always load .env file first if it exists
    from dotenv import load_dotenv
    if os.path.exists('.env'):
        load_dotenv(override=True)
        print(f"[ENV] Loaded environment from .env file")
    
    if mode == 'production':
        # AWS/Production deployment configuration
        # Try to get from environment (loaded from .env or system)
        env_vars = {
            'AWS_DEPLOYMENT': 'true',
            'DATABASE_URL': os.getenv('DATABASE_URL'),
            'GEMINI_API_KEY': os.getenv('GEMINI_API_KEY'),
            'GITHUB_TOKEN': os.getenv('GITHUB_TOKEN'),
            'GITHUB_CLIENT_ID': os.getenv('GITHUB_CLIENT_ID'),
            'GITHUB_CLIENT_SECRET': os.getenv('GITHUB_CLIENT_SECRET'),
            'OAUTH_REDIRECT_URI': os.getenv('OAUTH_REDIRECT_URI', 'http://localhost:5000/auth/callback'),
            'AWS_REGION': os.getenv('AWS_REGION', 'us-east-1')
        }
        
        # Validate required environment variables
        required_vars = ['DATABASE_URL', 'GEMINI_API_KEY', 'GITHUB_TOKEN', 'GITHUB_CLIENT_ID', 'GITHUB_CLIENT_SECRET']
        missing_vars = [var for var in required_vars if not env_vars.get(var)]
        if missing_vars:
            print(f"[ERROR] Missing required environment variables: {', '.join(missing_vars)}")
            print(f"[HINT] Make sure these are set in your .env file or system environment")
            return False
            
        print(f"[ENV] Configured for AWS Production deployment")
    else:
        # Development mode - load from .env file
        if os.path.exists('.env'):
            with open('.env', 'r') as f:
                for line in f:
                    if '=' in line and not line.strip().startswith('#'):
                        key, value = line.strip().split('=', 1)
                        os.environ[key] = value
            print(f"[ENV] Loaded development environment from .env")
        else:
            print(f"[WARNING] .env file not found for development mode")
            return False
    
    # Set environment variables (only log non-sensitive ones)
    for key, value in env_vars.items():
        if value:  # Only set if value exists
            os.environ[key] = value
            if key in ['DATABASE_URL', 'GEMINI_API_KEY', 'GITHUB_TOKEN', 'GITHUB_CLIENT_SECRET']:
                # Mask sensitive values
                masked_value = f"{value[:8]}...{value[-4:]}" if len(value) > 12 else "***"
                print(f"[ENV] {key} = {masked_value}")
            else:
                print(f"[ENV] {key} = {value}")
        else:
            print(f"[ENV] {key} = NOT SET")
    
    return True

def start_auth_server(port=8502):
    """Start the authentication server in background"""
    try:
        print(f"🔐 Starting auth server on port {port}...")
        subprocess.run([
            sys.executable, "auth_server.py", str(port)
        ], check=True)
    except Exception as e:
        print(f"❌ Auth server failed: {e}")

def start_streamlit_app(port=8501, mode='production'):
    """Start the Streamlit dashboard with background services"""
    
    print("=" * 60)
    print("GitHub Metrics Dashboard - Starting...")
    print("=" * 60)
    
    # Setup environment
    if not setup_environment(mode):
        return False
    
    # Display configuration info
    db_info = "AWS RDS PostgreSQL" if mode == 'production' else "Local Development"
    print(f"[INFO] Database: {db_info}")
    print(f"[INFO] Mode: {mode.title()}")
    print(f"[INFO] Dashboard URL: http://localhost:{port}")
    if mode == 'production':
        print(f"[NOTE] Gemini API may show quota warnings - fallback analysis will be used")
    
    # Try to start background services for performance optimization
    try:
        print(f"[INFO] Starting background services for performance optimization...")
        
        # Start background metrics service if available
        if os.path.exists("backend/background_metrics_service.py"):
            from backend.background_metrics_service import start_background_service
            
            # Try to start background service
            service_started = start_background_service()
            if service_started:
                print(f"✅ Background metrics service started successfully")
            else:
                print(f"⚠️ Background metrics service failed to initialize, using standard mode")
        else:
            print(f"⚠️ Background metrics service not found, using standard mode")
            
    except Exception as e:
        print(f"⚠️ Background services not available: {e}")
        print(f"[INFO] Continuing with standard mode (this is normal for development)...")
        # Don't fail the app if background services can't start
    
    print("=" * 60)
    
    # Find dashboard file
    dashboard_path = os.path.join("frontend", "dashboard.py")
    if not os.path.exists(dashboard_path):
        print(f"[ERROR] Dashboard file not found: {dashboard_path}")
        print(f"[INFO] Current directory: {os.getcwd()}")
        return False
    
    # Determine Python executable
    venv_python = os.path.join("venv", "Scripts", "python.exe")
    if os.path.exists(venv_python):
        python_executable = venv_python
        print(f"[INFO] Using virtual environment Python")
    else:
        python_executable = sys.executable
        print(f"[INFO] Using system Python")
    
    # Build streamlit command
    cmd = [
        python_executable, "-m", "streamlit", "run", 
        dashboard_path,
        f"--server.port={port}",
        "--server.address=localhost",
        "--server.headless=false",
        "--browser.gatherUsageStats=false"
    ]
    
    try:
        print(f"[INFO] Starting dashboard...")
        print(f"[CMD] {' '.join(cmd)}")
        
        # Start the process
        subprocess.run(cmd, env=os.environ)
        return True
        
    except KeyboardInterrupt:
        print(f"\n[INFO] Dashboard stopped by user")
        return True
    except Exception as e:
        print(f"[ERROR] Failed to start dashboard: {e}")
        return False

def main():
    """Main entry point with command line argument support"""
    
    # Parse command line arguments
    mode = 'production'  # Default to production
    port = 8501
    start_auth = False
    
    if len(sys.argv) > 1:
        if '--dev' in sys.argv or '--development' in sys.argv:
            mode = 'development'
            start_auth = True  # Development mode needs auth server
        if '--port' in sys.argv:
            try:
                port_idx = sys.argv.index('--port') + 1
                port = int(sys.argv[port_idx])
            except (IndexError, ValueError):
                print("❌ Invalid port specified")
                return 1
        if '--help' in sys.argv or '-h' in sys.argv:
            print("""
GitHub Metrics Dashboard Launcher

Usage:
  python app.py                    # Production mode (default)
  python app.py --dev              # Development mode
  python app.py --port 8502        # Custom port
  python app.py --dev --port 8502  # Development mode with custom port

Modes:
  production  : Uses AWS RDS database, GitHub OAuth
  development : Uses .env file, local Supabase auth server
            """)
            return 0
    
    print(f"GitHub Metrics Dashboard Launcher")
    print(f"Mode: {mode.title()}")
    
    # Check .env file for development mode
    if mode == 'development' and not os.path.exists('.env'):
        print("❌ .env file not found!")
        print("Please copy .env.example to .env and fill in your values")
        return 1
    
    try:
        # Start auth server in background for development mode
        if start_auth:
            auth_thread = threading.Thread(
                target=start_auth_server, 
                args=(8502,), 
                daemon=True
            )
            auth_thread.start()
            time.sleep(2)  # Give auth server time to start
        
        # Start Streamlit (this will block)
        success = start_streamlit_app(port, mode)
        
        return 0 if success else 1
        
    except KeyboardInterrupt:
        print("\n👋 Shutting down...")
        return 0
    except Exception as e:
        print(f"❌ Startup failed: {e}")
        return 1

if __name__ == "__main__":
    sys.exit(main())
