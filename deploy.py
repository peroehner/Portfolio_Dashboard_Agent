"""Notebook-friendly deployment entry point.

Run from the repo root after cloning:
    %cd Portfolio_Dashboard_Agent
    %run deploy.py

Or from shell:
    python deploy.py
"""
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
os.chdir(REPO_ROOT)
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from main import start_server

PORT = int(os.environ.get("PORT", 5000))
health_url = start_server(port=PORT, block=False)
print(f"Local health check: {health_url}")

authtoken = os.environ.get("NGROK_AUTHTOKEN", "").strip()
if authtoken:
    from pyngrok import ngrok

    ngrok.set_auth_token(authtoken)
    public_url = ngrok.connect(PORT)
    print(f"Public URL: {public_url}")
    print(f"Health check: {public_url}/health")
else:
    print("NGROK_AUTHTOKEN not set; Flask is running locally only.")
