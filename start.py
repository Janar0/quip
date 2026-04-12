"""Q.U.I.P. dev launcher — starts backend and frontend in one command.

Usage:
    python start.py          # SQLite mode (no Docker needed)
    python start.py --pg     # PostgreSQL + Redis via Docker
"""
import subprocess
import sys
import os
import time
import signal

ROOT = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.join(ROOT, "backend")
FRONTEND = os.path.join(ROOT, "frontend")

procs: list[subprocess.Popen] = []


def cleanup(*_):
    print("\nShutting down...")
    for p in procs:
        p.terminate()
    for p in procs:
        try:
            p.wait(timeout=5)
        except subprocess.TimeoutExpired:
            p.kill()
    sys.exit(0)


signal.signal(signal.SIGINT, cleanup)
signal.signal(signal.SIGTERM, cleanup)


def _docker_available() -> bool:
    """Check if Docker daemon is running."""
    try:
        subprocess.run(
            ["docker", "info"], capture_output=True, timeout=5, check=True,
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _ensure_sandbox_image():
    """Build quip-sandbox:latest if it doesn't exist yet."""
    dockerfile = os.path.join(ROOT, "Dockerfile.sandbox")
    if not os.path.exists(dockerfile):
        return

    # Check if image already exists
    result = subprocess.run(
        ["docker", "images", "-q", "quip-sandbox:latest"],
        capture_output=True, text=True, timeout=10,
    )
    if result.stdout.strip():
        print("Sandbox image: quip-sandbox:latest (exists)")
        return

    print("Building sandbox image (quip-sandbox:latest) — first time may take a few minutes...")
    subprocess.run(
        ["docker", "build", "-f", "Dockerfile.sandbox", "-t", "quip-sandbox:latest", "."],
        cwd=ROOT, check=True,
    )
    print("Sandbox image built successfully!")


def main():
    use_pg = "--pg" in sys.argv

    if use_pg:
        print("Starting PostgreSQL + Redis via Docker...")
        subprocess.run(["docker", "compose", "up", "-d"], cwd=ROOT, check=True)
        time.sleep(2)
        os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://quip:quip@localhost:5432/quip")
    else:
        print("Using SQLite (no Docker needed)")
        os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///quip.db")

    # Build sandbox image if Docker is available
    if _docker_available():
        _ensure_sandbox_image()
    else:
        print("Docker not available — sandbox features disabled")

    # Start backend
    print("Starting backend on :8000...")
    backend = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "quip.main:app", "--reload", "--port", "8000"],
        cwd=BACKEND,
        env={**os.environ},
    )
    procs.append(backend)
    time.sleep(2)

    # Start frontend
    print("Starting frontend on :5173...")
    frontend = subprocess.Popen(
        ["npm", "run", "dev"],
        cwd=FRONTEND,
        shell=True,
    )
    procs.append(frontend)

    docker_ok = _docker_available()
    print("\n  Q.U.I.P. is running!")
    print(f"  Database:  {'PostgreSQL (Docker)' if use_pg else 'SQLite (quip.db)'}")
    print(f"  Sandbox:   {'Ready (enable in Admin > Settings)' if docker_ok else 'Disabled (Docker not found)'}")
    print("  Frontend:  http://localhost:5173")
    print("  Backend:   http://localhost:8000")
    print("  API docs:  http://localhost:8000/docs")
    print("\n  Press Ctrl+C to stop.\n")

    try:
        while True:
            for p in procs:
                if p.poll() is not None:
                    print(f"Process exited with code {p.returncode}")
                    cleanup()
            time.sleep(1)
    except KeyboardInterrupt:
        cleanup()


if __name__ == "__main__":
    main()
