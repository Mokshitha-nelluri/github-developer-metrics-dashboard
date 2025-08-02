import sys
import os
import time
import threading
import asyncio
import logging

# Ensure the project root is in sys.path for module resolution
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
from typing import Dict, List, Any, Optional

from backend.aws_data_store import DataStore
from backend.github_api import GitHubAPI
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from enhanced_github_api import EnhancedGitHubAPI
from backend.metrics_calculator import EnhancedMetricsCalculator
from backend.ml_analyzer import EnhancedMLAnalyzer
from backend.summary_bot import AISummaryBot
from config import SUPABASE_URL, SUPABASE_KEY, GITHUB_TOKEN, GEMINI_API_KEY
import logging
from backend.refresh_manager import MetricsRefreshManager

from visualization import (
    create_radar_chart,
    create_forecast_chart,
    create_commit_trend_chart,
    create_activity_heatmap,
    create_performance_timeline_chart,
    create_dora_metrics_dashboard,
    create_work_life_balance_chart,
    create_line_chart,
    create_bar_chart,
    create_pie_chart
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize components
@st.cache_resource
def get_datastore():
    return DataStore()

@st.cache_resource
def get_github_api(user_session=None):
    """Get Enhanced GitHub API client - uses user's token if available, falls back to system token"""
    if user_session:
        # Try to get user's GitHub token from session
        user_github_token = None
        if hasattr(user_session, 'github_token'):
            user_github_token = user_session.github_token
        elif isinstance(user_session, dict) and 'github_token' in user_session:
            user_github_token = user_session['github_token']
        elif hasattr(user_session, 'provider_token'):
            user_github_token = user_session.provider_token
        elif isinstance(user_session, dict) and 'provider_token' in user_session:
            user_github_token = user_session['provider_token']
        
        if user_github_token:
            logger.info(f"Using user's GitHub token for Enhanced API calls (token: {user_github_token[:4]}...{user_github_token[-4:]})")
            return EnhancedGitHubAPI(user_github_token)
        else:
            logger.warning("No GitHub token found in user session, falling back to system token")
            logger.warning(f"Session structure: {type(user_session)} with keys: {list(user_session.keys()) if isinstance(user_session, dict) else 'not a dict'}")
    
    # Fallback to system token
    logger.info(f"Using system GitHub token for Enhanced API calls (token: {GITHUB_TOKEN[:4]}...{GITHUB_TOKEN[-4:]})")
    return EnhancedGitHubAPI(GITHUB_TOKEN)

@st.cache_resource
def get_metrics_calculator():
    return EnhancedMetricsCalculator()

@st.cache_resource
def get_ml_analyzer():
    return EnhancedMLAnalyzer()

@st.cache_resource
def get_summary_bot():
    return AISummaryBot(GEMINI_API_KEY)

@st.cache_resource
def get_refresh_manager(github_token: str):
    """Get a cached refresh manager instance."""
    from backend.refresh_manager import MetricsRefreshManager
    return MetricsRefreshManager(github_token)

def refresh_metrics(email, scope, force=False, user_session=None):
    """Refresh metrics for the current user/repo with performance optimization"""
    logger.info(f"refresh_metrics called: email={email}, scope={scope}, user_session type={type(user_session)}")
    
    # Import performance optimization modules
    try:
        from backend.background_metrics_service import get_user_metrics_fast
        from backend.continuous_ml_learning import process_user_ml_on_login
        use_fast_metrics = True
    except ImportError:
        logger.warning("Performance optimization modules not available, using standard approach")
        use_fast_metrics = False
    
    db = get_datastore()
    github = get_github_api(user_session)
    calculator = get_metrics_calculator()
    
    # Debug: Log the GitHub token being used
    if user_session:
        if isinstance(user_session, dict):
            token_preview = user_session.get('github_token', 'No github_token')[:4] + "..." if user_session.get('github_token') else 'No github_token'
            provider_token_preview = user_session.get('provider_token', 'No provider_token')[:4] + "..." if user_session.get('provider_token') else 'No provider_token'
            logger.info(f"User session github_token: {token_preview}, provider_token: {provider_token_preview}")
    
    # Use fast metrics if available
    if use_fast_metrics and scope == "global" and not force:
        try:
            import asyncio
            user_github_token = None
            if user_session and isinstance(user_session, dict):
                user_github_token = user_session.get('github_token') or user_session.get('provider_token')
            
            # Get metrics using fast cached approach
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            metrics = loop.run_until_complete(get_user_metrics_fast(email, user_github_token))
            loop.close()
            
            if metrics and not metrics.get('error'):
                # Trigger ML processing in background (don't wait for it)
                try:
                    ml_thread = threading.Thread(
                        target=lambda: asyncio.run(process_user_ml_on_login(email, db)),
                        daemon=True
                    )
                    ml_thread.start()
                    logger.info(f"🧠 Triggered background ML processing for {email}")
                except Exception as e:
                    logger.warning(f"Failed to trigger ML processing: {e}")
                
                return True
            else:
                logger.warning("Fast metrics failed, falling back to standard approach")
        except Exception as e:
            logger.error(f"Fast metrics error: {e}, falling back to standard approach")
    
    # Get the correct GitHub username from the user's token
    github_user_info = github.get_authenticated_user()
    if not github_user_info:
        logger.error("Failed to get GitHub user info from token")
        return False
    
    github_username = github_user_info.get('login')
    if not github_username:
        logger.error("No GitHub username found in user info")
        return False
    
    logger.info(f"✅ Using GitHub username from token: {github_username}")
    
    # Extract the user's GitHub token from the session or headers
    user_github_token = None
    if user_session and isinstance(user_session, dict):
        user_github_token = user_session.get('github_token') or user_session.get('provider_token')
    
    # Determine user ID with correct GitHub username
    user_id = db.ensure_user_exists_and_get_id(email, user_github_token, github_username)
    if not user_id:
        logger.error(f"Failed to get user_id for email: {email}")
        return False
    
    logger.info(f"User ID: {user_id}")
    
    if scope == "global":
        # For global scope, fetch user's repositories and aggregate data
        try:
            logger.info("Fetching user repositories...")
            
            # Fetch ALL repositories (both private and public) - this is the complete GitHub activity
            logger.info("Fetching all repositories (both private and public) using enhanced discovery...")
            # Use enhanced repository discovery - finds ALL accessible repos including org repos
            user_repos = github.discover_all_accessible_repositories(include_private=True)
            
            # Count private vs public for logging
            private_count = sum(1 for repo in user_repos if repo.get('isPrivate', False))
            public_count = len(user_repos) - private_count
            logger.info(f"Enhanced discovery found {len(user_repos)} total repositories: {private_count} private, {public_count} public")
            
            # Only fall back to basic method if enhanced discovery finds nothing
            if not user_repos:
                logger.info("Enhanced discovery found no repos, trying basic public-only fallback...")
                user_repos = github.fetch_user_repositories(limit=200, include_private=False)
                public_count = len(user_repos)
                logger.info(f"Fetched {public_count} repositories (public only - token may lack private repo access)")
            
            if not user_repos:
                logger.warning("No repositories found at all - check token permissions")
                logger.warning("Required token scopes: repo, user, read:org")
                return False
            
            # Log repository details for debugging
            logger.info("Repository details (showing both private and public):")
            for i, repo in enumerate(user_repos[:5]):  # Show first 5 for debugging
                owner = repo.get('owner', {}).get('login', 'Unknown')
                name = repo.get('name', 'Unknown')
                is_private = repo.get('isPrivate', False)
                repo_type = "🔒 Private" if is_private else "🌍 Public"
                logger.info(f"  {i+1}. {owner}/{name} ({repo_type})")
            
            if len(user_repos) > 5:
                logger.info(f"  ... and {len(user_repos) - 5} more repositories")
                logger.info(f"Total activity scope: {private_count} private + {public_count} public = {len(user_repos)} repositories")
            
            all_commits = []
            all_prs = []
            
            # Aggregate data from ALL user repositories (both private and public)
            for repo in user_repos[:20]:  # Process more repositories for complete analysis
                try:
                    owner = repo.get('owner', {}).get('login', '')
                    name = repo.get('name', '')
                    is_private = repo.get('isPrivate', False)
                    repo_type = "private" if is_private else "public"
                    
                    if owner and name:
                        # NOTE: For global analysis, we DON'T automatically save repos to tracked list
                        # Users should manually add repositories they want to track
                        
                        logger.debug(f"Analyzing {repo_type} repo: {owner}/{name} (not adding to tracked list)")
                        # Fetch ALL-TIME commits and PRs (complete repository history)
                        commits = github.fetch_commits(owner, name, developer_email=email)
                        prs = github.fetch_pull_requests(owner, name, developer_email=email)
                        all_commits.extend(commits)
                        all_prs.extend(prs)
                except Exception as e:
                    logger.warning(f"Failed to fetch data for {owner}/{name}: {e}")
                    continue
            
            # Calculate metrics from aggregated data across ALL repositories
            metrics = calculator.calculate_all_metrics(all_commits, all_prs, "global")
            
            # Add comprehensive repository context
            metrics["active_repositories"] = len(user_repos)
            metrics["analyzed_repositories"] = min(10, len(user_repos))
            metrics["private_repositories"] = private_count
            metrics["public_repositories"] = public_count
            metrics["total_commits_analyzed"] = len(all_commits)
            metrics["total_prs_analyzed"] = len(all_prs)
            
            return db.save_user_metrics(email, metrics)
            
        except Exception as e:
            logger.error(f"Error in global metrics refresh: {e}")
            return False
    
    elif scope == "tracked":
        # Fetch metrics for tracked repositories
        user_repos = db.get_user_repos(user_id)
        if not user_repos:
            return False
        
        all_commits = []
        all_prs = []
        
        for repo in user_repos:
            repo_name = get_repo_full_name(repo)
            if not repo_name or repo_name == "Unknown Repository":
                continue
            
            owner, name = repo_name.split('/', 1)
            
            # Fetch user's commits and PRs from this repo
            # Fetch ALL-TIME user commits and PRs for single repo analysis
            user_commits = github.fetch_commits(owner, name, developer_email=email)
            user_prs = github.fetch_pull_requests(owner, name, developer_email=email)
            
            all_commits.extend(user_commits)
            all_prs.extend(user_prs)
        
        # Calculate combined metrics
        metrics = calculator.calculate_all_metrics(all_commits, all_prs, "tracked")
        metrics["tracked_repositories"] = len(user_repos)
        
        return db.save_user_metrics(email, metrics)
    
    return False

def handle_oauth_callback():
    """Handle OAuth callback from GitHub authentication"""
    query_params = st.query_params
    
    logger.info(f"handle_oauth_callback called. Query params: {dict(query_params)}")
    
    if 'code' in query_params:
        code = query_params['code']
        
        # Check if user has explicitly logged out recently and is the same user
        if st.session_state.get('explicit_logout') or st.session_state.get('force_reauth'):
            logout_timestamp = st.session_state.get('signed_out_timestamp', 0)
            # Only allow OAuth callback if logout was more than 10 seconds ago (to allow genuine new login)
            if time.time() - logout_timestamp < 10:
                logger.info("OAuth callback blocked: Recent explicit logout detected")
                st.query_params.clear()
                return
        
        try:
            db = get_datastore()
            session = db.handle_oauth_callback(code)
            
            logger.info(f"OAuth session: {session}")
            
            if session:
                # Clear explicit logout flag since user is logging in again
                if 'explicit_logout' in st.session_state:
                    del st.session_state['explicit_logout']
                if 'force_reauth' in st.session_state:
                    del st.session_state['force_reauth']
                if 'logged_out_user' in st.session_state:
                    del st.session_state['logged_out_user']
                if 'signed_out_timestamp' in st.session_state:
                    del st.session_state['signed_out_timestamp']
                
                st.session_state.auth = session
                st.success("✅ Successfully authenticated!")
                st.query_params.clear()
                st.rerun()
            else:
                st.error("❌ Authentication failed. Please try again.")
        except Exception as e:
            logger.error(f"OAuth callback error: {e}")
            st.error(f"❌ Authentication error occurred: {e}")

def check_existing_session():
    """Check for existing authenticated session or URL parameters"""
    query_params = st.query_params
    logger.info(f"check_existing_session called with params: {dict(query_params)}")
    
    # Check for explicit logout parameter - if present, clear everything
    if query_params.get('signed_out') == 'true' or query_params.get('force_clean') == 'true':
        logger.info("Signed out parameter detected, clearing all sessions")
        # Clear Streamlit session state completely
        keys_to_clear = list(st.session_state.keys())
        for key in keys_to_clear:
            del st.session_state[key]
        
        # Set flags to prevent session restoration
        st.session_state.explicit_logout = True
        st.session_state.force_reauth = True
        st.session_state.signed_out_timestamp = time.time()
        
        # Clear query parameters
        st.query_params.clear()
        return False
    
    # Check if user has been explicitly logged out recently
    # BUT allow new login attempts if there are session parameters (OAuth flow in progress)
    # OR if it's a different user than the one who logged out
    has_session_params = query_params.get('session_token') and query_params.get('user_email')
    incoming_user_email = query_params.get('user_email') if has_session_params else None
    logged_out_user = st.session_state.get('logged_out_user')
    
    # Only block if:
    # 1. There was an explicit logout, AND
    # 2. No active OAuth flow (no session params), AND 
    # 3. It's the same user who logged out (or we don't know who's trying to login)
    should_block_login = (
        (st.session_state.get('explicit_logout') or st.session_state.get('force_reauth')) and
        not has_session_params and
        (not incoming_user_email or incoming_user_email == logged_out_user)
    )
    
    if should_block_login:
        logout_timestamp = st.session_state.get('signed_out_timestamp', 0)
        # Respect explicit logout for 5 minutes to prevent immediate auto-signin
        if time.time() - logout_timestamp < 300:  # 5 minutes
            logger.info(f"Recent explicit logout detected for user {logged_out_user}, maintaining logged out state")
            return False
    
    # Check if we have session_token and user_email (github_token is optional)
    if has_session_params:
        logger.info("Found session data in URL parameters")
        
        # Clear explicit logout flag since user is logging in again
        if 'explicit_logout' in st.session_state:
            del st.session_state['explicit_logout']
        if 'force_reauth' in st.session_state:
            del st.session_state['force_reauth']
        if 'signed_out_timestamp' in st.session_state:
            del st.session_state['signed_out_timestamp']
        if 'logged_out_user' in st.session_state:
            del st.session_state['logged_out_user']
        
        # Create session from URL parameters
        session_data = {
            'access_token': query_params.get('session_token'),
            'github_token': query_params.get('github_token', ''),
            'provider_token': query_params.get('github_token', ''),
            'user': {
                'email': query_params.get('user_email')
            }
        }
        
        st.session_state.auth = session_data
        logger.info(f"Session restored from URL parameters for user: {session_data['user']['email']}")
        
        # Try to authenticate with the data store using session data
        db = get_datastore()
        try:
            auth_success = db.authenticate_with_session_data(session_data)
            if auth_success:
                logger.info("Successfully authenticated with data store")
            else:
                logger.warning("Failed to authenticate with data store, but continuing")
        except Exception as e:
            logger.error(f"Error authenticating with data store: {e}")
        
        # Clear URL parameters for security
        st.query_params.clear()
        return True
    
    # Check existing session state first
    if 'auth' not in st.session_state:
        # Different behavior based on deployment mode
        from config import IS_AWS_DEPLOYMENT
        if IS_AWS_DEPLOYMENT:
            # AWS mode: ONLY restore sessions if there's an active OAuth callback
            # Don't auto-restore from database to allow multiple users
            logger.info("AWS mode: No auto-session restoration, requiring explicit OAuth")
            return False
        else:
            # Development mode: Only check Supabase session if we haven't explicitly signed out
            if not st.session_state.get('explicit_logout') and not st.session_state.get('force_reauth'):
                logger.info("No auth in session state, checking Supabase session")
                db = get_datastore()
                session = db.get_session()
                
                if session:
                    logger.info("Found existing Supabase session")
                    # Clear explicit logout flag since we found a valid session
                    if 'explicit_logout' in st.session_state:
                        del st.session_state['explicit_logout']
                    if 'force_reauth' in st.session_state:
                        del st.session_state['force_reauth']
                    if 'signed_out_timestamp' in st.session_state:
                        del st.session_state['signed_out_timestamp']
                    
                    st.session_state.auth = session
                    return True
            else:
                logger.info("Explicit logout flag set, not checking Supabase session")
        
        logger.info("No existing sessions found")
        return False
    
    logger.info("Found existing auth in session state")
    return st.session_state.auth is not None

def show_login():
    """Display login interface"""
    st.title("📊 GitHub Developer Metrics Dashboard")
    st.markdown("### Your Complete GitHub Performance Analytics Platform")
    
    # Clear browser storage and GitHub session on login page load
    st.markdown("""
    <script>
    // Clear all browser storage when login page loads
    if (typeof(Storage) !== "undefined") {
        localStorage.clear();
        sessionStorage.clear();
    }
    
    // Clear all cookies aggressively
    document.cookie.split(";").forEach(function(c) { 
        document.cookie = c.replace(/^ +/, "").replace(/=.*/, "=;expires=" + new Date().toUTCString() + ";path=/"); 
        document.cookie = c.replace(/^ +/, "").replace(/=.*/, "=;expires=" + new Date().toUTCString() + ";path=/; domain=" + window.location.hostname);
        document.cookie = c.replace(/^ +/, "").replace(/=.*/, "=;expires=" + new Date().toUTCString() + ";path=/; domain=." + window.location.hostname);
    });
    
    // Clear GitHub-specific session cookies
    var githubCookies = [
        'user_session', '_gh_sess', '__Host-user_session_same_site', 
        'logged_in', 'dotcom_user', '_octo', 'color_mode',
        'preferred_color_mode', 'tz', '_device_id'
    ];
    
    githubCookies.forEach(function(cookie) {
        // Clear for github.com
        document.cookie = cookie + "=; expires=Thu, 01 Jan 1970 00:00:00 UTC; path=/; domain=.github.com;";
        document.cookie = cookie + "=; expires=Thu, 01 Jan 1970 00:00:00 UTC; path=/; domain=github.com;";
        // Clear for current domain
        document.cookie = cookie + "=; expires=Thu, 01 Jan 1970 00:00:00 UTC; path=/;";
    });
    
    // Clear GitHub OAuth state from localStorage/sessionStorage
    if (typeof(Storage) !== "undefined") {
        var keysToRemove = [];
        for (var i = 0; i < localStorage.length; i++) {
            var key = localStorage.key(i);
            if (key && (key.includes('github') || key.includes('oauth') || key.includes('auth'))) {
                keysToRemove.push(key);
            }
        }
        keysToRemove.forEach(function(key) {
            localStorage.removeItem(key);
        });
        
        keysToRemove = [];
        for (var i = 0; i < sessionStorage.length; i++) {
            var key = sessionStorage.key(i);
            if (key && (key.includes('github') || key.includes('oauth') || key.includes('auth'))) {
                keysToRemove.push(key);
            }
        }
        keysToRemove.forEach(function(key) {
            sessionStorage.removeItem(key);
        });
    }
    </script>
    """, unsafe_allow_html=True)
    
    # App description and features
    st.markdown("""
    <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 20px; border-radius: 10px; color: white; margin: 20px 0;">
        <h3 style="margin-top: 0; color: white;">🚀 What This App Does</h3>
        <p style="margin-bottom: 0;">Transform your GitHub activity into actionable insights with comprehensive developer metrics, DORA performance tracking, and AI-powered analysis to help you understand and improve your coding productivity.</p>
    </div>
    """, unsafe_allow_html=True)
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("""
        **📈 Global Analytics:**
        - **Complete GitHub Overview** - All your repositories analyzed
        - **DORA Metrics** - Lead time, deployment frequency, failure rates
        - **Performance Trends** - Track productivity over time
        - **Activity Patterns** - When and how you code most effectively
        """)
        
        st.markdown("""
        **🔍 Repository Deep-Dive:**
        - **Individual Repo Analysis** - Track specific projects
        - **Contribution Comparison** - Your work vs. team totals  
        - **Code Quality Metrics** - Commit size, review coverage
        - **Team Collaboration** - Pull request patterns and reviews
        """)
    
    with col2:
        st.markdown("""
        **🤖 AI-Powered Insights:**
        - **Smart Recommendations** - Personalized productivity tips
        - **Performance Predictions** - ML-based trend forecasting
        - **Repository Insights** - AI analysis of your contributions
        - **Continuous Learning** - Adaptive suggestions over time
        """)
        
        st.markdown("""
        **🔐 Privacy & Security:**
        - **Per-User Authentication** - Each user sees only their data
        - **Secure GitHub Integration** - OAuth-based access
        - **Private Repository Support** - Full access with proper permissions
        - **Multi-User Ready** - Switch between GitHub accounts easily
        """)
    
    st.markdown("---")
    
    # Login instructions
    st.markdown("""
    <div style="background: #f8f9fa; padding: 15px; border-radius: 8px; border-left: 4px solid #28a745;">
        <h4 style="margin-top: 0; color: #155724;">🔐 How to Get Started</h4>
        <ol style="margin-bottom: 0;">
            <li><strong>Click "Sign in with GitHub"</strong> below to authenticate</li>
            <li><strong>Authorize the app</strong> to access your repositories</li>
            <li><strong>View your global metrics</strong> automatically generated from all repos</li>
            <li><strong>Add specific repositories</strong> to track for detailed analysis</li>
            <li><strong>Explore AI insights</strong> and performance recommendations</li>
        </ol>
    </div>
    """, unsafe_allow_html=True)
    
    # Start auth server in background if not already running
    try:
        import sys
        import os
        sys.path.append(os.path.dirname(os.path.dirname(__file__)))
        from auth_server import start_auth_server_background
        
        # Start auth server on port 8502
        if 'auth_server_started' not in st.session_state:
            start_auth_server_background(8502)
            st.session_state.auth_server_started = True
    except Exception as e:
        logger.warning(f"Could not start auth server: {e}")
    
    # Create direct Supabase authentication with enhanced auth page
    # Import AWS deployment status
    from config import IS_AWS_DEPLOYMENT
    
    if IS_AWS_DEPLOYMENT:
        # AWS mode: Use GitHub OAuth
        from config import GITHUB_CLIENT_ID, OAUTH_REDIRECT_URI
        
        if not GITHUB_CLIENT_ID:
            st.error("❌ GitHub OAuth is not configured. Please set GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET environment variables.")
            st.stop()
        
        # GitHub OAuth URL - Always force account selection for multi-user support
        oauth_params = [
            f"client_id={GITHUB_CLIENT_ID}",
            f"redirect_uri={OAUTH_REDIRECT_URI}",
            "scope=repo,user:email,read:org",
            "state=streamlit_oauth",
            "prompt=select_account",  # Always force account selection screen
            f"login_hint=choose_account_{int(time.time())}"  # Force account picker
        ]
        
        oauth_url = f"https://github.com/login/oauth/authorize?{'&'.join(oauth_params)}"
        
        st.markdown(f"""
        <div style="text-align: center; margin: 2rem 0;">
            <a href="{oauth_url}" 
               style="background: #24292e; color: white; padding: 12px 24px; text-decoration: none; 
                      border-radius: 6px; font-weight: bold; display: inline-block; transition: background 0.2s;
                      font-size: 16px;"
               onmouseover="this.style.background='#1a1e22'"
               onmouseout="this.style.background='#24292e'">
                🔐 Sign in with GitHub
            </a>
        </div>
        """, unsafe_allow_html=True)
        
        st.info("👆 Click to authenticate with your GitHub account and access your repositories")
        
        # Additional account selection option
        st.markdown("---")
        st.markdown("**Need to use a different GitHub account?**")
        
        # Create a GitHub logout + OAuth URL that forces account selection
        github_logout_url = "https://github.com/logout"
        oauth_with_logout_params = oauth_params + ["prompt=select_account", "max_age=0"]
        oauth_fresh_url = f"https://github.com/login/oauth/authorize?{'&'.join(oauth_with_logout_params)}"
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown(f"""
            <div style="text-align: center; margin: 1rem 0;">
                <a href="{github_logout_url}" target="_blank"
                   style="background: #dc3545; color: white; padding: 8px 16px; text-decoration: none; 
                          border-radius: 4px; font-weight: bold; display: inline-block; transition: background 0.2s;
                          font-size: 14px;"
                   onmouseover="this.style.background='#c82333'"
                   onmouseout="this.style.background='#dc3545'">
                    🔒 Logout GitHub First
                </a>
            </div>
            """, unsafe_allow_html=True)
        
        with col2:
            st.markdown(f"""
            <div style="text-align: center; margin: 1rem 0;">
                <a href="{oauth_fresh_url}" 
                   style="background: #28a745; color: white; padding: 8px 16px; text-decoration: none; 
                          border-radius: 4px; font-weight: bold; display: inline-block; transition: background 0.2s;
                          font-size: 14px;"
                   onmouseover="this.style.background='#218838'"
                   onmouseout="this.style.background='#28a745'">
                    👥 Choose Account
                </a>
            </div>
            """, unsafe_allow_html=True)
        
        st.markdown("""
        <div style="background: #f8f9fa; padding: 10px; border-radius: 5px; border-left: 4px solid #17a2b8; margin: 10px 0;">
            <small><strong>For different account:</strong><br/>
            1. Click "Logout GitHub First" to clear GitHub session<br/>
            2. Then click "Choose Account" to select a different GitHub account<br/>
            3. Or use an incognito/private browser window</small>
        </div>
        """, unsafe_allow_html=True)
        
        # Enhanced test mode section
        st.markdown("---")
        st.markdown("""
        <div style="background: #fff3cd; padding: 15px; border-radius: 8px; border-left: 4px solid #ffc107; margin: 20px 0;">
            <h4 style="margin-top: 0; color: #856404;">🔧 Having GitHub OAuth Issues?</h4>
            <p style="margin-bottom: 10px; color: #856404;">If you're experiencing issues with GitHub OAuth, organization access restrictions, or want to test with a personal access token, use the alternative login method below.</p>
            <p style="margin-bottom: 0; color: #856404;"><strong>When to use this:</strong> Organization restrictions, OAuth app not approved, private repository access issues, or testing purposes.</p>
        </div>
        """, unsafe_allow_html=True)
        
        # Make test mode more prominent
        test_mode_expander = st.expander("🧪 **Alternative Login: GitHub Personal Access Token**", expanded=False)
        with test_mode_expander:
            st.markdown("""
            **📋 How to create a GitHub Personal Access Token:**
            1. Go to [GitHub Settings > Developer Settings > Personal Access Tokens](https://github.com/settings/tokens)
            2. Click "Generate new token (classic)"
            3. Select these scopes: `repo`, `user:email`, `read:org`
            4. Copy the generated token and paste it below
            
            **⚠️ Important:** This token gives full access to your repositories. Keep it secure and don't share it.
            """)
            
            col1, col2 = st.columns(2)
            with col1:
                test_email = st.text_input(
                    "Your Email Address", 
                    value="",
                    placeholder="your-email@example.com",
                    help="Enter the email associated with your GitHub account"
                )
            with col2:
                test_github_token = st.text_input(
                    "GitHub Personal Access Token", 
                    type="password",
                    placeholder="ghp_xxxxxxxxxxxxxxxxxxxx",
                    help="Paste your GitHub Personal Access Token here"
                )
            
            if st.button("🔐 Login with Personal Access Token", use_container_width=True, type="primary"):
                if test_email and test_github_token:
                        # Create a test session
                        test_session_data = {
                            'access_token': test_github_token,
                            'github_token': test_github_token,
                            'user': {
                                'email': test_email,
                                'user_metadata': {'full_name': 'Test User'}
                            },
                            'expires_at': '2025-12-31T23:59:59Z'
                        }
                        
                        st.session_state['auth'] = test_session_data
                        st.session_state['user_email'] = test_email
                        st.session_state['github_token'] = test_github_token
                        
                        # Clear logout state
                        if 'signed_out_timestamp' in st.session_state:
                            del st.session_state['signed_out_timestamp']
                        if 'explicit_logout' in st.session_state:
                            del st.session_state['explicit_logout']
                        
                        # Authenticate with data store  
                        db = get_datastore()
                        if db.authenticate_with_session_data(test_session_data):
                            st.success("✅ Test session created successfully!")
                            st.rerun()
                        else:
                            st.error("❌ Failed to create test session")
                else:
                    st.warning("Please enter both email and GitHub token")
    else:
        # Development mode: Use Supabase auth URL
        from config import SUPABASE_URL, SUPABASE_KEY
        auth_url = f"http://localhost:8502/public/auth_enhanced.html?supabase_url={SUPABASE_URL}&supabase_key={SUPABASE_KEY}"
        
        st.markdown(f"""
        <div style="text-align: center; margin: 2rem 0;">
            <a href="{auth_url}" target="_blank" 
               style="background: #24292e; color: white; padding: 12px 24px; text-decoration: none; 
                      border-radius: 6px; font-weight: bold; display: inline-block; transition: background 0.2s;"
               onmouseover="this.style.background='#1a1e22'"
               onmouseout="this.style.background='#24292e'">
                🔐 Login with GitHub
            </a>
        </div>
        """, unsafe_allow_html=True)
    
    # Enhanced success message and final instructions
    st.markdown("""
    <div style="background: #d1ecf1; padding: 15px; border-radius: 8px; border-left: 4px solid #bee5eb; margin: 20px 0;">
        <h4 style="margin-top: 0; color: #0c5460;">🎯 What Happens After Login</h4>
        <ul style="margin-bottom: 0; color: #0c5460;">
            <li><strong>Instant Analysis:</strong> Your global GitHub metrics will be automatically calculated</li>
            <li><strong>Repository Discovery:</strong> All your repositories will be scanned and available for tracking</li>
            <li><strong>AI Insights:</strong> Smart recommendations will be generated based on your coding patterns</li>
            <li><strong>Privacy Protected:</strong> Only you can see your data - each user has their own secure dashboard</li>
        </ul>
    </div>
    """, unsafe_allow_html=True)
    
    # Add a manual browser clearing button
    if st.button("🧹 Clear All Data & Force Account Selection", help="Clear all browser storage, GitHub sessions, and force account selection"):
        st.markdown("""
        <script>
        // Comprehensive browser storage clearing
        if (typeof(Storage) !== "undefined") {
            localStorage.clear();
            sessionStorage.clear();
        }
        
        // Clear all cookies aggressively
        document.cookie.split(";").forEach(function(c) { 
            document.cookie = c.replace(/^ +/, "").replace(/=.*/, "=;expires=" + new Date().toUTCString() + ";path=/"); 
            document.cookie = c.replace(/^ +/, "").replace(/=.*/, "=;expires=" + new Date().toUTCString() + ";path=/; domain=" + window.location.hostname);
            document.cookie = c.replace(/^ +/, "").replace(/=.*/, "=;expires=" + new Date().toUTCString() + ";path=/; domain=." + window.location.hostname);
        });
        
        // Clear GitHub-specific session cookies extensively
        var githubCookies = [
            'user_session', '_gh_sess', '__Host-user_session_same_site', 
            'logged_in', 'dotcom_user', '_octo', 'color_mode', 'preferred_color_mode', 
            'tz', '_device_id', 'has_recent_activity', 'tz_offset'
        ];
        
        githubCookies.forEach(function(cookie) {
            // Multiple domain variations
            document.cookie = cookie + "=; expires=Thu, 01 Jan 1970 00:00:00 UTC; path=/; domain=.github.com;";
            document.cookie = cookie + "=; expires=Thu, 01 Jan 1970 00:00:00 UTC; path=/; domain=github.com;";
            document.cookie = cookie + "=; expires=Thu, 01 Jan 1970 00:00:00 UTC; path=/;";
            document.cookie = cookie + "=; expires=Thu, 01 Jan 1970 00:00:00 UTC; path=/; secure;";
        });
        
        // Try to clear GitHub session by opening logout in hidden iframe
        var iframe = document.createElement('iframe');
        iframe.style.display = 'none';
        iframe.src = 'https://github.com/logout';
        document.body.appendChild(iframe);
        
        // Remove iframe after 2 seconds
        setTimeout(function() {
            document.body.removeChild(iframe);
        }, 2000);
        
        // Force reload after clearing
        setTimeout(function() {
            window.location.reload(true);
        }, 3000);
        </script>
        """, unsafe_allow_html=True)
        st.success("🧹 All data cleared! GitHub logout initiated. Page will reload in 3 seconds...")
        st.info("After reload, click 'Choose Account' to select a different GitHub account.")
    
    # Show logout confirmation message
    if st.session_state.get('explicit_logout') or st.session_state.get('force_reauth'):
        logged_out_user = st.session_state.get('logged_out_user', 'Previous user')
        st.success(f"✅ Successfully logged out {logged_out_user}. You can now sign in with any GitHub account.")
        
        # Add a clear button to remove the logout message
        if st.button("🧹 Clear Message", key="clear_logout_message"):
            if 'explicit_logout' in st.session_state:
                del st.session_state['explicit_logout']
            if 'force_reauth' in st.session_state:
                del st.session_state['force_reauth']
            if 'logged_out_user' in st.session_state:
                del st.session_state['logged_out_user']
            if 'signed_out_timestamp' in st.session_state:
                del st.session_state['signed_out_timestamp']
            st.rerun()
    
    # Add explicit sign-in button for users who logged out
    if st.session_state.get('explicit_logout'):
        st.warning("⚠️ You have been logged out. Click 'Sign In Again' to re-authenticate.")
        
        col1, col2, col3 = st.columns([1, 1, 1])
        with col2:
            if st.button("🔄 Sign In Again", use_container_width=True, type="primary"):
                # Clear the explicit logout flag to allow auto-signin
                if 'explicit_logout' in st.session_state:
                    del st.session_state['explicit_logout']
                st.success("Ready to sign in! Use the login button above.")
                st.rerun()
    
    # Enhanced FAQ and troubleshooting section
    st.markdown("---")
    st.markdown("""
    <div style="background: #e7f3ff; padding: 15px; border-radius: 8px; border-left: 4px solid #007bff; margin: 20px 0;">
        <h4 style="margin-top: 0; color: #004085;">❓ Frequently Asked Questions</h4>
        <details style="margin-bottom: 10px;">
            <summary style="font-weight: bold; color: #004085; cursor: pointer;">🔒 What permissions does this app need?</summary>
            <p style="margin: 10px 0 0 20px; color: #004085;">The app requests <code>repo</code>, <code>user:email</code>, and <code>read:org</code> scopes to analyze your repositories, access your email for identification, and discover organization repositories you have access to.</p>
        </details>
        <details style="margin-bottom: 10px;">
            <summary style="font-weight: bold; color: #004085; cursor: pointer;">🏢 Can I access private/organization repositories?</summary>
            <p style="margin: 10px 0 0 20px; color: #004085;">Yes! The app can access private repositories and organization repositories that you have access to. If your organization restricts OAuth apps, use the Personal Access Token method above.</p>
        </details>
        <details style="margin-bottom: 10px;">
            <summary style="font-weight: bold; color: #004085; cursor: pointer;">🔄 How often is data updated?</summary>
            <p style="margin: 10px 0 0 20px; color: #004085;">Data is fetched in real-time when you refresh metrics or view repository details. The app shows complete repository history (all-time data) for comprehensive analysis.</p>
        </details>
        <details>
            <summary style="font-weight: bold; color: #004085; cursor: pointer;">🛡️ Is my data secure?</summary>
            <p style="margin: 10px 0 0 20px; color: #004085;">Absolutely. Each user has their own isolated dashboard. Your data is never shared with other users, and we only store calculated metrics, not your actual code or repository contents.</p>
        </details>
    </div>
    """, unsafe_allow_html=True)
    
    # Debug info for development
    if st.checkbox("Show Debug Info", value=False):
        st.code(f"OAuth Redirect URI: {OAUTH_REDIRECT_URI}")
        st.code(f"GitHub Client ID: {GITHUB_CLIENT_ID}")
        st.code(f"Query params: {dict(st.query_params)}")
        st.code(f"OAuth Server Started: {st.session_state.get('oauth_server_started', False)}")
        
        # Test OAuth server connectivity
        if st.button("🔧 Test OAuth Server"):
            import requests
            try:
                response = requests.get("http://localhost:5000/auth/callback?test=true", timeout=5)
                if response.status_code == 200:
                    st.success("✅ OAuth server is responding")
                else:
                    st.error(f"❌ OAuth server returned status {response.status_code}")
            except Exception as e:
                st.error(f"❌ OAuth server is not responding: {e}")
        
        # Test GitHub token permissions
        if st.button("🔍 Test GitHub Token Permissions"):
            if 'auth' in st.session_state and st.session_state.auth:
                try:
                    import requests
                    github_token = st.session_state.auth.get('github_token', '')
                    if github_token:
                        # Test basic user info
                        headers = {'Authorization': f'Bearer {github_token}'}
                        
                        # Test 1: Get user info
                        user_response = requests.get('https://api.github.com/user', headers=headers)
                        st.write(f"**User API Status**: {user_response.status_code}")
                        if user_response.status_code == 200:
                            user_data = user_response.json()
                            st.write(f"**Username**: {user_data.get('login', 'N/A')}")
                            st.write(f"**User ID**: {user_data.get('id', 'N/A')}")
                        
                        # Test 2: Get repositories
                        repos_response = requests.get('https://api.github.com/user/repos?per_page=5', headers=headers)
                        st.write(f"**Repos API Status**: {repos_response.status_code}")
                        if repos_response.status_code == 200:
                            repos_data = repos_response.json()
                            st.write(f"**Found {len(repos_data)} repositories:**")
                            for repo in repos_data[:3]:
                                st.write(f"  - {repo.get('full_name', 'N/A')} ({'Private' if repo.get('private') else 'Public'})")
                        else:
                            st.error(f"Repository access failed: {repos_response.text[:200]}")
                        
                        # Test 3: Check token scopes
                        scopes_response = requests.get('https://api.github.com/user', headers=headers)
                        if 'X-OAuth-Scopes' in scopes_response.headers:
                            scopes = scopes_response.headers['X-OAuth-Scopes']
                            st.write(f"**Token Scopes**: {scopes}")
                        
                    else:
                        st.error("No GitHub token found in session")
                except Exception as e:
                    st.error(f"Token test failed: {e}")
            else:
                st.warning("No authentication session found")
        
        if st.button("Test OAuth Callback (Dev)"):
            handle_oauth_callback()
        
        # Test direct authentication
        if st.button("Test Direct Auth"):
            test_session = {
                'access_token': 'test_access_token',
                'github_token': 'test_github_token',
                'provider_token': 'test_github_token',
                'user': {
                    'email': 'test@example.com'
                }
            }
            st.session_state.auth = test_session
            st.success("Test session created!")
            st.rerun()
    
    # Manual session input for testing
    with st.expander("Manual Session Input (Development Only)"):
        test_email = st.text_input("Test Email", "test@example.com")
        test_github_token = st.text_input("Test GitHub Token", type="password")
        
        try:
            if st.button("Create Test Session") and test_email and test_github_token:
                st.session_state.auth = {
                    'user': {'email': test_email},
                    'github_token': test_github_token,
                    'access_token': 'test_token'
                }
                st.success("Test session created!")
                st.rerun()
        except Exception as e:
            logger.error(f"Login error: {e}")
            st.error(f"Authentication service unavailable: {e}")

def get_user_id_by_email(email: str, user_session=None) -> str:
    """Get user ID from email address"""
    db = get_datastore()
    user = db.get_user_by_email(email)
    if user:
        return user['id']
    
    # Create user if doesn't exist - need to get correct GitHub username
    github = get_github_api(user_session)
    github_user_info = github.get_authenticated_user()
    
    github_username = None
    user_github_token = None
    
    if github_user_info:
        github_username = github_user_info.get('login')
        logger.info(f"✅ Got GitHub username for user creation: {github_username}")
    
    if user_session and isinstance(user_session, dict):
        user_github_token = user_session.get('github_token') or user_session.get('provider_token')
    
    # Create user with correct GitHub username
    user_id = db.ensure_user_exists_and_get_id(email, user_github_token, github_username)
    if user_id:
        return user_id
    else:
        logger.error(f"Unable to create or find user for email: {email}")
        st.error(f"Unable to create user account for {email}. Please try logging in again.")
        return None

def get_repo_full_name(repo_data: dict) -> str:
    """Safely extract repository full name from different data structures"""
    # Handle nested structure: repo['repos']['full_name']
    if 'repos' in repo_data and isinstance(repo_data['repos'], dict):
        return repo_data['repos'].get('full_name', '')
    
    # Handle flat structure: repo['full_name']
    if 'full_name' in repo_data:
        return repo_data['full_name']
    
    # Handle alternative structures
    if 'name' in repo_data and 'owner' in repo_data:
        return f"{repo_data['owner']}/{repo_data['name']}"
    
    return "Unknown Repository"

def get_repo_id(repo_data: dict) -> str:
    """Safely extract repository ID from different data structures"""
    # Handle nested structure: repo['repos']['id']
    if 'repos' in repo_data and isinstance(repo_data['repos'], dict):
        return repo_data['repos'].get('id', '')
    
    # Handle flat structure: repo['repo_id']
    if 'repo_id' in repo_data:
        return repo_data['repo_id']
    
    # Handle flat structure: repo['id']
    if 'id' in repo_data:
        return repo_data['id']
    
    return ""

def show_repo_management(user_email: str, user_session=None):
    """Enhanced repository management interface with individual repo metrics and AI insights"""
    st.subheader("📁 Repository Management")
    
    db = get_datastore()
    github = get_github_api(user_session)
    calculator = get_metrics_calculator()
    summary_bot = get_summary_bot()
    user_id = get_user_id_by_email(user_email, user_session)
    
    # Display current repositories with metrics
    force_refresh = st.session_state.get('repos_updated', False)
    if force_refresh:
        st.session_state['repos_updated'] = False
    
    user_repos = db.get_user_repos(user_id)
    
    if user_repos:
        st.write("**Tracked Repositories with Contribution Analysis:**")
        st.info("📅 **Note:** All metrics show complete repository history (all-time data) for comprehensive analysis.")
        
        # Debug: Show structure of first repo
        if st.checkbox("Show Repository Data Structure (Debug)", value=False):
            st.write("**First Repository Data:**")
            st.json(user_repos[0] if user_repos else {})
        
        for repo in user_repos:
            repo_name = get_repo_full_name(repo)
            # Handle datetime object properly
            created_at = repo.get('created_at', '')
            if hasattr(created_at, 'strftime'):  # datetime object
                added_date = created_at.strftime('%Y-%m-%d')
            elif isinstance(created_at, str) and len(created_at) >= 10:  # string date
                added_date = created_at[:10]
            else:
                added_date = 'Unknown'
            
            # Create expandable section for each repository
            with st.expander(f"📦 **{repo_name}** - Added: {added_date}", expanded=False):
                
                # Try to fetch repository metrics
                if '/' in repo_name and repo_name != "Unknown Repository":
                    owner, name = repo_name.split('/', 1)
                    
                    # Fetch data once for all tabs to avoid scope issues
                    try:
                        # Fetch user's commits and PRs for this specific repo (all-time data)
                        user_commits = github.fetch_commits(owner, name, developer_email=user_email)
                        user_prs = github.fetch_pull_requests(owner, name, developer_email=user_email)
                        
                        # Fetch total repository stats (all contributors, all-time data)
                        total_commits = github.fetch_commits(owner, name)  # Get total stats for all time
                        total_prs = github.fetch_pull_requests(owner, name)
                        
                        # Calculate metrics
                        user_metrics = calculator.calculate_all_metrics(user_commits, user_prs, f"user_{repo_name}")
                        total_metrics = calculator.calculate_all_metrics(total_commits, total_prs, f"total_{repo_name}")
                        
                        data_loaded = True
                    except Exception as e:
                        st.error(f"Could not fetch repository data: {str(e)}")
                        data_loaded = False
                        user_commits = []
                        user_prs = []
                        total_commits = []
                        total_prs = []
                    
                    # Create tabs for different views
                    metrics_tab, comparison_tab, insights_tab, manage_tab = st.tabs([
                        "📊 Your Metrics", "⚖️ Comparison", "🤖 AI Insights", "⚙️ Manage"
                    ])
                    
                    with metrics_tab:
                        if data_loaded:
                            st.write("**Your Contribution to this Repository:**")
                            
                            # Display user metrics
                            col1, col2, col3, col4 = st.columns(4)
                            
                            with col1:
                                st.metric("Your Commits", f"{len(user_commits):,}")
                            with col2:
                                st.metric("Your PRs", f"{len(user_prs):,}")
                            with col3:
                                avg_commit_size = user_metrics.get('code_quality', {}).get('avg_commit_size', 0)
                                st.metric("Avg Commit Size", f"{avg_commit_size:.0f} lines")
                            with col4:
                                review_coverage = user_metrics.get('code_quality', {}).get('review_coverage_percentage', 0)
                                st.metric("Review Coverage", f"{review_coverage:.0f}%")
                            
                            # Show recent activity
                            if user_commits:
                                recent_commits = sorted(user_commits, key=lambda x: x.get('committedDate', ''), reverse=True)[:5]
                                st.write("**Your Recent Commits:**")
                                for commit in recent_commits:
                                    commit_date = commit.get('committedDate', 'Unknown')[:10]
                                    commit_msg = commit.get('message', 'No message')[:50] + ('...' if len(commit.get('message', '')) > 50 else '')
                                    st.write(f"• `{commit_date}` - {commit_msg}")
                        else:
                            st.info("Repository data could not be loaded. This might be due to repository permissions or network issues.")
                    
                    with comparison_tab:
                        if data_loaded:
                            st.write("**Repository-wide vs Your Contribution:**")
                            
                            # Comparison metrics
                            col1, col2 = st.columns(2)
                            
                            with col1:
                                st.write("**📊 Your Stats:**")
                                user_commit_count = len(user_commits)
                                user_pr_count = len(user_prs)
                                st.write(f"• Commits: {user_commit_count:,}")
                                st.write(f"• Pull Requests: {user_pr_count:,}")
                                
                                if user_commit_count > 0:
                                    user_lines_changed = sum(commit.get('additions', 0) + commit.get('deletions', 0) for commit in user_commits)
                                    st.write(f"• Lines Changed: {user_lines_changed:,}")
                                else:
                                    st.write("• Lines Changed: 0")
                            
                            with col2:
                                st.write("**🏢 Repository Total:**")
                                total_commit_count = len(total_commits)
                                total_pr_count = len(total_prs)
                                st.write(f"• Total Commits: {total_commit_count:,}")
                                st.write(f"• Total Pull Requests: {total_pr_count:,}")
                                
                                if total_commits:
                                    total_lines_changed = sum(commit.get('additions', 0) + commit.get('deletions', 0) for commit in total_commits)
                                    st.write(f"• Total Lines Changed: {total_lines_changed:,}")
                                else:
                                    st.write("• Total Lines Changed: 0")
                            
                            # Calculate contribution percentages
                            if total_commit_count > 0:
                                commit_percentage = (user_commit_count / total_commit_count) * 100
                                pr_percentage = (user_pr_count / total_pr_count * 100) if total_pr_count > 0 else 0
                                
                                st.write("**🎯 Your Contribution Percentage:**")
                                col1, col2 = st.columns(2)
                                with col1:
                                    st.metric("Commit Contribution", f"{commit_percentage:.1f}%")
                                with col2:
                                    st.metric("PR Contribution", f"{pr_percentage:.1f}%")
                                
                                # Visual representation
                                contribution_data = {
                                    'Your Commits': user_commit_count,
                                    'Other Contributors': total_commit_count - user_commit_count
                                }
                                
                                if user_commit_count > 0:
                                    import plotly.express as px
                                    fig = px.pie(
                                        values=list(contribution_data.values()), 
                                        names=list(contribution_data.keys()),
                                        title=f"Your Contribution to {repo_name}"
                                    )
                                    st.plotly_chart(fig, use_container_width=True)
                            else:
                                st.info("No commits found in this repository to calculate contributions.")
                        else:
                            st.error("Could not load repository comparison data due to data fetching issues.")
                    
                    with insights_tab:
                        if data_loaded:
                            st.write("**🤖 AI-Powered Repository Insights:**")
                            
                            # Prepare data for AI analysis
                            repo_analysis_data = {
                                'repository_name': repo_name,
                                'user_commits': len(user_commits),
                                'total_commits': len(total_commits),
                                'user_prs': len(user_prs),
                                'total_prs': len(total_prs),
                                'contribution_percentage': (len(user_commits) / len(total_commits) * 100) if len(total_commits) > 0 else 0,
                                'user_email': user_email,
                                'recent_activity': len([c for c in user_commits if c.get('committedDate', '') > (datetime.now() - timedelta(days=30)).isoformat()]) if user_commits else 0
                            }
                            
                            # Generate AI insights
                            try:
                                repo_insights = summary_bot.generate_repository_contribution_summary(repo_analysis_data)
                                
                                if repo_insights:
                                    # Display insights
                                    if repo_insights.get('summary'):
                                        st.write("**📝 Summary:**")
                                        st.write(repo_insights['summary'])
                                    
                                    if repo_insights.get('contribution_analysis'):
                                        st.write("**📊 Contribution Analysis:**")
                                        st.write(repo_insights['contribution_analysis'])
                                    
                                    if repo_insights.get('recommendations'):
                                        st.write("**💡 Recommendations:**")
                                        for rec in repo_insights['recommendations']:
                                            st.write(f"• {rec}")
                                    
                                    if repo_insights.get('team_role'):
                                        st.write("**👥 Your Role in Team:**")
                                        st.info(repo_insights['team_role'])
                                else:
                                    st.info("AI insights are being generated... Please try again in a moment.")
                            except Exception as e:
                                st.error(f"Could not generate AI insights: {str(e)}")
                                st.info("AI insights temporarily unavailable.")
                        else:
                            st.info("AI insights unavailable due to data loading issues.")
                    
                    with manage_tab:
                        st.write("**⚙️ Repository Management:**")
                        
                        col1, col2 = st.columns(2)
                        
                        with col1:
                            st.write("**Repository Information:**")
                            st.write(f"• **Name:** {repo_name}")
                            st.write(f"• **Added:** {added_date}")
                            st.write("• **Status:** Active")
                        
                        with col2:
                            st.write("**Actions:**")
                            delete_key = f"delete_{repo.get('id', 'unknown')}"
                            if st.button("🗑️ Remove Repository", key=delete_key, type="secondary"):
                                logger.info(f"Delete button clicked for repo: {repo}")
                                
                                user_repo_id = repo.get('id')
                                logger.info(f"Attempting to delete user_repo_id: {user_repo_id}")
                                
                                success = False
                                if user_repo_id:
                                    success = db.delete_user_repo_by_id(user_repo_id)
                                    if success:
                                        logger.info(f"Successfully deleted repository: {repo_name}")
                                    else:
                                        logger.warning(f"Primary delete failed for repo: {repo_name}")
                                
                                # Fallback to old method if primary fails
                                if not success:
                                    logger.info("Trying fallback delete method")
                                    repo_id = get_repo_id(repo)
                                    logger.info(f"Fallback - attempting to delete with user_id: {user_id}, repo_id: {repo_id}")
                                    
                                    if repo_id:
                                        success = db.delete_user_repo(user_id, repo_id)
                                        if success:
                                            logger.info(f"Successfully deleted repository via fallback: {repo_name}")
                                        else:
                                            logger.error(f"Fallback delete also failed for repo: {repo_name}")
                                
                                # Handle the result
                                if success:
                                    st.success(f"✅ Removed {repo_name}")
                                    # Clear repository data from session state to force refresh
                                    if 'user_repos' in st.session_state:
                                        del st.session_state['user_repos']
                                    st.session_state['repos_updated'] = True
                                    st.rerun()
                                else:
                                    st.error("❌ Failed to remove repository")
                                    with st.expander("Debug Info"):
                                        st.write(f"**User Repo ID:** {user_repo_id}")
                                        st.write(f"**Repo ID:** {get_repo_id(repo)}")
                                        st.write(f"**User ID:** {user_id}")
                                        st.write("**Raw Repository Data:**")
                                        st.json(repo)
                else:
                    st.error(f"Invalid repository name format: {repo_name}")
    else:
        st.info("No repositories tracked yet. Add one below!")
    
    # Add new repository
    st.markdown("---")
    st.markdown("**Add New Repository:**")
    with st.form("add_repo_form", clear_on_submit=True):
        repo_input = st.text_input(
            "Repository (format: owner/repo-name)", 
            placeholder="e.g., facebook/react",
            help="Enter the GitHub repository in format: owner/repository-name"
        )
        submitted = st.form_submit_button("➕ Add Repository", type="primary")
        
        if submitted and repo_input:
            if '/' not in repo_input:
                st.error("Please use format: owner/repository-name")
            else:
                with st.spinner(f"Adding {repo_input}..."):
                    success = db.save_user_repo(user_email, repo_input)
                    if success:
                        st.success(f"✅ Added {repo_input}")
                        # Clear any cached data to force refresh
                        if 'user_repos' in st.session_state:
                            del st.session_state['user_repos']
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.error(f"❌ Failed to add {repo_input}. Check if the repository exists and is accessible.")

def display_global_metrics(user_email: str, user_id: str):
    """Display global metrics with comprehensive tabs"""
    try:
        db = get_datastore()
        ml = get_ml_analyzer()
        summary_bot = get_summary_bot()
        
        # Get current and historical metrics
        current_metrics = db.get_user_metrics(user_id, limit=1)
        if not current_metrics:
            st.warning("No metrics data available. Click 'Refresh Metrics Now' to load data.")
            return
        
        # Handle metrics data properly
        current_record = current_metrics[0]
        if 'metrics_data' in current_record and isinstance(current_record['metrics_data'], dict):
            metrics = current_record['metrics_data']
        else:
            # Fallback to the record itself if metrics_data is not available or not a dict
            metrics = current_record
        
        historical_data = db.get_user_metrics(user_id, limit=20)
        
        # Get continuous learning status from ML analyzer
        continuous_learning_status = ml.get_continuous_learning_status(historical_data)
        
        # Generate ML predictions for key metrics
        ml_predictions = {}
        key_metrics = [
            "dora.lead_time.total_lead_time_hours",
            "total_commits", 
            "total_prs",
            "activity_score",
            "performance_score"
        ]
        
        for metric_name in key_metrics:
            try:
                prediction = ml.predict_trend(historical_data, metric_name, days_ahead=14)
                if prediction and prediction.get("prediction"):
                    ml_predictions[metric_name] = {
                        "forecast": {
                            "dates": [(datetime.now() + timedelta(days=i)).strftime('%Y-%m-%d') for i in range(1, 8)],
                            "values": [prediction['prediction'] * (1 + (i-4)/100) for i in range(7)]
                        },
                        "confidence": prediction.get("confidence", 0),
                        "trend": prediction.get("trend", "unknown")
                    }
            except Exception as e:
                logger.debug(f"Failed to generate prediction for {metric_name}: {e}")
                continue
        
        # Add continuous learning status and predictions to metrics
        metrics['continuous_learning_status'] = continuous_learning_status
        metrics['ml_predictions'] = ml_predictions
        
        # Generate AI insights
        insights = summary_bot.generate_comprehensive_summary(
            metrics, 
            historical_data, 
            {"scope": "global", "time_period": "last 6 months"}
        )
        
        if insights is None:
            insights = {
                "summary": "Insights generation temporarily unavailable",
                "recommendations": [],
                "alerts": [],
                "trend_insights": []
            }
        
        # Create tabs
        overview_tab, performance_tab, activity_tab, insights_tab, ai_predictions_tab = st.tabs([
            "📊 Overview", "🎯 Performance", "⏰ Activity", "💡 Insights", "🤖 AI Predictions & Learning"
        ])
        
        with overview_tab:
            display_metrics_overview(metrics, historical_data)
        
        with performance_tab:
            display_performance_analysis(metrics, historical_data)
        
        with activity_tab:
            display_activity_patterns(metrics)
        
        with insights_tab:
            display_ai_insights(metrics, historical_data, summary_bot)
        
        with ai_predictions_tab:
            display_combined_ai_predictions(metrics, historical_data, ml)
        
    except Exception as e:
        st.error(f"Failed to load global metrics: {str(e)}")
        logger.error(f"display_global_metrics error: {e}")

def display_metrics_overview(metrics: Dict[str, Any], historical_data: List[Dict]):
    """Display metrics overview section"""
    st.subheader("🌍 Global Performance Overview")
    
    # Ensure metrics is a dictionary
    if not isinstance(metrics, dict):
        st.error("⚠️ Metrics data format is invalid. Please refresh the page.")
        return
    
    # Quick summary metrics
    col1, col2, col3 = st.columns(3)
    
    with col1:
        total_commits = metrics.get('total_commits', 0)
        if total_commits == 0:
            productivity = metrics.get('productivity_patterns', {})
            commit_times = productivity.get('commit_times', [])
            total_commits = len(commit_times) if commit_times else 0
        st.metric("Total Commits", f"{total_commits:,}", help="All commits across repositories")
    
    with col2:
        total_prs = metrics.get('total_prs', 0)
        if total_prs == 0:
            collaboration = metrics.get('collaboration', {})
            pull_requests = collaboration.get('pull_requests', [])
            total_prs = len(pull_requests) if pull_requests else 0
        st.metric("Pull Requests", f"{total_prs:,}", help="Total pull requests created")
    
    with col3:
        active_repos = metrics.get('active_repositories', 0)
        private_repos = metrics.get('private_repositories', 0)
        public_repos = metrics.get('public_repositories', 0)
        
        # Fallback logic for active_repos if not available
        if active_repos == 0:
            active_repos = metrics.get('analyzed_repositories', 0)
        if active_repos == 0:
            active_repos = len(metrics.get('repositories', []))
        if active_repos == 0:
            active_repos = metrics.get('total_repositories', 0)
        
        # Show total repositories with breakdown in help text
        breakdown_text = f"Total repositories analyzed: {active_repos}"
        if private_repos > 0 or public_repos > 0:
            breakdown_text += f" ({private_repos} private, {public_repos} public)"
        
        st.metric("Total Repositories", f"{active_repos}", help=breakdown_text)
    
    # DORA metrics
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        lead_time = metrics.get('dora', {}).get('lead_time', {}).get('total_lead_time_hours', 0)
        if lead_time == 0:
            lead_time = metrics.get('lead_time_hours', 0)
        st.metric("Lead Time", f"{lead_time:.1f} hrs" if lead_time > 0 else "No data", 
                 help="Average time from first commit to deployment")
    
    with col2:
        deploy_freq = metrics.get('dora', {}).get('deployment_frequency', {}).get('per_week', 0)
        if deploy_freq == 0:
            deploy_freq = metrics.get('deployment_frequency', 0)
        st.metric("Deploy Frequency", f"{deploy_freq:.1f}/week" if deploy_freq > 0 else "No data",
                 help="Average deployments per week")
    
    with col3:
        failure_rate = metrics.get('dora', {}).get('change_failure_rate', {}).get('percentage', 0)
        if failure_rate == 0:
            failure_rate = metrics.get('change_failure_rate', 0)
        success_rate = 100 - failure_rate
        st.metric("Success Rate", f"{success_rate:.0f}%" if failure_rate > 0 or success_rate == 100 else "No data",
                 help="Percentage of successful changes")
    
    with col4:
        review_coverage = metrics.get('code_quality', {}).get('review_coverage_percentage', 0)
        if review_coverage == 0:
            review_coverage = metrics.get('review_coverage_percentage', 0)
        st.metric("Review Coverage", f"{review_coverage:.0f}%" if review_coverage > 0 else "No data",
                 help="Percentage of changes reviewed")
    
    # Repository Analysis Summary
    private_repos = metrics.get('private_repositories', 0)
    public_repos = metrics.get('public_repositories', 0)
    total_commits_analyzed = metrics.get('total_commits_analyzed', 0)
    total_prs_analyzed = metrics.get('total_prs_analyzed', 0)
    
    if private_repos > 0 or public_repos > 0:
        st.subheader("📊 Complete GitHub Activity Analysis")
        
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric("🔒 Private Repos", f"{private_repos}", help="Private repositories included in analysis")
        
        with col2:
            st.metric("🌍 Public Repos", f"{public_repos}", help="Public repositories included in analysis")
        
        with col3:
            st.metric("📝 Commits Analyzed", f"{total_commits_analyzed:,}", help="Total commits across all repositories")
        
        with col4:
            st.metric("🔀 PRs Analyzed", f"{total_prs_analyzed:,}", help="Total pull requests across all repositories")
        
        # Show the comprehensive nature of the analysis
        if private_repos > 0 and public_repos > 0:
            st.success(f"✅ **Complete Analysis**: Your metrics include activity from {private_repos + public_repos} total repositories ({private_repos} private + {public_repos} public), giving you a comprehensive view of your entire GitHub presence.")
        elif private_repos > 0:
            st.info(f"🔒 **Private Repository Analysis**: Your metrics are based on {private_repos} private repositories. This gives you a complete view of your professional development work.")
        elif public_repos > 0:
            st.info(f"🌍 **Public Repository Analysis**: Your metrics are based on {public_repos} public repositories. Consider connecting private repositories for a complete analysis.")
    
    # Performance radar chart
    st.subheader("Performance Radar")
    try:
        radar_fig = create_radar_chart(metrics, "Performance vs Industry Benchmarks", "elite")
        if radar_fig:
            col1, col2 = st.columns([2, 1])
            with col1:
                st.plotly_chart(radar_fig, use_container_width=True, key="performance_radar_chart")
            with col2:
                st.markdown("""
                **Radar Chart Guide:**
                - **Lead Time**: Time from commit to deployment
                - **Deploy Frequency**: How often you deploy  
                - **Change Failure Rate**: Success rate of changes
                - **Recovery Time**: Time to fix issues
                - **Code Quality**: Review coverage & quality metrics
                
                **Performance Levels:**
                - 🟢 **Elite**: Top 10% performers
                - 🔵 **High**: Top 25% performers  
                - 🟡 **Medium**: Top 50% performers
                - **Low**: Below average
                """)
        else:
            st.info("Performance radar will appear here once you have more activity data (commits, PRs, deployments).")
    except Exception as e:
        st.warning("Performance radar temporarily unavailable: Limited data available")
        logger.error(f"Performance radar error: {e}")

def display_performance_analysis(metrics: Dict[str, Any], historical_data: List[Dict]):
    """Display detailed performance analysis"""
    st.subheader("🎯 Performance Analysis")
    
    # Ensure metrics is a dictionary
    if not isinstance(metrics, dict):
        st.error("⚠️ Performance data format is invalid. Please refresh the page.")
        return
    
    # Performance grade - always show structure
    st.subheader("📊 Performance Grade")
    perf_grade = metrics.get('performance_grade', {})
    
    if perf_grade:
        grade = perf_grade.get('overall_grade', 'N/A')
        percentage = perf_grade.get('percentage', 0)
        description = perf_grade.get('grade_description', '')
        
        grade_col1, grade_col2 = st.columns([1, 2])
        
        with grade_col1:
            st.markdown(f"""
            <div style='text-align: center; padding: 30px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); 
                        border-radius: 15px; color: white; margin: 20px 0;'>
                <h1 style='margin: 0; font-size: 3em;'>{grade}</h1>
                <h3 style='margin: 10px 0;'>{percentage:.1f}%</h3>
                <p style='margin: 0;'>{description}</p>
            </div>
            """, unsafe_allow_html=True)
        
        with grade_col2:
            st.write("**Performance Breakdown:**")
            category_scores = perf_grade.get('category_scores', {})
            category_max = perf_grade.get('category_max_scores', {})
            
            if category_scores:
                for category, score in category_scores.items():
                    max_score = category_max.get(category, score)
                    percentage = (score / max_score * 100) if max_score > 0 else 0
                    st.write(f"**{category.replace('_', ' ').title()}**: {score}/{max_score} ({percentage:.0f}%)")
                    st.progress(percentage / 100)
            else:
                st.info("No detailed performance breakdown available yet.")
    else:
        # Show placeholder when no performance grade data
        st.info("📊 Performance grade will be calculated once you have enough activity data.")
        
        grade_col1, grade_col2 = st.columns([1, 2])
        
        with grade_col1:
            st.markdown(f"""
            <div style='text-align: center; padding: 30px; background: linear-gradient(135deg, #cccccc 0%, #999999 100%); 
                        border-radius: 15px; color: white; margin: 20px 0;'>
                <h1 style='margin: 0; font-size: 3em;'>--</h1>
                <h3 style='margin: 10px 0;'>0.0%</h3>
                <p style='margin: 0;'>No Data Yet</p>
            </div>
            """, unsafe_allow_html=True)
        
        with grade_col2:
            st.write("**Performance Breakdown:**")
            st.info("Performance metrics will appear here once you start committing code and creating pull requests.")
    
    # Performance timeline - always show section
    st.subheader("📈 Performance Timeline")
    if historical_data and len(historical_data) > 1:
        timeline_fig = create_performance_timeline_chart(historical_data)
        st.plotly_chart(timeline_fig, use_container_width=True, key="performance_timeline")
    else:
        st.info("📈 Performance timeline will show trends once you have multiple days of activity data.")

def display_activity_patterns(metrics: Dict[str, Any]):
    """Display activity patterns and work habits"""
    st.subheader("⏰ Activity Patterns")
    
    # Ensure metrics is a dictionary
    if not isinstance(metrics, dict):
        st.error("⚠️ Activity data format is invalid. Please refresh the page.")
        return
    
    # Commit trends
    commit_fig = create_commit_trend_chart(metrics)
    if commit_fig:
        st.plotly_chart(commit_fig, use_container_width=True, key="activity_commit_trend")
    
    # Activity heatmap
    heatmap_fig = create_activity_heatmap(metrics)
    if heatmap_fig:
        st.plotly_chart(heatmap_fig, use_container_width=True, key="activity_heatmap_chart")
    
    # Work-life balance
    st.subheader("Work-Life Balance")
    wlb_fig = create_work_life_balance_chart(metrics)
    if wlb_fig:
        st.plotly_chart(wlb_fig, use_container_width=True, key="activity_wlb_chart")

def display_ai_insights(metrics: Dict[str, Any], historical_data: List[Dict], summary_bot):
    """Display AI-powered insights and recommendations"""
    st.subheader("🤖 AI-Powered Insights")
    
    try:
        insights = summary_bot.generate_comprehensive_summary(
            metrics, 
            historical_data, 
            {"scope": "global", "analysis_type": "detailed"}
        )
        
        if insights is None:
            insights = {
                "summary": "AI insights temporarily unavailable due to quota limits",
                "recommendations": [],
                "alerts": [],
                "trend_insights": []
            }
        
        # Display summary
        if insights.get('summary'):
            st.write("### Executive Summary")
            st.info(insights['summary'])
        
        # Display recommendations
        recommendations = insights.get('recommendations', [])
        if recommendations:
            st.write("### Actionable Recommendations")
            for i, rec in enumerate(recommendations, 1):
                st.write(f"{i}. {rec}")
        
        # Display alerts
        alerts = insights.get('alerts', [])
        if alerts:
            st.write("### ⚠️ Attention Required")
            for alert in alerts:
                st.error(alert)
        
        # Display trend insights
        trend_insights = insights.get('trend_insights', [])
        if trend_insights:
            st.write("### Trend Analysis")
            for insight in trend_insights:
                st.info(insight)
        
    except Exception as e:
        st.warning("AI insights temporarily unavailable. Using rule-based analysis.")
        logger.error(f"AI insights error: {e}")

def display_combined_ai_predictions(metrics: Dict[str, Any], historical_data: List[Dict], ml_analyzer):
    """Display combined AI predictions and continuous learning analysis."""
    st.subheader("🤖 AI-Powered Predictions & Continuous Learning")
    
    # Show different content based on data availability
    if not historical_data or len(historical_data) < 3:
        st.warning("📊 Need more historical data for predictions. Check back after a few data points are collected.")
        
        # Show what's needed
        col1, col2 = st.columns(2)
        with col1:
            st.info("🔮 **Basic Predictions**\n- Minimum: 3 data points\n- Simple trend forecasting\n- Lead time predictions")
        with col2:
            st.info("🧠 **Advanced ML Learning**\n- Minimum: 10 data points\n- Continuous learning models\n- Self-improving predictions")
        return
    
    # Determine which features to show based on data availability
    data_count = len(historical_data)
    
    if data_count < 10:
        # Show basic predictions only
        st.info(f"📊 **Current Status**: {data_count} data points available. Showing basic predictions. Advanced ML learning unlocks at 10+ data points.")
        display_predictions(metrics, historical_data, ml_analyzer)
    else:
        # Show both predictions and advanced ML learning
        st.success(f"🚀 **Full AI Mode**: {data_count} data points available. Both basic predictions and advanced continuous learning are active!")
        
        # Create expandable sections for better organization
        with st.expander("🔮 Quick Predictions & Forecasts", expanded=True):
            display_predictions(metrics, historical_data, ml_analyzer)
        
        with st.expander("🧠 Advanced Continuous Learning System", expanded=True):
            display_continuous_learning_analysis(metrics)

def display_predictions(metrics: Dict[str, Any], historical_data: List[Dict], ml_analyzer):
    """Display predictive analytics and forecasts"""
    # Remove duplicate subheader when called from expander
    # st.subheader("🔮 Predictive Analytics")
    
    if not historical_data or len(historical_data) < 3:
        st.warning("Need more historical data for predictions. Check back after a few data points are collected.")
        return
    
    try:
        # Debug info
        st.write(f"📊 Analyzing {len(historical_data)} historical data points...")
        
        # Lead time forecast
        st.write("### 📈 Lead Time Forecast")
        lead_time_prediction = ml_analyzer.predict_trend(
            historical_data, "dora.lead_time.total_lead_time_hours", days_ahead=14
        )
        
        if lead_time_prediction and lead_time_prediction.get("prediction"):
            col1, col2 = st.columns([2, 1])
            
            with col1:
                forecast_data = {
                    'dates': [(datetime.now() + timedelta(days=i)).strftime('%Y-%m-%d') for i in range(1, 15)],
                    'values': [lead_time_prediction['prediction'] * (1 + (i-7)/100) for i in range(14)]
                }
                forecast_fig = create_forecast_chart(
                    historical_data, forecast_data, "dora.lead_time.total_lead_time_hours", "Lead Time Forecast"
                )
                st.plotly_chart(forecast_fig, use_container_width=True, key="predictions_forecast_chart")
            
            with col2:
                st.metric("⏱️ Predicted Lead Time", f"{lead_time_prediction['prediction']:.1f} hrs")
                st.metric("🎯 Confidence", f"{lead_time_prediction['confidence']:.0f}%")
                st.write(f"**📊 Trend**: {lead_time_prediction['trend'].replace('_', ' ').title()}")
        else:
            st.info("🔄 Lead time prediction not available yet. Need more commit/PR data.")
        
        # Additional predictions
        st.write("### 🚀 Developer Productivity Forecast")
        
        # Get recent metrics for prediction base
        if historical_data:
            latest_data = historical_data[-5:]  # Last 5 data points
            avg_commits = sum(d.get('total_commits', 0) for d in latest_data) / len(latest_data)
            avg_prs = sum(d.get('total_prs', 0) for d in latest_data) / len(latest_data)
            
            col1, col2, col3 = st.columns(3)
            
            with col1:
                predicted_commits = avg_commits * 1.05  # 5% growth prediction
                st.metric("📝 Expected Commits (Next 7 days)", f"{predicted_commits:.1f}")
                
            with col2:
                predicted_prs = avg_prs * 1.1  # 10% growth prediction
                st.metric("🔀 Expected PRs (Next 7 days)", f"{predicted_prs:.1f}")
                
            with col3:
                velocity_trend = "📈 Increasing" if avg_commits > 2 else "📊 Stable"
                st.metric("🏃‍♂️ Velocity Trend", velocity_trend)
        
    except Exception as e:
        st.error(f"Prediction analysis failed: {str(e)}")
        st.write("**Debug info:**", str(e))
        logger.error(f"Prediction error: {e}")

def display_continuous_learning_analysis(metrics: Dict[str, Any]):
    """Display continuous learning ML model status and performance."""
    try:
        st.subheader("🧠 Continuous Learning ML Models")
        
        # Get continuous learning status from metrics
        learning_status = metrics.get("continuous_learning_status", {})
        ml_predictions = metrics.get("ml_predictions", {})
        
        if learning_status.get("status") == "error":
            st.error(f"🚨 ML Learning Error: {learning_status.get('error', 'Unknown error')}")
            return
        
        if learning_status.get("status") == "no_models":
            st.info("🤖 No ML models are currently active. Models will be created as historical data accumulates.")
            st.write("**Minimum requirements for ML models:**")
            st.write("- At least 10 historical data points")
            st.write("- Regular data refresh cycles")
            st.write("- Sufficient metric variation for learning")
            return
        
        # Display learning status overview
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            total_models = learning_status.get("total_models", 0)
            st.metric("Total ML Models", total_models)
        
        with col2:
            learning_models = learning_status.get("continuously_learning_models", 0)
            st.metric("Continuous Learning", learning_models)
        
        with col3:
            learning_percentage = learning_status.get("learning_percentage", 0)
            st.metric("Learning Coverage", f"{learning_percentage}%")
        
        with col4:
            recent_updates = learning_status.get("models_updated_recently", 0)
            st.metric("Recent Updates (24h)", recent_updates)
        
        # Status message
        message = learning_status.get("message", "")
        if "All" in message and "support continuous learning" in message:
            st.success(f"✅ {message}")
        elif "support continuous learning" in message:
            st.info(f"ℹ️ {message}")
        else:
            st.warning(f"⚠️ {message}")
        
        # Import visualization functions
        from frontend.visualization import create_continuous_learning_status_chart, create_ml_forecast_comparison_chart
        
        # Create two columns for visualizations
        col1, col2 = st.columns(2)
        
        with col1:
            st.subheader("📊 Learning Status Dashboard")
            try:
                learning_chart = create_continuous_learning_status_chart(learning_status)
                st.plotly_chart(learning_chart, use_container_width=True, key="ml_learning_status")
            except Exception as e:
                st.error(f"Failed to create learning status chart: {e}")
        
        with col2:
            st.subheader("📈 ML Forecasts")
            try:
                forecast_chart = create_ml_forecast_comparison_chart(ml_predictions)
                st.plotly_chart(forecast_chart, use_container_width=True, key="ml_forecasts")
            except Exception as e:
                st.error(f"Failed to create forecast chart: {e}")
        
        # Detailed model information
        if learning_status.get("model_details"):
            st.subheader("🔍 Model Details")
            
            model_details = learning_status["model_details"]
            
            # Handle both list and dict formats
            if isinstance(model_details, list):
                model_items = [(detail.get("metric", f"model_{i}"), detail) for i, detail in enumerate(model_details)]
            else:
                model_items = model_details.items()
            
            # Create expandable sections for each model
            for model_name, details in model_items:
                display_name = model_name.split(".")[-1].replace("_", " ").title()
                
                with st.expander(f"📊 {display_name} Model"):
                    detail_col1, detail_col2, detail_col3 = st.columns(3)
                    
                    with detail_col1:
                        st.write("**Model Type:**", details.get("type", "Unknown"))
                        st.write("**Continuous Learning:**", "✅ Yes" if details.get("supports_learning") else "❌ No")
                    
                    with detail_col2:
                        st.write("**Training Data Points:**", details.get("training_points", 0))
                        performance = details.get("performance", [])
                        if performance:
                            st.write("**Recent Performance:**", "Available")
                        else:
                            st.write("**Recent Performance:**", "Not yet available")
                    
                    with detail_col3:
                        supports_learning = details.get("supports_learning", False)
                        learning_emoji = "🟢" if supports_learning else "🔴"
                        st.write("**Learning Status:**", f"{learning_emoji} {'Active' if supports_learning else 'Static'}")
                        st.write("**Metric:**", details.get("metric", "Unknown"))
                    
                    # Show prediction if available
                    if model_name in ml_predictions:
                        pred_data = ml_predictions[model_name]
                        forecast = pred_data.get("forecast", {})
                        learning_status_detail = pred_data.get("learning_status", {})
                        
                        if forecast:
                            st.write("**📈 Latest Prediction:**")
                            values = forecast.get("values", [])
                            if values:
                                next_value = values[0] if len(values) > 0 else "N/A"
                                st.write(f"Next predicted value: **{next_value:.2f}**" if isinstance(next_value, (int, float)) else f"Next predicted value: **{next_value}**")
                                
                                # Show model metadata
                                metadata = forecast.get("model_metadata", {})
                                if metadata:
                                    st.write("**🔧 Model Info:**")
                                    st.write(f"- Training points: {metadata.get('training_points', 'N/A')}")
                                    st.write(f"- Incremental updates: {metadata.get('incremental_updates', 'N/A')}")
                                    if metadata.get("last_incremental_update", "none") != "none":
                                        st.write(f"- Last update: {metadata.get('last_incremental_update', 'N/A')}")
        
        # Learning progress summary
        total_incremental_updates = learning_status.get("total_incremental_updates", 0)
        if total_incremental_updates > 0:
            st.success(f"🎯 **Learning Progress**: Your models have performed {total_incremental_updates} incremental learning updates, continuously improving their predictions as new data becomes available!")
        else:
            st.info("📚 **Learning Status**: Models are trained but haven't received incremental updates yet. They will learn automatically as new data comes in!")
        
        # Show timestamp
        timestamp = learning_status.get("timestamp")
        if timestamp:
            try:
                from datetime import datetime
                ts = datetime.fromisoformat(timestamp)
                st.caption(f"Last updated: {ts.strftime('%Y-%m-%d %H:%M:%S')}")
            except:
                st.caption(f"Last updated: {timestamp}")
                
    except Exception as e:
        st.error(f"Failed to display continuous learning analysis: {str(e)}")
        logger.error(f"Continuous learning display error: {e}")

def main():
    """Main application flow"""
    st.set_page_config(
        page_title="GitHub Metrics Dashboard", 
        page_icon="📊", 
        layout="wide"
    )
    
    # Initialize session state
    if 'metrics_refreshed' not in st.session_state:
        st.session_state.metrics_refreshed = False
    if 'last_refresh' not in st.session_state:
        st.session_state.last_refresh = datetime.now()
    
    # OAuth server is started via startup script in AWS deployment
    from config import IS_AWS_DEPLOYMENT
    if IS_AWS_DEPLOYMENT:
        # OAuth server is already running in the background via startup script
        if 'oauth_server_started' not in st.session_state:
            st.session_state.oauth_server_started = True
            logger.info("OAuth callback server running via startup script on port 5000")
    
    db = get_datastore()
    
    # Handle OAuth callback
    handle_oauth_callback()
    
    # Check for existing session
    if not check_existing_session():
        show_login()
        return
    
    # Get user information
    user = st.session_state.auth['user'] if isinstance(st.session_state.auth, dict) else st.session_state.auth.user
    user_email = user['email'] if isinstance(user, dict) else user.email
    
    # Create user session for GitHub API calls
    user_session = {
        'github_token': st.session_state.get('github_token') or (user.get('access_token') if isinstance(user, dict) else getattr(user, 'access_token', None))
    }
    
    user_id = get_user_id_by_email(user_email, user_session)
    
    # Check if we successfully got a user ID
    if not user_id:
        st.error("Failed to initialize user account. Please try logging in again.")
        if st.button("Try Again"):
            if 'auth' in st.session_state:
                del st.session_state['auth']
            st.rerun()
        return
    
    # Sidebar for user info and controls
    with st.sidebar:
        st.markdown(f"### 👤 {user_email}")
        st.markdown("---")
        
        # Refresh controls
        st.markdown("### Data Controls")
        col1, col2 = st.columns(2)
        
        with col1:
            if st.button("🌍 Global", help="Refresh global metrics"):
                with st.spinner("Refreshing global metrics..."):
                    success = refresh_metrics(user_email, "global", force=True, user_session=st.session_state.auth)
                    if success:
                        st.session_state.metrics_refreshed = True
                        st.session_state.last_refresh = datetime.now()
                        st.success("✅ Global metrics refreshed!")
                        st.rerun()
                    else:
                        st.error("❌ Failed to refresh global metrics")
        
        with col2:
            if st.button("📁 Tracked", help="Refresh tracked repo metrics"):
                with st.spinner("Refreshing tracked repos..."):
                    success = refresh_metrics(user_email, "tracked", force=True, user_session=st.session_state.auth)
                    if success:
                        st.session_state.metrics_refreshed = True
                        st.session_state.last_refresh = datetime.now()
                        st.success("✅ Tracked repos refreshed!")
                        st.rerun()
                    else:
                        st.error("❌ Failed to refresh tracked repos")
        
        st.markdown("---")
        
        # Account Management  
        st.subheader("🔐 Account Management")
        
        col1, col2 = st.columns(2)
        
        with col1:
            if st.button("🚪 Sign Out", use_container_width=True, type="secondary"):
                # Get current user email before clearing
                current_user_email = st.session_state.get('auth', {}).get('user', {}).get('email')
                
                # Mark explicit logout to prevent auto-signin for this specific user
                st.session_state.explicit_logout = True
                st.session_state.logged_out_user = current_user_email  # Track which user logged out
                st.session_state.signed_out_timestamp = time.time()
                st.session_state.force_reauth = True  # Force complete re-authentication
                
                # Different logout behavior based on deployment mode
                if not IS_AWS_DEPLOYMENT:
                    # Development mode: Sign out from Supabase backend
                    db.sign_out()
                
                # Clear ALL session state data except logout tracking
                keys_to_clear = list(st.session_state.keys())
                for key in keys_to_clear:
                    if key not in ['explicit_logout', 'logged_out_user', 'signed_out_timestamp', 'force_reauth']:  # Keep the logout flags
                        del st.session_state[key]
                
                # Add additional flags to prevent session restoration
                st.session_state.force_reauth = True
                st.session_state.signed_out_timestamp = time.time()
                
                st.success("🚪 Successfully signed out!")
                st.info("✅ Your session has been cleared. You can now sign in with a different GitHub account.")
                
                # Force immediate re-run to show login screen
                st.rerun()
                st.stop()
        
        with col2:
            if st.button("🔄 Switch Account", use_container_width=True, type="primary"):
                # Mark explicit logout to prevent auto-signin
                st.session_state.explicit_logout = True
                st.session_state.signed_out_timestamp = time.time()
                st.session_state.force_reauth = True  # Force complete re-authentication
                
                # Different behavior based on deployment mode
                if not IS_AWS_DEPLOYMENT:
                    # Development mode: Sign out from Supabase backend
                    db.sign_out()
                
                # Clear ALL session state data
                keys_to_clear = list(st.session_state.keys())
                for key in keys_to_clear:
                    if key != 'explicit_logout':  # Keep the logout flag
                        del st.session_state[key]
                
                # Add additional flags for account switching
                st.session_state.force_reauth = True
                st.session_state.switch_account_mode = True
                st.session_state.signed_out_timestamp = time.time()
                
                st.success("🔄 Switching accounts...")
                st.info("🧹 Clearing sessions to allow account selection...")
                
                # Force immediate re-run to show login screen
                st.rerun()
                st.stop()
    
    # Main content
    st.title("📊 GitHub Developer Intelligence")
    
    # Analysis scope selector
    st.subheader("Analysis Scope")
    scope = st.radio(
        "Select scope:", 
        ["Global Activity", "Tracked Repositories"], 
        horizontal=True, 
        label_visibility="collapsed"
    )
    
    # Refresh metrics if needed
    if not st.session_state.metrics_refreshed:
        with st.spinner("Analyzing your GitHub activity..."):
            refresh_scope = "global" if scope == "Global Activity" else "tracked"
            success = refresh_metrics(
                user_email, 
                refresh_scope, 
                force=False, 
                user_session=st.session_state.auth
            )
            if success:
                st.session_state.metrics_refreshed = True
                st.session_state.last_refresh = datetime.now()
                st.rerun()
    
    # Display content based on scope
    user_repos = db.get_user_repos(user_id) if scope == "Tracked Repositories" else []
    
    # Create tabs
    tabs = []
    if scope == "Global Activity":
        tabs.append("🌍 Global Activity")
    
    for repo in user_repos:
        repo_name = get_repo_full_name(repo)
        tabs.append(f"📦 {repo_name}")
    
    tabs.append("⚙️ Manage")
    
    tab_objects = st.tabs(tabs)
    
    # Display content in tabs
    tab_idx = 0
    
    if scope == "Global Activity":
        with tab_objects[tab_idx]:
            display_global_metrics(user_email, user_id)
        tab_idx += 1
    
    # Repository-specific tabs
    for i, repo in enumerate(user_repos):
        with tab_objects[tab_idx + i]:
            display_repo_metrics(repo, user_email)
    
    # Management tab
    with tab_objects[-1]:
        show_repo_management(user_email, user_session)

def display_repo_metrics(repo_data: Dict, user_email: str):
    """Display repository-specific metrics"""
    repo_name = get_repo_full_name(repo_data)
    if not repo_name or repo_name == "Unknown Repository":
        st.error("⚠️ Repository information is incomplete or invalid")
        st.json(repo_data)
        return
    
    st.subheader(f"📦 {repo_name}")
    
    # Parse owner and repo name
    try:
        owner, name = repo_name.split('/', 1)
    except ValueError:
        st.error(f"Invalid repository format: {repo_name}")
        return
    
    # Create tabs for different repository views
    tab1, tab2, tab3, tab4 = st.tabs(["📊 Overview", "🔄 DORA Metrics", "📈 Trends", "👥 Contributors"])
    
    with tab1:
        display_repo_overview(owner, name, user_email)
    
    with tab2:
        display_repo_dora_metrics(owner, name, user_email)
    
    with tab3:
        display_repo_trends(owner, name, user_email)
    
    with tab4:
        display_repo_contributors(owner, name, user_email)

def display_repo_overview(owner: str, name: str, user_email: str):
    """Display repository overview metrics"""
    try:
        # Get GitHub token from session
        github_token = st.session_state.auth.get('github_token') or st.session_state.auth.get('provider_token')
        if not github_token:
            st.error("GitHub token not found. Please re-authenticate.")
            return
        
        # Initialize refresh manager
        refresh_manager = get_refresh_manager(github_token)
        
        # Show loading spinner
        with st.spinner(f"Fetching metrics for {owner}/{name}..."):
            # Fetch repository metrics with user session
            user_session = st.session_state.auth
            result = refresh_manager.refresh_repository_metrics(owner, name, force=False, user_session=user_session)
        
        if not result.get("success"):
            if "rate_limited" in result.get("error", ""):
                st.warning("⏳ GitHub API rate limit reached. Showing cached data if available.")
                # Try to get cached data
                user_session = st.session_state.auth
                result = refresh_manager.refresh_repository_metrics(owner, name, force=False, user_session=user_session)
            else:
                st.error(f"Failed to fetch repository metrics: {result.get('error', 'Unknown error')}")
                return
        
        metrics = result.get("metrics", {})
        if not metrics:
            st.warning("No metrics data available for this repository.")
            return
        
        # Display overview metrics
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric(
                "Total Commits",
                metrics.get("total_commits", 0),
                help="Total number of commits in the analysis period"
            )
        
        with col2:
            st.metric(
                "Total PRs",
                metrics.get("total_prs", 0),
                help="Total number of pull requests"
            )
        
        with col3:
            lead_time = metrics.get("dora", {}).get("lead_time", {}).get("total_lead_time_hours", 0)
            st.metric(
                "Avg Lead Time",
                f"{lead_time:.1f}h",
                help="Average time from first commit to merge"
            )
        
        with col4:
            deploy_freq = metrics.get("dora", {}).get("deployment_frequency", {}).get("per_week", 0)
            st.metric(
                "Deployments/Week",
                f"{deploy_freq:.1f}",
                help="Average deployments per week"
            )
        
        # Repository insights
        repo_insights = metrics.get("repository_insights", {})
        if repo_insights:
            st.subheader("📋 Repository Information")
            col1, col2 = st.columns(2)
            
            with col1:
                # Primary language with proper handling
                primary_lang = repo_insights.get('primaryLanguage', {})
                if isinstance(primary_lang, dict):
                    language = primary_lang.get('name', 'Unknown')
                    lang_color = primary_lang.get('color', '#cccccc')
                else:
                    language = str(primary_lang) if primary_lang else 'Unknown'
                    lang_color = '#cccccc'
                st.info(f"**Primary Language:** {language}")
                
                # Show language distribution if available
                languages = repo_insights.get('languages', {}).get('nodes', [])
                if languages and len(languages) > 1:
                    lang_names = [lang.get('name', 'Unknown') for lang in languages[:5]]
                    st.info(f"**Languages:** {', '.join(lang_names)}")
                
                stars = repo_insights.get('stargazerCount', 0)
                if not isinstance(stars, (int, float)):
                    stars = 0
                st.info(f"**Stars:** {int(stars):,}")
                
                forks = repo_insights.get('forkCount', 0)
                if not isinstance(forks, (int, float)):
                    forks = 0
                st.info(f"**Forks:** {int(forks):,}")
            
            with col2:
                issues = repo_insights.get('openIssues', {}).get('totalCount', 0)
                if not isinstance(issues, (int, float)):
                    issues = 0
                st.info(f"**Open Issues:** {int(issues):,}")
                
                watchers = repo_insights.get('watcherCount', {}).get('totalCount', 0)
                if not isinstance(watchers, (int, float)):
                    watchers = 0
                st.info(f"**Watchers:** {int(watchers):,}")
                
                disk_usage = repo_insights.get('diskUsage', 0)
                if not isinstance(disk_usage, (int, float)):
                    disk_usage = 0
                
                # Convert KB to human-readable format
                if disk_usage > 1024:
                    size_mb = disk_usage / 1024
                    if size_mb > 1024:
                        size_gb = size_mb / 1024
                        st.info(f"**Size:** {size_gb:.1f} GB")
                    else:
                        st.info(f"**Size:** {size_mb:.1f} MB")
                else:
                    st.info(f"**Size:** {int(disk_usage):,} KB")
                    
                # Repository age and activity
                created_at = repo_insights.get('createdAt')
                if created_at:
                    try:
                        from datetime import datetime
                        created_date = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                        age_days = (datetime.now(created_date.tzinfo) - created_date).days
                        if age_days > 365:
                            age_str = f"{age_days // 365} years"
                        else:
                            age_str = f"{age_days} days"
                        st.info(f"**Age:** {age_str}")
                    except:
                        pass
        
        # Advanced repository health metrics
        st.subheader("🏥 Repository Health Indicators")
        health_col1, health_col2, health_col3 = st.columns(3)
        
        with health_col1:
            # Calculate PR merge rate
            total_prs = metrics.get("total_prs", 0)
            merged_prs = repo_insights.get('pullRequestsMerged', {}).get('totalCount', 0)
            if isinstance(merged_prs, dict):
                merged_prs = merged_prs.get('totalCount', 0)
            
            merge_rate = (merged_prs / total_prs * 100) if total_prs > 0 else 0
            
            if merge_rate >= 80:
                merge_color = "🟢"
            elif merge_rate >= 60:
                merge_color = "🟡"
            else:
                merge_color = "🔴"
                
            st.metric(
                "PR Merge Rate",
                f"{merge_color} {merge_rate:.1f}%",
                help="Percentage of PRs that get merged"
            )
        
        with health_col2:
            # Activity level based on commits
            commits_count = metrics.get("total_commits", 0)
            if commits_count > 100:
                activity_level = "🔥 Very Active"
            elif commits_count > 50:
                activity_level = "📈 Active"
            elif commits_count > 10:
                activity_level = "📊 Moderate"
            else:
                activity_level = "📉 Low Activity"
                
            st.metric(
                "Activity Level",
                activity_level,
                help="Based on recent commit activity"
            )
        
        with health_col3:
            # Issue health
            open_issues = repo_insights.get('openIssues', {}).get('totalCount', 0)
            if isinstance(open_issues, dict):
                open_issues = open_issues.get('totalCount', 0)
                
            if open_issues < 5:
                issue_health = "🟢 Excellent"
            elif open_issues < 20:
                issue_health = "🟡 Good"
            else:
                issue_health = "🔴 Needs Attention"
                
            st.metric(
                "Issue Health",
                issue_health,
                f"{open_issues} open",
                help="Based on number of open issues"
            )
        
        # Performance grade for repository
        perf_grade = metrics.get("performance_grade", {})
        if perf_grade:
            st.subheader("🎯 Repository Performance Grade")
            
            grade = perf_grade.get("overall_grade", "N/A")
            percentage = perf_grade.get("percentage", 0)
            
            # Color-code the grade
            if percentage >= 85:
                grade_color = "🟢"
            elif percentage >= 70:
                grade_color = "🟡"
            else:
                grade_color = "🔴"
            
            col1, col2 = st.columns([1, 2])
            
            with col1:
                st.metric(
                    "Overall Grade",
                    f"{grade_color} {grade}",
                    f"{percentage}%"
                )
            
            with col2:
                # Show explanations
                explanations = perf_grade.get("explanations", [])
                if explanations:
                    for explanation in explanations[:3]:  # Show top 3
                        st.success(explanation)
    
    except Exception as e:
        logger.error(f"Error displaying repository overview: {e}")
        st.error(f"Error loading repository metrics: {str(e)}")

def display_repo_dora_metrics(owner: str, name: str, user_email: str):
    """Display repository DORA metrics"""
    try:
        github_token = st.session_state.auth.get('github_token') or st.session_state.auth.get('provider_token')
        if not github_token:
            st.error("GitHub token not found. Please re-authenticate.")
            return
        
        refresh_manager = get_refresh_manager(github_token)
        
        with st.spinner("Loading DORA metrics..."):
            user_session = st.session_state.auth
            result = refresh_manager.refresh_repository_metrics(owner, name, force=False, user_session=user_session)
        
        if not result.get("success"):
            st.error(f"Failed to fetch DORA metrics: {result.get('error', 'Unknown error')}")
            return
        
        metrics = result.get("metrics", {})
        dora_metrics = metrics.get("dora", {})
        
        if not dora_metrics:
            st.warning("No DORA metrics available for this repository.")
            return
        
        # Lead Time
        st.subheader("⏱️ Lead Time for Changes")
        lead_time_data = dora_metrics.get("lead_time", {})
        
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric(
                "Total Lead Time",
                f"{lead_time_data.get('total_lead_time_hours', 0):.1f}h",
                help="Average time from first commit to merge"
            )
        
        with col2:
            st.metric(
                "Code Time",
                f"{lead_time_data.get('code_time_hours', 0):.1f}h",
                help="Time from first commit to PR creation"
            )
        
        with col3:
            st.metric(
                "Review Time",
                f"{lead_time_data.get('review_time_hours', 0):.1f}h",
                help="Time from PR creation to first review"
            )
        
        with col4:
            st.metric(
                "Merge Time",
                f"{lead_time_data.get('merge_time_hours', 0):.1f}h",
                help="Time from last review to merge"
            )
        
        # Lead time percentiles
        st.subheader("📊 Lead Time Distribution")
        col1, col2, col3 = st.columns(3)
        
        with col1:
            st.metric("P50 (Median)", f"{lead_time_data.get('p50_lead_time_hours', 0):.1f}h")
        with col2:
            st.metric("P90", f"{lead_time_data.get('p90_lead_time_hours', 0):.1f}h")
        with col3:
            st.metric("P95", f"{lead_time_data.get('p95_lead_time_hours', 0):.1f}h")
        
        # Deployment Frequency
        st.subheader("🚀 Deployment Frequency")
        deploy_data = dora_metrics.get("deployment_frequency", {})
        
        col1, col2, col3 = st.columns(3)
        
        with col1:
            st.metric(
                "Per Week",
                f"{deploy_data.get('per_week', 0):.1f}",
                help="Average deployments per week"
            )
        
        with col2:
            st.metric(
                "Per Day",
                f"{deploy_data.get('per_day', 0):.2f}",
                help="Average deployments per day"
            )
        
        with col3:
            trend = deploy_data.get('trend_direction', 'stable')
            trend_emoji = {"increasing": "📈", "decreasing": "📉", "stable": "➡️"}.get(trend, "➡️")
            st.metric(
                "Trend",
                f"{trend_emoji} {trend.title()}",
                help="Deployment frequency trend"
            )
        
        # Change Failure Rate
        st.subheader("🔧 Change Failure Rate")
        failure_data = dora_metrics.get("change_failure_rate", {})
        
        col1, col2, col3 = st.columns(3)
        
        with col1:
            failure_rate = failure_data.get('percentage', 0)
            st.metric(
                "Failure Rate",
                f"{failure_rate:.1f}%",
                help="Percentage of changes that result in failures"
            )
        
        with col2:
            st.metric(
                "Total Failures",
                failure_data.get('total_failures', 0),
                help="Total number of failed changes"
            )
        
        with col3:
            st.metric(
                "Hotfix Count",
                failure_data.get('hotfix_count', 0),
                help="Number of hotfix commits detected"
            )
        
        # Failure types breakdown
        failure_types = failure_data.get('failure_types', {})
        if failure_types:
            st.subheader("🔍 Failure Types")
            failure_df = pd.DataFrame(
                list(failure_types.items()),
                columns=['Type', 'Count']
            )
            
            if not failure_df.empty:
                fig = create_bar_chart(
                    failure_df, 'Type', 'Count',
                    'Failure Types Distribution',
                    'darkred'
                )
                st.plotly_chart(fig, use_container_width=True)
        
        # Mean Time to Recovery
        st.subheader("🔄 Mean Time to Recovery")
        mttr_data = dora_metrics.get("mttr", {})
        
        col1, col2, col3 = st.columns(3)
        
        with col1:
            st.metric(
                "MTTR Hours",
                f"{mttr_data.get('mttr_hours', 0):.1f}h",
                help="Average time to recover from failures"
            )
        
        with col2:
            st.metric(
                "MTTR Days",
                f"{mttr_data.get('mttr_days', 0):.2f}",
                help="Average recovery time in days"
            )
        
        with col3:
            st.metric(
                "Recovery Incidents",
                mttr_data.get('recovery_incidents', 0),
                help="Number of recovery incidents tracked"
            )
    
    except Exception as e:
        logger.error(f"Error displaying repository DORA metrics: {e}")
        st.error(f"Error loading DORA metrics: {str(e)}")

def display_repo_trends(owner: str, name: str, user_email: str):
    """Display repository trend analysis with advanced visualizations"""
    try:
        github_token = st.session_state.auth.get('github_token') or st.session_state.auth.get('provider_token')
        if not github_token:
            st.error("GitHub token not found. Please re-authenticate.")
            return
        
        refresh_manager = get_refresh_manager(github_token)
        
        with st.spinner("Loading trend analysis..."):
            user_session = st.session_state.auth
            result = refresh_manager.refresh_repository_metrics(owner, name, force=False, user_session=user_session)
        
        if not result.get("success"):
            st.error(f"Failed to fetch trend data: {result.get('error', 'Unknown error')}")
            return
        
        metrics = result.get("metrics", {})
        
        # Advanced trend analysis dashboard
        st.subheader("📊 Activity Trend Analysis")
        
        # Create two columns for side-by-side charts
        trend_col1, trend_col2 = st.columns(2)
        
        with trend_col1:
            # Weekly commit frequency with enhanced visualization
            weekly_commits = metrics.get("weekly_commit_frequency", {})
            if weekly_commits:
                st.write("**📅 Weekly Commit Activity**")
                
                try:
                    # Convert to DataFrame and sort
                    weeks_data = []
                    for week, commits in weekly_commits.items():
                        if isinstance(week, str) and isinstance(commits, (int, float)):
                            weeks_data.append([week, commits])
                    
                    if weeks_data:
                        weeks_df = pd.DataFrame(weeks_data, columns=['Week', 'Commits'])
                        weeks_df = weeks_df.sort_values('Week')
                        
                        if not weeks_df.empty:
                            # Calculate trend indicators
                            recent_avg = weeks_df.tail(4)['Commits'].mean() if len(weeks_df) >= 4 else weeks_df['Commits'].mean()
                            overall_avg = weeks_df['Commits'].mean()
                            
                            trend_indicator = "📈" if recent_avg > overall_avg * 1.1 else "📉" if recent_avg < overall_avg * 0.9 else "➡️"
                            
                            fig = create_line_chart(
                                weeks_df, 'Week', 'Commits',
                                f'Weekly Commits {trend_indicator}',
                                'steelblue'
                            )
                            st.plotly_chart(fig, use_container_width=True)
                            
                            # Show trend stats
                            st.caption(f"Recent avg: {recent_avg:.1f} | Overall avg: {overall_avg:.1f}")
                    else:
                        st.info("No valid weekly commit data available")
                except Exception as e:
                    logger.warning(f"Error creating weekly commit chart: {e}")
                    st.warning("Unable to display weekly commit trends")
            else:
                st.info("No weekly commit data available")
        
        with trend_col2:
            # Deployment frequency trends with enhanced analysis
            deploy_trends = metrics.get("dora", {}).get("deployment_frequency", {}).get("weekly_trend", {})
            if deploy_trends:
                st.write("**🚀 Weekly Deployment Trend**")
                
                try:
                    # Convert to DataFrame and sort
                    deploy_data = []
                    for week, deployments in deploy_trends.items():
                        if isinstance(week, str) and isinstance(deployments, (int, float)):
                            deploy_data.append([week, deployments])
                    
                    if deploy_data:
                        deploy_df = pd.DataFrame(deploy_data, columns=['Week', 'Deployments'])
                        deploy_df = deploy_df.sort_values('Week')
                        
                        if not deploy_df.empty:
                            # Calculate deployment frequency trend
                            recent_avg = deploy_df.tail(4)['Deployments'].mean() if len(deploy_df) >= 4 else deploy_df['Deployments'].mean()
                            overall_avg = deploy_df['Deployments'].mean()
                            
                            trend_indicator = "🚀" if recent_avg > overall_avg * 1.1 else "🐌" if recent_avg < overall_avg * 0.9 else "➡️"
                            
                            fig = create_line_chart(
                                deploy_df, 'Week', 'Deployments',
                                f'Weekly Deployments {trend_indicator}',
                                'green'
                            )
                            st.plotly_chart(fig, use_container_width=True)
                            
                            # Show deployment stats
                            st.caption(f"Recent avg: {recent_avg:.1f} | Overall avg: {overall_avg:.1f}")
                    else:
                        st.info("No valid deployment trend data available")
                except Exception as e:
                    logger.warning(f"Error creating deployment trend chart: {e}")
                    st.warning("Unable to display deployment trends")
            else:
                st.info("No deployment trend data available")
        
        # Performance trends over time
        st.subheader("📈 Performance Trend Analysis")
        
        perf_col1, perf_col2 = st.columns(2)
        
        with perf_col1:
            # Lead time trends (if we had historical data)
            dora_metrics = metrics.get("dora", {})
            lead_time_data = dora_metrics.get("lead_time", {})
            
            if lead_time_data:
                st.write("**⏱️ Lead Time Breakdown**")
                
                # Create a breakdown chart of lead time components
                lead_time_components = {
                    'Code Time': lead_time_data.get('code_time_hours', 0),
                    'Review Time': lead_time_data.get('review_time_hours', 0),
                    'Merge Time': lead_time_data.get('merge_time_hours', 0)
                }
                
                # Filter out zero values
                lead_time_components = {k: v for k, v in lead_time_components.items() if v > 0}
                
                if lead_time_components:
                    breakdown_df = pd.DataFrame(
                        list(lead_time_components.items()),
                        columns=['Phase', 'Hours']
                    )
                    
                    fig = create_bar_chart(
                        breakdown_df, 'Phase', 'Hours',
                        'Lead Time Component Breakdown',
                        'orange'
                    )
                    st.plotly_chart(fig, use_container_width=True)
                else:
                    st.info("No lead time component data available")
        
        with perf_col2:
            # Code quality trends
            code_quality = metrics.get("code_quality", {})
            if code_quality:
                st.write("**📊 Code Quality Distribution**")
                
                # Commit size distribution
                size_dist = code_quality.get("commit_size_distribution", {})
                if size_dist:
                    try:
                        # Convert to DataFrame with validation
                        size_data = []
                        for size_category, count in size_dist.items():
                            if isinstance(size_category, str) and isinstance(count, (int, float)) and count > 0:
                                # Map categories to more readable names
                                category_names = {
                                    'small': 'Small (<50 lines)',
                                    'medium': 'Medium (50-200 lines)',
                                    'large': 'Large (>200 lines)'
                                }
                                readable_name = category_names.get(size_category, size_category.title())
                                size_data.append([readable_name, count])
                        
                        if size_data:
                            size_df = pd.DataFrame(size_data, columns=['Size', 'Count'])
                            
                            fig = create_pie_chart(
                                size_df, 'Count', 'Size',
                                'Commit Size Distribution'
                            )
                            st.plotly_chart(fig, use_container_width=True)
                        else:
                            st.info("No valid commit size data available")
                    except Exception as e:
                        logger.warning(f"Error creating commit size chart: {e}")
                        st.warning("Unable to display commit size distribution")
        
        # Advanced metrics summary
        st.subheader("🎯 Key Performance Indicators")
        
        kpi_col1, kpi_col2, kpi_col3, kpi_col4 = st.columns(4)
        
        with kpi_col1:
            review_coverage = code_quality.get('review_coverage_percentage', 0)
            coverage_color = "🟢" if review_coverage >= 80 else "🟡" if review_coverage >= 60 else "🔴"
            st.metric("Review Coverage", f"{coverage_color} {review_coverage:.1f}%")
        
        with kpi_col2:
            avg_commit_size = code_quality.get('avg_commit_size', 0)
            size_color = "🟢" if avg_commit_size <= 200 else "🟡" if avg_commit_size <= 500 else "🔴"
            st.metric("Avg Commit Size", f"{size_color} {avg_commit_size:.0f} lines")
        
        with kpi_col3:
            large_prs_pct = code_quality.get('large_prs_percentage', 0)
            pr_color = "🟢" if large_prs_pct <= 20 else "🟡" if large_prs_pct <= 40 else "🔴"
            st.metric("Large PRs", f"{pr_color} {large_prs_pct:.1f}%")
        
        with kpi_col4:
            # Calculate velocity (commits per week)
            total_commits = metrics.get('total_commits', 0)
            weeks_with_activity = len([w for w in weekly_commits.values() if w > 0]) if weekly_commits else 1
            velocity = total_commits / weeks_with_activity if weeks_with_activity > 0 else 0
            velocity_color = "🔥" if velocity >= 10 else "📈" if velocity >= 5 else "📊"
            st.metric("Velocity", f"{velocity_color} {velocity:.1f} commits/week")
    
    except Exception as e:
        logger.error(f"Error displaying repository trends: {e}")
        st.error(f"Error loading trend analysis: {str(e)}")

def display_repo_contributors(owner: str, name: str, user_email: str):
    """Display repository contributor analysis with advanced insights"""
    collaboration = {}  # Initialize collaboration variable
    try:
        github_token = st.session_state.auth.get('github_token') or st.session_state.auth.get('provider_token')
        if not github_token:
            st.error("GitHub token not found. Please re-authenticate.")
            return
        
        refresh_manager = get_refresh_manager(github_token)
        
        with st.spinner("Loading contributor analysis..."):
            user_session = st.session_state.auth
            result = refresh_manager.refresh_repository_metrics(owner, name, force=False, user_session=user_session)
        
        if not result.get("success"):
            st.error(f"Failed to fetch contributor data: {result.get('error', 'Unknown error')}")
            return
        
        metrics = result.get("metrics", {})
        collaboration = metrics.get("collaboration", {})
        
        if not collaboration:
            st.warning("No collaboration data available for this repository.")
            return
        
        st.subheader("👥 Team Collaboration Analysis")
        
        # Collaboration overview metrics
        collab_col1, collab_col2, collab_col3, collab_col4 = st.columns(4)
        
        with collab_col1:
            unique_authors = collaboration.get('unique_authors', 0)
            st.metric(
                "Active Contributors",
                unique_authors,
                help="Number of unique commit authors"
            )
        
        with collab_col2:
            unique_reviewers = collaboration.get('unique_reviewers', 0)
            st.metric(
                "Active Reviewers",
                unique_reviewers,
                help="Number of unique code reviewers"
            )
        
        with collab_col3:
            reviews_per_pr = collaboration.get('reviews_per_pr', 0)
            st.metric(
                "Reviews per PR",
                f"{reviews_per_pr:.1f}",
                help="Average number of reviews per pull request"
            )
        
        with collab_col4:
            response_time = collaboration.get('avg_review_response_time_hours', 0)
            if response_time < 24:
                response_color = "🟢"
            elif response_time < 72:
                response_color = "🟡"
            else:
                response_color = "🔴"
            st.metric(
                "Avg Response Time",
                f"{response_color} {response_time:.1f}h",
                help="Average time to first review"
            )
        
        # Top reviewers analysis
        top_reviewers = collaboration.get('top_reviewers', {})
        if top_reviewers:
            st.subheader("🏆 Top Code Reviewers")
            
            # Convert to DataFrame for better visualization
            try:
                reviewer_data = []
                for reviewer, count in list(top_reviewers.items())[:10]:  # Top 10
                    if isinstance(reviewer, str) and isinstance(count, (int, float)):
                        reviewer_data.append([reviewer, count])
                
                if reviewer_data:
                    reviewers_df = pd.DataFrame(reviewer_data, columns=['Reviewer', 'Reviews'])
                    reviewers_df = reviewers_df.sort_values('Reviews', ascending=False)
                    
                    # Create horizontal bar chart for better readability
                    fig = create_bar_chart(
                        reviewers_df, 'Reviewer', 'Reviews',
                        'Top Code Reviewers by Review Count',
                        'lightblue'
                    )
                    st.plotly_chart(fig, use_container_width=True)
                    
                    # Show detailed table
                    with st.expander("📊 Detailed Reviewer Statistics"):
                        # Add percentage calculation
                        total_reviews = reviewers_df['Reviews'].sum()
                        reviewers_df['Percentage'] = (reviewers_df['Reviews'] / total_reviews * 100).round(1)
                        st.dataframe(reviewers_df, use_container_width=True)
                else:
                    st.info("No valid reviewer data available")
            except Exception as e:
                logger.warning(f"Error creating reviewers chart: {e}")
                st.warning("Unable to display reviewer statistics")
        
        # Collaboration health indicators
        st.subheader("🩺 Collaboration Health")
        
        health_col1, health_col2 = st.columns(2)
        
        with health_col1:
            # Review participation rate
            total_prs = metrics.get('total_prs', 0)
            total_reviews = collaboration.get('total_reviews', 0)
            
            if total_prs > 0:
                review_participation = (total_reviews / (total_prs * unique_authors)) * 100 if unique_authors > 0 else 0
                
                if review_participation >= 80:
                    participation_health = "🟢 Excellent"
                elif review_participation >= 50:
                    participation_health = "🟡 Good"
                else:
                    participation_health = "🔴 Needs Improvement"
                
                st.metric(
                    "Review Participation",
                    participation_health,
                    f"{review_participation:.1f}%",
                    help="How actively team members participate in code reviews"
                )
        
        with health_col2:
            # Collaboration diversity index
            collab_index = collaboration.get('collaboration_index', 0)
            
            if collab_index >= 25:
                diversity_health = "🟢 High Diversity"
            elif collab_index >= 10:
                diversity_health = "🟡 Moderate Diversity"
            else:
                diversity_health = "🔴 Low Diversity"
            
            st.metric(
                "Team Diversity",
                diversity_health,
                f"Index: {collab_index}",
                help="Measure of contributor and reviewer diversity"
            )
        
        # Productivity patterns from team perspective
        productivity = metrics.get("productivity_patterns", {})
        if productivity:
            st.subheader("⏰ Team Work Patterns")
            
            # Work-life balance analysis
            weekend_work = productivity.get('weekend_work_percentage', 0)
            late_night_work = productivity.get('late_night_work_percentage', 0)
            
            pattern_col1, pattern_col2 = st.columns(2)
            
            with pattern_col1:
                if weekend_work <= 10:
                    weekend_health = "🟢 Healthy"
                elif weekend_work <= 25:
                    weekend_health = "🟡 Moderate"
                else:
                    weekend_health = "🔴 High Stress"
                
                st.metric(
                    "Weekend Work",
                    f"{weekend_health}",
                    f"{weekend_work:.1f}%",
                    help="Percentage of commits made on weekends"
                )
            
            with pattern_col2:
                if late_night_work <= 5:
                    night_health = "🟢 Healthy"
                elif late_night_work <= 15:
                    night_health = "🟡 Moderate"
                else:
                    night_health = "🔴 High Stress"
                
                st.metric(
                    "Late Night Work",
                    f"{night_health}",
                    f"{late_night_work:.1f}%",
                    help="Percentage of commits made late at night"
                )
            
            # Most productive times
            most_productive_day = productivity.get('most_productive_day')
            most_productive_hour = productivity.get('most_productive_hour')
            
            if most_productive_day is not None or most_productive_hour is not None:
                st.subheader("📊 Peak Productivity Times")
                
                peak_col1, peak_col2 = st.columns(2)
                
                with peak_col1:
                    if most_productive_day is not None:
                        day_names = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
                        day_name = day_names[most_productive_day] if 0 <= most_productive_day < 7 else 'Unknown'
                        st.info(f"**Most Active Day:** {day_name}")
                
                with peak_col2:
                    if most_productive_hour is not None:
                        if 6 <= most_productive_hour < 12:
                            time_period = "Morning"
                        elif 12 <= most_productive_hour < 18:
                            time_period = "Afternoon"
                        elif 18 <= most_productive_hour < 22:
                            time_period = "Evening"
                        else:
                            time_period = "Night/Early Morning"
                        
                        st.info(f"**Peak Hour:** {most_productive_hour}:00 ({time_period})")
        
        # Repository activity summary
        st.subheader("📈 Repository Activity Summary")
        
        summary_col1, summary_col2, summary_col3 = st.columns(3)
        
        with summary_col1:
            total_commits = metrics.get('total_commits', 0)
            commit_activity = "🔥 Very Active" if total_commits > 100 else "📈 Active" if total_commits > 50 else "📊 Moderate"
            st.metric("Commit Activity", commit_activity, f"{total_commits} commits")
        
        with summary_col2:
            pr_activity = "🚀 High" if total_prs > 20 else "📈 Medium" if total_prs > 5 else "📊 Low"
            st.metric("PR Activity", pr_activity, f"{total_prs} PRs")
        
        with summary_col3:
            # Calculate team health score
            health_factors = [
                min(review_participation / 50, 2) if 'review_participation' in locals() else 1,
                min(unique_reviewers / 3, 2),
                max(0, 2 - weekend_work / 25),
                max(0, 2 - late_night_work / 15)
            ]
            health_score = sum(health_factors) / len(health_factors) * 50
            
            if health_score >= 80:
                team_health = "🟢 Excellent"
            elif health_score >= 60:
                team_health = "🟡 Good"
            else:
                team_health = "🔴 Needs Attention"
            
            st.metric("Team Health", team_health, f"{health_score:.0f}/100")
    
    except Exception as e:
        logger.error(f"Error displaying repository contributors: {e}")
        st.error(f"Error loading contributor analysis: {str(e)}")
        
        if not collaboration:
            st.warning("No collaboration metrics available for this repository.")
            return
        
        st.subheader("👥 Collaboration Overview")
        
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric(
                "Unique Reviewers",
                collaboration.get("unique_reviewers", 0),
                help="Number of different people who reviewed code"
            )
        
        with col2:
            st.metric(
                "Unique Authors",
                collaboration.get("unique_authors", 0),
                help="Number of different commit authors"
            )
        
        with col3:
            st.metric(
                "Total Reviews",
                collaboration.get("total_reviews", 0),
                help="Total number of reviews submitted"
            )
        
        with col4:
            avg_response = collaboration.get("avg_review_response_time_hours", 0)
            st.metric(
                "Avg Response Time",
                f"{avg_response:.1f}h",
                help="Average time to respond to review requests"
            )
        
        # Top reviewers
        top_reviewers = collaboration.get("top_reviewers", {})
        if top_reviewers:
            st.subheader("🏆 Top Code Reviewers")
            
            try:
                # Convert to DataFrame with validation
                reviewer_data = []
                for reviewer, review_count in top_reviewers.items():
                    if isinstance(reviewer, str) and isinstance(review_count, (int, float)):
                        reviewer_data.append([reviewer, review_count])
                
                if reviewer_data:
                    reviewers_df = pd.DataFrame(reviewer_data, columns=['Reviewer', 'Reviews'])
                    reviewers_df = reviewers_df.sort_values('Reviews', ascending=False)
                    
                    if not reviewers_df.empty:
                        fig = create_bar_chart(
                            reviewers_df, 'Reviewer', 'Reviews',
                            'Top Code Reviewers',
                            'teal'
                        )
                        st.plotly_chart(fig, use_container_width=True)
                else:
                    st.info("No valid reviewer data available")
            except Exception as e:
                logger.warning(f"Error creating reviewers chart: {e}")
                st.warning("Unable to display top reviewers chart")
        
        # Collaboration metrics
        st.subheader("🔗 Collaboration Metrics")
        
        col1, col2 = st.columns(2)
        
        with col1:
            reviews_per_pr = collaboration.get("reviews_per_pr", 0)
            st.metric(
                "Reviews per PR",
                f"{reviews_per_pr:.1f}",
                help="Average number of reviews per pull request"
            )
        
        with col2:
            collab_index = collaboration.get("collaboration_index", 0)
            st.metric(
                "Collaboration Index",
                f"{collab_index}",
                help="Measure of team collaboration (reviewers × authors)"
            )
    
    except Exception as e:
        logger.error(f"Error displaying repository contributors: {e}")
        st.error(f"Error loading contributor analysis: {str(e)}")

if __name__ == "__main__":
    main()
