"""
Enhanced GitHub API with multiple repository fetching methods
"""
import requests
import time
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from backend.github_api import GitHubAPI

logger = logging.getLogger(__name__)

class EnhancedGitHubAPI(GitHubAPI):
    """Enhanced GitHub API with robust repository discovery, inherits from basic GitHubAPI."""
    
    def __init__(self, token: str):
        # Initialize parent class
        super().__init__(token)
        
        # Enhanced API specific initialization - override URLs if needed
        self.api_url = "https://api.github.com/graphql"
        self.graphql_url = "https://api.github.com/graphql"  # For compatibility
        logger.info("🚀 Enhanced GitHub API initialized with comprehensive repository discovery")
    
    def execute_query(self, query: str, variables: Optional[dict] = None, retries: int = 3, backoff_factor: int = 2) -> Optional[dict]:
        """Executes a GraphQL query with enhanced retry logic and rate limit handling."""
        attempt = 0
        while attempt < retries:
            try:
                response = requests.post(
                    self.api_url,
                    json={"query": query, "variables": variables or {}},
                    headers=self.headers
                )
                
                # Handle rate limiting
                if response.status_code == 429 or (response.status_code == 403 and "rate limit" in response.text.lower()):
                    reset_time = int(response.headers.get('X-RateLimit-Reset', time.time() + 60))
                    sleep_time = max(reset_time - int(time.time()), 60)
                    logger.warning(f"Rate limited. Sleeping for {sleep_time} seconds...")
                    time.sleep(sleep_time)
                    continue
                
                response.raise_for_status()
                data = response.json()
                
                if "errors" in data:
                    error_messages = [e.get("message", "Unknown error") for e in data["errors"]]
                    logger.error(f"GraphQL errors: {', '.join(error_messages)}")
                    raise ValueError(f"GraphQL errors: {', '.join(error_messages)}")
                
                return data
                
            except (requests.exceptions.RequestException, ValueError) as e:
                attempt += 1
                wait_time = backoff_factor ** attempt
                logger.warning(f"Attempt {attempt} failed: {e}. Retrying in {wait_time}s...")
                if attempt < retries:
                    time.sleep(wait_time)
        
        logger.error("All retries failed.")
        return None
    
    def discover_all_accessible_repositories(self, include_private: bool = True) -> List[Dict[str, Any]]:
        """Discover ALL accessible repositories using multiple methods."""
        logger.info("🔍 Starting comprehensive repository discovery...")
        
        all_repos = []
        
        # Method 1: GraphQL with different affiliations
        for affiliation_set in [
            ["OWNER", "COLLABORATOR", "ORGANIZATION_MEMBER"],
            ["OWNER"],
            ["COLLABORATOR"], 
            ["ORGANIZATION_MEMBER"]
        ]:
            try:
                repos = self._fetch_repos_graphql_by_affiliation(affiliation_set, include_private)
                for repo in repos:
                    repo_key = f"{repo.get('owner', {}).get('login', '')}/{repo.get('name', '')}"
                    if not any(r.get('full_name') == repo_key for r in all_repos):
                        repo['full_name'] = repo_key
                        all_repos.append(repo)
                        logger.info(f"📚 Found: {repo_key} (via {', '.join(affiliation_set)})")
            except Exception as e:
                logger.warning(f"GraphQL affiliation {affiliation_set} failed: {e}")
        
        # Method 2: Organization repositories (CRITICAL for missing repos)
        try:
            org_repos = self._fetch_organization_repositories(include_private)
            for repo in org_repos:
                repo_key = f"{repo.get('owner', {}).get('login', '')}/{repo.get('name', '')}"
                if not any(r.get('full_name') == repo_key for r in all_repos):
                    repo['full_name'] = repo_key
                    all_repos.append(repo)
                    logger.info(f"📚 Found via Organization: {repo_key}")
        except Exception as e:
            logger.warning(f"Organization repository discovery failed: {e}")
        
        # Method 3: REST API fallback
        try:
            rest_repos = self._fetch_repos_rest(include_private)
            for repo in rest_repos:
                repo_key = f"{repo.get('owner', {}).get('login', '')}/{repo.get('name', '')}"
                if not any(r.get('full_name') == repo_key for r in all_repos):
                    repo['full_name'] = repo_key
                    all_repos.append(repo)
                    logger.info(f"📚 Found via REST: {repo_key}")
        except Exception as e:
            logger.warning(f"REST API fallback failed: {e}")
        
        # Method 4: Search API for user's repositories
        try:
            search_repos = self._search_user_repositories(include_private)
            for repo in search_repos:
                repo_key = f"{repo.get('owner', {}).get('login', '')}/{repo.get('name', '')}"
                if not any(r.get('full_name') == repo_key for r in all_repos):
                    repo['full_name'] = repo_key
                    all_repos.append(repo)
                    logger.info(f"📚 Found via Search: {repo_key}")
        except Exception as e:
            logger.warning(f"Search API failed: {e}")
        
        logger.info(f"🎉 Repository discovery complete: {len(all_repos)} unique repositories found")
        return all_repos
    
    def _fetch_organization_repositories(self, include_private: bool = True) -> List[Dict[str, Any]]:
        """Fetch repositories from all user's organizations - CRITICAL method."""
        all_org_repos = []
        
        try:
            # Get user's organizations
            org_response = requests.get(f"{self.rest_url}/user/orgs", headers=self.headers)
            org_response.raise_for_status()
            organizations = org_response.json()
            
            logger.info(f"🏢 Found {len(organizations)} organizations")
            
            for org in organizations:
                org_name = org.get('login')
                logger.info(f"   Checking organization: {org_name}")
                
                try:
                    # Get repositories for this organization
                    org_repos_url = f"{self.rest_url}/orgs/{org_name}/repos"
                    params = {"per_page": 100, "type": "all"}
                    
                    page = 1
                    while page <= 10:  # Limit pages per org
                        params["page"] = page
                        
                        repo_response = requests.get(org_repos_url, headers=self.headers, params=params)
                        repo_response.raise_for_status()
                        org_repos = repo_response.json()
                        
                        if not org_repos:
                            break
                        
                        for repo in org_repos:
                            # Skip private repos if not requested
                            if repo.get("private", False) and not include_private:
                                continue
                            
                            # Convert to standard format
                            converted_repo = {
                                "name": repo.get("name"),
                                "owner": {
                                    "login": repo.get("owner", {}).get("login")
                                },
                                "isPrivate": repo.get("private", False),
                                "updatedAt": repo.get("updated_at"),
                                "createdAt": repo.get("created_at"),
                                "description": repo.get("description"),
                                "primaryLanguage": {
                                    "name": repo.get("language")
                                } if repo.get("language") else None,
                                "stargazerCount": repo.get("stargazers_count", 0),
                                "forkCount": repo.get("forks_count", 0)
                            }
                            all_org_repos.append(converted_repo)
                        
                        page += 1
                        if len(org_repos) < 100:  # Last page
                            break
                            
                except Exception as e:
                    logger.warning(f"Failed to fetch repos for organization {org_name}: {e}")
                    continue
                    
        except Exception as e:
            logger.warning(f"Failed to fetch organizations: {e}")
        
        logger.info(f"🏢 Organization discovery found {len(all_org_repos)} repositories")
        return all_org_repos
    
    def _fetch_repos_graphql_by_affiliation(self, affiliations: List[str], include_private: bool = True) -> List[Dict[str, Any]]:
        """Fetch repositories by specific affiliations."""
        privacy_filter = "" if include_private else "privacy: PUBLIC"
        affiliations_str = ", ".join(affiliations)
        
        query = f"""
        query($first: Int!, $cursor: String) {{
            viewer {{
                repositories(
                    first: $first,
                    after: $cursor,
                    orderBy: {{field: UPDATED_AT, direction: DESC}}
                    affiliations: [{affiliations_str}]
                    {privacy_filter}
                ) {{
                    nodes {{
                        name
                        owner {{
                            login
                        }}
                        isPrivate
                        updatedAt
                        createdAt
                        description
                        primaryLanguage {{
                            name
                        }}
                        stargazerCount
                        forkCount
                    }}
                    pageInfo {{
                        hasNextPage
                        endCursor
                    }}
                }}
            }}
        }}
        """
        
        all_repos = []
        variables = {"first": 100, "cursor": None}
        max_pages = 10
        page_count = 0
        
        while page_count < max_pages:
            data = self.execute_query(query, variables)
            if not data:
                break
            
            repos = data.get("data", {}).get("viewer", {}).get("repositories", {}).get("nodes", [])
            page_info = data.get("data", {}).get("viewer", {}).get("repositories", {}).get("pageInfo", {})
            
            if not repos:
                break
            
            all_repos.extend(repos)
            page_count += 1
            
            if not page_info.get("hasNextPage"):
                break
                
            variables["cursor"] = page_info["endCursor"]
        
        return all_repos
    
    def _fetch_repos_rest(self, include_private: bool = True) -> List[Dict[str, Any]]:
        """Fetch repositories using REST API."""
        url = f"{self.rest_url}/user/repos"
        repo_type = "all" if include_private else "public"
        
        all_repos = []
        page = 1
        max_pages = 20
        
        while page <= max_pages:
            params = {
                "per_page": 100,
                "type": repo_type,
                "sort": "updated",
                "affiliation": "owner,collaborator,organization_member",
                "page": page
            }
            
            try:
                response = requests.get(url, headers=self.headers, params=params)
                response.raise_for_status()
                repos = response.json()
                
                if not repos:
                    break
                
                # Convert to GraphQL-like format
                for repo in repos:
                    converted_repo = {
                        "name": repo.get("name"),
                        "owner": {
                            "login": repo.get("owner", {}).get("login")
                        },
                        "isPrivate": repo.get("private", False),
                        "updatedAt": repo.get("updated_at"),
                        "createdAt": repo.get("created_at"),
                        "description": repo.get("description"),
                        "primaryLanguage": {
                            "name": repo.get("language")
                        } if repo.get("language") else None,
                        "stargazerCount": repo.get("stargazers_count", 0),
                        "forkCount": repo.get("forks_count", 0)
                    }
                    all_repos.append(converted_repo)
                
                page += 1
                
                if len(repos) < 100:  # Last page
                    break
                    
            except Exception as e:
                logger.warning(f"REST API page {page} failed: {e}")
                break
        
        return all_repos
    
    def _search_user_repositories(self, include_private: bool = True) -> List[Dict[str, Any]]:
        """Search for user's repositories using Search API."""
        # Get current user first
        try:
            user_response = requests.get(f"{self.rest_url}/user", headers=self.headers)
            user_response.raise_for_status()
            username = user_response.json().get("login")
            
            if not username:
                return []
            
            # Search for repositories
            search_queries = [
                f"user:{username}",
                f"org:{username}",  # In case username is also an org
            ]
            
            all_repos = []
            
            for query in search_queries:
                url = f"{self.rest_url}/search/repositories"
                params = {
                    "q": query,
                    "per_page": 100,
                    "sort": "updated"
                }
                
                try:
                    response = requests.get(url, headers=self.headers, params=params)
                    response.raise_for_status()
                    data = response.json()
                    
                    for repo in data.get("items", []):
                        # Skip if private and not requested
                        if repo.get("private", False) and not include_private:
                            continue
                            
                        converted_repo = {
                            "name": repo.get("name"),
                            "owner": {
                                "login": repo.get("owner", {}).get("login")
                            },
                            "isPrivate": repo.get("private", False),
                            "updatedAt": repo.get("updated_at"),
                            "createdAt": repo.get("created_at"),
                            "description": repo.get("description"),
                            "primaryLanguage": {
                                "name": repo.get("language")
                            } if repo.get("language") else None,
                            "stargazerCount": repo.get("stargazers_count", 0),
                            "forkCount": repo.get("forks_count", 0)
                        }
                        all_repos.append(converted_repo)
                        
                except Exception as e:
                    logger.warning(f"Search query '{query}' failed: {e}")
            
            return all_repos
            
        except Exception as e:
            logger.warning(f"Search repositories failed: {e}")
            return []

    def fetch_global_user_activity(self, user_email: str, months_back: int = 6) -> Dict[str, Any]:
        """Fetch global user activity across all accessible repositories using enhanced discovery"""
        try:
            # Calculate date range
            end_date = datetime.now()
            start_date = end_date - timedelta(days=months_back * 30)
            
            # First, get user info to extract username
            user_info = self.get_authenticated_user()
            if not user_info:
                return {"error": "Failed to get user info"}
            
            username = user_info.get("login")
            if not username:
                return {"error": "Failed to get username"}
            
            # Use enhanced repository discovery instead of basic fetch
            logger.info("🔍 Using enhanced repository discovery for global activity...")
            repositories = self.discover_all_accessible_repositories(include_private=True)
            if not repositories:
                logger.warning("Enhanced discovery found no repos, trying basic fallback...")
                repositories = self.fetch_user_repositories(limit=100, include_private=True)
            
            if not repositories:
                return {"error": "No repositories found"}
            
            logger.info(f"🎯 Analyzing activity across {len(repositories)} repositories")
            
            all_commits = []
            all_prs = []
            
            # Fetch data from each repository (NO TIME LIMIT by default)
            for repo in repositories:
                try:
                    owner = repo.get("owner", {}).get("login", "")
                    name = repo.get("name", "")
                    
                    if not owner or not name:
                        continue
                    
                    # Fetch ALL-TIME commits and PRs (unless months_back specifically requested)
                    days_back_param = months_back * 30 if months_back < 12 else None  # Only limit if < 1 year
                    
                    # Fetch commits for this repo
                    repo_commits = self.fetch_commits(owner, name, developer_email=user_email, days_back=days_back_param)
                    if repo_commits:
                        # Add repository info to each commit
                        for commit in repo_commits:
                            commit["repository"] = f"{owner}/{name}"
                        all_commits.extend(repo_commits)
                    
                    # Fetch PRs for this repo
                    repo_prs = self.fetch_pull_requests(owner, name, developer_email=user_email, days_back=days_back_param)
                    if repo_prs:
                        # Add repository info to each PR
                        for pr in repo_prs:
                            pr["repository"] = f"{owner}/{name}"
                        all_prs.extend(repo_prs)
                        
                except Exception as e:
                    logger.warning(f"Failed to fetch data for {owner}/{name}: {str(e)}")
                    continue
            
            logger.info(f"🎉 Global activity: {len(all_commits)} commits + {len(all_prs)} PRs across {len(repositories)} repos")
            
            return {
                "commits": all_commits,
                "pull_requests": all_prs,
                "repositories": repositories,
                "user_info": user_info,
                "date_range": {
                    "start": start_date.isoformat(),
                    "end": end_date.isoformat()
                }
            }
        except Exception as e:
            logger.error(f"Error fetching global user activity: {str(e)}")
            return {"error": str(e)}

    def get_authenticated_user(self) -> Optional[Dict[str, Any]]:
        """Get authenticated user information"""
        try:
            url = f"{self.rest_url}/user"
            response = requests.get(url, headers=self.headers)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching user info: {str(e)}")
            return None
