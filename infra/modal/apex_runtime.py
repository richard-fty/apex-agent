from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import tomllib

import modal


if modal.is_local():
    REPO_ROOT = Path(__file__).resolve().parents[2]
    PI_ROOT = REPO_ROOT / ".pi"
else:
    # Modal imports this module again inside the built image. There the
    # entrypoint is /root/apex_runtime.py and the copied Pi files are in /app.
    REPO_ROOT = Path("/app")
    PI_ROOT = Path("/app/.pi")
APP_NAME = "apex-pi-runtime"
WORKSPACE_VOLUME_NAME = "apex-workspace"


def _read_optional(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


def _local_runtime_secret() -> modal.Secret:
    if not modal.is_local():
        return modal.Secret.from_dict({})
    modal_config = Path.home() / ".modal.toml"
    profile_name = os.getenv("MODAL_PROFILE", "richardye980718")
    profiles = tomllib.loads(modal_config.read_text(encoding="utf-8"))
    profile = profiles.get(profile_name)
    if not isinstance(profile, dict):
        active_profiles = [
            value
            for value in profiles.values()
            if isinstance(value, dict) and value.get("active") is True
        ]
        if len(active_profiles) != 1:
            raise RuntimeError(f"Unable to resolve active Modal profile {profile_name!r}")
        profile = active_profiles[0]
    token_id = str(profile["token_id"])
    token_secret = str(profile["token_secret"])
    runtime_token = hashlib.sha256(
        f"apex-pi-runtime-v1:{token_secret}".encode("utf-8"),
    ).hexdigest()
    values = {
        "APEX_MODAL_TOKEN_ID": token_id,
        "APEX_MODAL_TOKEN_SECRET": token_secret,
        "APEX_RUNTIME_TOKEN": runtime_token,
        "APEX_PI_AUTH_JSON": _read_optional(Path.home() / ".pi" / "agent" / "auth.json"),
        "APEX_PI_MODELS_JSON": _read_optional(Path.home() / ".pi" / "agent" / "models.json"),
    }
    return modal.Secret.from_dict(values)


runtime_secret = _local_runtime_secret()
workspace_volume = modal.Volume.from_name(
    WORKSPACE_VOLUME_NAME,
    create_if_missing=True,
)

pi_image = (
    modal.Image.from_registry("node:24-bookworm-slim", add_python="3.13")
    .apt_install("bash", "ca-certificates", "curl", "ffmpeg", "git", "ripgrep")
    .add_local_file(PI_ROOT / "package.json", "/app/.pi/package.json", copy=True)
    .run_commands("cd /app/.pi && npm install --omit=dev")
    .add_local_file(PI_ROOT / "SYSTEM.md", "/app/.pi/SYSTEM.md", copy=True)
    .add_local_dir(PI_ROOT / "extensions", "/app/.pi/extensions", copy=True)
    .add_local_dir(PI_ROOT / "skills", "/app/.pi/skills", copy=True)
    .add_local_dir(PI_ROOT / "remote", "/app/.pi/remote", copy=True)
    .add_local_dir(PI_ROOT / "modal", "/app/.pi/modal", copy=True)
    .run_commands("mkdir -p /workspace")
)

app = modal.App(APP_NAME)


@app.function(
    image=pi_image,
    secrets=[runtime_secret],
    volumes={"/workspace": workspace_volume},
    cpu=0.125,
    memory=(512, 1024),
    timeout=3600,
    min_containers=0,
    max_containers=1,
    scaledown_window=60,
)
@modal.web_server(8788, startup_timeout=60)
def pi_runtime() -> None:
    common_env = os.environ.copy()
    common_env.update(
        {
            "APEX_REMOTE_RUNTIME_PORT": "8788",
            "APEX_SANDBOX_BROKER_PORT": "8790",
            "APEX_SANDBOX_BROKER_URL": "http://127.0.0.1:8790",
            "APEX_REMOTE_WORKSPACE": "/workspace",
            "APEX_SANDBOX_APP_NAME": "apex-sandbox",
            "APEX_WORKSPACE_VOLUME": WORKSPACE_VOLUME_NAME,
            "APEX_SANDBOX_TIMEOUT_SECONDS": "600",
            "APEX_SANDBOX_IDLE_TIMEOUT_SECONDS": "180",
            "APEX_SANDBOX_CPU": "0.5",
            "APEX_SANDBOX_CPU_LIMIT": "1.0",
            "APEX_SANDBOX_MEMORY_MB": "512",
            "APEX_SANDBOX_MEMORY_LIMIT_MB": "1024",
        },
    )
    subprocess.Popen(
        ["python3", "/app/.pi/modal/sandbox_broker.py"],
        env=common_env,
    )
    node_env = {
        key: value
        for key, value in common_env.items()
        if key not in {"APEX_MODAL_TOKEN_ID", "APEX_MODAL_TOKEN_SECRET"}
    }
    subprocess.Popen(
        [
            "node",
            "--experimental-strip-types",
            "/app/.pi/remote/runtime-server.ts",
        ],
        cwd="/workspace",
        env=node_env,
    )
