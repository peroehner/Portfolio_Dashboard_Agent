"""Notebook-friendly deployment entry point.

Run from the repo root after cloning:
    %cd Portfolio_Dashboard_Agent
    %run deploy.py

Or from shell:
    python deploy.py
"""
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
os.chdir(REPO_ROOT)
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

print(f"Repo root: {REPO_ROOT}")

requirements = REPO_ROOT / "requirements.txt"
if requirements.is_file():
    print("Installing dependencies...")
    subprocess.check_call(
        [sys.executable, "-m", "pip", "install", "-q", "-r", str(requirements), "pyngrok"]
    )

try:
    from main import start_server
except ImportError as exc:
    main_file = REPO_ROOT / "main.py"
    has_start_server = (
        main_file.is_file() and "def start_server" in main_file.read_text(encoding="utf-8")
    )
    print(f"main.py found: {main_file.is_file()}")
    print(f"start_server defined in main.py: {has_start_server}")
    if not has_start_server:
        print("Your copy of main.py is outdated. Run: git pull")
    raise exc

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
