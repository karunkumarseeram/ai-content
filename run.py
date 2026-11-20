import argparse
import os
import sys
from pathlib import Path

import uvicorn

PROJECT_ROOT = Path(__file__).resolve().parent


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the 104Dairies news service")
    parser.add_argument(
        "--env",
        choices=("dev", "prod"),
        default="dev",
        help="dev enables reload and localhost binding; prod uses Render binding",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("PORT", "8000")),
        help="Port to listen on (defaults to Render's PORT or 8000)",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    sys.path.insert(0, str(PROJECT_ROOT))
    args = build_parser().parse_args(argv)
    if args.port < 1 or args.port > 65535:
        raise SystemExit("--port must be between 1 and 65535")

    os.environ["ENV"] = args.env
    host = "127.0.0.1" if args.env == "dev" else "0.0.0.0"
    print(f"Running 104Dairies in {args.env.upper()} mode on {host}:{args.port}")
    uvicorn.run(
        "app.main:app",
        host=host,
        port=args.port,
        reload=args.env == "dev",
        workers=1,
    )


if __name__ == "__main__":
    main()
