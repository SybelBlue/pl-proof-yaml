import re
import warnings
from collections import OrderedDict
from collections.abc import Callable, Iterable
from dataclasses import replace
from itertools import count
from pathlib import Path
from typing import TypeGuard

from . import yaml
from .errors import (
    BadTypeError,
    MissingFieldError,
    NameParseError,
    ParseError,
    SafeLineLoader,
    UnrecognizedKeyError,
    UnsupportedValueError,
    err_linespan_ctxt,
    linespan,
    no_traceback,
    source_path_ctxt,
    with_err_context,
)
from .types import (
    Blank,
    DefDict,
    Distractor,
    Line,
    LineId,
    Proof,
    Subgoal,
    YamlDict,
    YamlIterable,
    YamlKey,
    YamlValue,
    keyed_iter,
)

_MATH_SEGMENT_RE = re.compile(r"(?<!\\)(\$\$|\$)(.+?)(?<!\\)\1", re.DOTALL)
_LATEX_COMMAND_RE = re.compile(r"\\[A-Za-z]+")
_IDENTIFIER_RE = re.compile(r"[A-Za-z](?:_(?:\{[^{}]+\}|[A-Za-z0-9]+))?")

DEFAULT_YAML_PATH = Path(__file__).with_name("contradiction.proofs")
_PROOF_LINE_DEFAULT_KEYS = frozenset(
    {"step", "depends", "dependents", "defines", "label"}
)
_SHORT_PROOF_FILE_SUFFIX = ".proof"
_PROOF_FILE_SUFFIX = ".proof.yaml"
_SHORT_PROOFS_FILE_SUFFIX = ".proofs"
_PROOFS_FILE_SUFFIX = ".proofs.yaml"
_SHORT_MANIFEST_FILE_SUFFIX = ".manifest"
_MANIFEST_FILE_SUFFIX = ".manifest.yaml"


def _has_proof_suffix(path: Path) -> bool:
    return path.name.endswith(_PROOF_FILE_SUFFIX) or path.name.endswith(
        _SHORT_PROOF_FILE_SUFFIX
    )


def _has_proofs_suffix(path: Path) -> bool:
    return path.name.endswith(_PROOFS_FILE_SUFFIX) or path.name.endswith(
        _SHORT_PROOFS_FILE_SUFFIX
    )


def _has_manifest_suffix(path: Path) -> bool:
    return path.name.endswith(_MANIFEST_FILE_SUFFIX) or path.name.endswith(
        _SHORT_MANIFEST_FILE_SUFFIX
    )


def _extract_identifiers_from_texts(*texts: str) -> list[str]:
    identifiers: list[str] = []
    seen: set[str] = set()

    for text in texts:
        for match in _MATH_SEGMENT_RE.finditer(text):
            math_segment = _LATEX_COMMAND_RE.sub("", match.group(2))
            for identifier in _IDENTIFIER_RE.findall(math_segment):
                if identifier not in seen:
                    seen.add(identifier)
                    identifiers.append(identifier)

    return identifiers


def extract_line_identifiers(step: str, blanks: Iterable[Blank]) -> list[str]:
    return _extract_identifiers_from_texts(step, *(blank.correct for blank in blanks))


def _split_comma_separated[T](
    text: str, resolve_token: Callable[[str], tuple[T, ...]]
) -> tuple[T, ...]:
    stripped = text.strip()
    if not stripped:
        return ()

    if "," not in stripped:
        return resolve_token(stripped)

    items = []
    for part in stripped.split(","):
        items.extend(_split_comma_separated(part, resolve_token))
    return tuple(items)


def _line_depends_ancestors(
    line_id: LineId,
    lines_by_id: dict[LineId, Line],
    memo: dict[LineId, set[LineId]],
    visiting: set[LineId] | None = None,
) -> set[LineId]:
    if line_id in memo:
        return memo[line_id]
    if visiting is None:
        visiting = set()
    if line_id in visiting:
        return set()

    line = lines_by_id.get(line_id)
    if line is None:
        memo[line_id] = set()
        return memo[line_id]

    visiting.add(line_id)
    if line.depends_any_of:
        alternative_ancestors: list[set[LineId]] = []
        for alternative in line.depends_any_of:
            ancestors = set(alternative)
            for dep in alternative:
                ancestors.update(
                    _line_depends_ancestors(dep, lines_by_id, memo, visiting)
                )
            alternative_ancestors.append(ancestors)
        memo[line_id] = set.intersection(*alternative_ancestors)
        visiting.remove(line_id)
        return memo[line_id]

    ancestors: set[LineId] = set()
    for dep in (*line.depends, *line.implicit_depends):
        ancestors.add(dep)
        ancestors.update(_line_depends_ancestors(dep, lines_by_id, memo, visiting))

    memo[line_id] = ancestors
    visiting.remove(line_id)
    return memo[line_id]


def _split_depends(
    depends: Iterable[LineId], lines_by_id: dict[LineId, Line]
) -> tuple[frozenset[LineId], frozenset[LineId]]:
    unique_depends = tuple(dict.fromkeys(depends))
    memo: dict[LineId, set[LineId]] = {}
    ancestor_map = {
        dep: set(_line_depends_ancestors(dep, lines_by_id, memo))
        for dep in unique_depends
    }
    direct_depends = tuple(
        dep
        for dep in unique_depends
        if not any(
            dep in ancestor_map[other] for other in unique_depends if other != dep
        )
    )
    direct_set = set(direct_depends)
    implicit_depends = tuple(
        ancestor
        for dep in direct_depends
        for ancestor in _line_depends_ancestors(dep, lines_by_id, memo)
        if ancestor not in direct_set
    )
    return frozenset(direct_depends), frozenset(implicit_depends)


def _prune_impossible_alternatives(lines: Iterable[Line]) -> list[Line]:
    lines = tuple(lines)

    def _unavoidably_reaches(target: LineId) -> set[LineId]:
        unavoidable = {target}
        changed = True
        while changed:
            changed = False
            for candidate in lines:
                if candidate.id in unavoidable:
                    continue
                if candidate.depends_any_of:
                    reaches_target = all(
                        any(dep in unavoidable for dep in alternative)
                        for alternative in candidate.depends_any_of
                    )
                else:
                    reaches_target = any(
                        dep in unavoidable for dep in candidate.depends
                    )
                if reaches_target:
                    unavoidable.add(candidate.id)
                    changed = True
        return unavoidable

    pruned_lines: list[Line] = []
    for line in lines:
        if not line.depends_any_of:
            pruned_lines.append(line)
            continue

        unavoidable = _unavoidably_reaches(line.id)
        viable_alternatives = tuple(
            alternative
            for alternative in line.depends_any_of
            if not any(dep in unavoidable for dep in alternative)
        )
        if not viable_alternatives:
            raise ParseError(
                f"All dependency alternatives for line {line.id} are circular"
            )

        viable_depends = frozenset(
            dependency
            for alternative in viable_alternatives
            for dependency in alternative
        )
        pruned_lines.append(
            replace(
                line,
                depends=viable_depends,
                depends_any_of=viable_alternatives,
            )
        )

    return pruned_lines


def _check_reference_dag(lines: Iterable[Line]) -> None:
    lines_by_id = {line.id: line for line in lines}
    visiting: set[LineId] = set()
    visited: set[LineId] = set()
    stack: list[LineId] = []

    def _visit(node: LineId) -> None:
        if node in visited:
            return
        if node in visiting:
            cycle_start = stack.index(node)
            cycle = (*stack[cycle_start:], node)
            raise ParseError(
                f"Circular dependency detected: {' -> '.join(map(str, cycle))}"
            )

        visiting.add(node)
        stack.append(node)
        try:
            line = lines_by_id[node]
            dependencies = () if line.depends_any_of else line.depends
            for dependency in dependencies:
                if dependency in lines_by_id:
                    _visit(dependency)
        finally:
            stack.pop()
            visiting.remove(node)
        visited.add(node)

    for line_id in lines_by_id:
        _visit(line_id)


def _parse_depends(
    raw_depends: YamlValue,
    previous_lines: tuple[LineId, ...],
    known_vars: DefDict,
    current_line: LineId,
) -> tuple[YamlKey, ...]:
    def _mark_first_use(identifier: str) -> None:
        known_vars.set_first_use(identifier, current_line)

    def _resolve_known_var_token(token: str) -> tuple[YamlKey, ...]:
        stripped = token.strip()
        if not stripped:
            return ()
        if stripped in known_vars:
            _mark_first_use(stripped)
            return (known_vars[stripped].id,)

        identifiers = _extract_identifiers_from_texts(stripped)
        if not identifiers:
            raise NameParseError((stripped,))

        missing = tuple(name for name in identifiers if name not in known_vars)
        if missing:
            raise NameParseError(missing)

        resolved: list[YamlKey] = []
        for name in identifiers:
            _mark_first_use(name)
            resolved.append(known_vars[name].id)
        return tuple(resolved)

    def _parse_names(names: YamlValue) -> tuple[YamlKey, ...]:
        def _parse_name_text(text: str) -> tuple[YamlKey, ...]:
            stripped = text.strip()
            if not stripped:
                return ()
            if stripped.startswith("$") and stripped.endswith("$"):
                return _resolve_known_vars(stripped)
            return _resolve_known_var_token(stripped)

        match names:
            case str() as raw_text:
                return _split_comma_separated(raw_text, _parse_name_text)
            case list() | tuple():
                items: list[YamlKey] = []
                for part in names:
                    items.extend(_parse_names(part))
                return tuple(items)
            case float():
                raise BadTypeError((str, list), float, kind="depends.names value")
            case int():
                raise BadTypeError((str, list), int, kind="depends.names value")
            case _:
                raise NameParseError((str(names),))

    def _parse_lines_refs(lines: YamlValue) -> tuple[YamlKey, ...]:
        def _parse_line_text(text: str) -> tuple[YamlKey, ...]:
            stripped = text.strip()
            if not stripped:
                return ()
            if stripped.isdigit():
                return (int(stripped),)
            raise UnsupportedValueError(lines, kind="depends.lines")

        match lines:
            case str() as raw_text:
                return _split_comma_separated(raw_text, _parse_line_text)
            case list() | tuple():
                items: list[YamlKey] = []
                for part in lines:
                    items.extend(_parse_lines_refs(part))
                return tuple(items)
            case int() as line_id if type(line_id) is int:
                return (line_id,)
            case _:
                raise BadTypeError(
                    (int, list, tuple, str),
                    type(lines),
                    kind="depends.lines value",
                )

    def _take_previous(count: int) -> tuple[YamlKey, ...]:
        if count < 0:
            raise ParseError("previous depends count must be non-negative")
        if count == 0:
            return ()
        if count == 1 > len(previous_lines):
            return ()
        if count > len(previous_lines):
            raise ParseError(
                f"depends requests {count} previous lines, but only {len(previous_lines)} are available"
            )
        return previous_lines[-count:]

    def _parse_keyword(keyword, value) -> tuple[YamlKey, ...]:
        match keyword.strip().lower():
            case "all-previous" | "all previous":
                return previous_lines
            case "previous":
                match value:
                    case "all":
                        return previous_lines
                    case str() if value.strip().isdigit():
                        return _take_previous(int(value.strip()))
                    case int() as count if type(count) is int:
                        return _take_previous(count)
                    case str():
                        raise UnsupportedValueError(value, kind="previous depends")
                    case _:
                        raise BadTypeError(
                            (int, str), type(value), kind="previous depends value"
                        )
            case _:
                raise ParseError(f"Unknown depends keyword: {keyword}")

    def _resolve_known_vars(reference: str) -> tuple[YamlKey, ...]:
        stripped = reference.strip()
        if stripped.startswith("$") and stripped.endswith("$"):
            literal = stripped[1:-1].strip()
            return _split_comma_separated(literal, _resolve_known_var_token)

        return _resolve_known_var_token(stripped)

    def _parse_value(dep: YamlValue) -> tuple[YamlKey, ...]:
        match dep:
            case int() as line_id if type(line_id) is int:
                return (line_id,)
            case dict() as mapping:
                mapping = {
                    keyword: value
                    for keyword, value in mapping.items()
                    if keyword != "__linespan__"
                }
                if not mapping:
                    return ()
                items: list[YamlKey] = []
                for keyword, value in mapping.items():
                    if str(keyword).strip().lower() == "names":
                        items.extend(_parse_names(value))
                    elif str(keyword).strip().lower() == "lines":
                        items.extend(_parse_lines_refs(value))
                    else:
                        items.extend(_parse_keyword(str(keyword), value))
                return tuple(items)
            case str() as raw_text:
                text = raw_text.strip()
                lowered = text.lower()
                match lowered:
                    case "":
                        return ()
                    case "previous":
                        return _take_previous(1)
                    case "all-previous" | "all previous":
                        return previous_lines
                    case _ if text.startswith("$") and text.endswith("$"):
                        return _resolve_known_vars(text)
                    case _ if lowered.startswith("previous:"):
                        return _parse_keyword("previous", text[text.index(":") + 1 :])
                    case _ if "," in text:
                        items: list[YamlKey] = []
                        for part in text.split(","):
                            items.extend(_parse_value(part))
                        return tuple(items)
                    case _ if text.isdigit():
                        return (int(text),)
                    case _:
                        return _resolve_known_vars(text)
            case list() | tuple():
                items: list[YamlKey] = []
                for part in dep:
                    items.extend(_parse_value(part))
                return tuple(items)
            case _:
                raise BadTypeError(
                    (int, dict, list, tuple, str),
                    type(dep),
                    kind="depends value",
                )

    return tuple(dict.fromkeys(_parse_value(raw_depends)))


def _parse_depends_any_of(
    raw_depends: YamlValue,
    previous_lines: tuple[LineId, ...],
    known_vars: DefDict,
    current_line: LineId,
) -> tuple[tuple[YamlKey, ...], ...] | None:
    if not isinstance(raw_depends, dict) or "anyOf" not in raw_depends:
        return None

    alternatives = raw_depends["anyOf"]
    if not isinstance(alternatives, list):
        raise BadTypeError(list, type(alternatives), kind="depends.anyOf value")
    if not alternatives:
        raise ParseError("depends.anyOf must contain at least one alternative")
    return tuple(
        _parse_depends(alternative, previous_lines, known_vars, current_line)
        for alternative in alternatives
    )


def _parse_dependents(raw_dependents: YamlValue) -> bool:
    if raw_dependents is None:
        return False

    if not isinstance(raw_dependents, str):
        raise BadTypeError(str, type(raw_dependents), kind="dependents value")
    if raw_dependents.strip() in ("all below", "all-below"):
        return True

    raise UnsupportedValueError(raw_dependents, kind="dependents")


@with_err_context(label_template="Blank {id}")
def _parse_blank(id: YamlKey, blank_value: YamlValue):
    if not isinstance(blank_value, dict):
        raise BadTypeError(dict, type(blank_value), kind="Blank dictionary")
    correct = str(_require(blank_value, "correct", kind="Blank")[0])

    return Blank(
        id,
        correct,
        _parse_incorrect(blank_value.get("incorrect", ""), split_strings=True),
    )


def _parse_incorrect(value: YamlValue, *, split_strings: bool = False) -> list[str]:
    if isinstance(value, str):
        if not split_strings:
            return [value]
        return [s.strip() for s in value.split(",")]
    if isinstance(value, list):
        return list(map(str, value))
    return [str(value)]


def _require(data: YamlDict, *fields: YamlKey, kind=""):
    missing = tuple(field for field in fields if field not in data)
    if missing:
        raise MissingFieldError.from_fields(missing, kind=kind)
    return tuple(data.pop(field) for field in fields)


def _legacy_to_dataclass(proof):
    if not (
        len(proof.proof_steps)
        == len(proof.correct)
        == len(proof.incorrect)
        == len(proof.depends)
    ):
        raise ValueError(f"Mismatched proof data lengths for proof: {proof.problem!r}")

    line_map: OrderedDict[LineId, Line] = OrderedDict()
    definitions = DefDict()
    for line_id, step, correct, incorrect, depends in zip(
        count(start=1),
        proof.proof_steps,
        proof.correct,
        proof.incorrect,
        proof.depends,
    ):
        blanks = (Blank(id="BLANK", correct=correct, incorrect=[incorrect]),)
        uses = tuple(extract_line_identifiers(step, blanks))
        defines = tuple(
            identifier for identifier in uses if identifier not in definitions
        )
        raw_depends = _parse_depends(depends, tuple(line_map), definitions, line_id)
        direct_depends, implicit_depends = _split_depends(raw_depends, line_map)
        line = Line(
            id=line_id,
            step=step,
            blanks=blanks,
            depends=direct_depends,
            implicit_depends=implicit_depends,
            defines=defines,
            uses=uses,
        )
        line_map[line_id] = line
        for identifier in defines:
            definitions[identifier] = line
    return Proof(
        problem=proof.problem,
        lines=list(line_map.values()),
        hint=getattr(proof, "hint", ""),
    )


def legacy_proofs_to_dataclasses(proofs):
    return [_legacy_to_dataclass(p) for p in proofs]


def _parse_remainder_as_blanks(step: str, line_yaml: YamlDict):
    if "correct" in line_yaml or "incorrect" in line_yaml:
        if "correct" not in line_yaml:
            raise ParseError("Cannot have `incorrect` without `correct`")
        if "blanks" in line_yaml:
            raise ParseError(
                "Top-level `correct`/`incorrect` cannot be mixed with `blanks`."
            )
        if step.count("BLANK") != 1:
            raise ParseError(
                "Top-level `correct`/`incorrect` can only be used when the step has exactly one BLANK."
            )
        b = Blank(
            "BLANK",
            correct=str(line_yaml.pop("correct")),
            incorrect=_parse_incorrect(line_yaml.pop("incorrect", "")),
        )
        line_yaml.pop("__linespan__", None)
        if line_yaml:
            raise UnrecognizedKeyError(tuple(line_yaml.keys()))
        return (b,)

    raw_blanks = line_yaml.pop("blanks", None)
    line_yaml.pop("__linespan__", None)
    if line_yaml:
        raise UnrecognizedKeyError(tuple(line_yaml.keys()))
    if raw_blanks is None:
        return ()
    if not isinstance(raw_blanks, dict):
        raise BadTypeError(dict, type(raw_blanks), kind="Blanks dictionary")
    raw_blanks.pop("__linespan__", None)
    if not raw_blanks:
        raise ParseError("`blanks` must define at least one named blank.")
    return tuple(_parse_blank(id, value) for id, value in raw_blanks.items())


def _apply_line_defaults(
    line_yaml: YamlValue, default_line_yaml: YamlDict | None
) -> YamlValue:
    if not default_line_yaml:
        return line_yaml

    if isinstance(line_yaml, str):
        line_yaml = {"step": line_yaml}

    if not isinstance(line_yaml, dict):
        return line_yaml

    for key, value in default_line_yaml.items():
        line_yaml.setdefault(key, value)

    return line_yaml


def _next_generated_line_id(line_map: dict[LineId, Line]) -> int:
    numeric_ids = [line_id for line_id in line_map if isinstance(line_id, int)]
    return max(numeric_ids, default=0) + 1


def _is_subgoal_yaml(line_yaml: YamlValue) -> TypeGuard[YamlDict]:
    return isinstance(line_yaml, dict) and "subgoal" in line_yaml


def _expect_line_collection(value: YamlValue, *, kind: str) -> YamlIterable:
    if not isinstance(value, (list, dict)):
        raise BadTypeError((list, dict), type(value), kind=kind)
    return value


@with_err_context(label_template="Distractor {id}")
def _parse_distractor(id: YamlKey, value: YamlValue) -> Distractor:
    if isinstance(value, str):
        return Distractor(step=value)
    if not isinstance(value, dict):
        raise BadTypeError((str, dict), type(value))

    (step,) = _require(value, "step", kind="distractor")
    step = str(step)
    blanks = _parse_remainder_as_blanks(step, value)
    _check_blanks(step, blanks)
    return Distractor(step=step, blanks=blanks)


def _parse_distractors(value: YamlValue, *, kind: str) -> tuple[Distractor, ...]:
    if not isinstance(value, list):
        raise BadTypeError(list, type(value), kind=kind)

    return tuple(
        _parse_distractor(index, item) for index, item in enumerate(value, start=1)
    )


@with_err_context(label_template="Line.defines {id}")
def _parse_defines(_line_id: YamlKey, raw_defines: YamlValue) -> tuple[str, ...]:
    def _parse_define_value(value: YamlValue) -> tuple[str, ...]:
        match value:
            case str() as raw_text:
                stripped = raw_text.strip()
                if not stripped:
                    return ()
                if stripped.startswith("$") and stripped.endswith("$"):
                    return _split_comma_separated(
                        stripped[1:-1], lambda token: (token.strip(),)
                    )
                return _split_comma_separated(stripped, lambda token: (token.strip(),))
            case list() | tuple():
                items: list[str] = []
                for part in value:
                    items.extend(_parse_define_value(part))
                return tuple(items)
            case int() | float():
                return (str(value),)
            case None:
                return ()
            case _:
                raise NameParseError((str(value),))

    return tuple(dict.fromkeys(_parse_define_value(raw_defines)))


def _check_blanks(step_str: str, blanks: Iterable[Blank]) -> None:
    for b in blanks:
        blank_stub = str(b.id)
        if blank_stub not in step_str:
            raise ParseError(
                f"The step doesn't have {blank_stub} but blank data was given for it."
            )


@with_err_context(label_template="Proof Line {id}")
def _parse_line(
    id: YamlKey,
    line_yaml: YamlValue,
    line_map: dict[LineId, Line],
    defined_vars: DefDict,
    inherited_depends: set[LineId],
    default_line_yaml: YamlDict | None,
) -> Line:
    line_yaml = _apply_line_defaults(line_yaml, default_line_yaml)

    if isinstance(line_yaml, str):
        return Line(id, line_yaml)

    if not isinstance(line_yaml, dict):
        raise BadTypeError(dict, type(line_yaml))

    (step,) = _require(line_yaml, "step", kind="proof line")
    step = str(step)

    raw_depends = line_yaml.pop("depends", None)
    raw_dependents = line_yaml.pop("dependents", None)
    raw_defines = line_yaml.pop("defines", None)
    raw_label = line_yaml.pop("label", None)
    raw_distractors = line_yaml.pop("distractors", None)
    if raw_defines is not None and raw_label is not None:
        raise ParseError("Use either `label` or `defines`, not both.")
    if raw_defines is None:
        raw_defines = raw_label
    raw_depends_lineno = linespan(raw_depends)

    blanks = _parse_remainder_as_blanks(step, line_yaml)
    _check_blanks(step, blanks)

    uses = tuple(extract_line_identifiers(step, blanks))

    inferred_defines = tuple(
        identifier for identifier in uses if identifier not in defined_vars
    )
    depends_any_of = None
    if raw_depends is None:
        depends = ()
    else:
        with err_linespan_ctxt(raw_depends_lineno):
            depends_any_of = _parse_depends_any_of(
                raw_depends, tuple(line_map), defined_vars, id
            )
            depends = (
                _parse_depends(raw_depends, tuple(line_map), defined_vars, id)
                if depends_any_of is None
                else tuple(
                    dict.fromkeys(
                        dependency
                        for alternative in depends_any_of
                        for dependency in alternative
                    )
                )
            )

    user_defines = _parse_defines(id, raw_defines)
    for identifier in user_defines:
        if identifier not in defined_vars:
            continue
        first_use = defined_vars.get_first_use_id(identifier)
        if first_use is not None:
            raise ParseError(
                f"Cannot redefine {identifier!r} on line {id}; it was first used on line {first_use}."
            )
        previous_line = defined_vars[identifier]
        if identifier in previous_line.defines:
            line_map[previous_line.id] = replace(
                previous_line,
                defines=tuple(
                    existing
                    for existing in previous_line.defines
                    if existing != identifier
                ),
            )

    defines = tuple(dict.fromkeys((*inferred_defines, *user_defines)))

    depends = (*inherited_depends, *depends)
    if depends_any_of is None:
        depends, implicit_depends = _split_depends(depends, line_map)
        parsed_depends_any_of = ()
    else:
        split_alternatives = tuple(
            _split_depends((*inherited_depends, *alternative), line_map)
            for alternative in depends_any_of
        )
        parsed_depends_any_of = tuple(direct for direct, _ in split_alternatives)
        depends = frozenset(
            dependency
            for alternative in parsed_depends_any_of
            for dependency in alternative
        )
        implicit_depends = frozenset.intersection(
            *(implicit for _, implicit in split_alternatives)
        )
    dependents = "all" if _parse_dependents(raw_dependents) else None
    distractors = (
        ()
        if raw_distractors is None
        else _parse_distractors(raw_distractors, kind="line distractors")
    )
    return Line(
        id=id,
        step=step,
        blanks=blanks,
        depends=depends,
        implicit_depends=implicit_depends,
        depends_any_of=parsed_depends_any_of,
        defines=defines,
        uses=uses,
        dependents=dependents,
        distractors=distractors,
    )


@with_err_context(label_template="Proof Subgoal {id}")
def _parse_subgoal(
    id: YamlKey,
    subgoal_yaml: YamlDict,
    line_map: OrderedDict[LineId, Line],
    defined_vars: DefDict,
    inherited_depends: set[LineId],
    default_line_yaml: YamlDict | None,
    parent_id: LineId | None = None,
) -> None:
    if "step" in subgoal_yaml:
        nested_lines = subgoal_yaml.pop("subgoal")
        if "lines" in subgoal_yaml:
            raise ParseError(
                "Use `subgoal`, not `lines`, for nested lines on a subgoal header."
            )
        nested_lines = _expect_line_collection(nested_lines, kind="subgoal")
        header_yaml = subgoal_yaml
    else:
        title, nested_lines = _require(subgoal_yaml, "subgoal", "lines", kind="subgoal")
        if not isinstance(title, str):
            raise BadTypeError(str, type(title), kind="subgoal")
        nested_lines = _expect_line_collection(nested_lines, kind="subgoal lines")

        header_yaml: YamlDict = {"step": title}
        for key in ("depends", "dependents", "defines", "label"):
            if key in subgoal_yaml:
                header_yaml[key] = subgoal_yaml.pop(key)

        subgoal_yaml.pop("__linespan__", None)
        if subgoal_yaml:
            raise UnrecognizedKeyError(tuple(subgoal_yaml.keys()), kind="subgoal")

    header_line = _parse_line(
        id,
        header_yaml,
        line_map,
        defined_vars,
        inherited_depends,
        default_line_yaml=None,
    )
    line_map[header_line.id] = header_line
    for identifier in header_line.defines:
        defined_vars[identifier] = header_line

    nested_inherited_depends = {*inherited_depends, header_line.id}
    nested_start_ids = set(line_map)
    _parse_lines_into(
        nested_lines,
        line_map,
        defined_vars,
        nested_inherited_depends,
        default_line_yaml,
        parent_id=header_line.id,
    )

    nested_line_ids = tuple(
        line_id for line_id in line_map if line_id not in nested_start_ids
    )
    line_map[header_line.id] = replace(
        header_line,
        subgoal=Subgoal(
            line_ids=nested_line_ids,
            parent_id=parent_id,
        ),
    )


def _parse_lines_into(
    lines: YamlIterable,
    line_map: OrderedDict[LineId, Line],
    defined_vars: DefDict,
    inherited_depends: set[LineId],
    default_line_yaml: YamlDict | None,
    parent_id: LineId | None = None,
) -> None:
    local_inherited_depends = set(inherited_depends)
    for line_id, line_yaml in keyed_iter(lines):
        if isinstance(lines, list):
            line_id = _next_generated_line_id(line_map)

        if _is_subgoal_yaml(line_yaml):
            _parse_subgoal(
                line_id,
                line_yaml,
                line_map,
                defined_vars,
                local_inherited_depends,
                default_line_yaml,
                parent_id=parent_id,
            )
            continue

        line = _parse_line(
            line_id,
            line_yaml,
            line_map,
            defined_vars,
            local_inherited_depends,
            default_line_yaml,
        )

        line_map[line.id] = line

        for identifier in line.defines:
            defined_vars[identifier] = line

        if line.dependents == "all":
            local_inherited_depends.add(line.id)


@with_err_context(label_template="Proof {id} defaults")
def _parse_line_defaults(_thm_id: YamlKey, yaml: YamlValue) -> YamlDict:
    if not isinstance(yaml, dict):
        raise BadTypeError(dict, type(yaml), kind="proof default")
    unsupported_default_keys = tuple(
        key
        for key in yaml
        if key != "__linespan__" and key not in _PROOF_LINE_DEFAULT_KEYS
    )
    if unsupported_default_keys:
        raise ParseError(
            f"Unsupported proof line default key(s): {', '.join(map(str, unsupported_default_keys))}"
        )
    return {
        key: value
        for key, value in yaml.items()
        if key == "__linespan__" or key in _PROOF_LINE_DEFAULT_KEYS
    }


@with_err_context(label_template="Proof {id}")
def _parse_proof(
    id: YamlKey, yaml: YamlValue, *, warn_keyed_lines: bool = False
) -> Proof:
    if not isinstance(yaml, dict):
        raise BadTypeError(dict, type(yaml), kind="proof")

    problem, lines = _require(yaml, "problem", "lines", kind="proof")
    _ = linespan(lines)
    lines = _expect_line_collection(lines, kind="lines")
    if warn_keyed_lines and isinstance(lines, dict):
        warnings.warn(
            "Explicit keyed line maps are legacy authoring syntax; "
            "use list-based lines in .proof.yaml files.",
            stacklevel=2,
        )

    default_line_yaml = None
    raw_defaults = yaml.pop("defaults", None)
    if raw_defaults is None:
        raw_defaults = yaml.pop("default", None)
    if raw_defaults is not None:
        default_line_yaml = _parse_line_defaults(id, raw_defaults)

    raw_distractors = yaml.pop("distractors", None)
    distractors = (
        ()
        if raw_distractors is None
        else _parse_distractors(raw_distractors, kind="proof distractors")
    )

    line_map: OrderedDict[LineId, Line] = OrderedDict()
    defs = DefDict()
    _parse_lines_into(
        lines,
        line_map,
        defs,
        inherited_depends=set(),
        default_line_yaml=default_line_yaml,
    )

    lines = _prune_impossible_alternatives(line_map.values())
    _check_reference_dag(lines)

    return Proof(
        problem=str(problem),
        lines=lines,
        hint=str(yaml.get("hint", "")),
        distractors=distractors,
    )


def _load_yaml(path: Path) -> YamlValue:
    return yaml.load(path.read_text(encoding="utf-8"), Loader=SafeLineLoader) or []


def _resolve_manifest_proof_path(manifest_path: Path, proof_path: str) -> Path:
    resolved_path = manifest_path.parent / proof_path
    if (
        resolved_path.name.endswith(_SHORT_PROOF_FILE_SUFFIX)
        and not resolved_path.exists()
    ):
        resolved_path = resolved_path.with_name(resolved_path.name + ".yaml")
    return resolved_path


def _load_manifest_proofs(path: Path, loaded: YamlValue) -> list[Proof]:
    manifest = loaded.get("proofs") if isinstance(loaded, dict) else None
    if manifest is None:
        raise ValueError("Manifest file missing `proofs` key.")
    if not isinstance(manifest, list):
        raise BadTypeError(list, type(manifest), kind="proofs")

    proofs: list[Proof] = []
    for proof_path in manifest:
        if not isinstance(proof_path, str):
            raise BadTypeError(str, type(proof_path), kind="proof path")
        proofs.extend(loads(_resolve_manifest_proof_path(path, proof_path)))
    return proofs


def _parse_loaded_proof_database(loaded: YamlValue, path: Path) -> list[Proof]:
    warn_keyed_lines = _has_proof_suffix(path)

    if isinstance(loaded, dict):
        return [
            _parse_proof(k, v, warn_keyed_lines=warn_keyed_lines)
            for k, v in loaded.items()
        ]

    if not isinstance(loaded, list):
        raise BadTypeError((list, dict), type(loaded), kind="proof database")

    return [
        _parse_proof(i, item, warn_keyed_lines=warn_keyed_lines)
        for i, item in enumerate(loaded)
    ]


def _load_proof_files_from_dir(path: Path) -> list[Proof]:
    manifest_paths: list[Path] = []
    proof_paths: list[Path] = []
    for child_path in path.iterdir():
        if _has_manifest_suffix(child_path):
            manifest_paths.append(child_path)
        elif _has_proof_suffix(child_path):
            proof_paths.append(child_path)

    match manifest_paths:
        case []:
            return [load(proof_path) for proof_path in proof_paths]
        case [manifest_path]:
            return loads(manifest_path)
        case manifests:
            raise ValueError(
                f"{len(manifests)} manifests found at {path}, expected one or none."
            )


def loads(path: str | Path) -> list[Proof]:
    """Loads Proof objects from a .proof, .proofs, or .manifest file, or a directory of such files"""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(str(path))
    if path.is_dir():
        return _load_proof_files_from_dir(path)

    if not (
        _has_manifest_suffix(path)
        or _has_proof_suffix(path)
        or _has_proofs_suffix(path)
        or path.name.endswith(".yaml")
    ):
        raise ValueError(
            "A proof path must be a .yaml, .proof, .proofs, or .manifest file,"
            "or a directory of containing .manifest or .proof files."
        )

    loaded = _load_yaml(path)

    with no_traceback(), source_path_ctxt(path):
        if _has_proof_suffix(path):
            return [_parse_proof(0, loaded, warn_keyed_lines=True)]
        if _has_manifest_suffix(path):
            return _load_manifest_proofs(path, loaded)
        return _parse_loaded_proof_database(loaded, path)


def load(path: str | Path) -> Proof:
    """Loads a single Proof object from a .proof file."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(str(path))

    if path.is_dir() or _has_manifest_suffix(path) or _has_proofs_suffix(path):
        proofs = loads(path)
        if len(proofs) != 1:
            raise ValueError(
                f"{len(proofs)} proofs found at {path}, expected one. "
                "(Use `loads` to load multiple proofs.)"
            )
        return proofs[0]

    if not (_has_proof_suffix(path) or path.name.endswith(".yaml")):
        raise ValueError(
            "A proof path must be a .yaml, .proof, .proofs, or .manifest file,"
            "or a directory of containing .manifest or .proof files."
        )

    loaded = _load_yaml(path)
    with no_traceback(), source_path_ctxt(path):
        return _parse_proof(
            f"@{path.name}",
            loaded,
            warn_keyed_lines=_has_proof_suffix(path),
        )


def parse(val: str | YamlIterable) -> Proof:
    """Parses the string/dict/list into a Proof. For loading from a file use load/loads."""
    data = val
    if isinstance(val, str):
        data = yaml.parse(val, Loader=SafeLineLoader)  # type: ignore

    with no_traceback():
        return _parse_proof(0, data, warn_keyed_lines=True)  # type: ignore
