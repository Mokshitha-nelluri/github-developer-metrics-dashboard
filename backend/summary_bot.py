import json
import logging
import os
import time
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta
import hashlib

try:
    import google.generativeai as genai  # Gemini API
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False

logger = logging.getLogger(__name__)

class AISummaryBot:
    """AI-powered summary bot with Gemini integration and robust fallback."""
    
    # Class-level constants for thresholds (easy tuning)
    LEAD_TIME_ELITE = 24
    LEAD_TIME_EXCELLENT = 48
    LEAD_TIME_ALERT = 72
    DEPLOY_FREQ_EXCELLENT = 10
    DEPLOY_FREQ_LOW = 2
    FAILURE_RATE_ELITE = 5
    FAILURE_RATE_ALERT = 15
    WLB_ALERT = 50
    
    # Rate limiting for free tier - very conservative to prevent quota issues
    MAX_REQUESTS_PER_MINUTE = 10  # Very conservative limit  
    MAX_REQUESTS_PER_DAY = 40     # Much lower to ensure we never hit quota
    REQUEST_DELAY = 6.0           # Longer delay between requests
    
    def __init__(self, gemini_api_key: Optional[str] = None):
        self.gemini_api_key = gemini_api_key or os.getenv('GEMINI_API_KEY')
        
        # Allow disabling Gemini API via environment variable
        gemini_disabled = os.getenv('DISABLE_GEMINI_API', '').lower() in ('true', '1', 'yes')
        if gemini_disabled:
            logger.info("Gemini API disabled via DISABLE_GEMINI_API environment variable")
            self.gemini_api_key = None
        
        self.last_request_time = 0
        self.daily_request_count = 0
        self.daily_reset_time = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        self.cache = {}  # Simple in-memory cache
        
        if self.gemini_api_key and GEMINI_AVAILABLE:
            genai.configure(api_key=self.gemini_api_key)
    
    def _check_rate_limits(self) -> bool:
        """Check if we can make a request within rate limits"""
        now = time.time()
        current_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        
        # Reset daily count if new day
        if current_date > self.daily_reset_time:
            self.daily_request_count = 0
            self.daily_reset_time = current_date
            # Also reset any quota error flags
            if hasattr(self, '_quota_exceeded_until'):
                delattr(self, '_quota_exceeded_until')
        
        # Check if we're in quota exceeded cooldown
        if hasattr(self, '_quota_exceeded_until') and now < self._quota_exceeded_until:
            logger.warning(f"Gemini API quota exceeded, cooling down until {datetime.fromtimestamp(self._quota_exceeded_until)}")
            return False
        
        # Check daily limit with buffer (90% of max to be safe)
        if self.daily_request_count >= int(self.MAX_REQUESTS_PER_DAY * 0.9):
            logger.warning(f"Daily Gemini API limit nearly reached ({self.daily_request_count}/{self.MAX_REQUESTS_PER_DAY}), using fallback")
            return False
        
        # Check per-minute limit
        time_since_last = now - self.last_request_time
        if time_since_last < self.REQUEST_DELAY:
            sleep_time = self.REQUEST_DELAY - time_since_last
            logger.info(f"Rate limiting: waiting {sleep_time:.1f}s")
            time.sleep(sleep_time)
        
        return True
    
    def _get_cache_key(self, metrics: Dict, context: Dict = None) -> str:
        """Generate cache key for metrics"""
        # Create hash from key metrics to avoid duplicate API calls
        key_data = {
            'total_commits': metrics.get('total_commits', 0),
            'total_prs': metrics.get('total_prs', 0),
            'dora': metrics.get('dora', {}),
            'date': str(datetime.now().date())  # Cache per day
        }
        return hashlib.md5(json.dumps(key_data, sort_keys=True).encode()).hexdigest()
            
    def generate_comprehensive_summary(
        self,
        current_metrics: Dict[str, Any],
        historical_data: List[Dict] = None,
        context: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """Generate comprehensive AI-powered summary with Gemini and rule-based fallback."""
        
        # Check cache first
        cache_key = self._get_cache_key(current_metrics, context)
        if cache_key in self.cache:
            cached_result = self.cache[cache_key]
            logger.info("Using cached Gemini summary")
            return cached_result
        
        insights = {
            "summary": "",
            "recommendations": [],
            "alerts": [],
            "trend_insights": [],
            "performance_insights": []
        }
        
        # Try Gemini if available and within limits
        if self.gemini_api_key and GEMINI_AVAILABLE and self._check_rate_limits():
            try:
                gemini_insights = self._generate_gemini_summary(current_metrics, historical_data, context)
                if gemini_insights:
                    logger.info("Gemini summary generated successfully")
                    # Cache the result
                    self.cache[cache_key] = gemini_insights
                    return gemini_insights
            except Exception as e:
                logger.warning(f"Gemini summary failed: {e}")
                
        # Fallback to rule-based analysis
        logger.info("Using rule-based summary fallback")
        return self._generate_rule_based_summary(current_metrics, historical_data, context)
        
    def _generate_gemini_summary(
        self,
        current_metrics: Dict[str, Any],
        historical_data: List[Dict] = None,
        context: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """Generate summary using Gemini with optimized prompts."""
        try:
            # Use shorter, more efficient prompt
            prompt = self._build_optimized_prompt(current_metrics, historical_data, context)
            
            # Use faster Gemini Flash model instead of Pro for better rate limits
            model = genai.GenerativeModel("gemini-1.5-flash")
            
            # Configure for shorter responses to save tokens
            generation_config = genai.types.GenerationConfig(
                max_output_tokens=800,  # Limit response length
                temperature=0.3,        # Lower temperature for more focused responses
            )
            
            # Track request timing
            self.last_request_time = time.time()
            self.daily_request_count += 1
            
            response = model.generate_content(prompt, generation_config=generation_config)
            
            # Gemini's response is in response.text
            try:
                result = json.loads(response.text)
                logger.info(f"Gemini request #{self.daily_request_count} successful")
                return result
            except json.JSONDecodeError:
                logger.warning("Gemini response was not valid JSON, parsing manually")
                return self._parse_text_response(response.text)
                
        except Exception as e:
            error_msg = str(e)
            if "429" in error_msg or "quota" in error_msg.lower() or "exceeded" in error_msg.lower():
                logger.error(f"Gemini API quota exceeded: {error_msg}")
                # Set cooldown period - wait for 1 hour before trying again
                self._quota_exceeded_until = time.time() + 3600  # 1 hour cooldown
                # Also increment the daily count to prevent further attempts
                self.daily_request_count = self.MAX_REQUESTS_PER_DAY
                logger.info("Set 1-hour cooldown for Gemini API due to quota exceeded")
            else:
                logger.error(f"Gemini API error: {error_msg}")
            return None
            
    def _build_optimized_prompt(self, current_metrics, historical_data, context):
        """Build concise, optimized prompt for Gemini Flash model to minimize token usage."""
        
        # Extract key metrics only
        key_metrics = {
            'commits': current_metrics.get('total_commits', 0),
            'prs': current_metrics.get('total_prs', 0),
            'issues': current_metrics.get('total_issues', 0),
            'score': current_metrics.get('activity_score', 0)
        }
        
        # Extract DORA metrics if available
        dora = current_metrics.get('dora', {})
        if dora:
            key_metrics['lead_time'] = dora.get('lead_time_hours', 0)
            key_metrics['deploy_freq'] = dora.get('deployment_frequency', 0)
            key_metrics['failure_rate'] = dora.get('change_failure_rate', 0)
        
        # Simple historical trend if available
        trend_note = ""
        if historical_data and len(historical_data) > 1:
            try:
                prev_commits = historical_data[1].get('total_commits', 0)
                current_commits = current_metrics.get('total_commits', 0)
                if prev_commits > 0:
                    change = ((current_commits - prev_commits) / prev_commits) * 100
                    trend_note = f"Commits trend: {change:+.1f}%"
            except:
                pass
        
        # Ultra-compact prompt to save tokens
        prompt = f"""Analyze these developer metrics and respond in JSON format:

Metrics: {json.dumps(key_metrics)}
{trend_note}

Return JSON with exactly these keys (max 2 sentences each):
{{"summary": "brief overview", "recommendations": ["tip1", "tip2"], "alerts": ["urgent issue if any"], "performance_insights": ["key insight"]}}"""

        return prompt
    
    def _parse_text_response(self, text: str) -> Dict[str, Any]:
        """Parse non-JSON text response from Gemini"""
        try:
            # Try to extract JSON from text
            start = text.find('{')
            end = text.rfind('}') + 1
            if start >= 0 and end > start:
                json_text = text[start:end]
                return json.loads(json_text)
        except:
            pass
        
        # Fallback to simple parsing
        return {
            "summary": text[:200] + "..." if len(text) > 200 else text,
            "recommendations": ["Review the detailed analysis above"],
            "alerts": [],
            "performance_insights": ["Analysis completed with text parsing"]
        }
        
    def _generate_rule_based_summary(
        self,
        current_metrics: Dict[str, Any],
        historical_data: List[Dict] = None,
        context: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """Rule-based fallback analysis."""
        insights = {
            "summary": "",
            "recommendations": [],
            "alerts": [],
            "trend_insights": [],
            "performance_insights": []
        }
        
        # Extract metrics from nested structure
        dora_metrics = current_metrics.get('dora', {})
        lead_time_data = dora_metrics.get('lead_time', {})
        deploy_freq_data = dora_metrics.get('deployment_frequency', {})
        failure_rate_data = dora_metrics.get('change_failure_rate', {})
        
        lead_time = lead_time_data.get('total_lead_time_hours', 0)
        deploy_freq = deploy_freq_data.get('per_week', 0)
        failure_rate = failure_rate_data.get('percentage', 0)
        
        # Performance insights
        if lead_time < self.LEAD_TIME_ELITE:
            insights['performance_insights'].append("Elite lead time performance (< 24 hours)")
        elif lead_time < self.LEAD_TIME_EXCELLENT:
            insights['performance_insights'].append("Excellent lead time (< 48 hours)")
        elif lead_time > self.LEAD_TIME_ALERT:
            insights['alerts'].append("⏰ Lead time exceeds 72 hours - investigate bottlenecks")
            
        if deploy_freq > self.DEPLOY_FREQ_EXCELLENT:
            insights['performance_insights'].append("Exceptional deployment frequency (>10/week)")
        elif deploy_freq < self.DEPLOY_FREQ_LOW:
            insights['alerts'].append("📈 Low deployment frequency - consider smaller batches")
            
        if failure_rate < self.FAILURE_RATE_ELITE:
            insights['performance_insights'].append("Elite change success rate (<5% failures)")
        elif failure_rate > self.FAILURE_RATE_ALERT:
            insights['alerts'].append("🔧 High failure rate (>15%) - improve testing/review processes")
            
        # Code quality insights
        code_quality = current_metrics.get('code_quality', {})
        review_coverage = code_quality.get('review_coverage_percentage', 0)
        large_prs_pct = code_quality.get('large_prs_percentage', 0)
        
        if review_coverage < 70:
            insights['alerts'].append("📝 Low code review coverage (<70%)")
            insights['recommendations'].append("Increase code review coverage to improve quality")
            
        if large_prs_pct > 25:
            insights['alerts'].append("📦 High percentage of large PRs (>25%)")
            insights['recommendations'].append("Break down large PRs for easier reviews")
            
        # Work-life balance
        productivity = current_metrics.get('productivity_patterns', {})
        wlb_score = productivity.get('work_life_balance_score', 100)  # Default to good if not present
        weekend_work = productivity.get('weekend_work_percentage', 0)
        
        if wlb_score < self.WLB_ALERT:
            insights['alerts'].append("⚖️ Poor work-life balance detected")
            insights['recommendations'].append("Reduce weekend/late-night work to prevent burnout")
            
        if weekend_work > 20:
            insights['alerts'].append("🌅 Excessive weekend work (>20%)")
            
        # Performance grade insights
        perf_grade = current_metrics.get('performance_grade', {})
        grade = perf_grade.get('overall_grade', '')
        percentage = perf_grade.get('percentage', 0)
        
        if percentage >= 90:
            insights['performance_insights'].append(f"Outstanding overall performance ({grade} - {percentage}%)")
        elif percentage >= 80:
            insights['performance_insights'].append(f"Strong performance ({grade} - {percentage}%)")
        elif percentage < 70:
            insights['alerts'].append(f"Performance below expectations ({grade} - {percentage}%)")
            
        # Trend insights from historical data
        if historical_data and len(historical_data) > 2:
            try:
                self._analyze_historical_trends(historical_data, insights)
            except Exception as e:
                logger.debug(f"Failed to analyze trends: {e}")
                
        # Generate summary
        summary_parts = []
        
        if insights['performance_insights']:
            summary_parts.append(f"Performance highlights: {'. '.join(insights['performance_insights'][:2])}.")
            
        if insights['alerts']:
            alert_count = len(insights['alerts'])
            summary_parts.append(f" {alert_count} area{'s' if alert_count > 1 else ''} need attention.")
            
        if not summary_parts:
            summary_parts.append("Your metrics are within expected ranges.")
            
        insights['summary'] = " ".join(summary_parts)
        
        # Add default recommendations if none
        if not insights['recommendations']:
            if lead_time > self.LEAD_TIME_EXCELLENT:
                insights['recommendations'].append("Break down features into smaller PRs to reduce lead time")
            if deploy_freq < 3:
                insights['recommendations'].append("Implement CI/CD pipeline to increase deployment frequency")
            if failure_rate > 10:
                insights['recommendations'].append("Add automated testing for critical paths")
            if not insights['recommendations']:  # Still no recommendations
                insights['recommendations'].append("Continue maintaining current performance levels")
                
        return insights
        
    def _analyze_historical_trends(self, historical_data: List[Dict], insights: Dict):
        """Analyze historical trends and add insights."""
        try:
            # Extract lead times
            lead_times = []
            deploy_freqs = []
            failure_rates = []
            
            for entry in historical_data:
                metrics = entry.get('metrics_data', {}) or entry.get('metrics', {})
                dora = metrics.get('dora', {})
                
                lt = dora.get('lead_time', {}).get('total_lead_time_hours', 0)
                df = dora.get('deployment_frequency', {}).get('per_week', 0)
                fr = dora.get('change_failure_rate', {}).get('percentage', 0)
                
                if lt > 0:
                    lead_times.append(lt)
                if df > 0:
                    deploy_freqs.append(df)
                if fr >= 0:
                    failure_rates.append(fr)
                    
            # Analyze trends
            if len(lead_times) >= 3:
                recent_lt = sum(lead_times[-2:]) / 2
                older_lt = sum(lead_times[:2]) / 2
                
                if recent_lt > older_lt * 1.2:
                    insights['trend_insights'].append("📈 Lead time is increasing - investigate bottlenecks")
                elif recent_lt < older_lt * 0.8:
                    insights['trend_insights'].append("📉 Lead time is improving - great progress!")
                    
            if len(deploy_freqs) >= 3:
                recent_df = sum(deploy_freqs[-2:]) / 2
                older_df = sum(deploy_freqs[:2]) / 2
                
                if recent_df > older_df * 1.2:
                    insights['trend_insights'].append("🚀 Deployment frequency is increasing")
                elif recent_df < older_df * 0.8:
                    insights['trend_insights'].append("📉 Deployment frequency is declining")
                    
            if len(failure_rates) >= 3:
                recent_fr = sum(failure_rates[-2:]) / 2
                older_fr = sum(failure_rates[:2]) / 2
                
                if recent_fr > older_fr * 1.5:
                    insights['trend_insights'].append("⚠️ Failure rate is increasing - review quality processes")
                elif recent_fr < older_fr * 0.7:
                    insights['trend_insights'].append("✅ Failure rate is improving")
                    
        except Exception as e:
            logger.debug(f"Trend analysis error: {e}")
            
    def generate_weekly_summary(self, weekly_metrics: List[Dict]) -> Dict[str, Any]:
        """Generate a weekly summary from daily metrics."""
        if not weekly_metrics:
            return {"error": "No metrics provided for weekly summary"}
            
        try:
            # Aggregate weekly data
            total_commits = sum(day.get('total_commits', 0) for day in weekly_metrics)
            total_prs = sum(day.get('total_prs', 0) for day in weekly_metrics)
            avg_lead_time = sum(day.get('dora', {}).get('lead_time', {}).get('total_lead_time_hours', 0) 
                               for day in weekly_metrics) / len(weekly_metrics)
            
            weekly_summary = {
                "period": "week",
                "total_commits": total_commits,
                "total_prs": total_prs,
                "avg_lead_time_hours": round(avg_lead_time, 2),
                "active_days": len([day for day in weekly_metrics if day.get('total_commits', 0) > 0]),
                "summary": f"This week: {total_commits} commits, {total_prs} PRs, {avg_lead_time:.1f}h avg lead time"
            }
            
            # Add recommendations based on weekly patterns
            recommendations = []
            if total_commits < 5:
                recommendations.append("Consider increasing commit frequency for better code review")
            if avg_lead_time > 48:
                recommendations.append("Focus on reducing lead time through smaller PRs")
            if total_prs < 2:
                recommendations.append("Break work into more frequent pull requests")
                
            weekly_summary["recommendations"] = recommendations
            return weekly_summary
            
        except Exception as e:
            logger.error(f"Weekly summary generation failed: {e}")
            return {"error": str(e)}
            
    def generate_monthly_insights(self, monthly_data: List[Dict]) -> Dict[str, Any]:
        """Generate monthly performance insights."""
        try:
            if len(monthly_data) < 4:  # Need at least 4 weeks
                return {"error": "Insufficient data for monthly insights"}
                
            insights = {
                "month_summary": "",
                "key_achievements": [],
                "areas_for_improvement": [],
                "trend_analysis": {}
            }
            
            # Calculate monthly averages
            monthly_commits = sum(week.get('total_commits', 0) for week in monthly_data)
            monthly_prs = sum(week.get('total_prs', 0) for week in monthly_data)
            avg_lead_time = sum(week.get('avg_lead_time_hours', 0) for week in monthly_data) / len(monthly_data)
            
            insights["month_summary"] = (
                f"Monthly totals: {monthly_commits} commits, {monthly_prs} PRs. "
                f"Average lead time: {avg_lead_time:.1f} hours."
            )
            
            # Identify achievements
            if avg_lead_time < 24:
                insights["key_achievements"].append("Maintained elite lead time performance")
            if monthly_commits > 50:
                insights["key_achievements"].append("High development activity maintained")
            if monthly_prs > 10:
                insights["key_achievements"].append("Good pull request frequency")
                
            # Areas for improvement
            if avg_lead_time > 72:
                insights["areas_for_improvement"].append("Reduce lead time through smaller changes")
            if monthly_prs < 5:
                insights["areas_for_improvement"].append("Increase pull request frequency")
                
            return insights
            
        except Exception as e:
            logger.error(f"Monthly insights generation failed: {e}")
            return {"error": str(e)}
    
    def get_api_usage_stats(self) -> Dict[str, Any]:
        """Get current API usage statistics"""
        return {
            "daily_requests": self.daily_request_count,
            "daily_limit": self.MAX_REQUESTS_PER_DAY,
            "requests_remaining": self.MAX_REQUESTS_PER_DAY - self.daily_request_count,
            "cache_size": len(self.cache),
            "rate_limit_delay": self.REQUEST_DELAY,
            "daily_reset_time": self.daily_reset_time.isoformat(),
            "quota_percentage": (self.daily_request_count / self.MAX_REQUESTS_PER_DAY) * 100
        }
    
    def clear_cache(self):
        """Clear the API response cache"""
        self.cache.clear()
        logger.info("Summary bot cache cleared")
        
    def is_quota_available(self) -> bool:
        """Check if API quota is available"""
        current_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        if current_date > self.daily_reset_time:
            self.daily_request_count = 0
            self.daily_reset_time = current_date
        
        return self.daily_request_count < self.MAX_REQUESTS_PER_DAY
    
    def generate_repository_contribution_summary(self, repo_data: Dict[str, Any]) -> Dict[str, Any]:
        """Generate AI-powered analysis of user's contribution to a specific repository."""
        
        try:
            # Extract key metrics
            repo_name = repo_data.get('repository_name', 'Unknown Repository')
            user_commits = repo_data.get('user_commits', 0)
            total_commits = repo_data.get('total_commits', 0)
            user_prs = repo_data.get('user_prs', 0)
            total_prs = repo_data.get('total_prs', 0)
            contribution_percentage = repo_data.get('contribution_percentage', 0)
            user_email = repo_data.get('user_email', 'unknown')
            recent_activity = repo_data.get('recent_activity', 0)
            
            # Create cache key for this specific analysis
            cache_key = f"repo_{hashlib.md5(f'{repo_name}_{user_email}_{user_commits}_{total_commits}'.encode()).hexdigest()}"
            
            # Check cache first
            if cache_key in self.cache:
                logger.info(f"Using cached repository analysis for {repo_name}")
                return self.cache[cache_key]
            
            insights = {
                "summary": "",
                "contribution_analysis": "",
                "recommendations": [],
                "team_role": "",
                "recent_activity_assessment": ""
            }
            
            # Try Gemini API first if available and quota allows
            if self.gemini_api_key and GEMINI_AVAILABLE and self._check_rate_limits():
                try:
                    model = genai.GenerativeModel('gemini-1.5-flash')
                    
                    prompt = f"""
                    Analyze this developer's contribution to the repository '{repo_name}':
                    
                    User Statistics:
                    - User commits: {user_commits}
                    - User pull requests: {user_prs}
                    - Recent activity (last 30 days): {recent_activity} commits
                    
                    Repository Statistics:
                    - Total repository commits: {total_commits}
                    - Total repository pull requests: {total_prs}
                    - User's contribution percentage: {contribution_percentage:.1f}%
                    
                    Please provide:
                    1. A brief summary of the user's contribution level
                    2. Analysis of their role in the team (major contributor, occasional contributor, maintainer, etc.)
                    3. 2-3 specific recommendations for improvement or continued success
                    4. Assessment of recent activity level
                    
                    Keep the response concise and actionable. Focus on meaningful insights rather than just restating the numbers.
                    """
                    
                    response = model.generate_content(prompt)
                    
                    if response and response.text:
                        # Parse the response and structure it
                        ai_response = response.text.strip()
                        
                        # Try to extract structured information from AI response
                        lines = ai_response.split('\n')
                        current_section = None
                        
                        for line in lines:
                            line = line.strip()
                            if not line:
                                continue
                                
                            if 'summary' in line.lower() or line.startswith('1.'):
                                current_section = 'summary'
                                insights['summary'] = line.replace('1.', '').strip()
                            elif 'role' in line.lower() or 'team' in line.lower() or line.startswith('2.'):
                                current_section = 'team_role'
                                insights['team_role'] = line.replace('2.', '').strip()
                            elif 'recommendation' in line.lower() or line.startswith('3.'):
                                current_section = 'recommendations'
                            elif 'activity' in line.lower() or line.startswith('4.'):
                                current_section = 'recent_activity'
                                insights['recent_activity_assessment'] = line.replace('4.', '').strip()
                            elif current_section == 'recommendations' and (line.startswith('-') or line.startswith('•')):
                                insights['recommendations'].append(line.lstrip('-•').strip())
                            elif current_section and not insights.get(current_section if current_section != 'recommendations' else 'contribution_analysis'):
                                if current_section == 'summary':
                                    insights['summary'] = line
                                elif current_section == 'team_role':
                                    insights['team_role'] = line
                                elif current_section == 'recent_activity':
                                    insights['recent_activity_assessment'] = line
                        
                        # If we didn't get structured data, use the full response as summary
                        if not insights['summary']:
                            insights['summary'] = ai_response[:200] + "..." if len(ai_response) > 200 else ai_response
                        
                        self.last_request_time = time.time()
                        self.daily_request_count += 1
                        
                        # Cache the result
                        self.cache[cache_key] = insights
                        
                        logger.info(f"Generated AI repository analysis for {repo_name}")
                        return insights
                        
                except Exception as e:
                    error_msg = str(e)
                    if "429" in error_msg or "quota" in error_msg.lower() or "exceeded" in error_msg.lower():
                        logger.error(f"Gemini API quota exceeded in repository analysis: {error_msg}")
                        # Set cooldown period - wait for 1 hour before trying again
                        self._quota_exceeded_until = time.time() + 3600  # 1 hour cooldown
                        # Also increment the daily count to prevent further attempts
                        self.daily_request_count = self.MAX_REQUESTS_PER_DAY
                        logger.info("Set 1-hour cooldown for Gemini API due to quota exceeded")
                    else:
                        logger.warning(f"Gemini API failed for repository analysis: {e}")
                    # Fall through to rule-based analysis
            
            # Fallback to rule-based analysis
            logger.info(f"Using rule-based repository analysis for {repo_name}")
            
            # Generate rule-based summary
            if contribution_percentage >= 50:
                insights['summary'] = f"You are a major contributor to {repo_name}, responsible for {contribution_percentage:.1f}% of commits."
                insights['team_role'] = "Primary Maintainer - You handle the majority of development work"
            elif contribution_percentage >= 25:
                insights['summary'] = f"You are a significant contributor to {repo_name} with {contribution_percentage:.1f}% of total commits."
                insights['team_role'] = "Core Team Member - You play an important role in development"
            elif contribution_percentage >= 10:
                insights['summary'] = f"You are a regular contributor to {repo_name}, contributing {contribution_percentage:.1f}% of commits."
                insights['team_role'] = "Active Contributor - You make meaningful contributions to the project"
            elif contribution_percentage >= 1:
                insights['summary'] = f"You are an occasional contributor to {repo_name} with {contribution_percentage:.1f}% of commits."
                insights['team_role'] = "Occasional Contributor - You participate when needed"
            else:
                insights['summary'] = f"You have minimal contribution to {repo_name} currently."
                insights['team_role'] = "New or Minimal Contributor"
            
            # Generate contribution analysis
            if total_commits > 0:
                commit_ratio = user_commits / total_commits
                pr_ratio = (user_prs / total_prs) if total_prs > 0 else 0
                
                analysis_parts = []
                if commit_ratio > pr_ratio and user_prs > 0:
                    analysis_parts.append("You tend to make more direct commits than pull requests")
                elif pr_ratio > commit_ratio and user_commits > 0:
                    analysis_parts.append("You follow good practices with more pull requests than direct commits")
                
                if recent_activity > 0:
                    analysis_parts.append(f"You've been active recently with {recent_activity} commits in the last 30 days")
                else:
                    analysis_parts.append("No recent activity in the last 30 days")
                
                insights['contribution_analysis'] = ". ".join(analysis_parts) + "."
            
            # Generate recommendations
            recommendations = []
            
            if contribution_percentage < 1:
                recommendations.append("Consider increasing your involvement in this repository")
                recommendations.append("Start with small bug fixes or documentation improvements")
            elif contribution_percentage < 10:
                recommendations.append("Look for opportunities to take on larger features")
                recommendations.append("Consider reviewing other contributors' pull requests")
            elif contribution_percentage >= 50:
                recommendations.append("Consider mentoring newer contributors")
                recommendations.append("Focus on architectural decisions and code reviews")
            else:
                recommendations.append("Maintain your current contribution level")
                recommendations.append("Consider specializing in specific areas of the codebase")
            
            if recent_activity == 0:
                recommendations.append("Try to maintain more consistent activity in the repository")
            
            insights['recommendations'] = recommendations[:3]  # Limit to 3 recommendations
            
            # Recent activity assessment
            if recent_activity >= 10:
                insights['recent_activity_assessment'] = "Very active recently - excellent engagement"
            elif recent_activity >= 5:
                insights['recent_activity_assessment'] = "Good recent activity level"
            elif recent_activity >= 1:
                insights['recent_activity_assessment'] = "Some recent activity, could be more consistent"
            else:
                insights['recent_activity_assessment'] = "No recent activity - consider re-engaging with the project"
            
            # Cache the result
            self.cache[cache_key] = insights
            
            return insights
            
        except Exception as e:
            logger.error(f"Repository contribution analysis failed: {e}")
            return {
                "summary": f"Unable to analyze contribution to {repo_data.get('repository_name', 'repository')}",
                "contribution_analysis": "Analysis temporarily unavailable",
                "recommendations": ["Check back later for detailed insights"],
                "team_role": "Analysis pending",
                "recent_activity_assessment": "Data unavailable"
            }
