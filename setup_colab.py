"""One-time Colab setup: clone the repo to a flat /content path.

Run this in a fresh Colab session before deploy.py:
    %run setup_colab.py
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_URL = "https://github.com/peroehner/Portfolio_Dashboard_Agent.git"
SAFE_CWD = Path("/content")
TARGET = SAFE_CWD / "Portfolio_Dashboard_Agent"
NESTED = TARGET / "Portfolio_Dashboard_Agent"


def ensure_safe_cwd() -> None:
    """Recover when the notebook shell cwd was deleted by rm -rf."""
    try:
        os.getcwd()
    except OSError:
        pass
    os.chdir(SAFE_CWD)


def run_git_clone(destination: Path) -> None:
    subprocess.check_call(
        ["git", "clone", REPO_URL, str(destination)],
        cwd=str(SAFE_CWD),
    )


ensure_safe_cwd()

if NESTED.is_dir() and (NESTED / "main.py").is_file():
    print("Flattening double-nested clone...")
    shutil.rmtree(TARGET)
    run_git_clone(TARGET)
elif TARGET.is_dir() and (TARGET / "main.py").is_file():
    print("Repo already present; pulling latest changes...")
    subprocess.check_call(["git", "-C", str(TARGET), "pull"])
elif TARGET.is_dir():
    print("Broken repo folder found; recloning...")
    shutil.rmtree(TARGET)
    run_git_clone(TARGET)
else:
    print("Cloning repo...")
    run_git_clone(TARGET)

os.chdir(TARGET)
if str(TARGET) not in sys.path:
    sys.path.insert(0, str(TARGET))

print(f"Ready at: {TARGET}")
print("Next: set NGROK_AUTHTOKEN, then launch deploy with:")
print('  import runpy')
print(f'  runpy.run_path("{TARGET / "deploy.py"}", run_name="__main__")')
