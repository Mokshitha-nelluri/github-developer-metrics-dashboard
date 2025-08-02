import os
from dotenv import load_dotenv

# Always load .env file if it exists (for local development with AWS mode)
load_dotenv()

# =============================================================================
# ENVIRONMENT DETECTION
# =============================================================================
IS_AWS_DEPLOYMENT = os.getenv("AWS_DEPLOYMENT", "true").lower() == "true"

# =============================================================================
# DATABASE CONFIGURATION
# =============================================================================
if IS_AWS_DEPLOYMENT:
    # AWS RDS PostgreSQL + ElastiCache Redis
    DATABASE_URL = os.getenv("DATABASE_URL", "dummy_database_url")
    REDIS_URL = os.getenv("REDIS_URL")
    AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
    
    # Set Supabase variables to None for AWS mode
    SUPABASE_URL = None
    SUPABASE_KEY = None
    
    # Remove the DATABASE_URL requirement check for testing
    # if not DATABASE_URL:
    #     raise ValueError("DATABASE_URL is required for AWS deployment")
else:
    # Development: Supabase
    SUPABASE_URL = os.getenv("SUPABASE_URL")
    SUPABASE_KEY = os.getenv("SUPABASE_KEY")
    
    # Set AWS variables to None for development mode
    DATABASE_URL = None
    REDIS_URL = None
    AWS_REGION = None
    
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise ValueError("SUPABASE_URL and SUPABASE_KEY are required for development")

# =============================================================================
# API KEYS (Both environments)
# =============================================================================
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_CLIENT_ID = os.getenv("GITHUB_CLIENT_ID", "dummy_client_id")
GITHUB_CLIENT_SECRET = os.getenv("GITHUB_CLIENT_SECRET", "dummy_client_secret")

# OAuth redirect URI for AWS mode
def get_oauth_redirect_uri():
    """Get the OAuth redirect URI dynamically based on environment"""
    if IS_AWS_DEPLOYMENT:
        # In AWS, try to get the current public IP
        try:
            import requests
            # Try AWS EC2 instance metadata service first
            try:
                response = requests.get(
                    "http://169.254.169.254/latest/meta-data/public-ipv4",
                    timeout=2
                )
                if response.status_code == 200:
                    public_ip = response.text.strip()
                    return f"http://{public_ip}:5000/auth/callback"
            except:
                pass
            
            # Fallback to external IP detection service
            try:
                response = requests.get("https://api.ipify.org", timeout=5)
                if response.status_code == 200:
                    public_ip = response.text.strip()
                    return f"http://{public_ip}:5000/auth/callback"
            except:
                pass
        except ImportError:
            pass
    
    # Fallback to environment variable or localhost
    return os.getenv("OAUTH_REDIRECT_URI", "http://localhost:5000/auth/callback")

OAUTH_REDIRECT_URI = get_oauth_redirect_uri()

# Streamlit base URL for OAuth redirects
STREAMLIT_BASE_URL = os.getenv("STREAMLIT_BASE_URL", "http://localhost:8501")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY is not set in environment variables.")

# =============================================================================
# APPLICATION SETTINGS
# =============================================================================
AUTO_REFRESH_INTERVAL = int(os.getenv("AUTO_REFRESH_INTERVAL", 900))  # 15 minutes default
FORECAST_DAYS = int(os.getenv("FORECAST_DAYS", 14))
SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key-change-in-production")
# OAUTH_REDIRECT_URI is set above using get_oauth_redirect_uri() function

# =============================================================================
# DEPLOYMENT INFO
# =============================================================================
print(f"Deployment Mode: {'AWS Production' if IS_AWS_DEPLOYMENT else 'Development (Supabase)'}")
print(f"Database: {'RDS PostgreSQL' if IS_AWS_DEPLOYMENT else 'Supabase PostgreSQL'}")
print(f"Cache: {'ElastiCache Redis' if IS_AWS_DEPLOYMENT else 'None'}")