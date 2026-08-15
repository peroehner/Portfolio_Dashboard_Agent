"""Runtime deploy fingerprint for About / health (local vs Render)."""

from __future__ import annotations

import os
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Any


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in ("1", "true", "yes", "on")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _git_output(*args: str) -> str | None:
    try:
        out = subprocess.check_output(
            ["git", *args],
            cwd=_repo_root(),
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        return out or None
    except Exception:
        return None


def _env_commit() -> str | None:
    for key in ("BUILD_SHA", "RENDER_GIT_COMMIT", "GIT_COMMIT"):
        val = (os.environ.get(key) or "").strip()
        if val:
            return val
    return None


@lru_cache(maxsize=1)
def deploy_fingerprint() -> dict[str, Any]:
    """Stable build identity for About panels and /health.

    Match clients to a server by comparing ``build`` (short git SHA) and
    ``environment`` / ``host``. On Render, also compare ``serviceId`` with the
    service id shown in the Render dashboard (``srv-…``). Render's UI may also
    show separate deploy/build codes that are not injected into the runtime
    environment — the git SHA is the reliable cross-check.
    """
    on_render = _truthy(os.environ.get("RENDER"))
    commit = _env_commit() or _git_output("rev-parse", "HEAD")
    short = (commit[:12] if commit else None) or _git_output("rev-parse", "--short", "HEAD")
    branch = (os.environ.get("RENDER_GIT_BRANCH") or "").strip() or _git_output(
        "rev-parse", "--abbrev-ref", "HEAD"
    )
    host = (os.environ.get("RENDER_EXTERNAL_HOSTNAME") or "").strip() or None
    if not host and not on_render:
        host = "localhost"
    service_id = (os.environ.get("RENDER_SERVICE_ID") or "").strip() or None
    service_name = (os.environ.get("RENDER_SERVICE_NAME") or "").strip() or None
    instance_id = (os.environ.get("RENDER_INSTANCE_ID") or "").strip() or None
    environment = "render" if on_render else "local"

    label_parts = [p for p in (short, environment) if p]
    if service_id:
        # Last segment is often what people glance at in Render URLs.
        label_parts.append(service_id.split("-")[-1][:8] if "-" in service_id else service_id[-8:])

    return {
        "appVersion": "1.0",
        "environment": environment,
        "build": short,
        "gitCommit": commit or short,
        "gitBranch": branch,
        "host": host,
        "serviceId": service_id,
        "serviceName": service_name,
        "instanceId": instance_id,
        "label": " · ".join(label_parts) if label_parts else environment,
    }
