"""Single Colab entry point — safe when shell cwd is broken.

Paste into one cell (no %run, no %cd required):

    # 1) Colab sidebar -> Secrets -> add NGROK_AUTHTOKEN (real token from ngrok dashboard)
    # 2) Run:
    import urllib.request, runpy
    urllib.request.urlretrieve(
        "https://raw.githubusercontent.com/peroehner/Portfolio_Dashboard_Agent/main/colab_bootstrap.py",
        "/content/colab_bootstrap.py",
    )
    runpy.run_path("/content/colab_bootstrap.py", run_name="__main__")
"""
import os
import runpy
import shutil
import subprocess
import sys
from pathlib import Path

SAFE_CWD = Path("/content")
TARGET = SAFE_CWD / "Portfolio_Dashboard_Agent"
REPO_URL = "https://github.com/peroehner/Portfolio_Dashboard_Agent.git"
DEPLOY_SCRIPT = TARGET / "deploy.py"


def ensure_safe_cwd() -> None:
    try:
        os.getcwd()
    except OSError:
        pass
    os.chdir(SAFE_CWD)


ensure_safe_cwd()

if not DEPLOY_SCRIPT.is_file():
    print("Cloning repo...")
    if TARGET.exists():
        shutil.rmtree(TARGET)
    subprocess.check_call(
        ["git", "clone", REPO_URL, str(TARGET)],
        cwd=str(SAFE_CWD),
    )
else:
    print("Updating repo...")
    subprocess.check_call(["git", "-C", str(TARGET), "pull"])

print(f"Launching deploy.py from {DEPLOY_SCRIPT}")
runpy.run_path(str(DEPLOY_SCRIPT), run_name="__main__")
