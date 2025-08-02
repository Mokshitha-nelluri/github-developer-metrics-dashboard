import time
import asyncio
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from backend.data_store import DataStore
from backend.aws_data_store import AWSDataStore
from backend.github_api import GitHubAPI
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from enhanced_github_api import EnhancedGitHubAPI
from backend.metrics_calculator import EnhancedMetricsCalculator
from backend.ml_analyzer import EnhancedMLAnalyzer
from backend.summary_bot import AISummaryBot
import logging
import threading
from queue import Queue, Empty
import json

logger = logging.getLogger(__name__)

class MetricsRefreshManager:
    """Manages real-time metrics refresh with intelligent caching and rate limiting"""
    
    # Class-level constants for easy tuning
    RATE_LIMIT_WINDOW = 3600  # 1 hour in seconds
    MAX_REQUESTS_PER_HOUR = 4000  # GitHub API limit buffer
    CACHE_MAX_AGE_MINUTES = 15
    BACKGROUND_WORKER_SLEEP = 5
    PRIORITY_QUEUE_TIMEOUT = 30
    
    def __init__(self, github_token: str):
        self.github_api = EnhancedGitHubAPI(github_token)  # Use enhanced API for better repo discovery
        
        # Use AWS DataStore if AWS_DEPLOYMENT is enabled
        if os.getenv('AWS_DEPLOYMENT') == 'true':
            self.data_store = AWSDataStore()
            logger.info("Using AWS DataStore for refresh manager")
        else:
            self.data_store = DataStore()
            logger.info("Using Supabase DataStore for refresh manager")
            
        self.metrics_calculator = EnhancedMetricsCalculator()
        self.ml_analyzer = EnhancedMLAnalyzer()
        self.summary_bot = AISummaryBot()
        
        # Cache management
        self.cache = {}
        self.cache_timestamps = {}
        self.refresh_locks = {}
        
        # Rate limiting
        self.request_queue = Queue()
        self.request_timestamps = []
        
        # Background processing
        self.background_worker_running = False
        self.priority_queue = Queue()
        self.worker_thread = None  # Track the worker thread
        
    def should_refresh(self, cache_key: str, max_age_minutes: int = None) -> bool:
        """Check if data should be refreshed based on age and cache policy"""
        if max_age_minutes is None:
            max_age_minutes = self.CACHE_MAX_AGE_MINUTES
            
        if cache_key not in self.cache_timestamps:
            return True
            
        age = datetime.now() - self.cache_timestamps[cache_key]
        return age > timedelta(minutes=max_age_minutes)
        
    def get_cached_metrics(self, cache_key: str) -> Optional[Dict]:
        """Get cached metrics if available and fresh"""
        if cache_key in self.cache and not self.should_refresh(cache_key):
            logger.info(f"Serving cached metrics for {cache_key}")
            return self.cache[cache_key]
        return None
        
    def cache_metrics(self, cache_key: str, metrics: Dict):
        """Cache metrics with timestamp"""
        self.cache[cache_key] = metrics
        self.cache_timestamps[cache_key] = datetime.now()
        logger.info(f"Cached metrics for {cache_key}")
        
    def check_rate_limit(self) -> bool:
        """Check if we're within GitHub API rate limits"""
        now = time.time()
        
        # Remove old timestamps outside the window
        self.request_timestamps = [
            ts for ts in self.request_timestamps 
            if now - ts < self.RATE_LIMIT_WINDOW
        ]
        
        can_make_request = len(self.request_timestamps) < self.MAX_REQUESTS_PER_HOUR
        if can_make_request:
            self.request_timestamps.append(now)
            
        return can_make_request
        
    def refresh_user_metrics(self, email: str, scope: str, force: bool = False) -> Dict[str, Any]:
        """Refresh metrics for a user with comprehensive error handling"""
        cache_key = f"user_metrics_{email}_{scope}"
        
        # Check cache first unless forced
        if not force:
            cached = self.get_cached_metrics(cache_key)
            if cached:
                return {
                    "success": True,
                    "metrics": cached,
                    "source": "cache"
                }
                
        # Check if refresh is already in progress
        if cache_key in self.refresh_locks:
            logger.info(f"Refresh already in progress for {cache_key}")
            return {
                "success": False,
                "error": "refresh_in_progress"
            }
            
        # Acquire lock
        self.refresh_locks[cache_key] = datetime.now()
        
        try:
            # Rate limit check
            if not self.check_rate_limit():
                logger.warning("Rate limit exceeded, queuing for later")
                self.priority_queue.put({
                    "type": "user_metrics",
                    "email": email,
                    "scope": scope,
                    "timestamp": datetime.now()
                })
                return {
                    "success": False,
                    "error": "rate_limited",
                    "queued": True
                }
                
            # Get user ID
            user_id = self.data_store.ensure_user_exists_and_get_id(email)
            if not user_id:
                return {
                    "success": False,
                    "error": "user_not_found"
                }
                
            logger.info(f"Refreshing {scope} metrics for {email}")
            
            if scope == "global":
                result = self._refresh_global_metrics(email, user_id)
            elif scope == "tracked":
                result = self._refresh_tracked_metrics(email, user_id)
            else:
                return {
                    "success": False,
                    "error": "invalid_scope"
                }
                
            if result["success"]:
                # Cache the results
                self.cache_metrics(cache_key, result["metrics"])
                
                # Save to database
                save_success = self.data_store.save_user_metrics(email, result["metrics"])
                if not save_success:
                    logger.error(f"Failed to save metrics to database for {email}")
                    
            return result
            
        except Exception as e:
            logger.error(f"Error refreshing metrics for {email}: {str(e)}")
            return {
                "success": False,
                "error": str(e)
            }
        finally:
            # Release lock
            if cache_key in self.refresh_locks:
                del self.refresh_locks[cache_key]
                
    def _refresh_global_metrics(self, email: str, user_id: str) -> Dict[str, Any]:
        """Refresh global user metrics across all repositories"""
        try:
            activity_data = self.github_api.fetch_global_user_activity(email, months_back=6)
            
            if not activity_data or "error" in activity_data:
                return {
                    "success": False,
                    "error": "failed_to_fetch_activity"
                }
                
            commits = activity_data.get("commits", [])
            prs = activity_data.get("pull_requests", [])
            repositories = activity_data.get("repositories", [])
            
            if not commits and not prs:
                return {
                    "success": False,
                    "error": "no_activity_found"
                }
                
            metrics = self.metrics_calculator.calculate_all_metrics(commits, prs, "global")
            
            metrics.update({
                "scope": "global",
                "email": email,
                "user_id": user_id,
                "active_repositories": len(repositories),
                "github_username": activity_data.get("user_info", {}).get("login", ""),
                "total_commits": len(commits),
                "total_prs": len(prs),
                "refresh_timestamp": datetime.now().isoformat(),
                "data_period": "last_6_months"
            })
            
            # Initialize lead_time_forecast to avoid reference errors
            lead_time_forecast = None
            
            historical_data = self.data_store.get_user_metrics(user_id, limit=10)
            if historical_data and len(historical_data) > 2:
                try:
                    # Enhanced ML analysis with continuous learning
                    ml_results = {}
                    key_metrics = [
                        "dora.lead_time.total_lead_time_hours",
                        "dora.deployment_frequency.per_week", 
                        "dora.change_failure_rate.percentage",
                        "code_quality.review_coverage_percentage"
                    ]
                    
                    if len(historical_data) >= self.ml_analyzer.MIN_FORECAST_POINTS:
                        logger.info(f"Training/updating ML models with {len(historical_data)} data points")
                        
                        # Train/update models for key metrics with continuous learning
                        for metric_path in key_metrics:
                            try:
                                # Train or incrementally update the model
                                success = self.ml_analyzer.train_forecasting_model(
                                    historical_data, metric_path
                                )
                                
                                if success:
                                    # Generate predictions
                                    forecast = self.ml_analyzer.predict_metric(metric_path, periods=14)
                                    if forecast:
                                        ml_results[metric_path] = {
                                            "forecast": forecast,
                                            "learning_status": self.ml_analyzer.get_model_learning_status(metric_path)
                                        }
                                        
                                    logger.info(f"Successfully processed ML for {metric_path}")
                                else:
                                    logger.warning(f"Failed to train/update model for {metric_path}")
                                    
                            except Exception as e:
                                logger.warning(f"ML processing failed for {metric_path}: {e}")
                                continue
                        
                        # Store ML results
                        metrics["ml_predictions"] = ml_results
                        
                        # Backwards compatibility - keep lead_time_trend
                        lead_time_forecast = ml_results.get("dora.lead_time.total_lead_time_hours", {}).get("forecast")
                        metrics["predictions"] = {
                            "lead_time_trend": lead_time_forecast
                        }
                        
                    else:
                        logger.info("Not enough historical data for ML forecasting (need at least %d, got %d)", 
                                  self.ml_analyzer.MIN_FORECAST_POINTS, len(historical_data))
                        lead_time_forecast = None
                        metrics["predictions"] = {"lead_time_trend": None}
                        metrics["ml_predictions"] = {}
                    
                    # Anomaly detection
                    anomalies = self.ml_analyzer.detect_anomalies(
                        historical_data, "dora.deployment_frequency.per_week")
                    metrics["anomalies"] = anomalies
                    
                    # Add continuous learning summary
                    learning_summary = self._generate_learning_summary(ml_results)
                    metrics["continuous_learning_status"] = learning_summary
                    
                except Exception as e:
                    logger.warning(f"ML analysis failed: {e}")
                    metrics["ml_analysis"] = {"error": str(e)}
                    lead_time_forecast = None
                    metrics["predictions"] = {"lead_time_trend": None}
                    metrics["ml_predictions"] = {}
                    metrics["continuous_learning_status"] = {"status": "error", "error": str(e)}
                    
            # 4. Generate AI summary (pass current_metrics, historical_data, and context)
            summary = self.summary_bot.generate_comprehensive_summary(
                current_metrics=metrics,
                historical_data=historical_data,
                context={
                    "lead_time_forecast": lead_time_forecast,
                }
            )
            
            metrics["ai_summary"] = summary
            
            return {
                "success": True,
                "metrics": metrics
            }
            
        except Exception as e:
            logger.error(f"Global metrics refresh failed: {str(e)}")
            return {
                "success": False,
                "error": str(e)
            }
            
    def _refresh_tracked_metrics(self, email: str, user_id: str) -> Dict[str, Any]:
        """Refresh metrics for tracked repositories only"""
        try:
            user_repos = self.data_store.get_user_repos(user_id)
            if not user_repos:
                return {
                    "success": False,
                    "error": "no_tracked_repositories"
                }
                
            all_commits = []
            all_prs = []
            repo_metrics = {}
            failed_repos = []
            
            for repo_data in user_repos:
                # Handle both nested and flat repo data structures
                if 'repos' in repo_data and isinstance(repo_data['repos'], dict):
                    repo_name = repo_data['repos'].get('full_name', '')
                elif 'full_name' in repo_data:
                    repo_name = repo_data['full_name']
                else:
                    logger.warning(f"Could not extract repo name from: {repo_data}")
                    continue
                    
                if not repo_name:
                    continue
                    
                owner, name = repo_name.split('/', 1)
                
                try:
                    logger.info(f"Fetching data from {repo_name}")
                    repo_commits = self.github_api.fetch_commits(owner, name, developer_email=email)
                    repo_prs = self.github_api.fetch_pull_requests(owner, name, developer_email=email)
                    
                    repo_metrics[repo_name] = self.metrics_calculator.calculate_all_metrics(
                        repo_commits, repo_prs, "repository")
                    repo_metrics[repo_name].update({
                        "repository": repo_name,
                        "commits_count": len(repo_commits),
                        "prs_count": len(repo_prs)
                    })
                    
                    all_commits.extend(repo_commits)
                    all_prs.extend(repo_prs)
                    
                except Exception as e:
                    logger.error(f"Failed to fetch data from {repo_name}: {e}")
                    failed_repos.append({
                        "repo": repo_name,
                        "error": str(e)
                    })
                    continue
                    
            if not all_commits and not all_prs:
                return {
                    "success": False,
                    "error": "no_activity_in_tracked_repos"
                }
                
            combined_metrics = self.metrics_calculator.calculate_all_metrics(
                all_commits, all_prs, "tracked")
                
            combined_metrics.update({
                "scope": "tracked",
                "email": email,
                "user_id": user_id,
                "tracked_repositories": len(user_repos),
                "successful_repos": len(user_repos) - len(failed_repos),
                "failed_repos": failed_repos,
                "total_commits": len(all_commits),
                "total_prs": len(all_prs),
                "refresh_timestamp": datetime.now().isoformat(),
                "repository_breakdown": repo_metrics
            })
            
            return {
                "success": True,
                "metrics": combined_metrics
            }
            
        except Exception as e:
            logger.error(f"Tracked metrics refresh failed: {str(e)}")
            return {
                "success": False,
                "error": str(e)
            }
            
    def refresh_repository_metrics(self, repo_owner: str, repo_name: str, force: bool = False, user_session: Dict = None) -> Dict[str, Any]:
        """Refresh metrics for a specific repository"""
        cache_key = f"repo_metrics_{repo_owner}_{repo_name}"
        
        if not force:
            cached = self.get_cached_metrics(cache_key)
            if cached:
                return {
                    "success": True,
                    "metrics": cached,
                    "source": "cache"
                }
                
        try:
            if not self.check_rate_limit():
                return {
                    "success": False,
                    "error": "rate_limited"
                }
                
            repo_insights = self.github_api.fetch_repository_insights(repo_owner, repo_name)
            commits = self.github_api.fetch_commits(repo_owner, repo_name, developer_email=None)
            prs = self.github_api.fetch_pull_requests(repo_owner, repo_name, developer_email=None)
            
            metrics = self.metrics_calculator.calculate_all_metrics(commits, prs, "repository")
            
            metrics.update({
                "repository": f"{repo_owner}/{repo_name}",
                "repository_insights": repo_insights,
                "total_commits": len(commits),
                "total_prs": len(prs),
                "refresh_timestamp": datetime.now().isoformat()
            })
            
            self.cache_metrics(cache_key, metrics)
            
            # Save to database if user session is provided
            if user_session:
                self.data_store.save_repo_metrics(repo_owner, repo_name, metrics, user_session)
            else:
                logger.warning("Cannot save repository metrics: no authenticated user")
            
            return {
                "success": True,
                "metrics": metrics
            }
            
        except Exception as e:
            logger.error(f"Repository metrics refresh failed: {str(e)}")
            return {
                "success": False,
                "error": str(e)
            }
            
    def start_background_worker(self):
        """Start background worker for processing queued refresh requests"""
        if self.background_worker_running:
            return
            
        self.background_worker_running = True
        
        def worker():
            logger.info("Background refresh worker started")
            
            while self.background_worker_running:
                try:
                    try:
                        task = self.priority_queue.get(timeout=self.PRIORITY_QUEUE_TIMEOUT)
                        logger.info(f"Processing queued task: {task['type']}")
                        
                        if task["type"] == "user_metrics":
                            self.refresh_user_metrics(
                                task["email"], 
                                task["scope"], 
                                force=True
                            )
                            
                        self.priority_queue.task_done()
                        
                    except Empty:
                        continue
                        
                except Exception as e:
                    logger.error(f"Background worker error: {e}")
                    
                time.sleep(self.BACKGROUND_WORKER_SLEEP)
                
        self.worker_thread = threading.Thread(target=worker, daemon=True)
        self.worker_thread.start()
        logger.info("Background worker thread started")
        
    def stop_background_worker(self):
        """Stop the background worker and wait for thread to finish"""
        self.background_worker_running = False
        
        if self.worker_thread and self.worker_thread.is_alive():
            self.worker_thread.join(timeout=2)
            
        logger.info("Background worker stopped")
        
    def get_refresh_status(self, cache_key: str) -> Dict[str, Any]:
        """Get status of refresh operations"""
        return {
            "is_refreshing": cache_key in self.refresh_locks,
            "last_refresh": self.cache_timestamps.get(cache_key),
            "cache_exists": cache_key in self.cache,
            "queue_size": self.priority_queue.qsize(),
            "rate_limit_remaining": self.MAX_REQUESTS_PER_HOUR - len(self.request_timestamps)
        }
        
    def clear_cache(self, pattern: str = None):
        """Clear cache entries matching pattern or all if no pattern"""
        if pattern:
            keys_to_remove = [k for k in self.cache.keys() if pattern in k]
        else:
            keys_to_remove = list(self.cache.keys())
            
        for key in keys_to_remove:
            self.cache.pop(key, None)
            self.cache_timestamps.pop(key, None)
            
        logger.info(f"Cleared {len(keys_to_remove)} cache entries")
        
    def _generate_learning_summary(self, ml_results: Dict[str, Any]) -> Dict[str, Any]:
        """Generate a summary of continuous learning status for all models."""
        try:
            if not ml_results:
                return {
                    "status": "no_models",
                    "message": "No ML models available for continuous learning"
                }
            
            active_models = len(ml_results)
            continuously_learning = 0
            recent_updates = 0
            total_incremental_updates = 0
            
            model_statuses = {}
            
            for metric_path, results in ml_results.items():
                learning_status = results.get("learning_status", {})
                
                if learning_status.get("supports_continuous_learning", False):
                    continuously_learning += 1
                
                incremental_updates = learning_status.get("total_incremental_updates", 0)
                total_incremental_updates += incremental_updates
                
                # Check if updated recently (within last 24 hours)
                last_update = learning_status.get("last_incremental_update", "none")
                if last_update != "none":
                    try:
                        update_time = datetime.fromisoformat(last_update)
                        hours_since_update = (datetime.now() - update_time).total_seconds() / 3600
                        if hours_since_update < 24:
                            recent_updates += 1
                    except:
                        pass
                
                model_statuses[metric_path] = {
                    "type": learning_status.get("model_type", "unknown"),
                    "continuous_learning": learning_status.get("supports_continuous_learning", False),
                    "data_points": learning_status.get("training_data_points", 0),
                    "incremental_updates": incremental_updates,
                    "freshness": learning_status.get("model_freshness", "unknown")
                }
            
            summary = {
                "status": "active",
                "total_models": active_models,
                "continuously_learning_models": continuously_learning,
                "models_updated_recently": recent_updates,
                "total_incremental_updates": total_incremental_updates,
                "learning_percentage": round((continuously_learning / active_models) * 100, 1) if active_models > 0 else 0,
                "model_details": model_statuses,
                "timestamp": datetime.now().isoformat()
            }
            
            # Add status message
            if continuously_learning == active_models:
                summary["message"] = f"🧠 All {active_models} models support continuous learning"
            elif continuously_learning > 0:
                summary["message"] = f"🧠 {continuously_learning}/{active_models} models support continuous learning"
            else:
                summary["message"] = "WARNING: No models currently support continuous learning"
            
            return summary
            
        except Exception as e:
            logger.error(f"Failed to generate learning summary: {e}")
            return {
                "status": "error",
                "error": str(e),
                "message": "Failed to generate continuous learning summary"
            }


def refresh_all_metrics(github_token: str, max_users: int = None):
    """Refresh metrics for all users (for scheduled jobs)"""
    refresh_manager = MetricsRefreshManager(github_token)
    db = DataStore()
    
    try:
        users = db.get_active_users(days_back=30, limit=max_users)
        if not users:
            logger.info("No active users found for refresh")
            return
            
        logger.info(f"Starting bulk refresh for {len(users)} users")
        refresh_manager.start_background_worker()
        
        success_count = 0
        error_count = 0
        
        for user in users:
            try:
                global_result = refresh_manager.refresh_user_metrics(
                    user["email"], "global", force=True
                )
                tracked_result = refresh_manager.refresh_user_metrics(
                    user["email"], "tracked", force=True
                )
                
                if global_result.get("success") or tracked_result.get("success"):
                    success_count += 1
                else:
                    error_count += 1
                    
                time.sleep(1)  # Prevent rate limiting
                
            except Exception as e:
                logger.error(f"Failed to refresh metrics for {user['email']}: {e}")
                error_count += 1
                
        logger.info(f"Bulk refresh completed: {success_count} success, {error_count} errors")
        
    except Exception as e:
        logger.error(f"Bulk refresh failed: {str(e)}")
    finally:
        refresh_manager.stop_background_worker()
