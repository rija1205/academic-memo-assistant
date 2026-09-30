"""Compare two databases table by table, so a restore is proven rather than assumed.

``pg_restore`` returning 0 means the command succeeded. It does not mean the memoir is back:
the archive can restore an empty schema, a schema from the wrong moment, or a partial one
without a single error. The only evidence that a restore worked is that the data is there and
that it matches.

Comparison is by row count per table, on the union of both schemas' tables, so a table that
exists in the source and not in the target is a difference rather than something both sides
quietly omit.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API = ROOT / "services" / "api"


async def table_counts(url: str) -> dict[str, int]:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(url)
    try:
        async with engine.connect() as connection:
            names = await connection.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'public' AND table_type = 'BASE TABLE' "
                    "ORDER BY table_name"
                )
            )
            counts: dict[str, int] = {}
            for row in names:
                name = row[0]
                if name == "alembic_version":
                    continue
                counted = await connection.execute(
                    text(f'SELECT count(*) FROM "{name}"')
                )
                counts[name] = int(counted.scalar() or 0)
            return counts
    finally:
        await engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, help="base d'origine")
    parser.add_argument("--target", required=True, help="base restauree")
    parser.add_argument("--expect-tables", type=int, default=0,
                        help="nombre minimal de tables attendu dans la cible")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    sys.path.insert(0, str(API))

    try:
        source = asyncio.run(table_counts(args.source))
        target = asyncio.run(table_counts(args.target))
    except Exception as exc:  # noqa: BLE001 - reported as a comparison failure
        print(f"Comparaison impossible : {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    names = sorted(set(source) | set(target))
    differences: list[str] = []
    for name in names:
        left = source.get(name)
        right = target.get(name)
        if left is None:
            differences.append(f"{name} : absente de la base d'origine")
        elif right is None:
            differences.append(f"{name} : absente de la base restauree")
        elif left != right:
            differences.append(f"{name} : {left} lignes d'origine, {right} restaurees")

    if args.expect_tables and len(target) < args.expect_tables:
        differences.append(
            f"seulement {len(target)} tables restaurees, {args.expect_tables} attendues"
        )

    if args.json:
        print(json.dumps(
            {
                "tables_compared": len(names),
                "rows_source": sum(source.values()),
                "rows_target": sum(target.values()),
                "differences": differences,
            },
            indent=2,
            ensure_ascii=False,
        ))
        return 1 if differences else 0

    print(f"{len(names)} tables comparees, {sum(source.values())} lignes d'origine, "
          f"{sum(target.values())} lignes restaurees.")
    if differences:
        print(f"{len(differences)} difference(s) :")
        for item in differences:
            print(f"  - {item}")
        return 1
    print("Les deux bases contiennent exactement les memes tables avec le meme nombre de lignes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
