"""Ops CLI: migrations, seeding, evaluation. Run from the backend directory.

    python manage.py migrate
    python manage.py status
    python manage.py seed-demo
"""
from __future__ import annotations

import argparse
import sys

from app import db
from app import migrations as mig
from app.logging_setup import configure_logging


def cmd_migrate(_: argparse.Namespace) -> int:
    conn = db.connect()
    applied = mig.migrate(conn)
    print("applied migrations:", applied or ["(none pending)"])
    print("database:", conn.execute("SELECT 1").fetchone()[0] and db.settings.database_path)
    conn.close()
    return 0


def cmd_status(_: argparse.Namespace) -> int:
    conn = db.connect()
    applied = sorted(mig.applied(conn))
    tables = sorted(r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ))
    print("applied migrations:", applied or ["(none)"])
    print("tables:", tables)
    conn.close()
    return 0


def cmd_seed_demo(_: argparse.Namespace) -> int:
    from app.services.seed import seed_demo
    conn = db.connect()
    mig.migrate(conn)
    summary = seed_demo(conn)
    print("seed summary:", summary)
    conn.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    parser = argparse.ArgumentParser(prog="manage")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("migrate").set_defaults(func=cmd_migrate)
    sub.add_parser("status").set_defaults(func=cmd_status)
    sub.add_parser("seed-demo").set_defaults(func=cmd_seed_demo)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
