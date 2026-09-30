"""Compare the SQLAlchemy models against the SQL that the migrations actually produce.

Without a PostgreSQL to run them against, the migrations are the only description of the
schema that exists. The most damaging class of defect they can hide is drift: a column added
to a model and never migrated, a foreign key declared in Python and absent from the DDL, an
index the code relies on that no migration creates. The application then passes every unit
test and fails on the first query against a real database.

This is a static substitute, not a replacement. It cannot observe what the database does with
the DDL, only that the DDL and the models agree.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API = ROOT / "services" / "api"

sys.path.insert(0, str(API))


def model_tables() -> dict[str, dict]:
    """``table -> {"columns": set, "foreign_keys": set, "indexes": set, "uniques": set}``."""
    from app import models  # noqa: F401,PLC0415
    from app.db.base import Base  # noqa: PLC0415

    result: dict[str, dict] = {}
    for name, table in Base.metadata.tables.items():
        indexes = {
            tuple(sorted(column.name for column in index.columns))
            for index in table.indexes
        }
        unique_constraints = {
            tuple(sorted(column.name for column in constraint.columns))
            for constraint in table.constraints
            if constraint.__class__.__name__ == "UniqueConstraint"
        }
        result[name] = {
            "columns": {column.name for column in table.columns},
            "foreign_keys": {
                (column.name, list(column.foreign_keys)[0].target_fullname)
                for column in table.columns
                if column.foreign_keys
            },
            "indexes": indexes,
            # Index names, not column tuples: the migrations create expression indexes such
            # as ``uq_users_email_lower`` on ``lower(email)``, which no column comparison
            # would ever match, and an index the code names is an index the code can rely on.
            "index_names": {index.name for index in table.indexes if index.name},
            "indexes_by_name": {
                index.name: tuple(
                    sorted(
                        column.name
                        for column in index.columns
                        if getattr(column, "name", None)
                    )
                )
                for index in table.indexes
                if index.name
            },
            "uniques": unique_constraints | {
                tuple(sorted(column.name for column in index.columns))
                for index in table.indexes
                if index.unique
            },
        }
    return result


def migration_sql() -> str:
    """The DDL Alembic would run, obtained in offline mode so no database is needed."""
    completed = subprocess.run(
        [
            str(API / ".venv" / "Scripts" / "alembic.exe"),
            "upgrade",
            "head",
            "--sql",
        ],
        cwd=API,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise SystemExit(
            "alembic upgrade head --sql a echoue :\n"
            + (completed.stderr or completed.stdout)[-800:]
        )
    return completed.stdout


def parse_ddl(sql: str) -> dict[str, dict]:
    """Extract the tables the migrations produce, with their columns, keys and indexes.

    Three details of Alembic's output shaped this parser, and each of them produced a whole
    class of false positives before it was handled:

    * a column may arrive in the ``CREATE TABLE`` body **or** in a later
      ``ALTER TABLE ... ADD COLUMN``; reading only the first made ``users`` look like 4
      columns instead of 11;
    * a foreign key is a line of its own, ``FOREIGN KEY(col) REFERENCES t (id)``, so a naive
      column regex reported a column literally named ``FOREIGN``;
    * ``ALTER TABLE x ADD CONSTRAINT ck_... CHECK (...)`` adds a constraint, not a column.
    """
    tables: dict[str, dict] = {}

    def slot_for(name: str) -> dict:
        return tables.setdefault(
            name,
            {
                "columns": set(),
                "foreign_keys": set(),
                "uniques": set(),
                "indexes": set(),
                "index_names": set(),
                "indexes_by_name": {},
            },
        )

    def add_foreign_key(table: str, column: str, target_table: str, target_column: str) -> None:
        slot_for(table)["foreign_keys"].add(
            (column.strip('"'), f"{target_table.strip(chr(34))}.{target_column.strip(chr(34))}")
        )

    foreign_key_pattern = re.compile(
        r"FOREIGN\s+KEY\s*\(\s*([\w\"]+)\s*\)\s*REFERENCES\s+([\w\"]+)\s*\(\s*([\w\"]+)\s*\)",
        re.I,
    )

    for match in re.finditer(
        r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([\w\"]+)\s*\((.*?)\n\);",
        sql,
        re.S | re.I,
    ):
        name = match.group(1).strip('"')
        slot = slot_for(name)
        for raw_line in match.group(2).splitlines():
            line = raw_line.strip().rstrip(",")
            if not line:
                continue
            foreign = foreign_key_pattern.search(line)
            if foreign:
                add_foreign_key(name, foreign.group(1), foreign.group(2), foreign.group(3))
                continue
            upper = line.upper()
            if upper.startswith(("CONSTRAINT", "PRIMARY KEY", "UNIQUE (", "CHECK (")):
                continue
            column_match = re.match(r"([\w\"]+)\s+[\w\.\(\)\[\]]+", line)
            if not column_match:
                continue
            column = column_match.group(1).strip('"')
            slot["columns"].add(column)
            if " UNIQUE" in f" {upper}":
                slot["uniques"].add((column,))

    # ALTER TABLE name ADD COLUMN column type ...  — and nothing else.
    for match in re.finditer(
        r"ALTER\s+TABLE\s+([\w\"]+)\s+ADD\s+COLUMN\s+([\w\"]+)\s+[\w\.\(\)\[\]]+",
        sql,
        re.I,
    ):
        slot_for(match.group(1).strip('"'))["columns"].add(match.group(2).strip('"'))

    # ALTER TABLE name ADD CONSTRAINT ... FOREIGN KEY (col) REFERENCES t (id)
    for match in re.finditer(
        r"ALTER\s+TABLE\s+([\w\"]+)\s+ADD\s+CONSTRAINT\s+[\w\"]+\s+"
        r"FOREIGN\s+KEY\s*\(\s*([\w\"]+)\s*\)\s*REFERENCES\s+([\w\"]+)\s*\(\s*([\w\"]+)\s*\)",
        sql,
        re.I,
    ):
        add_foreign_key(
            match.group(1).strip('"'),
            match.group(2),
            match.group(3),
            match.group(4),
        )

    # ALTER TABLE name ADD UNIQUE (a, b)
    for match in re.finditer(
        r"ALTER\s+TABLE\s+([\w\"]+)\s+ADD\s+UNIQUE\s*\(([^)]*)\)", sql, re.I
    ):
        columns = tuple(sorted(item.strip().strip('"') for item in match.group(2).split(",")))
        slot_for(match.group(1).strip('"'))["uniques"].add(columns)

    for match in re.finditer(
        r"ALTER\s+TABLE\s+([\w\"]+)\s+DROP\s+COLUMN\s+([\w\"]+)", sql, re.I
    ):
        slot = tables.get(match.group(1).strip('"'))
        if slot:
            slot["columns"].discard(match.group(2).strip('"'))

    for match in re.finditer(
        r"CREATE\s+(UNIQUE\s+)?INDEX\s+(?:IF\s+NOT\s+EXISTS\s+)?([\w\"]+)"
        r"\s+ON\s+([\w\"]+)\s*(?:USING\s+\w+\s*)?\(([^)]*)\)",
        sql,
        re.I,
    ):
        slot = slot_for(match.group(3).strip('"'))
        columns = tuple(
            sorted(item.strip().strip('"') for item in match.group(4).split(","))
        )
        slot["indexes"].add(columns)
        name = match.group(2).strip('"')
        slot["index_names"].add(name)
        slot["indexes_by_name"][name] = columns
        if match.group(1):
            slot["uniques"].add(columns)

    return tables


def main() -> int:
    tables = model_tables()
    ddl = parse_ddl(migration_sql())

    problems: list[str] = []
    warnings: list[str] = []
    print(f"{'table':<32} {'modeles':>8} {'DDL':>6}")
    print("-" * 52)
    for name in sorted(tables):
        present = name in ddl
        print(
            f"{name:<32} {len(tables[name]['columns']):>8} "
            f"{len(ddl.get(name, {}).get('columns', ())) if present else 0:>6}"
            + ("" if present else "   <-- ABSENTE DU DDL")
        )
        if not present:
            problems.append(f"table declaree dans les modeles mais absente des migrations : {name}")

    print("-" * 52)
    for name in sorted(tables):
        if name not in ddl:
            continue
        model_columns = tables[name]["columns"]
        ddl_columns = ddl[name]["columns"]
        # Alembic's own bookkeeping table is not a model table and has no model counterpart.
        for column in sorted(model_columns - ddl_columns):
            problems.append(f"{name}.{column} : colonne dans le modele, absente des migrations")
        for column in sorted(ddl_columns - model_columns):
            problems.append(f"{name}.{column} : colonne dans les migrations, absente du modele")
        for column, target in sorted(tables[name]["foreign_keys"]):
            ddl_targets = ddl[name]["foreign_keys"]
            found = any(
                key_column == column
                and (key_target == target or key_target.split(".")[-1] == target.split(".")[-1])
                for key_column, key_target in ddl_targets
            )
            if not found:
                problems.append(
                    f"{name}.{column} : cle etrangere vers {target} declaree dans le modele, "
                    "absente des migrations"
                )
        # Index comparison is by covered columns, not by name. Five of them legitimately differ
        # in name between the models and the migrations — the model says
        # ``ix_assistant_citations_chunk`` where Alembic generated
        # ``ix_assistant_citations_chunk_id`` — while covering exactly the same column.
        # Reporting those as missing would be wrong; reporting nothing would hide a real
        # divergence between the test schema and the migrated one.
        ddl_index_columns = ddl[name]["indexes"]
        for index in sorted(tables[name]["index_names"] - ddl[name]["index_names"]):
            model_index = tables[name]["indexes_by_name"].get(index)
            covered = model_index is not None and model_index in ddl_index_columns
            if covered:
                twins = sorted(
                    ddl_name
                    for ddl_name, columns in ddl[name]["indexes_by_name"].items()
                    if columns == model_index
                )
                warnings.append(
                    f"{name}.{index} : doublon. La migration cree "
                    f"{', '.join(twins)} sur la ou les memes colonnes "
                    f"({', '.join(model_index)}), que le modele declare deux fois. "
                    "La colonne est donc bien indexee en production, mais une base creee "
                    "par create_all porterait deux index sur cette colonne."
                )
            else:
                problems.append(
                    f"{name}.{index} : index declare dans le modele sur "
                    f"{', '.join(model_index or ())}, aucune migration ne le cree"
                )

    print()
    if warnings:
        print(f"{len(warnings)} divergence(s) de nom, sans impact fonctionnel :")
        for item in warnings:
            print(f"  - {item}")
        print()
    if problems:
        print(f"{len(problems)} divergence(s) bloquante(s) entre modeles et migrations :")
        for item in problems:
            print(f"  - {item}")
        return 1
    print(
        f"Aucune divergence bloquante : {len(tables)} tables, "
        f"{sum(len(t['columns']) for t in tables.values())} colonnes, "
        f"{sum(len(t['foreign_keys']) for t in tables.values())} cles etrangeres, "
        f"{sum(len(t['index_names']) for t in tables.values())} index, "
        "concordants entre les modeles et le DDL."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
