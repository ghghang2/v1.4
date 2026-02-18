#!/usr/bin/env python3
"""
run.py –  Start the llama‑server + Streamlit UI + ngrok tunnel
and provide simple status/stop helpers.

Typical usage
-------------
    python run.py          # start everything
    python run.py --status # inspect current state
    python run.py --stop   # terminate all services
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Iterable
import psutil

# --------------------------------------------------------------------------- #
#  Constants & helpers
# --------------------------------------------------------------------------- #
SERVICE_INFO = Path("service_info.json")
# NGROK_LOG = Path("ngrok.log")
# STREAMLIT_LOG = Path("streamlit.log")
LLAMA_LOG = Path("llama_server.log")
REPO = "ghghang2/llamacpp_t4_v1"          # repo containing the pre‑built binary
MODEL = "unsloth/gpt-oss-20b-GGUF:F16"   # model used by llama‑server

# Ports used by the services
PORTS = (4040, 8000, 8002)

def _run(cmd: Iterable[str] | str, *, shell: bool = False,
          cwd: Path | None = None, capture: bool = False,
          env: dict | None = None) -> str | None:
    """Convenience wrapper around subprocess.run."""
    env = env or os.environ.copy()
    result = subprocess.run(
        cmd,
        shell=shell,
        cwd=cwd,
        env=env,
        check=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.STDOUT,
        text=True,
    )
    return result.stdout.strip() if capture else None

def _is_port_free(port: int) -> bool:
    """Return True if the port is not currently bound."""
    with subprocess.Popen(["ss", "-tuln"], stdout=subprocess.PIPE) as p:
        return str(port) not in p.stdout.read().decode()

def _wait_for(url: str, *, timeout: int = 30, interval: float = 1.0) -> bool:
    """Poll a URL until it returns 200 or timeout expires."""
    for _ in range(int(timeout / interval)):
        try:
            with urllib.request.urlopen(url, timeout=5) as r:
                return r.status == 200
        except Exception:
            pass
        time.sleep(interval)
    return False

# def _save_service_info(tunnel_url: str, llama: int, streamlit: int, ngrok: int) -> None:
#     """Persist the running process IDs and the public tunnel URL."""
#     data = {
#         "tunnel_url": tunnel_url,
#         "llama_server_pid": llama,
#         "streamlit_pid": streamlit,
#         "ngrok_pid": ngrok,
#         "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
#     }
#     SERVICE_INFO.write_text(json.dumps(data, indent=2))
#     Path("tunnel_url.txt").write_text(tunnel_url)

# --------------------------------------------------------------------------- #
#  Core logic – start the services
# --------------------------------------------------------------------------- #
def main() -> None:
    """Start all services and record their state."""
    # ---   Validate environment -----------------------------------------
    if not os.getenv("GITHUB_TOKEN"):
        sys.exit("[ERROR] GITHUB_TOKEN must be set")

    # ---  Ensure ports are free ----------------------------------------
    for p in PORTS:
        if not _is_port_free(p):
            sys.exit(f"[ERROR] Port {p} is already in use")

    # ---  Download the pre‑built llama‑server -------------------------
    _run(
        f"gh release download --repo {REPO} --pattern llama-server --skip-existing",
        shell=True,
        env={"GITHUB_TOKEN": os.getenv("GITHUB_TOKEN")},
    )
    _run("chmod +x ./llama-server", shell=True)

    # ---  Start llama‑server ------------------------------------------
    LLAMA_LOG_file = LLAMA_LOG.open("w", encoding="utf-8", buffering=1)
    llama_proc = subprocess.Popen(
            ["./llama-server", "-hf", MODEL, "--port", "8000", "--metrics"],#, "--chat-template-kwargs", '{"reasoning_effort":"high"}'
        stdout=LLAMA_LOG_file,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    print(f"llama-server started (PID: {llama_proc.pid}) – waiting…")
    if not _wait_for("http://localhost:8000/health", timeout=360):
        llama_proc.terminate()
        sys.exit("[ERROR] llama-server failed to start")

    # --- Install required packages ----------------------------
    print("Installing dependencies…")
    _run("pip install -r requirements.txt -qqq", shell=True)
    #    Install Playwright and the Firefox browser bundle.
    #    The Playwright installation requires system libraries; install those
    #    first via apt-get. These commands are prefixed with ``sudo`` so they
    #    run as root, which is typical for a Docker container or a CI
    #    environment.
    _run("sudo apt-get update", shell=True)
    _run(
        "sudo apt-get install -y libxcomposite1 libgtk-3-0 libatk1.0-0",
        shell=True,
    )
    # Playwright may need additional system dependencies; the --with-deps
    # flag instructs Playwright to install them automatically.
    _run("playwright install --with-deps firefox", shell=True)

#     # --- 6️⃣  Start Streamlit UI ------------------------------------------
#     STREAMLIT_LOG_file = STREAMLIT_LOG.open("w", encoding="utf-8", buffering=1)
#     streamlit_proc = subprocess.Popen(
#         [
#             "streamlit",
#             "run",
#             "app.py",
#             "--server.port",
#             "8002",
#             "--server.headless",
#             "true",
#             "--browser.gatherUsageStats=false",  # Disable Streamlit telemetry for privacy
#         ],
#         stdout=STREAMLIT_LOG_file,
#         stderr=subprocess.STDOUT,
#         start_new_session=True,
#     )
#     print(f"Streamlit started (PID: {streamlit_proc.pid}) – waiting…")
#     if not _wait_for("http://localhost:8002", timeout=30):
#         streamlit_proc.terminate()
#         sys.exit("[ERROR] Streamlit failed to start")

#     # --- Start ngrok tunnel ------------------------------------------
#     NGROK_LOG_file = NGROK_LOG.open("w", encoding="utf-8", buffering=1)
#     ngrok_config = f"""version: 2
# authtoken: {os.getenv('NGROK_TOKEN')}
# tunnels:
#   streamlit:
#     proto: http
#     addr: 8002
# """
#     Path("ngrok.yml").write_text(ngrok_config)

#     ngrok_proc = subprocess.Popen(
#         ["ngrok", "start", "--all", "--config", "ngrok.yml", "--log", "stdout"],
#         stdout=NGROK_LOG_file,
#         stderr=subprocess.STDOUT,
#         start_new_session=True,
#     )
#     print(f"ngrok started (PID: {ngrok_proc.pid}) – waiting…")
#     if not _wait_for("http://localhost:4040/api/tunnels", timeout=15):
#         ngrok_proc.terminate()
#         sys.exit("[ERROR] ngrok API did not become available")

#     # Grab the public URL
#     try:
#         with urllib.request.urlopen("http://localhost:4040/api/tunnels", timeout=5) as r:
#             tunnels = json.loads(r.read())
#             tunnel_url = next(
#                 (t["public_url"] for t in tunnels["tunnels"]
#                  if t["public_url"].startswith("https")),
#                 tunnels["tunnels"][0]["public_url"],
#             )
#     except Exception as exc:
#         sys.exit(f"[ERROR] Could not retrieve ngrok URL: {exc}")

#     print("ngrok tunnel established")
#     print(f"Public URL: {tunnel_url}")

    # Persist state
    # _save_service_info("tunnel_url", llama_proc.pid, "streamlit_proc.pid", "ngrok_proc.pid")

    print("\nALL SERVICES RUNNING SUCCESSFULLY!")
    print("=" * 70)

# --------------------------------------------------------------------------- #
#  Helper commands – status and stop
# --------------------------------------------------------------------------- #
def _load_service_info() -> dict:
    if not SERVICE_INFO.exists():
        raise FileNotFoundError("No service_info.json found – are the services running?")
    return json.loads(SERVICE_INFO.read_text())

def status() -> None:
    """Print a quick report of the running services."""
    try:
        info = _load_service_info()
    except FileNotFoundError as exc:
        print(exc)
        return

    print("\n" + "=" * 70)
    print("SERVICE STATUS")
    print("=" * 70)
    print(f"Started at: {info['started_at']}")
    # print(f"Public URL: {info['tunnel_url']}")
    print(f"llama-server PID: {info['llama_server_pid']}")
    # print(f"Streamlit PID: {info['streamlit_pid']}")
    # print(f"ngrok PID: {info['ngrok_pid']}")
    print("=" * 70)

    # Check if processes are alive
    for name, pid in [
        ("llama-server", info["llama_server_pid"]),
        # ("Streamlit", info["streamlit_pid"]),
        # ("ngrok", info["ngrok_pid"]),
    ]:
        try:
            os.kill(pid, 0)
            print(f"{name} is running (PID: {pid})")
        except OSError:
            print(f"{name} is NOT running (PID: {pid})")

    # # Verify tunnel
    # print("\nChecking ngrok tunnel status…")
    # try:
    #     tunnel_url = _load_service_info()["tunnel_url"]
    #     if _wait_for(tunnel_url, timeout=10):
    #         print(f"Tunnel is active: {tunnel_url}")
    #     else:
    #         print("Tunnel is not reachable")
    # except Exception as e:
    #     print(f"Tunnel check failed: {e}")

    # # Show recent logs
    # for name, log in [("llama-server", LLAMA_LOG), ("Streamlit", STREAMLIT_LOG), ("ngrok", NGROK_LOG)]:
    #     print(f"\n--- {name}.log (last 5 lines) ---")
    #     if log.exists():
    #         print(_run(f"tail -5 {log}", shell=True, capture=True))
    #     else:
    #         print(f"Log file {log} not found")

def stop() -> None:
    """Terminate all services and clean up."""
    try:
        info = _load_service_info()
    except FileNotFoundError:
        print("No service_info.json – nothing to stop")
        return

    print("Stopping services…")
    for name, pid in [
        ("llama-server", info["llama_server_pid"]),
        # ("Streamlit", info["streamlit_pid"]),
        # ("ngrok", info["ngrok_pid"]),
    ]:
        try:
            # First try a graceful terminate
            os.killpg(pid, signal.SIGTERM)
            print(f"Sent SIGTERM to {name} (PID {pid})")
            try:
                proc = psutil.Process(pid)
                for child in proc.children(recursive=True):
                    child.terminate()
                proc.terminate()
                print(f"{name} (PID {pid}) stopped (psutil)")
            except: 
                print(f"{name} (PID {pid}) not running (psutil)")

        except OSError as exc:
            # If the process is already dead, we’re fine
            try:
                if exc.errno == errno.ESRCH:
                    print(f"{name} (PID {pid}) not running")
                else:
                    print(f"Error stopping {name} (PID {pid}): {exc}")
            except: 
                print(f"{name} (PID {pid}) not running")
    
    # Optionally wait a moment for processes to exit
    time.sleep(1)

    # Clean up the service info files
    for path in (SERVICE_INFO, Path("tunnel_url.txt")):
        try:
            path.unlink()
        except FileNotFoundError:
            pass

    print("Cleaned up service info files")

# --------------------------------------------------------------------------- #
#  CLI entry point
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        if cmd == "--status":
            status()
        elif cmd == "--stop":
            stop()
        else:
            print(f"Unknown command: {cmd}")
            print("Usage: python run.py [--status|--stop]")
            sys.exit(1)
    else:
        main()