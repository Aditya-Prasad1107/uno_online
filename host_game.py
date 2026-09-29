"""UNO host launcher — turns this laptop into the game server.

Run it and it will:
  1. create/reuse a .venv and install Streamlit into it
  2. start the UNO server on this machine
  3. open a public https link via Cloudflare Tunnel (auto-downloaded, no account)
  4. keep the laptop awake while the game is running
  5. print the single link to share with friends

Usage:
    python host_game.py              # LAN + public tunnel link
    python host_game.py --lan-only   # same-WiFi only, no tunnel
    python host_game.py --port 8600  # use a different port

Stop the server with Ctrl+C.
"""

from __future__ import annotations

import argparse
import ctypes
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import signal
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
IS_WIN = platform.system() == "Windows"
VENV = ROOT / (".venv" if IS_WIN else ".venv-linux")
CF_DIR = ROOT / ".tools"
CF_BIN = CF_DIR / ("cloudflared.exe" if IS_WIN else "cloudflared")

CF_URLS = {
    ("Windows", "AMD64"): "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe",
    ("Windows", "ARM64"): "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-arm64.exe",
    ("Linux", "x86_64"): "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64",
    ("Linux", "aarch64"): "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64",
    ("Darwin", "arm64"): "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-darwin-arm64.tgz",
    ("Darwin", "x86_64"): "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-darwin-amd64.tgz",
}

C = {"g": "\033[92m", "y": "\033[93m", "r": "\033[91m", "c": "\033[96m",
     "b": "\033[1m", "d": "\033[2m", "x": "\033[0m"}
if IS_WIN:
    os.system("")          # enable ANSI colours in modern Windows terminals


def _spawn_kwargs() -> dict:
    """Start children detached so the whole tree can be killed reliably."""
    if IS_WIN:
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def kill_tree(proc: subprocess.Popen | None) -> None:
    if not proc or proc.poll() is not None:
        return
    try:
        if IS_WIN:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           capture_output=True)
        else:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except Exception:
        pass
    try:
        proc.wait(timeout=8)
    except Exception:
        try:
            if not IS_WIN:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            else:
                proc.kill()
        except Exception:
            pass


def say(msg: str, colour: str = "x") -> None:
    print(f"{C.get(colour, '')}{msg}{C['x']}", flush=True)


def rule() -> None:
    print(C["d"] + "─" * 62 + C["x"], flush=True)


# --------------------------------------------------------------------------- #
# venv
# --------------------------------------------------------------------------- #
def venv_python() -> Path:
    return VENV / ("Scripts/python.exe" if IS_WIN else "bin/python")


def _has_streamlit(py: Path) -> bool:
    try:
        subprocess.run([str(py), "-c", "import streamlit"], check=True, capture_output=True)
        return True
    except Exception:
        return False


def ensure_venv() -> Path:
    py = venv_python()
    if not py.exists():
        say(f"Creating virtual environment at {VENV.name} …", "c")
        try:
            subprocess.run([sys.executable, "-m", "venv", str(VENV)], check=True)
        except subprocess.CalledProcessError:
            say("Could not create a venv — using the current Python instead.", "y")
            return Path(sys.executable)
    if _has_streamlit(py):
        return py

    say("Installing Streamlit (first run only, ~1 min) …", "c")
    subprocess.run([str(py), "-m", "pip", "install", "-q", "--upgrade", "pip"], check=False)
    r = subprocess.run([str(py), "-m", "pip", "install", "-q", "-r",
                        str(ROOT / "requirements.txt")], capture_output=True, text=True)
    if r.returncode != 0 or not _has_streamlit(py):
        if _has_streamlit(Path(sys.executable)):
            say("Install failed, but Streamlit is available globally — using that.", "y")
            return Path(sys.executable)
        say("Could not install Streamlit. Check your internet connection, then retry.", "r")
        if r.stderr:
            say(r.stderr.strip()[:500], "d")
        sys.exit(1)
    return py


# --------------------------------------------------------------------------- #
# network helpers
# --------------------------------------------------------------------------- #
def lan_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def free_port(port: int) -> int:
    for p in range(port, port + 20):
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", p)) != 0:
                return p
    return port


def wait_for_port(port: int, timeout: int = 90) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(0.5)
    return False


# --------------------------------------------------------------------------- #
# cloudflared
# --------------------------------------------------------------------------- #
def ensure_cloudflared() -> Path | None:
    if CF_BIN.exists():
        return CF_BIN
    found = shutil.which("cloudflared")
    if found:
        return Path(found)
    key = (platform.system(), platform.machine())
    url = CF_URLS.get(key)
    if not url:
        return None
    CF_DIR.mkdir(exist_ok=True)
    say("Downloading Cloudflare Tunnel (one-time, ~35 MB) …", "c")
    try:
        if url.endswith(".tgz"):
            import tarfile
            tgz = CF_DIR / "cf.tgz"
            urllib.request.urlretrieve(url, tgz)
            with tarfile.open(tgz) as t:
                t.extractall(CF_DIR)
            tgz.unlink(missing_ok=True)
            for f in CF_DIR.iterdir():
                if f.name.startswith("cloudflared"):
                    f.rename(CF_BIN)
                    break
        else:
            urllib.request.urlretrieve(url, CF_BIN)
        if not IS_WIN:
            CF_BIN.chmod(0o755)
        return CF_BIN
    except Exception as e:
        say(f"Could not download the tunnel helper: {e}", "y")
        return None


PUBLIC_URL: str | None = None
URL_RE = re.compile(r"https://[-\w.]+\.trycloudflare\.com")


def pump_tunnel(proc: subprocess.Popen) -> None:
    global PUBLIC_URL
    for raw in iter(proc.stdout.readline, ""):
        m = URL_RE.search(raw)
        if m and not PUBLIC_URL:
            PUBLIC_URL = m.group(0)


# --------------------------------------------------------------------------- #
# keep awake
# --------------------------------------------------------------------------- #
def keep_awake() -> None:
    """Stop the laptop sleeping mid-game (reverts automatically on exit)."""
    if IS_WIN:
        try:                       # ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED
            ctypes.windll.kernel32.SetThreadExecutionState(0x80000003)
        except Exception:
            pass


def release_awake() -> None:
    if IS_WIN:
        try:
            ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)
        except Exception:
            pass


# --------------------------------------------------------------------------- #
def main() -> int:
    ap = argparse.ArgumentParser(description="Host UNO from this laptop.")
    ap.add_argument("--port", type=int, default=8501)
    ap.add_argument("--lan-only", action="store_true",
                    help="Skip the public tunnel; same-WiFi players only.")
    args = ap.parse_args()

    rule()
    say("  🎴  UNO — hosting from this laptop", "b")
    rule()

    py = ensure_venv()
    port = free_port(args.port)

    env = dict(os.environ, STREAMLIT_BROWSER_GATHER_USAGE_STATS="false")
    st_proc = subprocess.Popen(
        [str(py), "-m", "streamlit", "run", str(ROOT / "streamlit_app.py"),
         "--server.address", "0.0.0.0", "--server.port", str(port),
         "--server.headless", "true", "--browser.gatherUsageStats", "false"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env, cwd=str(ROOT),
        **_spawn_kwargs())

    say("Starting the game server …", "c")
    if not wait_for_port(port):
        say("Server failed to start. Run 'streamlit run streamlit_app.py' to see the error.", "r")
        kill_tree(st_proc)
        return 1

    cf_proc = None
    if not args.lan_only:
        cf = ensure_cloudflared()
        if cf:
            say("Opening a public link …", "c")
            cf_proc = subprocess.Popen(
                [str(cf), "tunnel", "--url", f"http://localhost:{port}", "--no-autoupdate"],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1, encoding="utf-8", errors="replace",
                **_spawn_kwargs())
            threading.Thread(target=pump_tunnel, args=(cf_proc,), daemon=True).start()
            for _ in range(60):
                if PUBLIC_URL:
                    break
                time.sleep(0.5)

    keep_awake()
    print()
    rule()
    say("  SERVER IS LIVE — your laptop is now the host", "g")
    rule()
    if PUBLIC_URL:
        say("  Share this link with friends (anywhere):", "b")
        say(f"     {PUBLIC_URL}", "c")
    elif not args.lan_only:
        say("  Public link unavailable — same-WiFi players can still join.", "y")
    say("  Same WiFi:  " + f"http://{lan_ip()}:{port}", "b")
    say(f"  On this laptop:  http://localhost:{port}", "d")
    rule()
    print("""  How it works:
    1. Open the link yourself, click 'Create a room', pick player count.
    2. Send friends the SAME link above.
    3. They click 'Join a room' and type your 4-letter room code.

  Keep this window open — closing it ends the game.
  Press Ctrl+C to stop the server.""")
    rule()

    # Also shut down cleanly if the window is closed / the OS sends SIGTERM.
    def _on_term(_sig, _frm):
        raise KeyboardInterrupt

    for sig in (signal.SIGTERM, getattr(signal, "SIGBREAK", None)):
        if sig is not None:
            try:
                signal.signal(sig, _on_term)
            except Exception:
                pass

    try:
        while st_proc.poll() is None:
            time.sleep(1)
    except KeyboardInterrupt:
        print()
        say("Shutting down …", "y")
    finally:
        release_awake()
        kill_tree(cf_proc)
        kill_tree(st_proc)
        say("Server stopped. Rooms cleared.", "d")
    return 0


if __name__ == "__main__":
    sys.exit(main())
