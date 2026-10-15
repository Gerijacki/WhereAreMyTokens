import argparse
import logging
import os
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(prog="wamt", description="WhereAreMyTokens")
    sub = parser.add_subparsers(dest="cmd", required=True)
    serve = sub.add_parser("serve", help="Run the API, dashboard and ingest worker")
    serve.add_argument("--host", default="0.0.0.0")
    serve.add_argument("--port", type=int, default=8787)
    sub.add_parser("ingest", help="Run a single ingestion scan and exit")
    sub.add_parser("reprice", help="Recompute API-equivalent costs after editing pricing.yaml")
    sub.add_parser("enrich", help="Recompute categories, signatures and cache events for all data")
    sub.add_parser("insights", help="Recompute automation insights and print them")

    dev = sub.add_parser("device", help="Manage devices that push data with `wamt agent`")
    dev_sub = dev.add_subparsers(dest="action", required=True)
    dev_add = dev_sub.add_parser("add", help="Create a device and print its token (shown once)")
    dev_add.add_argument("name")
    dev_sub.add_parser("list", help="List devices")
    dev_rm = dev_sub.add_parser("revoke", help="Revoke a device token")
    dev_rm.add_argument("name")

    agent = sub.add_parser("agent", help="Push this machine's Claude Code transcripts to a WAMT server")
    agent.add_argument("--server", default=os.environ.get("WAMT_SERVER"), help="e.g. https://wamt.example.com")
    agent.add_argument("--token", default=os.environ.get("WAMT_TOKEN"), help="device token from `wamt device add`")
    agent.add_argument("--dir", type=Path, default=Path(os.environ.get("WAMT_CLAUDE_DATA_DIR",
                                                                        Path.home() / ".claude" / "projects")))
    agent.add_argument("--state", type=Path, default=Path(os.environ.get(
        "WAMT_AGENT_STATE", Path.home() / ".config" / "wamt" / "agent-state.json")))
    agent.add_argument("--interval", type=float, default=10.0, help="seconds between syncs")
    agent.add_argument("--once", action="store_true", help="sync once and exit")
    agent.add_argument("--no-prompts", action="store_true", help="never send prompt text, only its metadata")

    demo = sub.add_parser("demo", help="Generate realistic synthetic transcripts to try WAMT without real data")
    demo.add_argument("--dir", type=Path, default=Path("demo-data"))
    demo.add_argument("--days", type=int, default=30)
    demo.add_argument("--seed", type=int, default=7)

    test_alert = sub.add_parser("test-alert", help="Send a test notification to WAMT_ALERT_URL")
    test_alert.add_argument("--url", default=None)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # Windows consoles default to cp1252
    if args.cmd == "serve":
        import uvicorn

        uvicorn.run("wamt.main:app", host=args.host, port=args.port, proxy_headers=True)
    elif args.cmd == "ingest":
        from wamt.analytics.enrich import backfill
        from wamt.collector.ingest import STATUS, reparse_if_needed, scan
        from wamt.db import init_engine

        init_engine()
        reparse_if_needed()
        lines = scan()
        backfill()
        print(f"Ingested {lines} lines from {STATUS.files_changed}/{STATUS.files_seen} files "
              f"in {STATUS.last_scan_seconds}s")
        if STATUS.last_error:
            print(f"Last error: {STATUS.last_error}")
    elif args.cmd == "reprice":
        from wamt.collector.ingest import reprice
        from wamt.db import init_engine

        init_engine()
        print(f"Repriced {reprice()} API calls")
    elif args.cmd == "enrich":
        from wamt.analytics.enrich import backfill
        from wamt.db import init_engine

        init_engine()
        backfill(force=True)
        print("Derived data recomputed")
    elif args.cmd == "insights":
        from sqlalchemy import select

        from wamt.db import Insight, init_engine, new_session
        from wamt.insights.engine import refresh

        init_engine()
        refresh()
        with new_session() as db:
            rows = db.scalars(select(Insight).where(Insight.stale.is_(False))
                              .order_by(Insight.est_usd_month.desc())).all()
            for i in rows:
                print(f"[{i.severity:6}] ${i.est_usd_month:7.2f}/mo  {i.type:17} {i.title}")
    elif args.cmd == "device":
        from sqlalchemy import select

        from wamt import devices
        from wamt.db import Device, init_engine, new_session

        init_engine()
        with new_session() as db:
            if args.action == "add":
                try:
                    token = devices.create(db, args.name)
                except ValueError as e:
                    raise SystemExit(str(e)) from e
                print(f"Device '{args.name}' created. Its token (shown only once):\n\n  {token}\n")
                print("On that machine run:  wamt agent --server <url> --token <token>")
            elif args.action == "list":
                for d in db.scalars(select(Device).order_by(Device.name)):
                    state = "revoked" if d.revoked else "active"
                    print(f"{d.name:24} {state:8} last seen {d.last_seen_at or 'never'}")
            elif not devices.revoke(db, args.name):
                raise SystemExit(f"No device named {args.name!r}")
            else:
                print(f"Device '{args.name}' revoked")
    elif args.cmd == "agent":
        from wamt.agent import Agent

        if not args.server or not args.token:
            raise SystemExit("--server and --token are required (or WAMT_SERVER / WAMT_TOKEN)")
        Agent(args.server, args.token, args.dir, args.state, send_prompts=not args.no_prompts).run(
            interval=args.interval, once=args.once)
    elif args.cmd == "demo":
        from wamt.demo import generate

        n = generate(args.dir, days=args.days, seed=args.seed)
        print(f"Wrote {n} demo transcripts to {args.dir}. Try: WAMT_CLAUDE_DATA_DIR={args.dir} wamt serve")
    elif args.cmd == "test-alert":
        from wamt.alerts import send

        send("WhereAreMyTokens test", "Alerts are working.", url=args.url)
        print("Sent")


if __name__ == "__main__":
    main()
