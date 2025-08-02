#!/usr/bin/env python3
"""
Background Metrics Refresh Service
Handles asynchronous metrics collection and caching for improved performance
"""
import os
import asyncio
import schedule
import time
import threading
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import logging
from concurrent.futures import ThreadPoolExecutor
import json

try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class BackgroundMetricsService:
    """
    Background service for pre-computing and caching user metrics
    Runs independently of the Streamlit app for better performance
    """
    
    def __init__(self):
        # Initialize Redis for caching (can fallback to database)
        if REDIS_AVAILABLE:
            try:
                self.redis_client = redis.Redis(
                    host=os.environ.get('REDIS_HOST', 'localhost'),
                    port=int(os.environ.get('REDIS_PORT', 6379)),
                    db=0,
                    decode_responses=True
                )
                self.redis_client.ping()  # Test connection
                self.use_redis = True
                logger.info("✅ Redis cache initialized")
            except Exception as e:
                logger.warning(f"⚠️ Redis not available, using database cache: {e}")
                self.use_redis = False
        else:
            logger.warning("⚠️ Redis not installed, using database cache")
            self.use_redis = False
        
        self.db = None  # Will be initialized when needed
        self.github_api = None
        self.metrics_calculator = None
        self.ml_analyzer = None
        
        # Performance settings
        self.max_concurrent_users = 10
        self.cache_ttl = 3600  # 1 hour cache
        self.background_refresh_interval = 15  # 15 minutes
        
    def initialize_components(self):
        """Initialize database and API components"""
        try:
            from backend.aws_data_store import DataStore
            from backend.github_api import GitHubAPI
            from backend.metrics_calculator import EnhancedMetricsCalculator
            from backend.ml_analyzer import EnhancedMLAnalyzer
            from config import GITHUB_TOKEN
            
            self.db = DataStore()
            self.github_api = GitHubAPI(GITHUB_TOKEN)
            self.metrics_calculator = EnhancedMetricsCalculator()
            self.ml_analyzer = EnhancedMLAnalyzer()
            self.github_token = GITHUB_TOKEN
            
            logger.info("✅ Background service components initialized")
            return True
        except Exception as e:
            logger.error(f"❌ Failed to initialize components: {e}")
            return False
    
    async def refresh_user_metrics_async(self, user_email: str, user_github_token: str = None) -> Dict:
        """
        Asynchronously refresh metrics for a single user
        This runs in background without blocking the UI
        """
        start_time = time.time()
        logger.info(f"🔄 Starting background refresh for user: {user_email}")
        
        try:
            # Use user's token if available, fallback to system token
            from backend.github_api import GitHubAPI
            github_api = GitHubAPI(user_github_token or self.github_token)
            
            # Get user info and repositories
            user_info = github_api.get_authenticated_user()
            if not user_info:
                raise Exception("Failed to get user info")
            
            github_username = user_info.get('login')
            user_id = self.db.ensure_user_exists_and_get_id(user_email, user_github_token, github_username)
            
            # Fetch repositories in batches to avoid timeout
            logger.info(f"📦 Fetching repositories for {github_username}")
            repositories = github_api.fetch_user_repositories(limit=50, include_private=True)
            
            if not repositories:
                logger.warning(f"No repositories found for {github_username}")
                return {"error": "No repositories found"}
            
            # Process repositories in parallel batches
            all_commits = []
            all_prs = []
            
            # Process top 10 most active repositories to avoid long delays
            active_repos = sorted(repositories[:10], 
                                key=lambda r: r.get('pushed_at', '2020-01-01'), 
                                reverse=True)
            
            logger.info(f"📊 Processing {len(active_repos)} most active repositories")
            
            # Use ThreadPoolExecutor for concurrent GitHub API calls
            with ThreadPoolExecutor(max_workers=5) as executor:
                futures = []
                
                for repo in active_repos:
                    owner = repo.get('owner', {}).get('login', '')
                    name = repo.get('name', '')
                    
                    if owner and name:
                        # Submit async tasks for commits and PRs
                        future_commits = executor.submit(
                            github_api.fetch_commits, owner, name, developer_email=user_email
                        )
                        future_prs = executor.submit(
                            github_api.fetch_pull_requests, owner, name, developer_email=user_email
                        )
                        
                        futures.append((future_commits, future_prs, f"{owner}/{name}"))
                
                # Collect results with timeout
                for future_commits, future_prs, repo_name in futures:
                    try:
                        commits = future_commits.result(timeout=30)  # 30 second timeout per repo
                        prs = future_prs.result(timeout=30)
                        
                        all_commits.extend(commits)
                        all_prs.extend(prs)
                        
                        logger.info(f"✅ Processed {repo_name}: {len(commits)} commits, {len(prs)} PRs")
                        
                    except Exception as e:
                        logger.warning(f"⚠️ Failed to process {repo_name}: {e}")
                        continue
            
            # Calculate comprehensive metrics
            logger.info(f"🧮 Calculating metrics from {len(all_commits)} commits and {len(all_prs)} PRs")
            metrics = self.metrics_calculator.calculate_all_metrics(all_commits, all_prs, "global")
            
            # Add repository context
            metrics.update({
                "total_repositories": len(repositories),
                "analyzed_repositories": len(active_repos),
                "total_commits_analyzed": len(all_commits),
                "total_prs_analyzed": len(all_prs),
                "last_updated": datetime.now().isoformat(),
                "refresh_duration_seconds": round(time.time() - start_time, 2)
            })
            
            # Save to database
            success = self.db.save_user_metrics(user_email, metrics)
            if not success:
                raise Exception("Failed to save metrics to database")
            
            # Cache the results
            await self.cache_user_metrics(user_email, metrics)
            
            elapsed_time = time.time() - start_time
            logger.info(f"✅ Background refresh completed for {user_email} in {elapsed_time:.2f} seconds")
            
            return metrics
            
        except Exception as e:
            logger.error(f"❌ Background refresh failed for {user_email}: {e}")
            return {"error": str(e), "user_email": user_email}
    
    async def cache_user_metrics(self, user_email: str, metrics: Dict):
        """Cache metrics for fast retrieval"""
        try:
            cache_key = f"user_metrics:{user_email}"
            
            if self.use_redis:
                # Cache in Redis with TTL
                self.redis_client.setex(
                    cache_key, 
                    self.cache_ttl, 
                    json.dumps(metrics, default=str)
                )
                logger.info(f"💾 Cached metrics for {user_email} in Redis")
            else:
                # Cache in database table
                self.db.cache_user_metrics(user_email, metrics, self.cache_ttl)
                logger.info(f"💾 Cached metrics for {user_email} in database")
                
        except Exception as e:
            logger.error(f"❌ Failed to cache metrics for {user_email}: {e}")
    
    async def get_cached_metrics(self, user_email: str) -> Optional[Dict]:
        """Retrieve cached metrics if available"""
        try:
            # Check if service is properly initialized
            if self.db is None:
                logger.warning(f"⚠️ Background service not initialized, cannot get cached metrics for {user_email}")
                return None
                
            cache_key = f"user_metrics:{user_email}"
            
            if self.use_redis:
                cached_data = self.redis_client.get(cache_key)
                if cached_data:
                    metrics = json.loads(cached_data)
                    logger.info(f"🎯 Retrieved cached metrics for {user_email} from Redis")
                    return metrics
            else:
                # Get from database cache
                cached_metrics = self.db.get_cached_user_metrics(user_email)
                if cached_metrics:
                    logger.info(f"🎯 Retrieved cached metrics for {user_email} from database")
                    return cached_metrics
            
            logger.info(f"🔍 No cached metrics found for {user_email}")
            return None
            
        except Exception as e:
            logger.error(f"❌ Failed to retrieve cached metrics for {user_email}: {e}")
            return None
    
    def schedule_background_refreshes(self):
        """Schedule periodic background refreshes for active users"""
        def refresh_active_users():
            """Refresh metrics for users who have logged in recently"""
            try:
                # Get users who logged in within last 24 hours
                active_users = self.db.get_recently_active_users(hours=24)
                
                logger.info(f"🔄 Starting background refresh for {len(active_users)} active users")
                
                # Process users in batches to avoid overwhelming the system
                async def refresh_batch(users_batch):
                    tasks = []
                    for user in users_batch:
                        user_email = user.get('email')
                        user_token = user.get('github_token')
                        if user_email:
                            task = self.refresh_user_metrics_async(user_email, user_token)
                            tasks.append(task)
                    
                    if tasks:
                        results = await asyncio.gather(*tasks, return_exceptions=True)
                        successful = sum(1 for r in results if not isinstance(r, Exception))
                        logger.info(f"✅ Background refresh batch completed: {successful}/{len(tasks)} successful")
                
                # Process in batches of 5 users
                batch_size = 5
                for i in range(0, len(active_users), batch_size):
                    batch = active_users[i:i + batch_size]
                    asyncio.run(refresh_batch(batch))
                    time.sleep(10)  # Brief pause between batches
                
            except Exception as e:
                logger.error(f"❌ Background refresh failed: {e}")
        
        # Schedule refreshes every 15 minutes
        schedule.every(self.background_refresh_interval).minutes.do(refresh_active_users)
        
        logger.info(f"⏰ Scheduled background refreshes every {self.background_refresh_interval} minutes")
    
    def start_scheduler(self):
        """Start the background scheduler"""
        def run_scheduler():
            logger.info("🚀 Starting background metrics scheduler")
            while True:
                schedule.run_pending()
                time.sleep(60)  # Check every minute
        
        scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
        scheduler_thread.start()
        logger.info("✅ Background scheduler started")
    
    def start_service(self):
        """Start the complete background service"""
        logger.info("🚀 Starting Background Metrics Service")
        
        if not self.initialize_components():
            logger.error("❌ Failed to initialize service components")
            return False
        
        self.schedule_background_refreshes()
        self.start_scheduler()
        
        logger.info("✅ Background Metrics Service is running")
        return True

# Singleton instance
background_service = BackgroundMetricsService()

# API for Streamlit app to use
async def get_user_metrics_fast(user_email: str, user_github_token: str = None) -> Dict:
    """
    Fast metrics retrieval for Streamlit app
    Returns cached data immediately, triggers background refresh if needed
    """
    # Check if background service is initialized
    if background_service.db is None:
        logger.warning(f"⚠️ Background service not initialized, falling back to standard metrics retrieval")
        # Return an error indicator so the caller can use standard approach
        return {"error": "background_service_not_initialized", "fallback_required": True}
    
    # Try to get cached metrics first
    cached_metrics = await background_service.get_cached_metrics(user_email)
    
    if cached_metrics:
        # Check if cache is fresh (less than 1 hour old)
        last_updated = cached_metrics.get('last_updated')
        if last_updated:
            try:
                update_time = datetime.fromisoformat(last_updated.replace('Z', '+00:00'))
                if datetime.now() - update_time < timedelta(hours=1):
                    logger.info(f"🎯 Returning fresh cached metrics for {user_email}")
                    return cached_metrics
            except Exception:
                pass
    
    # If no fresh cache, trigger background refresh but return what we have
    if cached_metrics:
        logger.info(f"⚡ Returning cached metrics, triggering background refresh for {user_email}")
        # Trigger async refresh (don't wait for it)
        asyncio.create_task(background_service.refresh_user_metrics_async(user_email, user_github_token))
        return cached_metrics
    
    # If no cache at all, do a quick initial fetch
    logger.info(f"🔄 No cache found, performing initial fetch for {user_email}")
    metrics = await background_service.refresh_user_metrics_async(user_email, user_github_token)
    return metrics

def start_background_service():
    """Start the background service (call this when app starts)"""
    return background_service.start_service()

if __name__ == "__main__":
    # Run as standalone service
    start_background_service()
    
    # Keep the service running
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        logger.info("👋 Background service shutting down")
