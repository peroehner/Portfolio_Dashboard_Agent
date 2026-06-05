"""Notebook-friendly deployment entry point.

Preferred in Colab (works even if shell cwd is broken):
    import runpy
    runpy.run_path("/content/Portfolio_Dashboard_Agent/deploy.py", run_name="__main__")

Or use colab_bootstrap.py to clone + deploy in one step.
"""
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

SAFE_CWD = Path("/content")

try:
    os.getcwd()
except OSError:
    os.chdir(SAFE_CWD)

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


def clean_token(token):
    """Remove hidden newlines/spaces often pasted into Colab Secrets."""
    return "".join(str(token).split())


def get_ngrok_authtoken():
    """Read ngrok token from env or Colab Secrets; ignore placeholders."""
    token = clean_token(os.environ.get("NGROK_AUTHTOKEN", ""))
    if not token:
        try:
            from google.colab import userdata
            token = clean_token(userdata.get("NGROK_AUTHTOKEN"))
        except Exception:
            pass

    invalid = {"", "your_token_here", "token", "none", "null", "placeholder"}
    if token.lower() in invalid or len(token) < 20:
        return None
    return token


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

def verify_public_tunnel(public_url):
    """Confirm ngrok can reach Flask through the tunnel."""
    import urllib.error
    import urllib.request

    req = urllib.request.Request(
        f"{public_url}/health",
        headers={"ngrok-skip-browser-warning": "true"},
    )
    with urllib.request.urlopen(req, timeout=10) as response:
        body = response.read().decode()
        print(f"Tunnel verify ({response.status}): {body}")


authtoken = get_ngrok_authtoken()
if authtoken:
    try:
        from pyngrok import ngrok

        print(f"Ngrok token loaded ({len(authtoken)} chars, ends with ...{authtoken[-4:]})")
        ngrok.kill()
        ngrok.set_auth_token(authtoken)
        tunnel = ngrok.connect(PORT, bind_tls=True)
        public_url = str(tunnel.public_url)
        print(f"Public URL: {public_url}")
        print(f"Health check: {public_url}/health")
        verify_public_tunnel(public_url)
        print("Browser tip: on first visit ngrok shows a warning page — click 'Visit Site'.")
    except Exception as exc:
        print("Ngrok tunnel failed; Flask is still running locally.")
        print(f"Local health check: http://127.0.0.1:{PORT}/health")
        print(f"Error: {exc}")
        print("Use an authtoken from https://dashboard.ngrok.com/get-started/your-authtoken")
        print("Do not use an API key. Re-save the Colab Secret with no spaces or line breaks.")
else:
    print("NGROK_AUTHTOKEN not set or still a placeholder.")
    print("Colab: add NGROK_AUTHTOKEN in Secrets (key icon), then rerun.")
    print(f"Flask is running locally at http://127.0.0.1:{PORT}/health")
