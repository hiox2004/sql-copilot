"""Print the database structure compactly: columns, types, keys, allowed values.

Usage:  python scripts/show_schema.py                 (all tables)
        python scripts/show_schema.py users orders    (only these)
"""

import sys

import psycopg

from t2sql.core.config import REPO_ROOT, Settings
from t2sql.core.profile import load_profile
from t2sql.dialects import get_dialect


def main(names: list[str]) -> int:
    profile = load_profile(REPO_ROOT / "data" / "profiles" / "saas.yaml")
    with psycopg.connect(Settings.from_env().ro_dsn) as conn:
        schema = get_dialect(profile.dialect).introspect(conn, profile.schema_name)
    for table in schema.tables:
        if names and table.name not in names:
            continue
        print(f"{table.name}  (pk: {', '.join(table.primary_key)})")
        for col in table.columns:
            extra = f"  values: {list(col.enum_values)}" if col.enum_values else ""
            print(f"    {col.name} {col.data_type}{'' if col.nullable else ' NOT NULL'}{extra}")
        for fk in table.foreign_keys:
            print(f"    FK {','.join(fk.columns)} -> {fk.ref_table}({','.join(fk.ref_columns)})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
