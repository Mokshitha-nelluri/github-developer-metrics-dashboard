#!/usr/bin/env python3
"""
Simple HTTP server to serve the auth.html file for GitHub OAuth
Run this alongside your Streamlit app for authentication.
"""

import http.server
import socketserver
import os
import threading
from pathlib import Path

class AuthHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        # Change to the project root directory to serve files
        super().__init__(*args, directory=os.path.dirname(__file__), **kwargs)
    
    def end_headers(self):
        # Add CORS headers
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        super().end_headers()
    
    def do_GET(self):
        """Handle GET requests with enhanced logging and error handling"""
        try:
            # Log the request for debugging
            print(f"📥 Auth server request: {self.path}")
            
            # Handle specific paths
            if self.path == '/auth/logout' or self.path.startswith('/auth/logout?'):
                # Redirect logout requests to auth.html with logout parameter
                self.send_response(302)
                self.send_header('Location', '/public/auth.html?logout=true')
                self.end_headers()
                return
            
            # Default handling for other requests
            super().do_GET()
            
        except Exception as e:
            print(f"❌ Auth server error handling request {self.path}: {e}")
            self.send_error(500, f"Internal server error: {e}")
    
    def log_message(self, format, *args):
        """Override to provide cleaner logging"""
        print(f"🔐 Auth server: {format % args}")

def start_auth_server(port=8502):
    """Start the authentication server in a separate thread"""
    try:
        with socketserver.TCPServer(("", port), AuthHTTPRequestHandler) as httpd:
            print(f"🔐 Auth server running at http://localhost:{port}")
            print(f"📄 Auth page: http://localhost:{port}/public/auth.html")
            httpd.serve_forever()
    except Exception as e:
        print(f"❌ Failed to start auth server: {e}")

def start_auth_server_background(port=8502):
    """Start auth server in background thread"""
    thread = threading.Thread(target=start_auth_server, args=(port,), daemon=True)
    thread.start()
    return thread

if __name__ == "__main__":
    import sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8502
    print(f"Starting auth server on port {port}...")
    start_auth_server(port)
