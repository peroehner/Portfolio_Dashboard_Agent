"""Notebook-friendly deployment entry point.

Clean Colab setup (run once):
    %run setup_colab.py

Deploy:
    %cd /content/Portfolio_Dashboard_Agent
    %run deploy.py
"""
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
PARENT_ROOT = REPO_ROOT.parent
PARENT_MAIN = PARENT_ROOT / "main.py"


def load_start_server():
    """Import start_server from this repo's main.py, not a stale parent copy."""
    if PARENT_MAIN.is_file() and PARENT_MAIN != REPO_ROOT / "main.py":
        print("WARNING: double-nested clone detected.")
        print(f"  Active repo: {REPO_ROOT}")
        print(f"  Stale copy:  {PARENT_MAIN}")
        print("Run setup_colab.py once to flatten, or: rm -rf /content/Portfolio_Dashboard_Agent && git clone ...")

    parent_dir = str(PARENT_ROOT)
    if parent_dir in sys.path:
        sys.path.remove(parent_dir)

    sys.modules.pop("main", None)
    os.chdir(REPO_ROOT)
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))

    main_path = REPO_ROOT / "main.py"
    if not main_path.is_file():
        raise FileNotFoundError(f"main.py not found at {main_path}")

    spec = importlib.util.spec_from_file_location("pda_main", main_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load module spec for {main_path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    if not hasattr(module, "start_server"):
        raise ImportError(
            f"start_server missing in {main_path}. Run: git pull"
        )

    return module.start_server


print(f"Repo root: {REPO_ROOT}")

requirements = REPO_ROOT / "requirements.txt"
if requirements.is_file():
    print("Installing dependencies...")
    subprocess.check_call(
        [sys.executable, "-m", "pip", "install", "-q", "-r", str(requirements), "pyngrok"]
    )

start_server = load_start_server()

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
