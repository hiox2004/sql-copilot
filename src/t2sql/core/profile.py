"""A database profile: the small YAML in data/profiles/ that says which database this is.

A profile ties together a dialect name (which adapter to use), the schema to read, and where its
dictionary lives. Adding a second database means adding one profile plus one dictionary.
"""

from pathlib import Path
from typing import Annotated

import yaml
from pydantic import BaseModel, ConfigDict, StringConstraints, ValidationError

_Name = Annotated[str, StringConstraints(strict=True, pattern=r"^[a-z][a-z0-9_]*$", max_length=64)]


class Profile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: _Name
    dialect: _Name
    schema_name: _Name  # the database schema to read (a namespace), usually "public"
    dictionary: Annotated[str, StringConstraints(strict=True, min_length=1)]  # repo-relative path


def load_profile(path: Path) -> Profile:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"cannot read profile {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ValueError(f"invalid YAML in profile {path}: {exc}") from exc
    try:
        return Profile.model_validate(raw)
    except ValidationError as exc:
        raise ValueError(f"invalid profile {path}:\n{exc}") from exc
