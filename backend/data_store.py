import os
import time
from supabase import create_client, Client
from datetime import datetime
from typing import Optional, Dict, Any, List, Union
from config import SUPABASE_URL, SUPABASE_KEY
import logging

logger = logging.getLogger(__name__)

class DataStore:
    def __init__(self):
        """Initialize Supabase connection with proper credentials."""
        self.client: Optional[Client] = None
        self.supabase: Optional[Client] = None
        self._session = None
        
        # Store URL and key for access by frontend
        self.supabase_url = SUPABASE_URL
        self.supabase_key = SUPABASE_KEY
        
        try:
            self.client = create_client(SUPABASE_URL, SUPABASE_KEY)
            self.supabase = self.client  # Keep reference for backward compatibility
            logger.info("Supabase client initialized")
        except Exception as e:
            logger.error(f"Failed to initialize Supabase client: {str(e)}")
            raise e
    
    def authenticate_with_session_data(self, session_data: Dict[str, Any]) -> bool:
        """Authenticate using session data from Supabase auth."""
        try:
            if not session_data:
                return False
            
            # Set the session
            auth_data = {
                'access_token': session_data.get('access_token'),
                'refresh_token': session_data.get('refresh_token'),
                'expires_at': session_data.get('expires_at', int(time.time()) + 3600),
                'user': session_data.get('user')
            }
            
            # Try to set auth context for subsequent requests if we have the tokens
            try:
                if auth_data['access_token'] and auth_data.get('refresh_token'):
                    self.client.auth.set_session(
                        access_token=auth_data['access_token'],
                        refresh_token=auth_data['refresh_token']
                    )
                    logger.info("Successfully set Supabase auth session")
            except Exception as e:
                logger.warning(f"Could not set Supabase auth session: {e}")
            
            # Ensure we have user info for database operations
            if auth_data.get('user') and auth_data['user'].get('email'):
                # Get GitHub token from various possible locations
                github_token = (
                    session_data.get('provider_token') or
                    session_data.get('github_token') or
                    None
                )
                
                github_username = (
                    session_data.get('user', {}).get('user_metadata', {}).get('user_name') or
                    session_data.get('user', {}).get('user_metadata', {}).get('preferred_username') or
                    None
                )
                
                user_id = self.ensure_user_exists_and_get_id(
                    auth_data['user']['email'],
                    github_token,
                    github_username
                )
                
                if user_id:
                    self._session = auth_data
                    logger.info(f"Authentication successful for {auth_data['user']['email']}")
                    if github_token:
                        logger.info("GitHub token found and stored")
                    else:
                        logger.warning("No GitHub token found - will use system token as fallback")
                    return True
                else:
                    logger.error("Failed to create/find user in database")
            else:
                logger.error("No user email found in session data")
            
            return False
        except Exception as e:
            logger.error(f"Authentication failed: {str(e)}")
            return False
    
    def get_base_url(self) -> str:
        """Get the base URL for redirects based on environment."""
        port = os.getenv("STREAMLIT_SERVER_PORT", "8501")
        
        if os.getenv("STREAMLIT_SERVER_PORT"):
            return f"http://localhost:{port}"
        
        supabase_url = os.getenv("SUPABASE_URL", SUPABASE_URL)
        if "localhost" in supabase_url or "127.0.0.1" in supabase_url:
            return "http://localhost:8501"
        
        production_url = os.getenv("PRODUCTION_URL")
        if production_url:
            return production_url
        
        return "http://localhost:8501"
    
    def get_session(self) -> Optional[Dict[str, Any]]:
        """Get current authenticated session"""
        try:
            session = self.client.auth.get_session()
            if session:
                self._session = session
                logger.info("Session retrieved successfully")
                return session
            return None
        except Exception as e:
            logger.error(f"Session retrieval failed: {str(e)}")
            return None
    
    def sign_out(self) -> bool:
        """Sign out the current user and clear all session data completely"""
        try:
            # Step 1: Sign out from Supabase with global scope
            try:
                self.client.auth.sign_out()
            except Exception as e:
                logger.warning(f"Supabase sign_out error (continuing anyway): {e}")
            
            # Step 2: Clear cached session completely
            self._session = None
            
            # Step 3: Try to clear any persistent storage on the client side
            # This is a backend operation, so we can't clear browser storage directly,
            # but we ensure our server-side state is completely clean
            
            # Step 4: Create a new client instance to ensure clean state
            try:
                # Re-initialize the client to ensure no cached auth state
                from config import SUPABASE_URL, SUPABASE_KEY
                self.client = create_client(SUPABASE_URL, SUPABASE_KEY)
                logger.info("Supabase client re-initialized after sign out")
            except Exception as e:
                logger.warning(f"Could not re-initialize Supabase client: {e}")
            
            logger.info("✅ User signed out successfully - all sessions cleared")
            return True
        except Exception as e:
            logger.error(f"Sign out failed: {str(e)}")
            # Even if there are errors, ensure our local session is cleared
            self._session = None
            return False
    
    def handle_oauth_callback(self, code: str) -> Optional[Dict[str, Any]]:
        """Handle OAuth callback and exchange code for session"""
        try:
            # This would typically involve exchanging the code for tokens
            # For now, return None to indicate it needs proper implementation
            logger.warning("OAuth callback handling needs proper implementation")
            return None
        except Exception as e:
            logger.error(f"OAuth callback failed: {str(e)}")
            return None
    
    def get_user_github_token(self, email: str) -> Optional[str]:
        """Get GitHub token for a user"""
        try:
            result = self.supabase.rpc('get_user_github_token', {
                'user_email': email
            }).execute()
            return result.data if result.data else None
        except Exception as e:
            logger.error(f"Error getting GitHub token: {e}")
            return None
    
    def ensure_user_exists_and_get_id(self, email: str, github_token: str = None, github_username: str = None) -> str:
        """Enhanced version that can store GitHub tokens"""
        try:
            # Try to get existing user first
            user = self.get_user_by_email(email)
            if user:
                # Update GitHub token if provided
                if github_token:
                    self.update_user_github_token(email, github_token, github_username)
                return user['id']
            
            # Create new user using the simplified stored procedure
            result = self.supabase.rpc('save_user_metrics', {
                'user_email': email,
                'metrics_data': {}  # Empty metrics for now
            }).execute()
            
            if result.data and len(result.data) > 0:
                # Handle both single result and array of results
                data = result.data[0] if isinstance(result.data, list) else result.data
                if data and data.get('status') == 'success':
                    user_id = data['user_id']
                    
                    # Update GitHub token if provided
                    if github_token:
                        self.update_user_github_token(email, github_token, github_username)
                    
                    logger.info(f"Successfully created/found user {email} with ID {user_id}")
                    return user_id
            
            logger.error(f"Failed to create user - result: {result}")
            return None
        except Exception as e:
            logger.error(f"Error ensuring user exists: {e}")
            return None
    
    def get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        """Get user by email address using stored procedure to bypass RLS"""
        try:
            response = self.client.rpc('get_user_by_email', {'user_email': email}).execute()
            if response.data and len(response.data) > 0:
                return response.data[0]
            return None
        except Exception as e:
            logger.error(f"Error getting user by email: {str(e)}")
            # Fallback to direct query
            try:
                response = self.client.table('users').select('*').eq('email', email).execute()
                if response.data:
                    return response.data[0]
                return None
            except Exception as fallback_e:
                logger.error(f"Fallback query also failed: {str(fallback_e)}")
                return None
    
    def get_user_repos(self, user_id: str) -> List[Dict[str, Any]]:
        """Get all repositories for a user using stored procedure to bypass RLS"""
        try:
            # Get user email from session if available
            user_email = None
            if self._session and 'user' in self._session and 'email' in self._session['user']:
                user_email = self._session['user']['email']
                logger.info(f"Using session email for repos lookup: {user_email}")
            else:
                logger.warning(f"No session email available, cannot retrieve repos for user_id {user_id}")
                return []
            
            # Use stored procedure
            response = self.client.rpc('get_user_repos_data', {'user_email': user_email}).execute()
            
            if response.data:
                logger.info(f"Retrieved {len(response.data)} repos for user {user_email}")
                
                # Transform flat structure to nested structure expected by dashboard
                transformed_repos = []
                for repo_data in response.data:
                    transformed_repo = {
                        'id': repo_data.get('user_repo_id'),  # user_repos table id for deletion
                        'created_at': repo_data.get('repo_created_at', ''),
                        'repos': {
                            'id': repo_data.get('repo_id'),
                            'owner': repo_data.get('owner'),
                            'name': repo_data.get('name'),
                            'full_name': repo_data.get('full_name')
                        }
                    }
                    transformed_repos.append(transformed_repo)
                
                return transformed_repos
            else:
                logger.info(f"No repos found for user {user_email}")
                return []
        except Exception as e:
            logger.error(f"Error getting user repos: {str(e)}")
            return []
    
    def debug_user_repo_data(self, user_email: str) -> Dict[str, Any]:
        """Debug method to check user and repo data"""
        try:
            # Get user info
            user = self.get_user_by_email(user_email)
            logger.info(f"Debug - User data: {user}")
            
            if not user:
                return {"error": "User not found"}
            
            user_id = user['id']
            
            # Check user_repos table
            user_repos_response = self.client.table('user_repos').select('*').eq('user_id', user_id).execute()
            logger.info(f"Debug - user_repos table data: {user_repos_response.data}")
            
            # Check repos table
            repos_response = self.client.table('repos').select('*').execute()
            logger.info(f"Debug - repos table data (first 5): {repos_response.data[:5] if repos_response.data else []}")
            
            return {
                "user": user,
                "user_repos": user_repos_response.data,
                "total_repos": len(repos_response.data) if repos_response.data else 0
            }
        except Exception as e:
            logger.error(f"Error in debug_user_repo_data: {str(e)}")
            return {"error": str(e)}
    
    def delete_user_repo(self, user_id: str, repo_id: str, cleanup_unused_repo: bool = True) -> bool:
        """Remove a repository association for a user"""
        try:
            response = self.client.table('user_repos') \
                .delete() \
                .eq('user_id', user_id) \
                .eq('repo_id', repo_id) \
                .execute()
            
            success = response is not None
            if success:
                logger.info(f"Delete operation completed for user {user_id}, repo {repo_id}")
                logger.info(f"Response data: {response.data}")
                
                # Clean up unused repository if requested
                if cleanup_unused_repo:
                    self._cleanup_unused_repo(repo_id)
            
            return success
        except Exception as e:
            logger.error(f"Error deleting user repo: {str(e)}")
            return False
    
    def delete_user_repo_by_id(self, user_repo_id: str, cleanup_unused_repo: bool = True) -> bool:
        """Remove a repository association by user_repo ID using stored procedure to bypass RLS"""
        try:
            # Get user email from session
            user_email = None
            if self._session and 'user' in self._session and 'email' in self._session['user']:
                user_email = self._session['user']['email']
                logger.info(f"Using session email for deletion: {user_email}")
            else:
                logger.warning(f"No session email available, cannot delete repo for user_repo_id {user_repo_id}")
                return False
            
            # Use stored procedure to delete (bypasses RLS)
            response = self.client.rpc('delete_user_repo_by_id', {
                'user_email': user_email,
                'user_repo_id': user_repo_id
            }).execute()
            
            # For stored procedures, check if the response indicates success
            success = response.data is True if response.data is not None else False
            
            if success:
                logger.info(f"Successfully deleted user_repo_id: {user_repo_id} via stored procedure")
            else:
                logger.warning(f"Stored procedure returned false for user_repo_id: {user_repo_id}")
            
            return success
        except Exception as e:
            logger.error(f"Error deleting user repo by ID: {str(e)}")
            return False
    
    def _cleanup_unused_repo(self, repo_id: str) -> bool:
        """Clean up a repository if no other users are associated with it"""
        try:
            # Check if any other users are still associated with this repo
            associations = self.client.table('user_repos') \
                .select('id') \
                .eq('repo_id', repo_id) \
                .execute()
            
            if not associations.data:
                # No other associations found
                # Safe to delete the repository
                delete_response = self.client.table('repos') \
                    .delete() \
                    .eq('id', repo_id) \
                    .execute()
                
                logger.info(f"Cleaned up unused repository: {repo_id}")
                return True
            else:
                logger.info(f"Repository {repo_id} still has {len(associations.data)} associations, not deleting")
                return False
        except Exception as e:
            logger.warning(f"Error during repository cleanup: {e}")
            return False
    
    def save_user_repo(self, user_email: str, repo_full_name: str) -> bool:
        """Save user repository association using stored procedure"""
        try:
            owner, name = repo_full_name.split('/', 1)
            
            response = self.client.rpc(
                'save_user_repo',
                {
                    'user_email': user_email,
                    'repo_owner': owner,
                    'repo_name': name
                }
            ).execute()
            
            # Log the full response for debugging
            logger.info(f"Save user repo response: {response}")
            
            # Check if the response indicates success
            # The stored procedure might return different formats
            success = False
            if hasattr(response, 'data') and response.data:
                if isinstance(response.data, list) and len(response.data) > 0:
                    # Check if first item has status or is a success indicator
                    first_item = response.data[0]
                    if isinstance(first_item, dict):
                        success = first_item.get('status') == 'success' or first_item.get('success') == True
                    else:
                        # If it's not a dict, assume success if data exists
                        success = True
                elif isinstance(response.data, dict):
                    success = response.data.get('status') == 'success' or response.data.get('success') == True
                else:
                    # For other data types, consider success if data exists
                    success = bool(response.data)
            
            if success:
                logger.info(f"User repo association saved: {user_email} -> {repo_full_name}")
            else:
                logger.error(f"Save user repo failed - response: {response.data if hasattr(response, 'data') else 'No data'}")
            
            return success
        except Exception as e:
            logger.error(f"Error saving user repo: {str(e)}")
            return False
    
    def save_user_metrics(self, email: str, metrics: Dict[str, Any]) -> bool:
        """Save user metrics using stored procedure - simplified to avoid overload conflicts"""
        try:
            # Use the simple version of the stored procedure to avoid conflicts
            response = self.client.rpc(
                'save_user_metrics',
                {
                    'user_email': email,
                    'metrics_data': metrics
                }
            ).execute()
            
            success = hasattr(response, 'data') and response.data
            if success:
                logger.info(f"User metrics saved for {email}")
            else:
                logger.error(f"Save user metrics failed - response: {response.data if hasattr(response, 'data') else 'No data'}")
            
            return success
        except Exception as e:
            # If we get the overload error, try a fallback approach
            if "Could not choose the best candidate function" in str(e):
                logger.warning(f"Function overload error detected, attempting fallback for {email}")
                return self._save_user_metrics_fallback(email, metrics)
            else:
                logger.error(f"Error saving user metrics: {str(e)}")
                return False
    
    def _save_user_metrics_fallback(self, email: str, metrics: Dict[str, Any]) -> bool:
        """Fallback method to save metrics without using stored procedures"""
        try:
            # Get or create user
            user = self.get_user_by_email(email)
            if not user:
                logger.error(f"Could not find or create user for {email}")
                return False
            
            user_id = user['id']
            
            # Save metrics directly to the metrics_user table
            metrics_data = {
                'user_id': user_id,
                'timestamp': datetime.now().isoformat(),
                'metrics_data': metrics
            }
            
            response = self.client.table('metrics_user').insert(metrics_data).execute()
            success = len(response.data) > 0
            
            if success:
                logger.info(f"User metrics saved via fallback for {email}")
            else:
                logger.error(f"Fallback save failed for {email}")
            
            return success
        except Exception as e:
            logger.error(f"Error in fallback save_user_metrics: {str(e)}")
            return False
    
    def save_repo_metrics(self, repo_owner: str, repo_name: str, metrics: Dict[str, Any], user_session: Dict = None) -> bool:
        """Save repository metrics to the database using stored procedure"""
        try:
            # Get current user email from session (use passed session if available)
            session_to_use = user_session or self._session
            user_email = None
            
            if session_to_use and 'user' in session_to_use and 'email' in session_to_use['user']:
                user_email = session_to_use['user']['email']
            
            if not user_email:
                logger.error("Cannot save repository metrics: no authenticated user email")
                return False
            
            # Use stored procedure to save repository metrics (bypasses RLS)
            response = self.client.rpc('save_repo_metrics', {
                'user_email': user_email,
                'repo_owner': repo_owner,
                'repo_name': repo_name,
                'metrics_data': metrics
            }).execute()
            
            # Check if the response indicates success
            success = False
            if hasattr(response, 'data') and response.data:
                if isinstance(response.data, list) and len(response.data) > 0:
                    first_item = response.data[0]
                    if isinstance(first_item, dict):
                        success = first_item.get('status') == 'success'
                        if success:
                            logger.info(f"Repository metrics saved for {repo_owner}/{repo_name} via stored procedure")
                        else:
                            logger.error(f"Stored procedure failed with status: {first_item.get('status')}")
                    else:
                        success = bool(first_item)
                elif isinstance(response.data, dict):
                    success = response.data.get('status') == 'success'
                else:
                    success = bool(response.data)
            
            if not success:
                logger.error(f"Failed to save repository metrics for {repo_owner}/{repo_name} - response: {response.data if hasattr(response, 'data') else 'No data'}")
            
            return success
            
        except Exception as e:
            logger.error(f"Error saving repository metrics for {repo_owner}/{repo_name}: {str(e)}")
            return False
    
    def get_repo_metrics(self, repo_owner: str, repo_name: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Get repository metrics history"""
        try:
            repo_full_name = f"{repo_owner}/{repo_name}"
            
            # Get repository record first
            repo_response = self.client.table('repos').select("*").eq('full_name', repo_full_name).execute()
            
            if not repo_response.data:
                logger.warning(f"Repository {repo_full_name} not found in database")
                return []
            
            repo_id = repo_response.data[0]['id']
            
            # Get metrics for this repository
            metrics_response = self.client.table('metrics_repo') \
                .select("*") \
                .eq('repo_id', repo_id) \
                .order('timestamp', desc=True) \
                .limit(limit) \
                .execute()
            
            if metrics_response.data:
                logger.info(f"Retrieved {len(metrics_response.data)} metrics records for {repo_full_name}")
                return metrics_response.data
            else:
                logger.warning(f"No metrics found for repository {repo_full_name}")
                return []
                
        except Exception as e:
            logger.error(f"Error getting repository metrics for {repo_owner}/{repo_name}: {str(e)}")
            return []
    
    def get_user_metrics(self, user_id: str, limit: int = 30) -> List[Dict[str, Any]]:
        """Get user metrics history using stored procedure to bypass RLS"""
        try:
            # Get user email from session if available
            user_email = None
            if self._session and 'user' in self._session and 'email' in self._session['user']:
                user_email = self._session['user']['email']
                logger.info(f"Using session email for metrics lookup: {user_email}")
            else:
                # Try to get email using stored procedure with user_id
                # This is a workaround - we'll create a helper function
                logger.warning(f"No session email available, cannot retrieve metrics for user_id {user_id}")
                return []
            
            # Use stored procedure
            response = self.client.rpc('get_user_metrics_data', {
                'user_email': user_email,
                'limit_count': limit
            }).execute()
            
            if response.data:
                logger.info(f"Retrieved {len(response.data)} user metrics for {user_email}")
                return response.data
            else:
                logger.warning(f"No metrics found for user {user_email}")
                return []
        except Exception as e:
            logger.error(f"Error getting user metrics: {str(e)}")
            return []
    
    def update_user_github_token(self, email: str, github_token: str, github_username: str = None) -> bool:
        """Update GitHub token for a user"""
        try:
            update_data = {'github_token': github_token}
            if github_username:
                update_data['github_username'] = github_username
            
            response = self.client.table('users') \
                .update(update_data) \
                .eq('email', email) \
                .execute()
            
            success = len(response.data) > 0
            if success:
                logger.info(f"GitHub token updated for {email}")
            
            return success
        except Exception as e:
            logger.error(f"Error updating GitHub token: {str(e)}")
            return False

def get_datastore() -> DataStore:
    """Get or create a DataStore instance."""
    if not hasattr(get_datastore, '_instance'):
        get_datastore._instance = DataStore()
    return get_datastore._instance


class TestDataStore:
    """Mock data store for testing scenarios when real AWS/Supabase config is not available"""
    
    def __init__(self):
        """Initialize test data store with mock data"""
        self._session = None
        logger.info("TestDataStore initialized for testing")
    
    def authenticate_with_session_data(self, session_data: Dict[str, Any]) -> bool:
        """Mock authentication - always succeeds"""
        self._session = session_data
        logger.info("TestDataStore: Mock authentication successful")
        return True
    
    def get_session(self) -> Optional[Dict[str, Any]]:
        """Return mock session"""
        return self._session
    
    def sign_out(self):
        """Mock sign out"""
        self._session = None
        logger.info("TestDataStore: Mock sign out")
        return True
    
    def get_base_url(self) -> str:
        """Return test base URL"""
        return "http://localhost:8501"
    
    def handle_oauth_callback(self, code: str) -> Optional[Dict[str, Any]]:
        """Mock OAuth callback - returns test session"""
        return {
            "user": {
                "id": "test-user-id",
                "email": "test@example.com",
                "name": "Test User"
            },
            "access_token": "test-token",
            "github_token": "test-github-token"
        }
    
    def get_user_github_token(self, email: str) -> Optional[str]:
        """Return mock GitHub token"""
        return "mock-github-token"
    
    def ensure_user_exists_and_get_id(self, email: str, github_token: str = None, github_username: str = None) -> str:
        """Return mock user ID"""
        return "test-user-id"
    
    def get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        """Return mock user data"""
        return {
            'id': 'test-user-id',
            'email': email,
            'github_token': 'mock-token',
            'github_username': 'test-user'
        }
    
    def update_user_github_token(self, email: str, github_token: str, github_username: str = None) -> bool:
        """Mock update - always succeeds"""
        return True
    
    def get_user_repos(self, user_id: str) -> List[Dict[str, Any]]:
        """Return empty repo list for testing"""
        return []
    
    def save_user_repo(self, user_email: str, repo_full_name: str) -> bool:
        """Mock save - always succeeds"""
        return True
    
    def get_user_metrics(self, user_id: str, limit: int = 30) -> List[Dict[str, Any]]:
        """Return empty metrics for testing"""
        return []
    
    def get_repo_metrics(self, repo_owner: str, repo_name: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Return empty repo metrics for testing"""
        return []
    
    def save_user_metrics(self, email: str, metrics: Dict[str, Any]) -> bool:
        """Mock save - always succeeds"""
        logger.info(f"TestDataStore: Mock saved metrics for {email}")
        return True
    
    def save_repo_metrics(self, repo_owner: str, repo_name: str, metrics: Dict[str, Any], user_session: Dict = None) -> bool:
        """Mock save - always succeeds"""
        return True
    
    def delete_user_repo_by_id(self, user_repo_id: str) -> bool:
        """Mock delete - always succeeds"""
        return True
    
    def delete_user_repo(self, user_id: str, repo_id: str) -> bool:
        """Mock delete - always succeeds"""
        return True
