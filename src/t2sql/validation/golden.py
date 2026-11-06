"""Golden queries: questions with a verified SQL answer, used to score the copilot.

Files live in data/eval/golden/<domain>.yaml. Every item is checked by actually executing it
(tests/integration/test_golden_set.py), so a golden answer is never just somebody's opinion.
"""

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

_Slug = Annotated[str, StringConstraints(strict=True, pattern=r"^[a-z][a-z0-9_]*$", max_length=64)]
_Text = Annotated[str, StringConstraints(strict=True, min_length=1, strip_whitespace=True)]


class GoldenItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: _Slug
    # Items that ask the same thing in different words share one template id. Train/test splits
    # are made by template, so the model is never tested on a template it practised on.
    template: _Slug
    question: Annotated[str, StringConstraints(strict=True, min_length=8, strip_whitespace=True)]
    sql: _Text
    difficulty: Literal["easy", "medium", "hard"]
    tags: list[_Slug] = Field(default_factory=list)
    order_matters: bool = False  # True for "top N" / "sorted by" questions
    expect_empty: bool = False  # True only when the correct answer really is zero rows


class GoldenFile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    domain: _Slug
    items: list[GoldenItem] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_ids(self) -> "GoldenFile":
        ids = [i.id for i in self.items]
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        if dupes:
            raise ValueError(f"duplicate golden ids in {self.domain}: {dupes}")
        return self


def load_golden_file(path: Path) -> GoldenFile:
    try:
        return GoldenFile.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    except (OSError, yaml.YAMLError, ValidationError) as exc:
        raise ValueError(f"invalid golden file {path}: {exc}") from exc


def load_all_golden(directory: Path) -> list[GoldenItem]:
    """Load every *.yaml in `directory`; ids must be unique across files."""
    items: list[GoldenItem] = []
    for path in sorted(directory.glob("*.yaml")):
        items.extend(load_golden_file(path).items)
    ids = [i.id for i in items]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    if dupes:
        raise ValueError(f"duplicate golden ids across files: {dupes}")
    return items
