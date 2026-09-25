from __future__ import annotations

import importlib.util
import re
import reprlib
import sys
from collections.abc import Callable
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from functools import wraps
from pathlib import Path
from types import ModuleType
from typing import Any, cast

import chevron
import lxml.html
import prairielearn as pl

PACKAGE_DIR = Path(__file__).resolve().parent

DEBUG_PROOF_YAML: ContextVar[bool] = ContextVar("DEBUG_PROOF_YAML", default=True)


@contextmanager
def debugging_mode(debug=True):
    id = DEBUG_PROOF_YAML.set(debug)
    try:
        yield id
    finally:
        DEBUG_PROOF_YAML.reset(id)


def _debug(message: str) -> None:
    if DEBUG_PROOF_YAML.get(False):
        print(f"[pl-proof-yaml] {message}", file=sys.stderr, flush=True)


def _with_debug_logging[**P, R](f: Callable[P, R]) -> Callable[P, R]:
    """Call `_debug` when the wrapped function starts and finishes."""

    @wraps(f)
    def inner(*args: P.args, **kwargs: P.kwargs) -> R:
        _debug(
            f"{f.__name__} called: "
            f"args={reprlib.repr(args)}, kwargs={reprlib.repr(kwargs)}"
        )
        try:
            out = f(*args, **kwargs)
        except:
            _debug(f"{f.__name__} erred!")
            raise

        _debug(f"{f.__name__} completed: retvalue={reprlib.repr(out)}")
        return out

    return inner


@_with_debug_logging
def _find_course_dir(path: Path) -> Path:
    for candidate in (path, *path.parents):
        if (candidate / "infoCourse.json").exists():
            return candidate
    return path.parents[2]


COURSE_DIR = _find_course_dir(PACKAGE_DIR)

_debug(f"module import: package_dir={PACKAGE_DIR}, course_dir={COURSE_DIR}")

from .proof_yaml_parser import Blank, Distractor, Proof, loads

TEMPLATE_FILE = PACKAGE_DIR / "pl-proof-yaml.mustache"
_ELEMENT_CONTROLLERS: dict[str, ModuleType] = {}

REQUIRED_ATTRIBS = ("answers-name",)
OPTIONAL_ATTRIBS = (
    "directory",
    "proof-file",
    "proof-dir",
    "proof-index",
    "grading-method",
    "source-blocks-order",
    "partial-credit",
    "feedback",
    "source-header",
    "solution-header",
    "solution-placement",
    "weight",
    "inline",
    "display-blocks",
    "allow-blank",
    "include-distractors",
    "hide-problem-statement",
)

DIRECTORY_OPTIONS = (
    "clientFilesCourse",
    "clientFilesQuestion",
    "question",
    "serverFilesCourse",
)


@dataclass(frozen=True)
class Block:
    parts: tuple[dict[str, Any], ...]
    correct: bool
    tag: str
    depends: str
    distractor_for: str | None = None


@dataclass(frozen=True)
class BlankDropdown:
    answers_name: str
    label: str
    width_ch: int
    choices: tuple[dict[str, str], ...]
    allow_blank: bool = False


def _get_string_attrib(
    element: Any, name: str, default: str | None = None
) -> str | None:
    value = pl.get_string_attrib(element, name, default)
    if isinstance(value, str):
        value = value.strip()
    return value or default


def _resolve_file(raw_path: str, directory: str, data: dict[str, Any]) -> Path:
    options = data["options"]
    if directory == "serverFilesCourse":
        root = Path(options["server_files_course_path"]).resolve()
    elif directory == "clientFilesCourse":
        root = Path(options["client_files_course_path"]).resolve()
    elif directory == "clientFilesQuestion":
        root = Path(
            options.get(
                "client_files_question_path",
                Path(options["question_path"]) / "clientFilesQuestion",
            )
        ).resolve()
    elif directory == "question":
        root = Path(options["question_path"]).resolve()
    else:
        choices = ", ".join(sorted(DIRECTORY_OPTIONS))
        raise ValueError(f"Attribute 'directory' must be one of: {choices}.")

    path = (root / raw_path).resolve()
    if root not in path.parents and path != root:
        raise ValueError(f"Path {raw_path!r} must stay inside {directory}.")
    _debug(f"resolved {directory}:{raw_path} -> {path} exists={path.exists()}")
    return path


def _load_proofs(element: Any, data: dict[str, Any]) -> list[Proof]:
    directory = cast(str, _get_string_attrib(element, "directory", "serverFilesCourse"))
    proof_file = _get_string_attrib(element, "proof-file")
    proof_dir = _get_string_attrib(element, "proof-dir")
    _debug(
        "load request: "
        f"directory={directory!r}, proof_file={proof_file!r}, proof_dir={proof_dir!r}"
    )

    if proof_file and proof_dir:
        raise ValueError("Use either 'proof-file' or 'proof-dir', not both.")
    if proof_file:
        return loads(_resolve_file(proof_file, directory, data))
    if proof_dir:
        return loads(_resolve_file(proof_dir, directory, data))

    raise ValueError("pl-proof-yaml requires either 'proof-file' or 'proof-dir'.")


def _line_parts_with_dropdowns(
    step: str, blanks: tuple[Blank, ...], dropdowns: list[BlankDropdown]
) -> tuple[dict[str, Any], ...]:
    parts: list[dict[str, Any]] = []
    remaining = step
    for blank, dropdown in zip(blanks, dropdowns, strict=True):
        blank_id = str(blank.id)
        marker = blank_id if blank_id in remaining else "BLANK"
        before, separator, after = remaining.partition(marker)
        if separator:
            parts.append({"text": before})
            parts.append({"dropdown": _dropdown_context(dropdown)})
            remaining = after
        else:
            parts.append({"text": remaining})
            remaining = ""
    if remaining:
        parts.append({"text": remaining})
    return tuple(parts)


def _line_tag(line_id: object) -> str:
    return "line-" + re.sub(r"[^A-Za-z0-9_-]", "-", str(line_id)).strip("-")


def _blank_answers_name(answers_name: str, line_tag: str, blank: Blank) -> str:
    blank_tag = re.sub(r"[^A-Za-z0-9_-]", "-", str(blank.id)).strip("-")
    return f"{answers_name}-{line_tag}-{blank_tag}"


def _dedupe_choices(blank: Blank) -> tuple[dict[str, str], ...]:
    choices: list[dict[str, str]] = []
    seen: set[str] = set()
    for value, correct in (
        (blank.correct, True),
        *((x, False) for x in blank.incorrect),
    ):
        if value in seen:
            continue
        seen.add(value)
        choices.append({"text": value, "correct": "true" if correct else "false"})
    return tuple(choices)


def _dropdown_context(dropdown: BlankDropdown) -> dict[str, Any]:
    return {
        "answers_name": dropdown.answers_name,
        "label": dropdown.label,
        "width_ch": dropdown.width_ch,
        "choices": list(dropdown.choices),
        "allow_blank": dropdown.allow_blank,
    }


def _dropdown_width_ch(choices: tuple[dict[str, str], ...]) -> int:
    return max((len(choice["text"]) for choice in choices), default=12)


def _make_blocks_and_dropdowns(
    theorem: Proof, answers_name: str
) -> tuple[list[Block], list[BlankDropdown]]:
    tags_by_id = {line.id: _line_tag(line.id) for line in theorem.lines}
    blocks: list[Block] = []
    dropdowns: list[BlankDropdown] = []
    has_unpaired_distractors = bool(theorem.distractors)

    def append_distractor(
        distractor: Distractor,
        tag: str,
        distractor_for: str | None = None,
        *,
        allow_blank: bool = False,
    ) -> None:
        distractor_dropdowns = [
            BlankDropdown(
                answers_name=_blank_answers_name(answers_name, tag, blank),
                label=f"{tag}:{blank.id}",
                width_ch=_dropdown_width_ch(choices := _dedupe_choices(blank)),
                choices=choices,
                allow_blank=allow_blank,
            )
            for blank in distractor.blanks
        ]
        dropdowns.extend(distractor_dropdowns)
        blocks.append(
            Block(
                parts=_line_parts_with_dropdowns(
                    distractor.step, distractor.blanks, distractor_dropdowns
                ),
                correct=False,
                tag=tag,
                depends="",
                distractor_for=distractor_for,
            )
        )

    for line in theorem.lines:
        line_tag = tags_by_id[line.id]
        group_allows_blank = has_unpaired_distractors or bool(line.distractors)
        line_dropdowns = [
            BlankDropdown(
                answers_name=_blank_answers_name(answers_name, line_tag, blank),
                label=f"{line_tag}:{blank.id}",
                width_ch=_dropdown_width_ch(choices := _dedupe_choices(blank)),
                choices=choices,
                allow_blank=group_allows_blank,
            )
            for blank in line.blanks
        ]
        dropdowns.extend(line_dropdowns)
        blocks.append(
            Block(
                parts=_line_parts_with_dropdowns(
                    line.step, line.blanks, line_dropdowns
                ),
                correct=True,
                tag=line_tag,
                depends="|".join(
                    ",".join(
                        tags_by_id[dependency]
                        for dependency in alternative
                        if dependency in tags_by_id
                    )
                    for alternative in (
                        line.depends_any_of if line.depends_any_of else (line.depends,)
                    )
                ),
            )
        )

        for index, distractor in enumerate(line.distractors, start=1):
            append_distractor(
                distractor,
                f"distractor-{line_tag}-{index}",
                distractor_for=line_tag,
                allow_blank=group_allows_blank,
            )

    for index, distractor in enumerate(theorem.distractors, start=1):
        append_distractor(
            distractor,
            f"distractor-global-{index}",
            allow_blank=True,
        )

    return blocks, dropdowns


def _render_template(template_file: Path, context: dict[str, Any]) -> str:
    with template_file.open(encoding="utf-8") as template:
        return chevron.render(
            template,
            context,
            partials_path=str(template_file.parent),
        )


def _render_order_blocks(html_params: dict[str, Any]) -> str:
    return _render_template(TEMPLATE_FILE, html_params)


def _render_multiple_choice(dropdown: BlankDropdown) -> str:
    return _render_template(
        PACKAGE_DIR / "pl-proof-yaml-multiple-choice.mustache",
        _dropdown_context(dropdown),
    )


def _find_element_controller(element_name: str) -> Path:
    controller_name = f"{element_name}.py"
    candidates = [
        Path.cwd() / "elements" / element_name / controller_name,
        Path.cwd()
        / "apps"
        / "prairielearn"
        / "elements"
        / element_name
        / controller_name,
    ]
    for parent in Path.cwd().parents:
        candidates.extend(
            [
                parent / "elements" / element_name / controller_name,
                parent
                / "apps"
                / "prairielearn"
                / "elements"
                / element_name
                / controller_name,
            ]
        )
    pl_path = Path(getattr(pl, "__file__", "")).resolve()
    for parent in pl_path.parents:
        candidates.extend(
            [
                parent / "elements" / element_name / controller_name,
                parent
                / "apps"
                / "prairielearn"
                / "elements"
                / element_name
                / controller_name,
            ]
        )
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    raise FileNotFoundError(f"Could not locate PrairieLearn's {controller_name}")


def _load_element_controller(element_name: str) -> ModuleType:
    if element_name in _ELEMENT_CONTROLLERS:
        return _ELEMENT_CONTROLLERS[element_name]

    controller_path = _find_element_controller(element_name)
    controller_dir = controller_path.parent
    if str(controller_dir) not in sys.path:
        sys.path.insert(0, str(controller_dir))

    if element_name == "pl-order-blocks":
        try:
            module = pl.load_host_script("pl-order-blocks.py")
        except ImportError:
            module = None
        if module is not None:
            _ELEMENT_CONTROLLERS[element_name] = module
            _debug(f"loaded {element_name} host script from {controller_path}")
            return module

    module_name = f"_pl_proof_yaml_{element_name.replace('-', '_')}"
    spec = importlib.util.spec_from_file_location(module_name, controller_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load {controller_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    _ELEMENT_CONTROLLERS[element_name] = module
    _debug(f"loaded {element_name} controller from {controller_path}")
    return module


@_with_debug_logging
def _build_parts(
    element_html: str | bytes, data: dict[str, Any]
) -> tuple[str, list[BlankDropdown], str | None]:
    _debug(f"build called with element_html={element_html!r}")
    element = lxml.html.fragment_fromstring(element_html)
    pl.check_attribs(element, list(REQUIRED_ATTRIBS), list(OPTIONAL_ATTRIBS))
    _debug(f"attributes after parse: {dict(element.attrib)}")

    proof_index = pl.get_integer_attrib(element, "proof-index", 0)
    proofs = _load_proofs(element, data)
    _debug(f"loaded {len(proofs)} proof(s), requested proof_index={proof_index}")
    if proof_index < 0 or proof_index >= len(proofs):
        raise ValueError(
            f"proof-index {proof_index} is out of range for {len(proofs)} proof(s)."
        )

    answers_name = cast(str, _get_string_attrib(element, "answers-name"))
    theorem = proofs[proof_index]
    blocks, dropdowns = _make_blocks_and_dropdowns(theorem, answers_name)
    correct_count = sum(1 for block in blocks if block.correct)
    _debug(
        f"selected proof problem={theorem.problem!r}; "
        f"blocks={len(blocks)}, correct={correct_count}, "
        f"dropdowns={len(dropdowns)}"
    )

    grading_method = _get_string_attrib(element, "grading-method", "dag")
    emit_dag_attrs = grading_method == "dag"

    html_params = {
        "answers_name": answers_name,
        "grading_method": grading_method,
        "source_blocks_order": _get_string_attrib(
            element, "source-blocks-order", "random-sections"
        ),
        "distractor_order": None,
        "partial_credit": _get_string_attrib(element, "partial-credit"),
        "feedback": _get_string_attrib(element, "feedback"),
        "source_header": _get_string_attrib(element, "source-header"),
        "solution_header": _get_string_attrib(element, "solution-header"),
        "solution_placement": _get_string_attrib(element, "solution-placement"),
        "max_incorrect": None,
        "min_incorrect": None,
        "weight": _get_string_attrib(element, "weight"),
        "inline": _get_string_attrib(element, "inline"),
        "display_blocks": _get_string_attrib(element, "display-blocks"),
        "allow_blank": _get_string_attrib(element, "allow-blank"),
        "blocks": [
            {
                "parts": list(block.parts),
                "correct": "true" if block.correct else "false",
                "tag": block.tag,
                "depends": block.depends,
                "has_depends": bool(block.depends),
                "distractor_for": block.distractor_for,
                "emit_dag_attrs": emit_dag_attrs,
            }
            for block in blocks
        ],
    }
    order_blocks_html = _render_order_blocks(html_params)
    _debug(
        f"rendered pl-order-blocks html length={len(order_blocks_html)}; "
        f"multiple_choice_count={len(dropdowns)}"
    )
    problem_statement = (
        None
        if pl.get_boolean_attrib(element, "hide-problem-statement", False)
        else theorem.problem
    )
    return order_blocks_html, dropdowns, problem_statement


@_with_debug_logging
def render(element_html: str | bytes, data: dict[str, Any]) -> str:
    order_blocks_html, _dropdowns, problem_statement = _build_parts(element_html, data)
    if problem_statement is None:
        return order_blocks_html
    return _render_template(
        PACKAGE_DIR / "pl-proof-yaml-problem.mustache",
        {
            "problem_statement": problem_statement,
            "order_blocks_html": order_blocks_html,
        },
    )


@_with_debug_logging
def prepare(element_html: str | bytes, data: dict[str, Any]) -> None:
    order_blocks_html, dropdowns, _problem_statement = _build_parts(element_html, data)
    _load_element_controller("pl-order-blocks").prepare(order_blocks_html, data)
    multiple_choice = _load_element_controller("pl-multiple-choice")
    for dropdown in dropdowns:
        multiple_choice.prepare(_render_multiple_choice(dropdown), data)


@_with_debug_logging
def parse(element_html: str | bytes, data: dict[str, Any]) -> None:
    order_blocks_html, dropdowns, _problem_statement = _build_parts(element_html, data)
    _load_element_controller("pl-order-blocks").parse(order_blocks_html, data)
    multiple_choice = _load_element_controller("pl-multiple-choice")
    for dropdown in dropdowns:
        multiple_choice.parse(_render_multiple_choice(dropdown), data)


@_with_debug_logging
def grade(element_html: str | bytes, data: dict[str, Any]) -> None:
    order_blocks_html, dropdowns, _problem_statement = _build_parts(element_html, data)
    _load_element_controller("pl-order-blocks").grade(order_blocks_html, data)
    multiple_choice = _load_element_controller("pl-multiple-choice")
    for dropdown in dropdowns:
        multiple_choice.grade(_render_multiple_choice(dropdown), data)


@_with_debug_logging
def test(element_html: str | bytes, data: dict[str, Any]) -> None:
    order_blocks_html, dropdowns, _problem_statement = _build_parts(element_html, data)
    _load_element_controller("pl-order-blocks").test(order_blocks_html, data)
    multiple_choice = _load_element_controller("pl-multiple-choice")
    for dropdown in dropdowns:
        multiple_choice.test(_render_multiple_choice(dropdown), data)
