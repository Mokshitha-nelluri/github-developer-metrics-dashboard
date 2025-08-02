"""
AWS-Compatible Data Store - Replaces Supabase for Production Deployment
"""
import os
import psycopg2
import json
import logging
from datetime import datetime
from typing import Optional, Dict, Any, List
from contextlib import contextmanager

logger = logging.getLogger(__name__)

class AWSDataStore:
    """Production data store using AWS RDS PostgreSQL"""
    
    def __init__(self):
        """Initialize AWS-based data connections"""
        # RDS PostgreSQL Connection
        self.database_url = os.getenv("DATABASE_URL")
        if not self.database_url:
            raise ValueError("DATABASE_URL environment variable is required")
            
        self._session = None
        logger.info("AWS Data Store initialized")
    
    @contextmanager
    def get_db_connection(self):
        """Context manager for database connections with proper cleanup"""
        conn = None
        try:
            conn = psycopg2.connect(self.database_url)
            yield conn
        except Exception as e:
            if conn:
                conn.rollback()
            logger.error(f"Database connection error: {e}")
            raise
        finally:
            if conn:
                conn.close()
    
    def authenticate_with_session_data(self, session_data: Dict[str, Any]) -> bool:
        """Authenticate using session data"""
        try:
            if not session_data:
                return False
            
            # Set internal session
            self._session = {
                'access_token': session_data.get('access_token'),
                'user': session_data.get('user', {}),
                'expires_at': session_data.get('expires_at')
            }
            
            logger.info("Session authenticated successfully")
            return True
        except Exception as e:
            logger.error(f"Authentication failed: {e}")
            return False
    
    def get_session(self) -> Optional[Dict[str, Any]]:
        """Get current authenticated session"""
        return self._session
    
    def sign_out(self):
        """Sign out user and clear session"""
        self._session = None
        logger.info("User signed out")
        return True
    
    def get_base_url(self) -> str:
        """Get base URL for OAuth redirects"""
        return "http://localhost:8501"  # Default Streamlit URL
    
    def handle_oauth_callback(self, code: str) -> Optional[Dict[str, Any]]:
        """Handle OAuth callback and exchange code for access token"""
        try:
            import requests
            from config import GITHUB_CLIENT_ID, GITHUB_CLIENT_SECRET, OAUTH_REDIRECT_URI
            
            # Exchange authorization code for access token
            token_url = "https://github.com/login/oauth/access_token"
            token_data = {
                "client_id": GITHUB_CLIENT_ID,
                "client_secret": GITHUB_CLIENT_SECRET,
                "code": code,
                "redirect_uri": OAUTH_REDIRECT_URI
            }
            
            token_headers = {
                "Accept": "application/json",
                "User-Agent": "GitHub-Metrics-App"
            }
            
            logger.info(f"Exchanging OAuth code for access token...")
            token_response = requests.post(token_url, data=token_data, headers=token_headers)
            token_response.raise_for_status()
            
            token_info = token_response.json()
            
            if "access_token" not in token_info:
                logger.error(f"No access token in response: {token_info}")
                return None
            
            access_token = token_info["access_token"]
            
            # Get user information from GitHub
            user_url = "https://api.github.com/user"
            user_headers = {
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/vnd.github.v3+json",
                "User-Agent": "GitHub-Metrics-App"
            }
            
            user_response = requests.get(user_url, headers=user_headers)
            user_response.raise_for_status()
            user_info = user_response.json()
            
            # Get user's primary email
            email_url = "https://api.github.com/user/emails"
            email_response = requests.get(email_url, headers=user_headers)
            email_response.raise_for_status()
            email_info = email_response.json()
            
            # Find primary email
            primary_email = None
            for email in email_info:
                if email.get("primary", False):
                    primary_email = email["email"]
                    break
            
            if not primary_email:
                primary_email = user_info.get("email")
            
            if not primary_email:
                logger.error("Could not determine user's primary email address")
                return None
            
            # Store/update user in database
            github_username = user_info.get("login")
            user_id = self.ensure_user_exists_and_get_id(
                email=primary_email,
                github_token=access_token,
                github_username=github_username
            )
            
            # Create session object
            session_data = {
                "user": {
                    "id": user_id,
                    "email": primary_email,
                    "name": user_info.get("name", github_username),
                    "avatar_url": user_info.get("avatar_url"),
                    "login": github_username
                },
                "access_token": access_token,
                "github_token": access_token,
                "token_type": token_info.get("token_type", "bearer"),
                "scope": token_info.get("scope", "")
            }
            
            logger.info(f"OAuth successful for user: {primary_email} ({github_username})")
            return session_data
            
        except Exception as e:
            logger.error(f"OAuth callback failed: {str(e)}")
            return None
    
    def get_user_github_token(self, email: str) -> Optional[str]:
        """Get user's GitHub token from database"""
        try:
            with self.get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        "SELECT github_token FROM users WHERE email = %s",
                        (email,)
                    )
                    result = cursor.fetchone()
                    return result[0] if result else None
        except Exception as e:
            logger.error(f"Error getting GitHub token: {e}")
            return None
    
    def ensure_user_exists_and_get_id(self, email: str, github_token: str = None, github_username: str = None) -> str:
        """Ensure user exists in database and return user ID"""
        try:
            with self.get_db_connection() as conn:
                with conn.cursor() as cursor:
                    # Check if user exists
                    cursor.execute("SELECT id FROM users WHERE email = %s", (email,))
                    result = cursor.fetchone()
                    
                    if result:
                        user_id = result[0]
                        # Update GitHub token if provided
                        if github_token:
                            cursor.execute(
                                "UPDATE users SET github_token = %s, github_username = %s, updated_at = NOW() WHERE id = %s",
                                (github_token, github_username, user_id)
                            )
                            conn.commit()
                        return str(user_id)
                    else:
                        # Create new user
                        cursor.execute(
                            "INSERT INTO users (email, github_token, github_username) VALUES (%s, %s, %s) RETURNING id",
                            (email, github_token, github_username)
                        )
                        user_id = cursor.fetchone()[0]
                        conn.commit()
                        return str(user_id)
        except Exception as e:
            logger.error(f"Error ensuring user exists: {e}")
            raise
    
    def get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        """Get user data by email"""
        try:
            with self.get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        "SELECT id, email, github_token, github_username, created_at, updated_at FROM users WHERE email = %s",
                        (email,)
                    )
                    result = cursor.fetchone()
                    if result:
                        return {
                            'id': str(result[0]),
                            'email': result[1],
                            'github_token': result[2],
                            'github_username': result[3],
                            'created_at': result[4],
                            'updated_at': result[5]
                        }
                    return None
        except Exception as e:
            logger.error(f"Error getting user by email: {e}")
            return None
    
    def update_user_github_token(self, email: str, github_token: str, github_username: str = None) -> bool:
        """Update user's GitHub token"""
        try:
            with self.get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        "UPDATE users SET github_token = %s, github_username = %s, updated_at = NOW() WHERE email = %s",
                        (github_token, github_username, email)
                    )
                    conn.commit()
                    return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Error updating GitHub token: {e}")
            return False
    
    def get_user_repos(self, user_id: str) -> List[Dict[str, Any]]:
        """Get repositories for a user"""
        try:
            with self.get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("""
                        SELECT r.id, r.owner, r.name, r.full_name, r.description, 
                               r.url, r.language, r.stargazers_count, r.forks_count,
                               ur.role, ur.created_at
                        FROM repos r
                        JOIN user_repos ur ON r.id = ur.repo_id
                        WHERE ur.user_id = %s
                        ORDER BY r.stargazers_count DESC
                    """, (user_id,))
                    
                    results = cursor.fetchall()
                    repos = []
                    for row in results:
                        repos.append({
                            'id': str(row[0]),
                            'owner': row[1],
                            'name': row[2],
                            'full_name': row[3],
                            'description': row[4],
                            'url': row[5],
                            'language': row[6],
                            'stargazers_count': row[7],
                            'forks_count': row[8],
                            'role': row[9],
                            'created_at': row[10]
                        })
                    return repos
        except Exception as e:
            logger.error(f"Error getting user repos: {e}")
            return []
    
    def save_user_repo(self, user_email: str, repo_full_name: str) -> bool:
        """Save a repository for a user"""
        try:
            # Get user by email
            user = self.get_user_by_email(user_email)
            if not user:
                logger.error(f"User not found: {user_email}")
                return False
            
            user_id = user['id']
            
            # Parse repo owner and name
            if '/' not in repo_full_name:
                logger.error(f"Invalid repo format: {repo_full_name}")
                return False
            
            owner, name = repo_full_name.split('/', 1)
            
            with self.get_db_connection() as conn:
                with conn.cursor() as cursor:
                    # Insert or get repository
                    cursor.execute("""
                        INSERT INTO repos (owner, name, full_name)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (full_name) DO NOTHING
                        RETURNING id;
                    """, (owner, name, repo_full_name))
                    
                    result = cursor.fetchone()
                    if result:
                        repo_id = result[0]
                    else:
                        # Repository already exists, get its ID
                        cursor.execute("SELECT id FROM repos WHERE full_name = %s", (repo_full_name,))
                        repo_result = cursor.fetchone()
                        if not repo_result:
                            logger.error(f"Failed to find or create repository: {repo_full_name}")
                            return False
                        repo_id = repo_result[0]
                    
                    # Link user to repository
                    cursor.execute("""
                        INSERT INTO user_repos (user_id, repo_id)
                        VALUES (%s, %s)
                        ON CONFLICT (user_id, repo_id) DO NOTHING;
                    """, (user_id, repo_id))
                    
                    conn.commit()
                    logger.info(f"Successfully linked {user_email} to {repo_full_name}")
                    return True
                    
        except Exception as e:
            logger.error(f"Error saving user repo: {e}")
            return False
    
    def get_user_metrics(self, user_id: str, limit: int = 30) -> List[Dict[str, Any]]:
        """Get user metrics history"""
        try:
            with self.get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("""
                        SELECT date, total_commits, total_prs, total_issues, 
                               contributions_score, repos_contributed, languages, 
                               activity_score, metrics_data, created_at, updated_at,
                               metric_timestamp
                        FROM metrics_user 
                        WHERE user_id = %s 
                        ORDER BY date DESC 
                        LIMIT %s
                    """, (user_id, limit))
                    
                    results = cursor.fetchall()
                    metrics = []
                    for row in results:
                        # Base metrics from columns
                        base_metrics = {
                            'date': row[0].isoformat() if hasattr(row[0], 'isoformat') else str(row[0]),
                            'total_commits': row[1] or 0,
                            'total_prs': row[2] or 0,
                            'total_issues': row[3] or 0,
                            'contributions_score': float(row[4]) if row[4] else 0.0,
                            'repos_contributed': row[5] or 0,
                            'languages': row[6] or {},
                            'activity_score': float(row[7]) if row[7] else 0.0,
                            'created_at': row[9].isoformat() if row[9] and hasattr(row[9], 'isoformat') else str(row[9]) if row[9] else None,
                            'updated_at': row[10].isoformat() if row[10] and hasattr(row[10], 'isoformat') else str(row[10]) if row[10] else None,
                            'metric_timestamp': row[11].isoformat() if row[11] and hasattr(row[11], 'isoformat') else str(row[11]) if row[11] else None
                        }
                        
                        # Merge comprehensive metrics data if available
                        if row[8]:  # metrics_data column
                            comprehensive_data = row[8] if isinstance(row[8], dict) else {}
                            # Merge base metrics with comprehensive data, giving priority to base metrics for core fields
                            final_metrics = {**comprehensive_data, **base_metrics}
                            # Ensure metrics_data key exists for dashboard compatibility
                            final_metrics['metrics_data'] = comprehensive_data
                            metrics.append(final_metrics)
                        else:
                            # Just use base metrics if no comprehensive data
                            base_metrics['metrics_data'] = base_metrics
                            metrics.append(base_metrics)
                    
                    logger.info(f"Retrieved {len(metrics)} user metrics records")
                    return metrics
        except Exception as e:
            logger.error(f"Error getting user metrics: {e}")
            return []
    
    def get_repo_metrics(self, repo_owner: str, repo_name: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Get repository metrics history"""
        try:
            repo_full_name = f"{repo_owner}/{repo_name}"
            
            with self.get_db_connection() as conn:
                with conn.cursor() as cursor:
                    # Get repository ID first
                    cursor.execute("SELECT id FROM repos WHERE full_name = %s", (repo_full_name,))
                    repo_result = cursor.fetchone()
                    
                    if not repo_result:
                        logger.warning(f"Repository {repo_full_name} not found in database")
                        return []
                    
                    repo_id = repo_result[0]
                    
                    # Get metrics for this repository
                    cursor.execute("""
                        SELECT date, stars, forks, watchers, issues, pull_requests,
                               contributors, commits, releases, health_score, 
                               activity_score, created_at, updated_at
                        FROM metrics_repo 
                        WHERE repo_id = %s 
                        ORDER BY date DESC 
                        LIMIT %s
                    """, (repo_id, limit))
                    
                    results = cursor.fetchall()
                    metrics = []
                    for row in results:
                        metrics.append({
                            'date': row[0].isoformat() if row[0] else None,
                            'stars': row[1] or 0,
                            'forks': row[2] or 0,
                            'watchers': row[3] or 0,
                            'issues': row[4] or 0,
                            'pull_requests': row[5] or 0,
                            'contributors': row[6] or 0,
                            'commits': row[7] or 0,
                            'releases': row[8] or 0,
                            'health_score': float(row[9]) if row[9] else 0.0,
                            'activity_score': float(row[10]) if row[10] else 0.0,
                            'created_at': row[11].isoformat() if row[11] else None,
                            'updated_at': row[12].isoformat() if row[12] else None
                        })
                    
                    logger.info(f"Retrieved {len(metrics)} repo metrics records for {repo_full_name}")
                    return metrics
        except Exception as e:
            logger.error(f"Error getting repo metrics: {e}")
            return []
    
    def save_user_metrics(self, email: str, metrics: Dict[str, Any]) -> bool:
        """Save user metrics to database"""
        try:
            # Get user ID first
            user = self.get_user_by_email(email)
            if not user:
                logger.error(f"User not found for email: {email}")
                return False

            user_id = user['id']

            with self.get_db_connection() as conn:
                with conn.cursor() as cursor:
                    # Insert or update metrics with FULL comprehensive data
                    cursor.execute("""
                        INSERT INTO metrics_user 
                        (user_id, date, total_commits, total_prs, total_issues, 
                         contributions_score, repos_contributed, languages, activity_score, metrics_data)
                        VALUES (%s, CURRENT_DATE, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (user_id, date) 
                        DO UPDATE SET
                            total_commits = EXCLUDED.total_commits,
                            total_prs = EXCLUDED.total_prs,
                            total_issues = EXCLUDED.total_issues,
                            contributions_score = EXCLUDED.contributions_score,
                            repos_contributed = EXCLUDED.repos_contributed,
                            languages = EXCLUDED.languages,
                            activity_score = EXCLUDED.activity_score,
                            metrics_data = EXCLUDED.metrics_data,
                            updated_at = NOW()
                    """, (
                        user_id,
                        metrics.get('total_commits', 0),
                        metrics.get('total_prs', 0),
                        metrics.get('total_issues', 0),
                        metrics.get('contributions_score', 0),
                        metrics.get('repos_contributed', 0),
                        json.dumps(metrics.get('languages', {})),
                        metrics.get('activity_score', 0),
                        json.dumps(metrics)  # Save the COMPLETE metrics data as JSONB
                    ))
                    conn.commit()
                    logger.info(f"Saved comprehensive user metrics for {email} (including DORA, repository breakdowns, etc.)")
                    return True
        except Exception as e:
            logger.error(f"Error saving user metrics: {e}")
            return False

    def save_repo_metrics(self, repo_owner: str, repo_name: str, metrics: Dict[str, Any], user_session: Dict = None) -> bool:
        """Save repository metrics to database"""
        try:
            repo_full_name = f"{repo_owner}/{repo_name}"
            
            with self.get_db_connection() as conn:
                with conn.cursor() as cursor:
                    # Get or create repository
                    cursor.execute("SELECT id FROM repos WHERE full_name = %s", (repo_full_name,))
                    repo_result = cursor.fetchone()
                    
                    if not repo_result:
                        # Create repository record (simplified)
                        cursor.execute("""
                            INSERT INTO repos (owner, name, full_name, description, url, language)
                            VALUES (%s, %s, %s, %s, %s, %s)
                            RETURNING id
                        """, (
                            repo_owner, repo_name, repo_full_name,
                            metrics.get('description', ''),
                            metrics.get('url', ''),
                            metrics.get('language', '')
                        ))
                        repo_id = cursor.fetchone()[0]
                    else:
                        repo_id = repo_result[0]
                    
                    # Insert or update metrics
                    cursor.execute("""
                        INSERT INTO metrics_repo 
                        (repo_id, date, stars, forks, watchers, issues, pull_requests,
                         contributors, commits, releases, health_score, activity_score)
                        VALUES (%s, CURRENT_DATE, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (repo_id, date) 
                        DO UPDATE SET
                            stars = EXCLUDED.stars,
                            forks = EXCLUDED.forks,
                            watchers = EXCLUDED.watchers,
                            issues = EXCLUDED.issues,
                            pull_requests = EXCLUDED.pull_requests,
                            contributors = EXCLUDED.contributors,
                            commits = EXCLUDED.commits,
                            releases = EXCLUDED.releases,
                            health_score = EXCLUDED.health_score,
                            activity_score = EXCLUDED.activity_score,
                            updated_at = NOW()
                    """, (
                        repo_id,
                        metrics.get('stars', 0),
                        metrics.get('forks', 0),
                        metrics.get('watchers', 0),
                        metrics.get('issues', 0),
                        metrics.get('pull_requests', 0),
                        metrics.get('contributors', 0),
                        metrics.get('commits', 0),
                        metrics.get('releases', 0),
                        metrics.get('health_score', 0),
                        metrics.get('activity_score', 0)
                    ))
                    conn.commit()
                    logger.info(f"Saved repo metrics for {repo_full_name}")
                    return True
        except Exception as e:
            logger.error(f"Error saving repo metrics: {e}")
            return False
    
    def delete_user_repo_by_id(self, user_repo_id: str) -> bool:
        """Delete a user-repo relationship by user_repo table ID"""
        try:
            with self.get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("DELETE FROM user_repos WHERE id = %s", (user_repo_id,))
                    deleted_count = cursor.rowcount
                    conn.commit()
                    
                    logger.info(f"Deleted user-repo relationship (ID: {user_repo_id})")
                    return deleted_count > 0
        except Exception as e:
            logger.error(f"Error deleting user repo by ID: {e}")
            return False
    
    def delete_user_repo(self, user_id: str, repo_id: str) -> bool:
        """Delete a user-repo relationship by user_id and repo_id"""
        try:
            with self.get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        "DELETE FROM user_repos WHERE user_id = %s AND repo_id = %s", 
                        (user_id, repo_id)
                    )
                    deleted_count = cursor.rowcount
                    conn.commit()
                    
                    logger.info(f"Deleted user-repo relationship (User: {user_id}, Repo: {repo_id})")
                    return deleted_count > 0
        except Exception as e:
            logger.error(f"Error deleting user repo: {e}")
            return False


# Compatibility function for existing code
def DataStore():
    """Factory function that returns appropriate data store based on environment"""
    if os.getenv("AWS_DEPLOYMENT") == "true":
        # For testing in AWS mode, return a mock data store if no real AWS config
        try:
            return AWSDataStore()
        except Exception as e:
            # If AWS DataStore fails (no real config), return a test-friendly version
            logger.warning(f"AWS DataStore failed ({e}), falling back to TestDataStore for testing")
            from backend.data_store import TestDataStore
            return TestDataStore()
    else:
        # Return original Supabase-based DataStore for development
        try:
            from backend.data_store import DataStore as SupabaseDataStore
            return SupabaseDataStore()
        except Exception as e:
            logger.warning(f"Supabase DataStore failed ({e}), falling back to TestDataStore for testing")
            from backend.data_store import TestDataStore
            return TestDataStore() 