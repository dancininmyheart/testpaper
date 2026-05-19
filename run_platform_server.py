from __future__ import annotations

import argparse
import os

from backend.main import create_app


def _should_start_worker(reload_enabled: bool) -> bool:
    if not reload_enabled:
        return True
    return os.getenv("WERKZEUG_RUN_MAIN") == "true"


def main() -> None:
    from dotenv import load_dotenv

    load_dotenv()

    parser = argparse.ArgumentParser(description="Run unified platform backend (Flask).")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8020)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()

    app = create_app(start_worker=_should_start_worker(args.reload))
    app.run(
        host=args.host,
        port=args.port,
        debug=args.reload,
        use_reloader=args.reload,
        threaded=True,
    )


if __name__ == "__main__":
    main()
