"""The red-team set: attacks the copilot must block, and which safety layer must stop each one."""

from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    model_validator,
)

Layer = Literal["db_role", "guard_parser", "guard_limits", "guard_pii"]
Category = Literal["write", "ddl", "privilege", "stacking", "dos", "pii", "prompt_injection"]
_Text = Annotated[str, StringConstraints(strict=True, min_length=1)]


class RedTeamItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: Annotated[str, StringConstraints(strict=True, pattern=r"^[a-z][a-z0-9_]*$")]
    category: Category
    description: _Text
    question: _Text | None = None  # what an attacker types
    sql: _Text | None = None  # what a tricked model might emit
    blocked_by: Annotated[list[Layer], Field(min_length=1)]

    @model_validator(mode="after")
    def _has_something_to_run(self) -> "RedTeamItem":
        if self.question is None and self.sql is None:
            raise ValueError("an item needs a question, an sql, or both")
        if "db_role" in self.blocked_by and self.sql is None:
            raise ValueError("a db_role item must give the sql the database should refuse")
        return self


class RedTeamSet(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: int
    items: list[RedTeamItem]

    @model_validator(mode="after")
    def _unique_ids(self) -> "RedTeamSet":
        ids = [item.id for item in self.items]
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        if duplicates:
            raise ValueError(f"duplicate red-team ids: {duplicates}")
        return self

    def blocked_by(self, layer: str) -> list[RedTeamItem]:
        return [item for item in self.items if layer in item.blocked_by]


def load_redteam(path: Path) -> RedTeamSet:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        return RedTeamSet.model_validate(raw)
    except (OSError, yaml.YAMLError, ValidationError) as exc:
        raise ValueError(f"invalid red-team file {path}: {exc}") from exc
