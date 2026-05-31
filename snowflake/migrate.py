"""
Snowflake DDL migration runner.

Usage:
    python snowflake/migrate.py --up      # apply all DDL files in order
    python snowflake/migrate.py --down    # drop the EHRZIPPER database

Note on import path: this module lives under ``snowflake/`` to keep DDL and
its runner together. To avoid shadowing the ``snowflake-connector-python``
package, ``snowflake/`` is intentionally NOT a Python package
(no ``__init__.py``). Run via ``python snowflake/migrate.py``, not
``python -m snowflake.migrate``. The import of the connector still works
because the top-level ``snowflake`` package is installed into site-packages
and we never add this directory to ``sys.path`` as a package root.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from snowflake.connector import SnowflakeConnection

DDL_DIR = Path(__file__).parent / "ddl"


def _split_statements(sql: str) -> list[str]:
    """
    Split a SQL script into individual statements on top-level semicolons.

    Crude but adequate for our DDL — we don't have stored procedures with
    embedded semicolons. Strips leading whitespace and skips empty fragments.
    """
    statements: list[str] = []
    buf: list[str] = []
    in_line_comment = False
    in_block_comment = False
    quote_char: str | None = None
    i = 0
    while i < len(sql):
        ch = sql[i]
        nxt = sql[i + 1] if i + 1 < len(sql) else ""
        if in_line_comment:
            buf.append(ch)
            if ch == "\n":
                in_line_comment = False
        elif in_block_comment:
            buf.append(ch)
            if ch == "*" and nxt == "/":
                buf.append(nxt)
                i += 1
                in_block_comment = False
        elif quote_char is not None:
            buf.append(ch)
            if ch == quote_char:
                quote_char = None
        else:
            if ch == "-" and nxt == "-":
                in_line_comment = True
                buf.append(ch)
            elif ch == "/" and nxt == "*":
                in_block_comment = True
                buf.append(ch)
            elif ch in ("'", '"'):
                quote_char = ch
                buf.append(ch)
            elif ch == ";":
                stmt = "".join(buf).strip()
                if stmt and not _is_comment_only(stmt):
                    statements.append(stmt)
                buf = []
            else:
                buf.append(ch)
        i += 1
    tail = "".join(buf).strip()
    if tail and not _is_comment_only(tail):
        statements.append(tail)
    return statements


def _is_comment_only(stmt: str) -> bool:
    """True if the fragment contains only SQL comments / whitespace."""
    out: list[str] = []
    i = 0
    in_line = False
    in_block = False
    while i < len(stmt):
        ch = stmt[i]
        nxt = stmt[i + 1] if i + 1 < len(stmt) else ""
        if in_line:
            if ch == "\n":
                in_line = False
        elif in_block:
            if ch == "*" and nxt == "/":
                i += 1
                in_block = False
        elif ch == "-" and nxt == "-":
            in_line = True
        elif ch == "/" and nxt == "*":
            in_block = True
        else:
            out.append(ch)
        i += 1
    return "".join(out).strip() == ""


def _connect() -> SnowflakeConnection:
    # Connection logic (key-pair auth + clock-skew tolerance) is centralized in
    # ehrzipper.sf_connect so the migration runner and the data loaders share
    # one code path. We default the warehouse to EHRZIPPER_WH for the migration.
    import importlib.util

    here = Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location(
        "ehrzipper.sf_connect", here / "ehrzipper" / "sf_connect.py"
    )
    assert spec is not None and spec.loader is not None
    sf_connect = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sf_connect)
    os.environ.setdefault("SNOWFLAKE_WAREHOUSE", "EHRZIPPER_WH")
    return sf_connect.connect()


def up() -> None:
    """Run every .sql file in ddl/ in lexical order."""
    files = sorted(DDL_DIR.glob("*.sql"))
    if not files:
        print(f"No DDL files found in {DDL_DIR}", file=sys.stderr)
        sys.exit(1)
    conn = _connect()
    try:
        cur = conn.cursor()
        try:
            for f in files:
                print(f"==> Applying {f.name}")
                script = f.read_text(encoding="utf-8")
                for stmt in _split_statements(script):
                    cur.execute(stmt)
            conn.commit()
            print("==> Migration complete.")
        finally:
            cur.close()
    finally:
        conn.close()


def down() -> None:
    """Drop the EHRZIPPER database. Destructive."""
    conn = _connect()
    try:
        cur = conn.cursor()
        try:
            print("==> Dropping database EHRZIPPER (destructive)")
            cur.execute("DROP DATABASE IF EXISTS EHRZIPPER")
            conn.commit()
            print("==> Drop complete.")
        finally:
            cur.close()
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="EHRzipper Snowflake migration runner")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--up", action="store_true", help="Apply all DDL files in order")
    g.add_argument("--down", action="store_true", help="Drop the EHRZIPPER database (destructive)")
    args = p.parse_args(argv)
    if args.up:
        up()
    elif args.down:
        down()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
