#!/usr/bin/env python3
"""
OAuth Callback Server for GitHub Metrics
Handles GitHub OAuth callbacks and redirects back to Streamlit
"""

import http.server
import socketserver
import urllib.parse
import webbrowser
import logging
import threading
import time
import os
import requests
from typing import Optional

logger = logging.getLogger(__name__)

class OAuthCallbackHandler(http.server.SimpleHTTPRequestHandler):
    """Handle OAuth callback requests"""
    
    def get_streamlit_redirect_url(self, code: str, state: str) -> str:
        """Get stable Streamlit redirect URL for OAuth callback"""
        # Use environment variable for production stability
        base_url = os.getenv("STREAMLIT_BASE_URL")
        
        if not base_url:
            # Use fixed production URL or localhost for development
            is_aws_deployment = os.getenv("AWS_DEPLOYMENT", "true").lower() == "true"
            if is_aws_deployment:
                # Use the fixed production URL - update this to match your actual domain/IP
                base_url = os.getenv("AWS_STREAMLIT_URL", "http://44.199.213.241:8501")
            else:
                base_url = "http://localhost:8501"
        
        return f"{base_url}?code={code}&state={state}"
    
    def do_GET(self):
        """Handle GET requests for OAuth callback"""
        try:
            # Parse the URL and query parameters
            parsed_url = urllib.parse.urlparse(self.path)
            query_params = urllib.parse.parse_qs(parsed_url.query)
            
            if parsed_url.path == "/auth/callback":
                # This is the OAuth callback
                code = query_params.get('code', [None])[0]
                state = query_params.get('state', [None])[0]
                error = query_params.get('error', [None])[0]
                
                if error:
                    logger.error(f"OAuth error: {error}")
                    self.send_error_response(f"Authentication error: {error}")
                    return
                
                if not code:
                    logger.error("No authorization code received")
                    self.send_error_response("No authorization code received")
                    return
                
                # Success! Create redirect URL to Streamlit with the code
                streamlit_url = self.get_streamlit_redirect_url(code, state)
                
                # Send redirect response
                self.send_response(302)
                self.send_header('Location', streamlit_url)
                self.end_headers()
                
                logger.info(f"OAuth callback successful, redirecting to Streamlit with code: {code[:10]}...")
                
            else:
                # Serve static files (like success page)
                super().do_GET()
                
        except Exception as e:
            logger.error(f"Error handling OAuth callback: {e}")
            self.send_error_response("Internal server error")
    
    def send_error_response(self, message: str):
        """Send an error response"""
        self.send_response(400)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        
        # Get the stable Streamlit URL for the back link
        is_aws_deployment = os.getenv("AWS_DEPLOYMENT", "true").lower() == "true"
        if is_aws_deployment:
            back_url = os.getenv("AWS_STREAMLIT_URL", "http://44.199.213.241:8501")
        else:
            back_url = "http://localhost:8501"
        
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Authentication Error</title>
            <style>
                body {{ 
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                    background: #f8f9fa;
                    margin: 0;
                    padding: 2rem;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    min-height: 100vh;
                }}
                .container {{
                    background: white;
                    padding: 2rem;
                    border-radius: 8px;
                    box-shadow: 0 2px 10px rgba(0,0,0,0.1);
                    text-align: center;
                    max-width: 500px;
                }}
                .error {{ color: #dc3545; }}
                .retry-btn {{
                    background: #007bff;
                    color: white;
                    border: none;
                    padding: 10px 20px;
                    border-radius: 4px;
                    text-decoration: none;
                    display: inline-block;
                    margin-top: 1rem;
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <h2 class="error">Authentication Failed</h2>
                <p>{message}</p>
                <a href="{back_url}" class="retry-btn">← Back to Dashboard</a>
            </div>
        </body>
        </html>
        """
        
        self.wfile.write(html_content.encode())
    
    def log_message(self, format, *args):
        """Override to use our logger"""
        logger.info(f"OAuth Server: {format % args}")

class OAuthCallbackServer:
    """OAuth callback server manager"""
    
    def __init__(self, port: int = 5000):
        self.port = port
        self.server = None
        self.server_thread = None
    
    def start(self) -> bool:
        """Start the OAuth callback server"""
        try:
            # In AWS deployment, bind to all interfaces; in development, bind to localhost
            is_aws_deployment = os.getenv("AWS_DEPLOYMENT", "true").lower() == "true"
            host = "0.0.0.0" if is_aws_deployment else "localhost"
            
            self.server = socketserver.TCPServer((host, self.port), OAuthCallbackHandler)
            self.server_thread = threading.Thread(target=self.server.serve_forever, daemon=True)
            self.server_thread.start()
            logger.info(f"OAuth callback server started on http://{host}:{self.port}")
            return True
        except Exception as e:
            logger.error(f"Failed to start OAuth callback server: {e}")
            return False
    
    def stop(self):
        """Stop the OAuth callback server"""
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            logger.info("OAuth callback server stopped")

# Global server instance
_oauth_server: Optional[OAuthCallbackServer] = None

def start_oauth_server(port: int = 5000) -> bool:
    """Start the OAuth callback server"""
    global _oauth_server
    
    if _oauth_server is None:
        _oauth_server = OAuthCallbackServer(port)
        return _oauth_server.start()
    return True

def stop_oauth_server():
    """Stop the OAuth callback server"""
    global _oauth_server
    
    if _oauth_server:
        _oauth_server.stop()
        _oauth_server = None

if __name__ == "__main__":
    # Test the server
    logging.basicConfig(level=logging.INFO)
    
    print("Starting OAuth callback server on http://localhost:5000")
    if start_oauth_server():
        print("Server started! Visit http://localhost:5000/auth/callback?code=test to test")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nShutting down...")
            stop_oauth_server()
    else:
        print("Failed to start server")
