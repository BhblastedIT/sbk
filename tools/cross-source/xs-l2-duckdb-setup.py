""











from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

import duckdb
from sbk_resources import configure_duckdb

from sbk_config import DATA_ROOT

DUCKDB_PATH = DATA_ROOT / "sbk.duckdb"


def _connetti(**kw) -> duckdb.DuckDBPyConnection:
    ""




    con = duckdb.connect(str(DUCKDB_PATH), **kw)
    configure_duckdb(con)
    return con


def parquet_to_view_info(parquet_path: Path) -> tuple[str, str] | None:
    ""







    try:
        rel = parquet_path.relative_to(DATA_ROOT)
    except ValueError:
        return None

    parts = list(rel.parts)
    if len(parts) < 2:
        return None

    schema = parts[0].replace("-", "_")
    remaining = parts[1:]


    name_parts = []
    for part in remaining:
        if part.endswith(".parquet"):
            part = part[: -len(".parquet")]

        if part in ("processed", "raw"):
            continue
        name_parts.append(part)

    if not name_parts:
        return None

    view_name = "_".join(name_parts)

    view_name = re.sub(r"[^a-zA-Z0-9_]", "_", view_name)

    view_name = re.sub(r"_+", "_", view_name).strip("_")

    return (schema, view_name)






_NON_DATO = ("work", "docs", "secrets", "runtime")


def find_all_parquets() -> list[Path]:
    ""
    out = []
    for p in sorted(DATA_ROOT.rglob("*.parquet")):
        rel = p.relative_to(DATA_ROOT).parts
        if rel and rel[0] in _NON_DATO:
            continue
        if "test-fixtures" in rel:
            continue
        out.append(p)
    return out


def build_views(con: duckdb.DuckDBPyConnection) -> list[tuple[str, str, str]]:
    ""
    parquets = find_all_parquets()
    created = []
    schemas_created: set[str] = set()

    for pq in parquets:
        info = parquet_to_view_info(pq)
        if info is None:
            continue

        schema, view_name = info

        if schema not in schemas_created:
            con.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
            schemas_created.add(schema)

        full_name = f'"{schema}"."{view_name}"'
        pq_str = str(pq)

        con.execute(f"CREATE OR REPLACE VIEW {full_name} AS SELECT * FROM read_parquet('{pq_str}')")
        created.append((schema, view_name, pq_str))

    return created


def setup_database() -> list[tuple[str, str, str]]:
    ""
    DUCKDB_PATH.parent.mkdir(parents=True, exist_ok=True)

    con = _connetti()


    user_schemas = con.execute(
        "SELECT schema_name FROM information_schema.schemata "
        "WHERE schema_name NOT IN ('information_schema', 'pg_catalog', 'main')"
    ).fetchall()
    for (s,) in user_schemas:
        con.execute(f'DROP SCHEMA IF EXISTS "{s}" CASCADE')

    created = build_views(con)
    con.close()
    return created


def list_views():
    ""
    if not DUCKDB_PATH.exists():
        print("Database not found. Run without --list first to create it.")
        return

    con = _connetti(read_only=True)
    views = con.execute(
        "SELECT table_schema, table_name FROM information_schema.views "
        "WHERE table_schema NOT IN ('information_schema', 'pg_catalog') "
        "ORDER BY table_schema, table_name"
    ).fetchall()
    con.close()

    current_schema = None
    for schema, view in views:
        if schema != current_schema:
            if current_schema is not None:
                print()
            print(f"  {schema}/")
            current_schema = schema
        print(f"    {view}")

    print(f"\n{len(views)} views total")


def run_query(sql: str):
    ""
    if not DUCKDB_PATH.exists():
        print("Database not found. Run without --query first to create it.")
        return

    con = _connetti(read_only=True)
    try:
        result = con.execute(sql)
        columns = [desc[0] for desc in result.description]
        rows = result.fetchall()

        if not rows:
            print("(no results)")
            return


        col_widths = [len(c) for c in columns]
        for row in rows:
            for i, val in enumerate(row):
                col_widths[i] = max(col_widths[i], len(str(val)[:80]))

        header = " | ".join(c.ljust(col_widths[i]) for i, c in enumerate(columns))
        print(header)
        print("-" * len(header))
        for row in rows:
            line = " | ".join(str(v)[:80].ljust(col_widths[i]) for i, v in enumerate(row))
            print(line)

        print(f"\n({len(rows)} rows)")
    except Exception as e:
        print(f"Query error: {e}")
    finally:
        con.close()


def main():
    parser = argparse.ArgumentParser(description="SBK DuckDB view layer")
    parser.add_argument("--list", action="store_true", help="List all views")
    parser.add_argument("--query", type=str, help="Run a SQL query")
    args = parser.parse_args()

    if args.list:
        list_views()
    elif args.query:
        run_query(args.query)
    else:
        print(f"Building DuckDB view layer at {DUCKDB_PATH}")
        created = setup_database()

        schemas = sorted({s for s, _, _ in created})
        print(f"\nCreated {len(created)} views in {len(schemas)} schemas:")
        for schema in schemas:
            views_in_schema = [v for s, v, _ in created if s == schema]
            print(f"  {schema}: {', '.join(views_in_schema)}")

        print(f"\nDatabase: {DUCKDB_PATH}")
        print(f"Size: {DUCKDB_PATH.stat().st_size / 1024:.0f} KB")
        print("\nUsage examples:")
        print("  --list                               # List all views")
        print('  --query "SELECT count(*) FROM enriched.contacts_merged"')
        print('  --query "SELECT name, email FROM attio.people LIMIT 10"')
        print('  --query "DESCRIBE enriched.contacts_merged"')


from pipeline_decorator import pipeline_step


@pipeline_step(name="l2-duckdb-setup", source="l2-duckdb-setup", stage="l2")
def _pipeline_run():
    main()


if __name__ == "__main__":
    _pipeline_run()
