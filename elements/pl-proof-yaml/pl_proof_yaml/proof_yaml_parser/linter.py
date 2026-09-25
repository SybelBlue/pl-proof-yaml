from __future__ import annotations

import argparse
import glob
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from . import yaml
from .parse import loads
from .types import keyed_iter

_DEFAULT_DEPENDS_TEXT = "previous"
_DEFAULT_DEPENDS_THRESHOLD = 0.4


def _is_sequential_numbered_dict(lines: Any) -> bool:
    if not isinstance(lines, dict) or not lines:
        return False

    keys: list[int] = []
    for key, _ in keyed_iter(lines):
        if isinstance(key, int):
            keys.append(key)
        elif isinstance(key, str) and key.isdigit():
            keys.append(int(key))
        else:
            return False

    expected = list(range(1, len(keys) + 1))
    return keys == expected


def _depends_mentions_line_keys(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, int):
        return True
    if isinstance(value, str):
        return value.strip().isdigit()
    if isinstance(value, (list, tuple, set)):
        return any(_depends_mentions_line_keys(item) for item in value)
    if isinstance(value, dict):
        mapping = {k: v for k, v in value.items() if k != "__linespan__"}
        for key, inner in mapping.items():
            normalized_key = str(key).strip().lower()
            if normalized_key in {"lines", "anyof"} and _depends_mentions_line_keys(
                inner
            ):
                return True
        return False
    return False


def _is_numeric_depends_atom(value: Any) -> bool:
    return isinstance(value, int) or (
        isinstance(value, str) and value.strip().isdigit()
    )


def _depends_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip().lower()
        return text or None
    if isinstance(value, int):
        return str(value)
    if isinstance(value, dict):
        mapping = {k: v for k, v in value.items() if k != "__linespan__"}
        if len(mapping) == 1:
            key, inner = next(iter(mapping.items()))
            if str(key).strip().lower() == _DEFAULT_DEPENDS_TEXT and (
                inner == 1 or (isinstance(inner, str) and inner.strip() == "1")
            ):
                return _DEFAULT_DEPENDS_TEXT
        if x := yaml.safe_dump(mapping, sort_keys=True):
            return str(x.strip())
        return None
    if isinstance(value, (list, tuple)):
        parts = [part for part in (_depends_text(item) for item in value) if part]
        return ", ".join(parts) if parts else None
    return str(value).strip().lower() or None


def _default_depends_ratio(lines: Any) -> float:
    if not isinstance(lines, dict) or not lines:
        return 0.0

    signatures = Counter()
    total = 0
    for _, line in keyed_iter(lines):
        total += 1
        if isinstance(line, dict):
            signature = _depends_text(line.get("depends"))
            if signature is not None:
                signatures[signature] += 1

    if not signatures or total == 0:
        return 0.0

    top_signature, top_count = signatures.most_common(1)[0]
    if top_signature != _DEFAULT_DEPENDS_TEXT:
        return 0.0
    return top_count / total


def _get_defaults_bucket(theorem: dict[str, Any]) -> dict[str, Any]:
    defaults = theorem.get("defaults")
    if isinstance(defaults, dict):
        return defaults

    legacy_defaults = theorem.get("default")
    if isinstance(legacy_defaults, dict):
        return legacy_defaults

    defaults = {}
    theorem["defaults"] = defaults
    return defaults


def _strip_previous_depends(lines: Any) -> None:
    if not isinstance(lines, dict):
        return

    for _, line in keyed_iter(lines):
        if (
            isinstance(line, dict)
            and _depends_text(line.get("depends")) == _DEFAULT_DEPENDS_TEXT
        ):
            line.pop("depends", None)


def _get_existing_defaults_bucket(theorem: dict[str, Any]) -> dict[str, Any] | None:
    defaults = theorem.get("defaults")
    if isinstance(defaults, dict):
        return defaults

    legacy_defaults = theorem.get("default")
    if isinstance(legacy_defaults, dict):
        return legacy_defaults

    return None


def _strip_redeclared_default_depends(theorem: dict[str, Any]) -> bool:
    lines = theorem.get("lines")
    defaults = _get_existing_defaults_bucket(theorem)
    if not isinstance(lines, dict) or defaults is None:
        return False

    default_depends = _depends_text(defaults.get("depends"))
    if default_depends is None:
        return False

    changed = False
    for _, line in keyed_iter(lines):
        if not isinstance(line, dict) or "depends" not in line:
            continue
        if _depends_text(line.get("depends")) != default_depends:
            continue
        line.pop("depends", None)
        changed = True

    return changed


def _hoist_default_depends(theorem: dict[str, Any]) -> bool:
    lines = theorem.get("lines")
    if _default_depends_ratio(lines) < _DEFAULT_DEPENDS_THRESHOLD:
        return False

    defaults = _get_defaults_bucket(theorem)
    current_depends = _depends_text(defaults.get("depends"))
    if current_depends not in (None, _DEFAULT_DEPENDS_TEXT):
        return False
    if current_depends is None:
        defaults["depends"] = _DEFAULT_DEPENDS_TEXT
    _strip_previous_depends(lines)
    return True


def _can_unkey_theorem(theorem: dict[str, Any]) -> bool:
    lines = theorem.get("lines")
    if not _is_sequential_numbered_dict(lines):
        return False

    for _, line in keyed_iter(lines):  # type: ignore
        if isinstance(line, dict) and _depends_mentions_line_keys(line.get("depends")):
            return False
    return True


def _prune_depends_value(raw_depends: Any, keep_depends: set[Any]) -> Any:
    if raw_depends is None:
        return None
    if _is_numeric_depends_atom(raw_depends):
        return int(raw_depends) if int(raw_depends) in keep_depends else None
    if isinstance(raw_depends, list):
        pruned: list[Any] = []
        for item in raw_depends:
            pruned_item = _prune_depends_value(item, keep_depends)
            if pruned_item is not None:
                pruned.append(pruned_item)
        return pruned or None
    if isinstance(raw_depends, tuple):
        pruned = [
            item
            for item in (
                _prune_depends_value(item, keep_depends) for item in raw_depends
            )
            if item is not None
        ]
        return pruned or None
    if isinstance(raw_depends, dict):
        mapping = {k: v for k, v in raw_depends.items() if k != "__linespan__"}
        normalized_keys = {str(key).strip().lower() for key in mapping}
        if normalized_keys == {"lines"}:
            key = next(iter(mapping))
            pruned_lines = _prune_depends_value(mapping[key], keep_depends)
            if pruned_lines is None:
                return None
            return {key: pruned_lines}
        if normalized_keys == {"anyof"}:
            key = next(iter(mapping))
            alternatives = mapping[key]
            if not isinstance(alternatives, list):
                return raw_depends
            return {
                key: [
                    pruned if pruned is not None else []
                    for alternative in alternatives
                    for pruned in (_prune_depends_value(alternative, keep_depends),)
                ]
            }
        return raw_depends
    return raw_depends


def _unkey_theorems(data: list[dict[str, Any]], parsed_theorems: list[Any]) -> int:
    converted = 0
    for theorem, parsed_theorem in zip(data, parsed_theorems):
        changed = _hoist_default_depends(theorem)
        if _strip_redeclared_default_depends(theorem):
            changed = True
        inherited_all_below: set[Any] = set()
        lines = theorem.get("lines")
        if isinstance(lines, dict) and hasattr(parsed_theorem, "lines"):
            for (_, line_yaml), parsed_line in zip(
                keyed_iter(lines), parsed_theorem.lines
            ):
                if not isinstance(line_yaml, dict) or "depends" not in line_yaml:
                    if getattr(parsed_line, "dependents", None) == "all":
                        inherited_all_below.add(parsed_line.id)
                    continue

                keep_depends = set(parsed_line.depends) - inherited_all_below
                pruned_depends = _prune_depends_value(
                    line_yaml["depends"], keep_depends
                )
                if pruned_depends is None:
                    line_yaml.pop("depends", None)
                    changed = True
                elif pruned_depends != line_yaml["depends"]:
                    line_yaml["depends"] = pruned_depends
                    changed = True

                if getattr(parsed_line, "dependents", None) == "all":
                    inherited_all_below.add(parsed_line.id)
        if _can_unkey_theorem(theorem):
            theorem["lines"] = [line for _, line in keyed_iter(theorem["lines"])]
            changed = True
        if changed:
            converted += 1
    return converted


def _move_lines_last(theorem: dict[str, Any]) -> None:
    if "lines" not in theorem:
        return

    lines = theorem.pop("lines")
    theorem["lines"] = lines


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Parse theorem YAML, hoist repeated depends: previous defaults, "
            "and convert safe numbered lines mappings to list-style lines."
        )
    )
    parser.add_argument(
        "path",
        help="YAML file or glob pattern to rewrite",
    )
    parser.add_argument(
        "--in-place",
        action="store_true",
        help="Rewrite the YAML file instead of printing the transformed output.",
    )
    return parser


def _glob_paths(pattern: str) -> list[Path]:
    return [
        Path(match)
        for match in sorted(glob.glob(pattern, recursive=True))
        if Path(match).is_file()
    ]


def _theorems_to_lint(data: Any, path: Path) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and path.name.endswith((".proof", ".proof.yaml")):
        return [data]
    if isinstance(data, dict) and path.name.endswith((".manifest", ".manifest.yaml")):
        return []
    raise SystemExit(
        f"Expected {path} to contain a proof, proof database, or manifest."
    )


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    paths = _glob_paths(args.path)
    if not paths:
        parser.error(f"path pattern matched no files: {args.path}")

    converted = 0
    outputs: list[str] = []
    for path in paths:
        parsed_theorems = loads(path)
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        theorem_data = _theorems_to_lint(data, path)

        converted += _unkey_theorems(theorem_data, parsed_theorems)
        for theorem in theorem_data:
            if isinstance(theorem, dict):
                _move_lines_last(theorem)
        output = yaml.safe_dump(
            data,
            sort_keys=False,
            allow_unicode=True,
            default_flow_style=False,
            width=1000,
        )
        if output is None:
            continue

        if args.in_place:
            if isinstance(output, bytes):
                path.write_bytes(output)
            else:
                path.write_text(output, encoding="utf-8")
        else:
            outputs.append(str(output))

    if outputs:
        print("---\n".join(outputs), end="")

    print(f"Converted {converted} theorem block(s).", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
