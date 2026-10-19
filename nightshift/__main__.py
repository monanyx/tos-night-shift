"""
Usage:
  python -m nightshift run              check every policy, record changes, rebuild the site
  python -m nightshift run --only google
  python -m nightshift build            rebuild the site from saved data
  python -m nightshift demo             build a demo site from three fictional apps
  python -m nightshift check URL        preview what text we'd extract from a page
"""

from __future__ import annotations

import argparse
from pathlib import Path

from .extract import extract_text
from .fetch import fetch
from .runner import run
from .site import build


def main() -> None:
    parser = argparse.ArgumentParser(prog="nightshift", description="ToS Night Shift")
    parser.add_argument("--root", type=Path, default=Path("."), help="repo root (default: current folder)")
    parser.add_argument("--services", type=Path, default=None, help="services file (default: ROOT/services.yaml)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_run = sub.add_parser("run", help="check policies and record changes")
    p_run.add_argument("--only", help="only check this service id")
    p_run.add_argument("--no-site", action="store_true", help="skip rebuilding the website")

    sub.add_parser("build", help="rebuild the website")

    p_demo = sub.add_parser("demo", help="build a demo site from fictional apps")
    p_demo.add_argument("--out", type=Path, default=Path("demo-site"))

    p_check = sub.add_parser("check", help="show extracted text for a URL")
    p_check.add_argument("url")
    p_check.add_argument("--selector")
    p_check.add_argument("--render", action="store_true")

    args = parser.parse_args()
    services = args.services or args.root / "services.yaml"

    if args.cmd == "run":
        run(args.root, services, only=args.only)
        if not args.no_site:
            build(args.root, services)
    elif args.cmd == "build":
        build(args.root, services)
    elif args.cmd == "demo":
        from .demo import build_demo
        print(f"demo site → {build_demo(args.out)}/index.html")
    elif args.cmd == "check":
        text = extract_text(fetch(args.url, render=args.render), selector=args.selector, url=args.url)
        print(text[:3000])
        print(f"\n--- {len(text):,} characters, {len(text.splitlines())} paragraphs ---")


if __name__ == "__main__":
    main()
