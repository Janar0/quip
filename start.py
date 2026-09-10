"""Start local development: python start.py (after installing both dependencies)."""

import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"


def stop_processes(processes):
    for process in processes:
        if process.poll() is None:
            if os.name == "nt":
                process.terminate()
            else:
                os.killpg(process.pid, signal.SIGTERM)
    for process in processes:
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            if os.name == "nt":
                process.kill()
            else:
                os.killpg(process.pid, signal.SIGKILL)
            process.wait()


def main() -> int:
    if len(sys.argv) > 1:
        print(
            "Usage: python start.py\nConfigure an external database with DATABASE_URL in .env."
        )
        return 2
    interpreter = (
        BACKEND / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    )
    npm = shutil.which("npm.cmd" if os.name == "nt" else "npm")
    if not interpreter.exists() or not (FRONTEND / "node_modules").is_dir() or not npm:
        print(
            "Install dependencies first:\n  cd backend && uv sync --frozen --extra dev\n  cd ../frontend && npm ci"
        )
        return 1

    processes = []

    def interrupt(_signal, _frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupt)
    try:
        for command, directory in [
            (
                [
                    str(interpreter),
                    "-m",
                    "uvicorn",
                    "quip.main:app",
                    "--reload",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    "8000",
                ],
                BACKEND,
            ),
            ([npm, "run", "dev", "--", "--port", "5173", "--strictPort"], FRONTEND),
        ]:
            processes.append(
                subprocess.Popen(
                    command,
                    cwd=directory,
                    start_new_session=os.name != "nt",
                )
            )
        print(
            "Frontend: http://127.0.0.1:5173\nBackend: http://127.0.0.1:8000/docs\nPress Ctrl+C to stop.",
            flush=True,
        )
        while True:
            for process in processes:
                code = process.poll()
                if code is not None:
                    print(f"Development process exited with code {code}", flush=True)
                    return code or 1
            time.sleep(0.25)
    except KeyboardInterrupt:
        return 0
    finally:
        stop_processes(processes)


if __name__ == "__main__":
    raise SystemExit(main())
