from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Start Flask fullstack server (frontend + backend).")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8020)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent
    cmd = [
        sys.executable,
        "run_platform_server.py",
        "--host",
        args.host,
        "--port",
        str(args.port),
    ]
    if args.reload:
        cmd.append("--reload")

    print(f"[fullstack] flask app: http://{args.host}:{args.port}")
    proc = subprocess.Popen(cmd, cwd=str(root))
    try:
        proc.wait()
    except KeyboardInterrupt:
        proc.terminate()


if __name__ == "__main__":
    main()
