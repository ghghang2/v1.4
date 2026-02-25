#!/usr/bin/env python3
"""
run.py – Start llama-server and provide simple status/stop helpers.

Usage
-----
    python run.py          # start everything
    python run.py --status # inspect current state
    python run.py --stop   # terminate all services
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import psutil

# --------------------------------------------------------------------------- #
#  Constants
# --------------------------------------------------------------------------- #
SERVICE_INFO  = Path("service_info.json")
LLAMA_LOG     = Path("llama_server.log")
REPO          = "ghghang2/llamacpp_t4_v1"
# Q4_K_M (~12 GB) fits entirely in T4 VRAM — no CPU offload, maximum TPS.
# Switch to Q8_0 (~21 GB) only if output quality is insufficient (will require partial CPU offload).
MODEL         = "unsloth/gpt-oss-20b-GGUF:F16"
PORT          = 8000
N_PARALLEL    = 1      # matches 1-2 simultaneous users; fewer slots = faster per-request TPS
CTX_SIZE      = 40000  # tokens per slot; total KV mem ≈ CTX_SIZE * N_PARALLEL * layers. 32K fits within T4 headroom at Q4_K_M + N_PARALLEL=2
N_GPU_LAYERS  = 999    # offload all layers to GPU (llama.cpp clamps to actual layer count)


# --------------------------------------------------------------------------- #
#  Helpers
# --------------------------------------------------------------------------- #
def _run(cmd: str, *, extra_env: dict | None = None) -> None:
    """Run a shell command, optionally merging extra environment variables."""
    env = {**os.environ, **(extra_env or {})}
    subprocess.run(cmd, shell=True, env=env, check=True)


def _is_port_free(port: int) -> bool:
    result = subprocess.run(["ss", "-tuln"], capture_output=True, text=True)
    return str(port) not in result.stdout


def _wait_for(url: str, *, timeout: int = 360, interval: float = 1.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=5) as r:
                if r.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(interval)
    return False


def _save_service_info(pid: int) -> None:
    SERVICE_INFO.write_text(json.dumps({
        "llama_server_pid": pid,
        "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }, indent=2))


def _load_service_info() -> dict:
    if not SERVICE_INFO.exists():
        raise FileNotFoundError("No service_info.json found – are the services running?")
    return json.loads(SERVICE_INFO.read_text())


def _kill_pid(name: str, pid: int) -> None:
    """Gracefully terminate a process and its children."""
    try:
        proc = psutil.Process(pid)
        for child in proc.children(recursive=True):
            child.terminate()
        proc.terminate()
        print(f"{name} (PID {pid}) stopped")
    except psutil.NoSuchProcess:
        print(f"{name} (PID {pid}) was not running")
    except Exception as exc:
        print(f"Error stopping {name} (PID {pid}): {exc}")


# --------------------------------------------------------------------------- #
#  Commands
# --------------------------------------------------------------------------- #
def main() -> None:
    if not os.getenv("GITHUB_TOKEN"):
        sys.exit("[ERROR] GITHUB_TOKEN must be set")

    if not _is_port_free(PORT):
        sys.exit(f"[ERROR] Port {PORT} is already in use")

    # Download pre-built llama-server binary
    _run(
        f"gh release download --repo {REPO} --pattern llama-server --skip-existing",
        extra_env={"GITHUB_TOKEN": os.environ["GITHUB_TOKEN"]},
    )
    _run("chmod +x ./llama-server")

    # Start llama-server fully detached — stdin from /dev/null, close_fds=True,
    # and parent closes its file handle immediately after Popen returns.
    # This ensures the notebook shell has no open fd tying it to the child process.
    log_file = LLAMA_LOG.open("w", encoding="utf-8", buffering=1)
    with open(os.devnull, "r") as devnull:
        llama_proc = subprocess.Popen(
            [
                "./llama-server",
                "-hf",            MODEL,
                "--port",         str(PORT),
                "--parallel",     str(N_PARALLEL),
                "--ctx-size",     str(CTX_SIZE),
                "--n-gpu-layers", str(N_GPU_LAYERS),
                "--flash-attn", "1",
                "--mlock",
                "--metrics",
            ],
            stdin=devnull,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            close_fds=True,
        )
    log_file.close()  # parent closes its copy; child retains its own fd

    print(f"llama-server started (PID: {llama_proc.pid}) – waiting for health…")
    if not _wait_for(f"http://localhost:{PORT}/health"):
        llama_proc.terminate()
        sys.exit("[ERROR] llama-server failed to start within timeout")

    # Install Python dependencies
    print("Installing Python dependencies…")
    _run("pip install -r requirements.txt -qqq")

    # Install Playwright + system deps
    print("Installing Playwright dependencies…")
    _run("sudo apt-get update -qq")
    _run("sudo apt-get install -y libxcomposite1 libgtk-3-0 libatk1.0-0")
    _run("playwright install --with-deps firefox")

    _save_service_info(llama_proc.pid)
    print("\nALL SERVICES RUNNING SUCCESSFULLY!")
    print("=" * 60)
    os._exit(0)  # Hard-exit so the notebook cell stops immediately


def status() -> None:
    try:
        info = _load_service_info()
    except FileNotFoundError as exc:
        print(exc)
        return

    pid = info["llama_server_pid"]
    alive = psutil.pid_exists(pid)
    print("=" * 60)
    print(f"Started at : {info['started_at']}")
    print(f"llama-server PID {pid}: {'running' if alive else 'NOT running'}")
    print("=" * 60)


def stop() -> None:
    try:
        info = _load_service_info()
    except FileNotFoundError:
        print("No service_info.json – nothing to stop")
        return

    print("Stopping services…")
    _kill_pid("llama-server", info["llama_server_pid"])
    time.sleep(1)

    SERVICE_INFO.unlink(missing_ok=True)
    print("Cleaned up service info")


# --------------------------------------------------------------------------- #
#  Entry point
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    commands = {"--status": status, "--stop": stop}
    if len(sys.argv) == 1:
        main()
    elif sys.argv[1] in commands:
        commands[sys.argv[1]]()
    else:
        print(f"Unknown command: {sys.argv[1]}")
        print("Usage: python run.py [--status | --stop]")
        sys.exit(1)