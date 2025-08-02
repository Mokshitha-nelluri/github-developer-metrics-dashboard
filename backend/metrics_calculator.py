from datetime import datetime, timedelta
import statistics
from typing import Dict, List, Any, Tuple
import logging
import numpy as np
from collections import defaultdict, Counter

logger = logging.getLogger(__name__)

class EnhancedMetricsCalculator:
    """Advanced metrics calculator with performance grading and trend analysis."""
    
    def __init__(self):
        # Industry benchmarks (based on DORA research and industry data)
        self.benchmarks = {
            "elite": {
                "lead_time_hours": 24,
                "deployment_frequency_per_week": 10,
                "change_failure_rate": 5,
                "mttr_hours": 1
            },
            "high": {
                "lead_time_hours": 168,  # 1 week
                "deployment_frequency_per_week": 3,
                "change_failure_rate": 10,
                "mttr_hours": 24
            },
            "medium": {
                "lead_time_hours": 720,  # 1 month
                "deployment_frequency_per_week": 1,
                "change_failure_rate": 15,
                "mttr_hours": 168
            }
        }
    
    def calculate_all_metrics(self, commits: List[Dict], pull_requests: List[Dict], scope: str) -> Dict[str, Any]:
        """Calculate comprehensive set of metrics."""
        metrics = {}
        
        # Store raw totals for dashboard summaries
        metrics["total_commits"] = len(commits)
        metrics["total_prs"] = len(pull_requests)
        
        # DORA metrics
        metrics["dora"] = self.calculate_advanced_dora_metrics(commits, pull_requests)
        
        # Code quality
        metrics["code_quality"] = self.calculate_code_quality_metrics(commits, pull_requests)
        
        # Productivity patterns
        metrics["productivity_patterns"] = self.calculate_productivity_patterns(commits)
        
        # Collaboration
        metrics["collaboration"] = self.calculate_collaboration_metrics(pull_requests)
        
        # Performance grade
        metrics["performance_grade"] = self.get_performance_grade(metrics)
        
        # Add calculated values to top level for easier access
        metrics["lead_time_hours"] = metrics["dora"]["lead_time"].get("total_lead_time_hours", 0)
        metrics["deployment_frequency"] = metrics["dora"]["deployment_frequency"].get("per_week", 0)
        metrics["change_failure_rate"] = metrics["dora"]["change_failure_rate"].get("percentage", 0)
        metrics["review_coverage_percentage"] = metrics["code_quality"].get("review_coverage_percentage", 0)
        metrics["work_life_balance_score"] = metrics["productivity_patterns"].get("work_life_balance_score", 0)
        
        # Weekly trends
        if scope == "global":
            metrics["weekly_commit_frequency"] = self._calculate_weekly_trend(commits, "committedDate")
        elif scope == "tracked":
            metrics["weekly_commit_frequency"] = self._calculate_weekly_trend(commits, "committedDate")
        
        metrics["deployment_frequency_by_week"] = metrics["dora"]["deployment_frequency"].get("weekly_trend", {})
        
        return metrics
    
    def _calculate_weekly_trend(self, data: List[Dict], date_field: str) -> Dict[str, int]:
        """Calculate weekly activity trend."""
        weekly_counts = defaultdict(int)
        
        for item in data:
            if date_str := item.get(date_field):
                try:
                    date = self._parse_date(date_str)
                    week_key = date.strftime("%Y-W%U")
                    weekly_counts[week_key] += 1
                except Exception:
                    continue
        
        return dict(weekly_counts)
    
    def _parse_date(self, date_str):
        """Parse GitHub date string to datetime object with improved microsecond handling"""
        try:
            if isinstance(date_str, str):
                # Handle different date formats
                date_str = date_str.replace("Z", "+00:00")
                
                # Try to parse with microseconds first
                try:
                    # Handle microseconds with variable precision
                    if "." in date_str and "+" in date_str:
                        # Split to handle microseconds properly
                        date_part, tz_part = date_str.rsplit("+", 1)
                        if "." in date_part:
                            base_part, micro_part = date_part.rsplit(".", 1)
                            # Normalize microseconds to 6 digits
                            if len(micro_part) > 6:
                                micro_part = micro_part[:6]
                            elif len(micro_part) < 6:
                                micro_part = micro_part.ljust(6, '0')
                            date_str = f"{base_part}.{micro_part}+{tz_part}"
                    
                    return datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%S.%f%z").replace(tzinfo=None)
                except ValueError:
                    # Try without microseconds
                    return datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%S%z").replace(tzinfo=None)
            return date_str
        except ValueError:
            try:
                # Legacy format
                return datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%SZ")
            except ValueError:
                logger.warning(f"Failed to parse date: {date_str}")
                return datetime.now()
    
    def calculate_advanced_dora_metrics(self, commits: List[Dict], pull_requests: List[Dict]) -> Dict[str, Any]:
        """Calculate comprehensive DORA metrics with detailed breakdown."""
        # Lead Time for Changes (detailed breakdown)
        lead_time_data = self._calculate_detailed_lead_time(pull_requests)
        
        # Deployment Frequency
        deployment_freq = self._calculate_deployment_frequency(pull_requests)
        
        # Change Failure Rate (enhanced detection)
        failure_rate = self._calculate_enhanced_failure_rate(pull_requests, commits)
        
        # Mean Time to Recovery
        mttr = self._calculate_mttr(pull_requests, commits)
        
        return {
            "lead_time": lead_time_data,
            "deployment_frequency": deployment_freq,
            "change_failure_rate": failure_rate,
            "mttr": mttr
        }
    
    def _calculate_detailed_lead_time(self, pull_requests: List[Dict]) -> Dict[str, Any]:
        """Calculate detailed lead time breakdown."""
        lead_times = []
        code_times = []  # Time from first commit to PR creation
        review_times = []  # Time from PR creation to first review
        merge_times = []  # Time from last review to merge
        
        for pr in pull_requests:
            if not pr.get("mergedAt"):
                continue
            
            try:
                created_at = self._parse_date(pr["createdAt"])
                merged_at = self._parse_date(pr["mergedAt"])
                
                # Get commit dates
                commits = pr.get("commits", {}).get("nodes", [])
                if commits:
                    commit_dates = [
                        self._parse_date(commit["commit"]["committedDate"])
                        for commit in commits
                        if commit.get("commit", {}).get("committedDate")
                    ]
                    
                    if commit_dates:
                        first_commit = min(commit_dates)
                        
                        # Code time: first commit to PR creation
                        code_time = (created_at - first_commit).total_seconds()
                        if code_time >= 0:
                            code_times.append(code_time)
                        
                        # Total lead time: first commit to merge
                        total_lead_time = (merged_at - first_commit).total_seconds()
                        if total_lead_time >= 0:
                            lead_times.append(total_lead_time)
                        
                        # Review time: PR creation to first review
                        reviews = pr.get("reviews", {}).get("nodes", [])
                        if reviews:
                            review_dates = [
                                self._parse_date(review["submittedAt"])
                                for review in reviews
                                if review.get("submittedAt")
                            ]
                            
                            if review_dates:
                                first_review = min(review_dates)
                                review_time = (first_review - created_at).total_seconds()
                                if review_time >= 0:
                                    review_times.append(review_time)
                                
                                # Merge time: last review to merge
                                last_review = max(review_dates)
                                merge_time = (merged_at - last_review).total_seconds()
                                if merge_time >= 0:
                                    merge_times.append(merge_time)
                
            except Exception as e:
                logger.warning(f"Failed to calculate lead time for PR: {e}")
                continue
        
        return {
            "total_lead_time_sec": self._average(lead_times),
            "total_lead_time_hours": self._average(lead_times) / 3600 if lead_times else 0,
            "code_time_sec": self._average(code_times),
            "code_time_hours": self._average(code_times) / 3600 if code_times else 0,
            "review_time_sec": self._average(review_times),
            "review_time_hours": self._average(review_times) / 3600 if review_times else 0,
            "merge_time_sec": self._average(merge_times),
            "merge_time_hours": self._average(merge_times) / 3600 if merge_times else 0,
            "p50_lead_time_hours": self._percentile(lead_times, 50) / 3600 if lead_times else 0,
            "p90_lead_time_hours": self._percentile(lead_times, 90) / 3600 if lead_times else 0,
            "p95_lead_time_hours": self._percentile(lead_times, 95) / 3600 if lead_times else 0
        }
    
    def _calculate_deployment_frequency(self, pull_requests: List[Dict]) -> Dict[str, Any]:
        """Calculate deployment frequency with trends."""
        if not pull_requests:
            return {
                "per_week": 0,
                "per_day": 0,
                "weekly_trend": {}
            }
        
        # Group by week
        weekly_deployments = defaultdict(int)
        daily_deployments = defaultdict(int)
        
        for pr in pull_requests:
            if pr.get("mergedAt"):
                try:
                    merge_date = self._parse_date(pr["mergedAt"])
                    week_key = merge_date.strftime("%Y-W%U")
                    day_key = merge_date.strftime("%Y-%m-%d")
                    weekly_deployments[week_key] += 1
                    daily_deployments[day_key] += 1
                except Exception as e:
                    logger.warning(f"Failed to parse merge date: {e}")
                    continue
        
        # Calculate averages
        avg_per_week = sum(weekly_deployments.values()) / len(weekly_deployments) if weekly_deployments else 0
        avg_per_day = sum(daily_deployments.values()) / len(daily_deployments) if daily_deployments else 0
        
        # Calculate trend (last 4 weeks vs previous 4 weeks)
        sorted_weeks = sorted(weekly_deployments.keys())
        trend = "stable"
        
        if len(sorted_weeks) >= 8:
            recent_weeks = sorted_weeks[-4:]
            previous_weeks = sorted_weeks[-8:-4]
            recent_avg = sum(weekly_deployments[week] for week in recent_weeks) / 4
            previous_avg = sum(weekly_deployments[week] for week in previous_weeks) / 4
            
            if recent_avg > previous_avg * 1.2:
                trend = "increasing"
            elif recent_avg < previous_avg * 0.8:
                trend = "decreasing"
        
        return {
            "per_week": round(avg_per_week, 2),
            "per_day": round(avg_per_day, 2),
            "weekly_trend": dict(weekly_deployments),
            "daily_trend": dict(daily_deployments),
            "trend_direction": trend,
            "total_deployments": len([pr for pr in pull_requests if pr.get("mergedAt")])
        }
    
    def _calculate_enhanced_failure_rate(self, pull_requests: List[Dict], commits: List[Dict]) -> Dict[str, Any]:
        """Calculate enhanced change failure rate with detailed analysis."""
        if not pull_requests:
            return {
                "percentage": 0,
                "failure_types": {},
                "hotfix_count": 0
            }
        
        failure_indicators = {
            "revert": ["revert", "rollback", "undo"],
            "hotfix": ["hotfix", "emergency", "urgent", "critical"],
            "bugfix": ["fix", "bug", "issue", "broken", "error"],
            "patch": ["patch", "quick fix", "band-aid"]
        }
        
        failure_counts = defaultdict(int)
        total_failures = 0
        failed_prs = []
        
        for pr in pull_requests:
            if not pr.get("mergedAt"):
                continue
            
            title = pr.get("title", "").lower()
            body = pr.get("body", "").lower()
            is_failure = False
            failure_type = None
            
            # Check PR title and body for failure indicators
            for f_type, keywords in failure_indicators.items():
                if any(keyword in title or keyword in body for keyword in keywords):
                    failure_counts[f_type] += 1
                    total_failures += 1
                    is_failure = True
                    failure_type = f_type
                    break
            
            if is_failure:
                failed_prs.append({
                    "number": pr.get("number"),
                    "title": pr.get("title"),
                    "type": failure_type,
                    "merged_at": pr.get("mergedAt")
                })
        
        # Also check commits for failure patterns
        hotfix_commits = 0
        for commit in commits[-50:]:  # Check recent commits
            message = commit.get("message", "").lower()
            if any(keyword in message for keyword in failure_indicators["hotfix"]):
                hotfix_commits += 1
        
        failure_rate = (total_failures / len(pull_requests)) * 100 if pull_requests else 0
        
        return {
            "percentage": round(failure_rate, 2),
            "failure_types": dict(failure_counts),
            "hotfix_count": hotfix_commits,
            "failed_prs": failed_prs,
            "total_failures": total_failures,
            "total_prs": len(pull_requests)
        }
    
    def _calculate_mttr(self, pull_requests: List[Dict], commits: List[Dict]) -> Dict[str, Any]:
        """Calculate Mean Time to Recovery."""
        recovery_times = []
        
        # Look for pairs of failure and fix PRs
        sorted_prs = sorted(
            [pr for pr in pull_requests if pr.get("mergedAt")],
            key=lambda x: self._parse_date(x["mergedAt"])
        )
        
        failure_keywords = ["bug", "fix", "issue", "broken", "error", "hotfix"]
        
        for i, pr in enumerate(sorted_prs):
            title = pr.get("title", "").lower()
            
            # If this is a fix PR, look for the original issue
            if any(keyword in title for keyword in failure_keywords):
                # Look back for potential failure point
                failure_time = None
                fix_time = self._parse_date(pr["mergedAt"])
                
                # Simple heuristic: assume failure happened at previous deployment
                if i > 0:
                    failure_time = self._parse_date(sorted_prs[i-1]["mergedAt"])
                    recovery_time = (fix_time - failure_time).total_seconds()
                    if recovery_time > 0:
                        recovery_times.append(recovery_time)
        
        avg_mttr = self._average(recovery_times) if recovery_times else 0
        
        return {
            "mttr_sec": avg_mttr,
            "mttr_hours": avg_mttr / 3600 if avg_mttr else 0,
            "mttr_days": avg_mttr / 86400 if avg_mttr else 0,
            "recovery_incidents": len(recovery_times),
            "p50_mttr_hours": self._percentile(recovery_times, 50) / 3600 if recovery_times else 0,
            "p90_mttr_hours": self._percentile(recovery_times, 90) / 3600 if recovery_times else 0
        }
    
    def calculate_code_quality_metrics(self, commits: List[Dict], pull_requests: List[Dict]) -> Dict[str, Any]:
        """Calculate code quality and maintainability metrics."""
        # Commit size analysis
        commit_sizes = []
        large_commits = 0
        
        for commit in commits:
            size = (commit.get("additions", 0) + commit.get("deletions", 0))
            commit_sizes.append(size)
            if size > 500:  # Large commit threshold
                large_commits += 1
        
        # PR size analysis
        pr_sizes = []
        large_prs = 0
        
        for pr in pull_requests:
            size = (pr.get("additions", 0) + pr.get("deletions", 0))
            pr_sizes.append(size)
            if size > 1000:  # Large PR threshold
                large_prs += 1
        
        # Review coverage
        reviewed_prs = sum(1 for pr in pull_requests if pr.get("reviews", {}).get("nodes"))
        review_coverage = (reviewed_prs / len(pull_requests)) * 100 if pull_requests else 0
        
        # Files changed analysis
        files_changed = []
        for commit in commits:
            files_changed.append(commit.get("changedFiles", 0))
        
        return {
            "avg_commit_size": self._average(commit_sizes),
            "avg_pr_size": self._average(pr_sizes),
            "large_commits_percentage": (large_commits / len(commits)) * 100 if commits else 0,
            "large_prs_percentage": (large_prs / len(pull_requests)) * 100 if pull_requests else 0,
            "review_coverage_percentage": round(review_coverage, 2),
            "avg_files_per_commit": self._average(files_changed),
            "commit_size_distribution": {
                "small": sum(1 for size in commit_sizes if size < 50),
                "medium": sum(1 for size in commit_sizes if 50 <= size < 200),
                "large": sum(1 for size in commit_sizes if size >= 200)
            }
        }
    
    def calculate_productivity_patterns(self, commits: List[Dict]) -> Dict[str, Any]:
        """Analyze productivity patterns and work habits."""
        if not commits:
            return {}
        
        commit_times = []
        day_counts = defaultdict(int)
        hour_counts = defaultdict(int)
        
        for commit in commits:
            try:
                commit_date = self._parse_date(commit["committedDate"])
                commit_times.append(commit_date)
                
                # Day of week (0 = Monday)
                day_counts[commit_date.weekday()] += 1
                
                # Hour of day
                hour_counts[commit_date.hour] += 1
            except Exception as e:
                logger.warning(f"Failed to parse commit date: {e}")
                continue
        
        # Calculate streaks
        commit_dates = sorted(set(date.date() for date in commit_times))
        current_streak = 0
        max_streak = 0
        
        for i, date in enumerate(commit_dates):
            if i == 0:
                current_streak = 1
            else:
                if (date - commit_dates[i-1]).days == 1:
                    current_streak += 1
                else:
                    current_streak = 1
            max_streak = max(max_streak, current_streak)
        
        # Work-life balance indicators
        weekend_commits = day_counts[5] + day_counts[6]  # Saturday + Sunday
        weekday_commits = sum(day_counts[i] for i in range(5))
        weekend_percentage = (weekend_commits / len(commits)) * 100 if commits else 0
        
        late_night_commits = sum(hour_counts[hour] for hour in range(22, 24)) + sum(hour_counts[hour] for hour in range(0, 6))
        late_night_percentage = (late_night_commits / len(commits)) * 100 if commits else 0
        
        return {
            "commits_by_day": dict(day_counts),
            "commits_by_hour": dict(hour_counts),
            "weekend_work_percentage": round(weekend_percentage, 2),
            "late_night_work_percentage": round(late_night_percentage, 2),
            "max_commit_streak": max_streak,
            "most_productive_day": max(day_counts, key=day_counts.get) if day_counts else None,
            "most_productive_hour": max(hour_counts, key=hour_counts.get) if hour_counts else None,
            "work_life_balance_score": max(0, 100 - weekend_percentage - late_night_percentage)
        }
    
    def calculate_collaboration_metrics(self, pull_requests: List[Dict]) -> Dict[str, Any]:
        """Calculate team collaboration metrics."""
        if not pull_requests:
            return {}
        
        reviewers = []
        review_response_times = []
        pr_authors = []
        
        for pr in pull_requests:
            author = pr.get("author", {}).get("login")
            if author:
                pr_authors.append(author)
            
            reviews = pr.get("reviews", {}).get("nodes", [])
            for review in reviews:
                reviewer = review.get("author", {}).get("login")
                if reviewer and reviewer != author:
                    reviewers.append(reviewer)
                    
                    # Calculate review response time
                    try:
                        pr_created = self._parse_date(pr["createdAt"])
                        review_submitted = self._parse_date(review["submittedAt"])
                        response_time = (review_submitted - pr_created).total_seconds()
                        if response_time > 0:
                            review_response_times.append(response_time)
                    except Exception as e:
                        logger.warning(f"Failed to calculate review response time: {e}")
        
        # Unique collaborators
        unique_reviewers = len(set(reviewers))
        unique_authors = len(set(pr_authors))
        
        # Review distribution
        reviewer_counts = Counter(reviewers)
        
        return {
            "unique_reviewers": unique_reviewers,
            "unique_authors": unique_authors,
            "avg_review_response_time_hours": self._average(review_response_times) / 3600 if review_response_times else 0,
            "total_reviews": len(reviewers),
            "reviews_per_pr": len(reviewers) / len(pull_requests) if pull_requests else 0,
            "top_reviewers": dict(reviewer_counts.most_common(5)),
            "collaboration_index": unique_reviewers * unique_authors  # Simple collaboration metric
        }
    
    def get_performance_grade(self, metrics: Dict[str, Any]) -> Dict[str, Any]:
        """Calculate comprehensive performance grade with detailed breakdown."""
        scores = {}
        max_scores = {}
        explanations = []
        
        # DORA Metrics Scoring (40% of total)
        dora_score = 0
        dora_max = 40
        
        # Lead time (10 points)
        lead_time_hours = metrics.get("dora", {}).get("lead_time", {}).get("total_lead_time_hours", 0)
        if lead_time_hours <= self.benchmarks["elite"]["lead_time_hours"]:
            dora_score += 10
            explanations.append("🏆 Elite lead time performance")
        elif lead_time_hours <= self.benchmarks["high"]["lead_time_hours"]:
            dora_score += 8
            explanations.append("High-performing lead time")
        elif lead_time_hours <= self.benchmarks["medium"]["lead_time_hours"]:
            dora_score += 6
            explanations.append("Medium lead time performance")
        else:
            dora_score += 3
            explanations.append("Lead time needs improvement")
        
        # Deployment frequency (10 points)
        deploy_freq = metrics.get("dora", {}).get("deployment_frequency", {}).get("per_week", 0)
        if deploy_freq >= self.benchmarks["elite"]["deployment_frequency_per_week"]:
            dora_score += 10
            explanations.append("Elite deployment frequency")
        elif deploy_freq >= self.benchmarks["high"]["deployment_frequency_per_week"]:
            dora_score += 8
            explanations.append("High deployment frequency")
        elif deploy_freq >= self.benchmarks["medium"]["deployment_frequency_per_week"]:
            dora_score += 6
            explanations.append("Good deployment cadence")
        else:
            dora_score += 3
            explanations.append("Consider increasing deployment frequency")
        
        # Change failure rate (10 points)
        failure_rate = metrics.get("dora", {}).get("change_failure_rate", {}).get("percentage", 0)
        if failure_rate <= self.benchmarks["elite"]["change_failure_rate"]:
            dora_score += 10
            explanations.append("Elite change success rate")
        elif failure_rate <= self.benchmarks["high"]["change_failure_rate"]:
            dora_score += 8
            explanations.append("High-quality changes")
        elif failure_rate <= self.benchmarks["medium"]["change_failure_rate"]:
            dora_score += 6
            explanations.append("Acceptable change quality")
        else:
            dora_score += 3
            explanations.append("🔧 Focus on change quality improvement")
        
        # MTTR (10 points)
        mttr_hours = metrics.get("dora", {}).get("mttr", {}).get("mttr_hours", 0)
        if mttr_hours <= self.benchmarks["elite"]["mttr_hours"]:
            dora_score += 10
            explanations.append("Elite recovery time")
        elif mttr_hours <= self.benchmarks["high"]["mttr_hours"]:
            dora_score += 8
            explanations.append("🔧 Fast recovery capability")
        elif mttr_hours <= self.benchmarks["medium"]["mttr_hours"]:
            dora_score += 6
            explanations.append("⏰ Reasonable recovery time")
        else:
            dora_score += 3
            explanations.append("🚨 Improve incident response time")
        
        scores["dora"] = dora_score
        max_scores["dora"] = dora_max
        
        # Code Quality Scoring (25% of total)
        quality_score = 0
        quality_max = 25
        
        review_coverage = metrics.get("code_quality", {}).get("review_coverage_percentage", 0)
        if review_coverage >= 90:
            quality_score += 10
            explanations.append("Excellent review coverage")
        elif review_coverage >= 70:
            quality_score += 8
            explanations.append("Good review practices")
        else:
            quality_score += 5
            explanations.append("Increase code review coverage")
        
        large_prs_pct = metrics.get("code_quality", {}).get("large_prs_percentage", 0)
        if large_prs_pct <= 10:
            quality_score += 8
            explanations.append("📦 Well-sized pull requests")
        elif large_prs_pct <= 25:
            quality_score += 6
            explanations.append("📏 Consider smaller PRs")
        else:
            quality_score += 3
            explanations.append("Break down large pull requests")
        
        avg_files_per_commit = metrics.get("code_quality", {}).get("avg_files_per_commit", 0)
        if avg_files_per_commit <= 5:
            quality_score += 7
            explanations.append("Focused commits")
        else:
            quality_score += 4
            explanations.append("📂 Consider more focused commits")
        
        scores["code_quality"] = quality_score
        max_scores["code_quality"] = quality_max
        
        # Productivity Patterns (20% of total)
        productivity_score = 0
        productivity_max = 20
        
        work_life_balance = metrics.get("productivity_patterns", {}).get("work_life_balance_score", 0)
        if work_life_balance >= 80:
            productivity_score += 10
            explanations.append("Excellent work-life balance")
        elif work_life_balance >= 60:
            productivity_score += 8
            explanations.append("🏠 Good work-life balance")
        else:
            productivity_score += 5
            explanations.append("🌅 Consider improving work-life balance")
        
        commit_streak = metrics.get("productivity_patterns", {}).get("max_commit_streak", 0)
        if commit_streak >= 7:
            productivity_score += 10
            explanations.append("🔥 Great consistency streak")
        elif commit_streak >= 3:
            productivity_score += 7
            explanations.append("Good consistency")
        else:
            productivity_score += 4
            explanations.append("Work on consistent contributions")
        
        scores["productivity"] = productivity_score
        max_scores["productivity"] = productivity_max
        
        # Collaboration (15% of total)
        collaboration_score = 0
        collaboration_max = 15
        
        unique_reviewers = metrics.get("collaboration", {}).get("unique_reviewers", 0)
        if unique_reviewers >= 5:
            collaboration_score += 8
            explanations.append("🤝 Strong team collaboration")
        elif unique_reviewers >= 2:
            collaboration_score += 6
            explanations.append("👥 Good team interaction")
        else:
            collaboration_score += 3
            explanations.append("🌐 Expand collaboration network")
        
        review_response_time = metrics.get("collaboration", {}).get("avg_review_response_time_hours", 0)
        if review_response_time <= 24:
            collaboration_score += 7
            explanations.append("Fast review responses")
        elif review_response_time <= 72:
            collaboration_score += 5
            explanations.append("⏰ Reasonable review timing")
        else:
            collaboration_score += 2
            explanations.append("🕐 Improve review response time")
        
        scores["collaboration"] = collaboration_score
        max_scores["collaboration"] = collaboration_max
        
        # Calculate overall grade
        total_score = sum(scores.values())
        total_max = sum(max_scores.values())
        percentage = (total_score / total_max) * 100
        
        if percentage >= 90:
            grade = "A+"
            grade_description = "Elite Performance"
        elif percentage >= 85:
            grade = "A"
            grade_description = "Excellent Performance"
        elif percentage >= 80:
            grade = "A-"
            grade_description = "Very Good Performance"
        elif percentage >= 75:
            grade = "B+"
            grade_description = "Good Performance"
        elif percentage >= 70:
            grade = "B"
            grade_description = "Above Average Performance"
        elif percentage >= 65:
            grade = "B-"
            grade_description = "Average Performance"
        elif percentage >= 60:
            grade = "C+"
            grade_description = "Below Average Performance"
        elif percentage >= 55:
            grade = "C"
            grade_description = "Needs Improvement"
        else:
            grade = "C-"
            grade_description = "Significant Improvement Needed"
        
        return {
            "overall_grade": grade,
            "grade_description": grade_description,
            "percentage": round(percentage, 1),
            "total_score": total_score,
            "max_score": total_max,
            "category_scores": scores,
            "category_max_scores": max_scores,
            "explanations": explanations,
            "improvement_areas": self._get_improvement_recommendations(scores, max_scores),
            "strengths": self._get_strengths(scores, max_scores)
        }
    
    def _get_improvement_recommendations(self, scores: Dict[str, int], max_scores: Dict[str, int]) -> List[str]:
        """Generate specific improvement recommendations."""
        recommendations = []
        
        for category, score in scores.items():
            max_score = max_scores[category]
            percentage = (score / max_score) * 100
            
            if percentage < 70:
                if category == "dora":
                    recommendations.append("Focus on DORA metrics: reduce lead times, increase deployment frequency")
                elif category == "code_quality":
                    recommendations.append("Improve code quality: increase review coverage, create smaller PRs")
                elif category == "productivity":
                    recommendations.append("Enhance productivity: maintain consistent contributions, improve work-life balance")
                elif category == "collaboration":
                    recommendations.append("Strengthen collaboration: engage more reviewers, respond faster to reviews")
        
        return recommendations
    
    def _get_strengths(self, scores: Dict[str, int], max_scores: Dict[str, int]) -> List[str]:
        """Identify top performing metric categories based on percentage of max score."""
        strengths = []
        
        for category, score in scores.items():
            max_score = max_scores[category]
            percentage = (score / max_score) * 100
            
            if percentage >= 80:
                if category == "dora":
                    strengths.append("Excellent DORA metrics performance - industry-leading delivery capabilities")
                elif category == "code_quality":
                    strengths.append("Outstanding code quality practices - thorough reviews and well-sized changes")
                elif category == "productivity":
                    strengths.append("Strong productivity patterns - consistent contributions with good work-life balance")
                elif category == "collaboration":
                    strengths.append("🤝 Exceptional team collaboration - active engagement with multiple reviewers")
        
        # If no major strengths, identify the best performing area
        if not strengths and scores:
            best_category = max(scores.items(), key=lambda x: x[1] / max_scores[x[0]])[0]
            if best_category == "dora":
                strengths.append("DORA metrics show the most potential for improvement")
            elif best_category == "code_quality":
                strengths.append("Code quality practices are your strongest area")
            elif best_category == "productivity":
                strengths.append("Productivity patterns show consistent development habits")
            elif best_category == "collaboration":
                strengths.append("👥 Collaboration metrics indicate good team interaction")
        
        return strengths
    
    def _average(self, values: List[float]) -> float:
        """Return the average of a list of values, or 0.0 if empty."""
        return float(np.mean(values)) if values else 0.0
    
    def _percentile(self, values: List[float], percentile: int) -> float:
        """Return the given percentile of a list of values, or 0.0 if empty."""
        return float(np.percentile(values, percentile)) if values else 0.0
    
    def _median(self, values: List[float]) -> float:
        """Return the median of a list of values, or 0.0 if empty."""
        return float(np.median(values)) if values else 0.0
