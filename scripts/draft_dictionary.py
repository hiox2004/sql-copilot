"""Generate a draft dictionary for a database profile.

Usage (venv active, database running):
    python scripts/draft_dictionary.py saas
Writes data/dictionaries/<profile>.draft.yaml (refuses to overwrite a finished <profile>.yaml).
"""

import argparse
import sys

import psycopg

from t2sql.core.config import REPO_ROOT, Settings
from t2sql.core.profile import load_profile
from t2sql.dialects import get_dialect
from t2sql.retrieval.draft_dictionary import draft_dictionary_yaml


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile", help="profile id, e.g. saas (data/profiles/<id>.yaml)")
    args = parser.parse_args()

    profile = load_profile(REPO_ROOT / "data" / "profiles" / f"{args.profile}.yaml")
    dialect = get_dialect(profile.dialect)
    settings = Settings.from_env()

    # Read-only role: introspection only needs to read the catalog.
    with psycopg.connect(settings.ro_dsn) as conn:
        schema = dialect.introspect(conn, profile.schema_name)

    out_path = REPO_ROOT / "data" / "dictionaries" / f"{profile.id}.draft.yaml"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(draft_dictionary_yaml(schema, profile.id, dialect.name), encoding="utf-8")
    print(f"wrote {out_path} ({len(schema.tables)} tables)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
