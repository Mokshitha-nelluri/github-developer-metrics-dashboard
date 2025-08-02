import sys
import os
import time

# Ensure the project root is in sys.path for module resolution
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
from typing import Dict, List, Any, Optional

from backend.data_store import DataStore
from backend.github_api import GitHubAPI
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
    create_work_life_balance_chart
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
    """Get GitHub API client - uses user's token if available, falls back to system token"""
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
            logger.info("Using user's GitHub token for API calls")
            return GitHubAPI(user_github_token)
        else:
            logger.warning("No GitHub token found in user session, falling back to system token")
    
    # Fallback to system token
    return GitHubAPI(GITHUB_TOKEN)

@st.cache_resource
def get_metrics_calculator():
    return EnhancedMetricsCalculator()

@st.cache_resource
def get_ml_analyzer():
    return EnhancedMLAnalyzer()

@st.cache_resource
def get_summary_bot():
    return AISummaryBot(GEMINI_API_KEY)

def refresh_metrics(email, scope, force=False, user_session=None):
    """Refresh metrics for the current user/repo"""
    db = get_datastore()
    github = get_github_api(user_session)
    calculator = get_metrics_calculator()
    
    # Determine user ID
    user_id = db.ensure_user_exists_and_get_id(email)
    if not user_id:
        return False
    
    if scope == "global":
        # For global scope, fetch user's repositories and aggregate data
        try:
            # Get user's public repositories
            user_repos = github.fetch_user_repositories(limit=50, include_private=False)
            if not user_repos:
                return False
            
            all_commits = []
            all_prs = []
            
            # Aggregate data from user's repositories
            for repo in user_repos[:10]:  # Limit to first 10 repos to avoid rate limits
                try:
                    owner = repo.get('owner', {}).get('login', '')
                    name = repo.get('name', '')
                    if owner and name:
                        commits = github.fetch_commits(owner, name, developer_email=email, days_back=180)
                        prs = github.fetch_pull_requests(owner, name, developer_email=email, days_back=180)
                        all_commits.extend(commits)
                        all_prs.extend(prs)
                except Exception as e:
                    logger.warning(f"Failed to fetch data for {owner}/{name}: {e}")
                    continue
            
            # Calculate metrics from aggregated data
            metrics = calculator.calculate_all_metrics(all_commits, all_prs, "global")
            
            # Add additional context
            metrics["active_repositories"] = len(user_repos)
            metrics["analyzed_repositories"] = min(10, len(user_repos))
            
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
        try:
            db = get_datastore()
            session = db.handle_oauth_callback(code)
            
            logger.info(f"OAuth session: {session}")
            
            if session:
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
    
    # Check if we have session_token and user_email (github_token is optional)
    if query_params.get('session_token') and query_params.get('user_email'):
        logger.info("Found session data in URL parameters")
        
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
    
    # Check existing session state
    if 'auth' not in st.session_state:
        logger.info("No auth in session state, checking Supabase session")
        db = get_datastore()
        session = db.get_session()
        
        if session:
            logger.info("Found existing Supabase session")
            st.session_state.auth = session
            return True
        
        logger.info("No existing sessions found")
        return False
    
    logger.info("Found existing auth in session state")
    return st.session_state.auth is not None

def show_login():
    """Display login interface"""
    st.title("🔐 GitHub Metrics Dashboard")
    st.markdown("### Welcome! Please authenticate to continue.")
    
    col1, col2, col3 = st.columns([1, 2, 1])
    
    with col2:
        st.markdown("""
        **Features:**
        - Real-time GitHub metrics for YOUR repositories
        - DORA performance tracking
        - 🤖 AI-powered insights
        - 📁 Multi-repository analysis
        - 🔐 Secure per-user authentication
        """)
    
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
    
    st.info("👆 Click to authenticate with your GitHub account and view your personal metrics")
    
    st.markdown("""
    **How it works:**
    1. Click the login button above
    2. Authorize the app with your GitHub account
    3. View metrics from YOUR repositories
    4. Each user sees their own data securely
    """)
    
    # Debug info for development
    if st.checkbox("Show Debug Info", value=False):
        st.code(f"Supabase URL: {SUPABASE_URL}")
        st.code(f"Query params: {dict(st.query_params)}")
        
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

def get_user_id_by_email(email: str) -> str:
    """Get user ID from email address"""
    db = get_datastore()
    user = db.get_user_by_email(email)
    if user:
        return user['id']
    
    # Create user if doesn't exist
    user_id = db.ensure_user_exists_and_get_id(email)
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

def show_repo_management(user_email: str):
    """Enhanced repository management interface"""
    st.subheader("📁 Repository Management")
    
    db = get_datastore()
    user_id = get_user_id_by_email(user_email)
    
    # Display current repositories with metrics
    force_refresh = st.session_state.get('repos_updated', False)
    if force_refresh:
        st.session_state['repos_updated'] = False
    
    user_repos = db.get_user_repos(user_id)
    
    if user_repos:
        st.write("**Tracked Repositories:**")
        
        # Debug: Show structure of first repo
        if st.checkbox("Show Repository Data Structure (Debug)", value=False):
            st.write("**First Repository Data:**")
            st.json(user_repos[0] if user_repos else {})
        
        for repo in user_repos:
            repo_name = get_repo_full_name(repo)
            added_date = repo.get('created_at', '')[:10] if repo.get('created_at') else 'Unknown'
            
            col1, col2, col3 = st.columns([3, 2, 1])
            
            with col1:
                st.write(f"📦 **{repo_name}**")
                st.caption(f"Added: {added_date}")
            
            with col2:
                st.write("Status: Active")
            
            with col3:
                delete_key = f"delete_{repo.get('id', 'unknown')}"
                if st.button("🗑️", key=delete_key, help="Remove repository"):
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
                        # Show debug info
                        with st.expander("Debug Info"):
                            st.write(f"**User Repo ID:** {user_repo_id}")
                            st.write(f"**Repo ID:** {get_repo_id(repo)}")
                            st.write(f"**User ID:** {user_id}")
                            st.write("**Raw Repository Data:**")
                            st.json(repo)
    else:
        st.info("No repositories tracked yet. Add one below!")
    
    # Add new repository
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
        
        metrics = current_metrics[0]['metrics_data']
        historical_data = db.get_user_metrics(user_id, limit=20)
        
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
        overview_tab, performance_tab, activity_tab, insights_tab, predictions_tab = st.tabs([
            "📊 Overview", "🎯 Performance", "⏰ Activity", "💡 Insights", "🔮 Predictions"
        ])
        
        with overview_tab:
            display_metrics_overview(metrics, historical_data)
        
        with performance_tab:
            display_performance_analysis(metrics, historical_data)
        
        with activity_tab:
            display_activity_patterns(metrics)
        
        with insights_tab:
            display_ai_insights(metrics, historical_data, summary_bot)
        
        with predictions_tab:
            display_predictions(metrics, historical_data, ml)
        
    except Exception as e:
        st.error(f"Failed to load global metrics: {str(e)}")
        logger.error(f"display_global_metrics error: {e}")

def display_metrics_overview(metrics: Dict[str, Any], historical_data: List[Dict]):
    """Display metrics overview section"""
    st.subheader("🌍 Global Performance Overview")
    
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
        if active_repos == 0:
            active_repos = metrics.get('analyzed_repositories', 0)
        if active_repos == 0:
            active_repos = len(metrics.get('repositories', []))
        if active_repos == 0:
            active_repos = metrics.get('total_repositories', 0)
        st.metric("Active Repositories", f"{active_repos}", help="Repositories with recent activity")
    
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
    
    # Performance grade
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
            
            for category, score in category_scores.items():
                max_score = category_max.get(category, score)
                percentage = (score / max_score * 100) if max_score > 0 else 0
                st.write(f"**{category.replace('_', ' ').title()}**: {score}/{max_score} ({percentage:.0f}%)")
                st.progress(percentage / 100)
    
    # Performance timeline
    if historical_data and len(historical_data) > 1:
        st.subheader("Performance Timeline")
        timeline_fig = create_performance_timeline_chart(historical_data)
        st.plotly_chart(timeline_fig, use_container_width=True, key="performance_timeline")

def display_activity_patterns(metrics: Dict[str, Any]):
    """Display activity patterns and work habits"""
    st.subheader("⏰ Activity Patterns")
    
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

def display_predictions(metrics: Dict[str, Any], historical_data: List[Dict], ml_analyzer):
    """Display predictive analytics and forecasts"""
    st.subheader("🔮 Predictive Analytics")
    
    if not historical_data or len(historical_data) < 3:
        st.warning("Need more historical data for predictions. Check back after a few data points are collected.")
        return
    
    try:
        # Lead time forecast
        st.write("### Lead Time Forecast")
        lead_time_prediction = ml_analyzer.predict_trend(
            historical_data, "lead_time_hours", days_ahead=14
        )
        
        if lead_time_prediction and lead_time_prediction.get("prediction"):
            col1, col2 = st.columns([2, 1])
            
            with col1:
                forecast_data = {
                    'dates': [(datetime.now() + timedelta(days=i)).strftime('%Y-%m-%d') for i in range(1, 15)],
                    'values': [lead_time_prediction['prediction'] * (1 + (i-7)/100) for i in range(14)]
                }
                forecast_fig = create_forecast_chart(
                    historical_data, forecast_data, "lead_time_hours", "Lead Time Forecast"
                )
                st.plotly_chart(forecast_fig, use_container_width=True, key="predictions_forecast_chart")
            
            with col2:
                st.metric("Predicted Lead Time", f"{lead_time_prediction['prediction']:.1f} hrs")
                st.metric("Confidence", f"{lead_time_prediction['confidence']:.0f}%")
                st.write(f"**Trend**: {lead_time_prediction['trend'].replace('_', ' ').title()}")
        
    except Exception as e:
        st.error(f"Prediction analysis failed: {str(e)}")
        logger.error(f"Prediction error: {e}")

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
    user_id = get_user_id_by_email(user_email)
    
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
                db.sign_out()
                for key in list(st.session_state.keys()):
                    del st.session_state[key]
                st.success("Signing out...")
                st.info("Redirecting to sign out page...")
                
                auth_url = f"http://localhost:8502/public/auth_enhanced.html?signed_out=true&timestamp={int(time.time() * 1000)}"
                st.markdown(f"""
                <script>
                window.open('{auth_url}', '_self');
                </script>
                """, unsafe_allow_html=True)
                st.stop()
        
        with col2:
            if st.button("🔄 Switch Account", use_container_width=True, type="primary"):
                db.sign_out()
                for key in list(st.session_state.keys()):
                    del st.session_state[key]
                st.success("Switching accounts...")
                st.info("Redirecting to account selection...")
                
                auth_url = f"http://localhost:8502/public/auth_enhanced.html?signed_out=true&switch_account=true&timestamp={int(time.time() * 1000)}"
                st.markdown(f"""
                <script>
                window.open('{auth_url}', '_self');
                </script>
                """, unsafe_allow_html=True)
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
        show_repo_management(user_email)

def display_repo_metrics(repo_data: Dict, user_email: str):
    """Display repository-specific metrics"""
    repo_name = get_repo_full_name(repo_data)
    if not repo_name or repo_name == "Unknown Repository":
        st.error("⚠️ Repository information is incomplete or invalid")
        st.json(repo_data)
        return
    
    st.subheader(f"📦 {repo_name}")
    st.info("Repository-specific metrics will be displayed here. This requires additional API calls to fetch repo-specific data.")

if __name__ == "__main__":
    main()
