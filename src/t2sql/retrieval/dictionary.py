"""Load and validate a dictionary YAML file.

Two things PyYAML does that would silently corrupt a dictionary, and how this loader handles them:
  1. Duplicate keys: the last one wins and the earlier one vanishes. We raise instead.
  2. YAML 1.1 booleans: unquoted on/off/yes/no become True/False. The models use strict
     strings, so the file must quote them ("on"); validation then points at the exact field.
"""

from pathlib import Path

import yaml
from pydantic import ValidationError

from t2sql.core.dictionary_models import Dictionary

_MERGE_TAG = "tag:yaml.org,2002:merge"


class DictionaryError(Exception):
    """A dictionary file could not be loaded. The message is written for humans."""


class _UniqueKeyLoader(yaml.SafeLoader):
    """SafeLoader that refuses duplicate mapping keys instead of silently keeping the last."""

    def construct_mapping(self, node, deep=False):  # noqa: ANN001 - signature fixed by PyYAML
        seen: dict[object, int] = {}
        for key_node, _value_node in node.value:
            if key_node.tag == _MERGE_TAG:
                continue
            key = self.construct_object(key_node, deep=True)
            try:
                hash(key)
            except TypeError:
                continue  # unhashable key: let PyYAML raise its own error
            line = key_node.start_mark.line + 1
            if key in seen:
                raise DictionaryError(
                    f"duplicate key {key!r} on line {line} (first used on line {seen[key]})"
                )
            seen[key] = line
        return super().construct_mapping(node, deep=deep)


def parse_dictionary(text: str, source: str = "<string>") -> Dictionary:
    """Parse YAML text into a validated Dictionary, or raise DictionaryError."""
    try:
        data = yaml.load(text, Loader=_UniqueKeyLoader)  # noqa: S506 - SafeLoader subclass
    except DictionaryError as exc:
        raise DictionaryError(f"{source}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise DictionaryError(f"{source}: invalid YAML: {exc}") from exc

    if not isinstance(data, dict):
        raise DictionaryError(f"{source}: the top level must be a mapping (meta, tables, ...)")

    try:
        return Dictionary.model_validate(data)
    except ValidationError as exc:
        raise DictionaryError(_format_validation_error(source, exc)) from exc


def load_dictionary(path: str | Path) -> Dictionary:
    """Read a dictionary YAML file and return it validated."""
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise DictionaryError(f"{path}: cannot read file: {exc.strerror or exc}") from exc
    return parse_dictionary(text, source=str(path))


def _format_validation_error(source: str, exc: ValidationError) -> str:
    errors = exc.errors()
    lines = [f"{source}: {len(errors)} problem(s) found:"]
    for err in errors:
        location = ".".join(str(part) for part in err["loc"]) or "(top level)"
        message = err["msg"].removeprefix("Value error, ")
        if err["type"] == "string_type" and isinstance(err.get("input"), bool):
            message += (
                f" (YAML read an unquoted word as {str(err['input']).lower()}: "
                'put on/off/yes/no/true/false in quotes, e.g. "on")'
            )
        lines.append(f"  - {location}: {message}")
    return "\n".join(lines)
