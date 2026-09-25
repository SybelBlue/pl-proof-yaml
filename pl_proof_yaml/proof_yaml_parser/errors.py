import abc
import textwrap
from collections.abc import Callable, Generator, Iterable, Sequence
from contextlib import AbstractContextManager, contextmanager, nullcontext
from contextvars import ContextVar
from dataclasses import dataclass
from functools import wraps
from pathlib import Path
from typing import Concatenate, Self

from .types import Linespan, YamlKey, YamlValue
from .yaml import SafeLoader

_PARSE_SRC_PATH: ContextVar[Path] = ContextVar("_PARSE_SRC_PATH")
_PARSE_LINE_SPAN: ContextVar[tuple[int, int]] = ContextVar("_PARSE_LINE_SPAN")
_PARSE_KEY_BREADCRUMBS: ContextVar[tuple[str, ...]] = ContextVar(
    "_PARSE_KEY_CHAIN", default=()
)


def nullable_contextmanager[T](
    cm: Callable[[T], Generator],
) -> Callable[[T | None], AbstractContextManager]:
    @wraps(cm)
    def inner(t: T | None) -> AbstractContextManager:
        if t is None:
            return nullcontext()
        return contextmanager(cm)(t)

    return inner


@nullable_contextmanager
def source_path_ctxt(path: Path):
    """Sets the source file path for error printing in this block"""
    token = _PARSE_SRC_PATH.set(path)
    try:
        yield
    finally:
        _PARSE_SRC_PATH.reset(token)


@nullable_contextmanager
def err_label_ctxt(label: str):
    """Sets the key-data for error breadcrumbing in this block"""
    token = _PARSE_KEY_BREADCRUMBS.set(_PARSE_KEY_BREADCRUMBS.get() + (label,))
    try:
        yield
    finally:
        _PARSE_KEY_BREADCRUMBS.reset(token)


@contextmanager
def no_traceback():
    """Sets the first level of traceback here."""
    try:
        yield
    except Exception as e:
        e.__traceback__ = None
        raise


class SafeLineLoader(SafeLoader):
    def construct_mapping(self, node, deep=True):
        mapping = super().construct_mapping(node, deep=deep)
        mapping["__linespan__"] = node.start_mark.line, node.end_mark.line
        return mapping


def linespan(data: YamlValue, remove=True) -> Linespan | None:
    if not isinstance(data, dict):
        return None
    out: YamlValue | Linespan = (data.pop if remove else data.get)("__linespan__", None)  # type: ignore
    if (
        type(out) is tuple
        and len(out) == 2
        and all(type(inner) is int for inner in out)
    ):
        return out
    return None


type ParseFn[**P, S: YamlValue, T] = Callable[Concatenate[YamlKey, S, P], T]


def with_err_context[**P, S: YamlValue, T](
    *, label_template: str = "{id}"
) -> Callable[[ParseFn[P, S, T]], ParseFn[P, S, T]]:
    """Uses the first two arguments of a parse function to deduce err_label and linespan context"""

    def wrapper(parse_fn: ParseFn[P, S, T]) -> ParseFn[P, S, T]:
        @wraps(parse_fn)
        def inner(
            id: YamlKey,
            ls: S,
            *args: P.args,
            **kwargs: P.kwargs,
        ) -> T:
            with (
                err_label_ctxt(label_template.format(id=id)),
                err_linespan_ctxt(linespan(ls)),
            ):
                return parse_fn(id, ls, *args, **kwargs)

        return inner

    return wrapper


@nullable_contextmanager
def err_linespan_ctxt(line: tuple[int, int]):
    """Sets the linespan for error highlighting in this block"""
    token = _PARSE_LINE_SPAN.set(line)
    try:
        yield
    finally:
        _PARSE_LINE_SPAN.reset(token)


def err_linespan_ctxt_from(token: YamlValue):
    """Sets the linespan for error highlighting in this block from a source"""
    return err_linespan_ctxt(linespan(token))


def _format_parse_error(message: str, missing_fields: Iterable[YamlKey] = ()) -> str:
    src_path = _PARSE_SRC_PATH.get(None)
    line = _PARSE_LINE_SPAN.get(None)
    if line is None or src_path is None:
        return message
    s, e = line
    lines = list(_read_linespan(src_path, s, e))
    last = lines[-1]
    ind = last[: -len(last.lstrip())]
    breadcrumbs = " > ".join(_PARSE_KEY_BREADCRUMBS.get()) + ":"
    return "\n".join(
        filter(
            bool,
            (
                message.rstrip(),
                " ",
                breadcrumbs.rstrip(),
                textwrap.indent("".join(lines), "> ").rstrip(),
                *(
                    textwrap.indent(f"{missing_field}: ...", "+ " + ind)
                    for missing_field in missing_fields
                ),
                (
                    textwrap.indent("^ try adding this here", "  " + ind)
                    if missing_fields
                    else ""
                ),
                " ",
                f"Source: {src_path}:{s}",
            ),
        )
    )


def _read_linespan(path: Path, start: int, stop: int):
    with open(str(path)) as f:
        for _ in range(max(0, start - 1)):
            f.readline()
        for _, line in zip(range(start, stop + 1), f):
            yield line


class YamlParseError(abc.ABC, SyntaxError):
    formatted_message: str

    @abc.abstractmethod
    def cause(self) -> str:
        raise NotImplementedError

    def get_missing_fields(self) -> Sequence[YamlKey]:
        return ()

    def __post_init__(self) -> None:
        self.formatted_message = (
            type(self).__name__
            + ": "
            + _format_parse_error(
                self.cause(), missing_fields=self.get_missing_fields()
            )
        )
        SyntaxError.__init__(self, self.formatted_message)

    def __str__(self) -> str:
        return self.formatted_message


@dataclass(slots=True)
class ParseError(YamlParseError):
    message: str

    def cause(self) -> str:
        return self.message


@dataclass(slots=True)
class NameParseError(YamlParseError):
    names: tuple[str, ...]

    def cause(self) -> str:
        s = "s" if len(self.names) != 1 else ""
        return f"Unknown name{s}: {', '.join(self.names)}"


@dataclass(slots=True)
class UnsupportedValueError(YamlParseError):
    value: YamlValue
    kind: str

    def cause(self) -> str:
        return f"Unsupported {self.kind} value: {self.value!r}"


@dataclass(slots=True)
class UnrecognizedKeyError(YamlParseError):
    keys: tuple[YamlKey, ...]
    kind: str = ""

    def cause(self) -> str:
        ctxt = f"{self.kind} " if self.kind else ""
        return f"Unrecognized {ctxt}keys: {', '.join(map(str, self.keys))}"


@dataclass(slots=True)
class MissingFieldError(YamlParseError):
    fields: tuple[YamlKey, ...]
    kind: str

    def cause(self) -> str:
        s = "s" if len(self.fields) != 1 else ""
        ctxt = self.kind and f" {self.kind}"
        return f"Missing{ctxt} attribute{s}: {', '.join(f'"{f}"' for f in self.fields)}"

    def get_missing_fields(self) -> Sequence[int | str]:
        return self.fields

    @classmethod
    def from_fields(cls, fields: Iterable[YamlKey], *, kind: str = "") -> Self:
        return cls(tuple(fields), kind=kind)


def _type_name(expected_type: str | type | tuple[str | type, ...]) -> str:
    if isinstance(expected_type, tuple):
        return " or ".join(_type_name(item) for item in expected_type)
    if isinstance(expected_type, str):
        return f"`{expected_type}`"
    return f"a {expected_type.__name__}"


@dataclass(slots=True)
class BadTypeError(YamlParseError):
    expected_type: str | type | tuple[str | type, ...]
    gotten_type: str | type
    kind: str = ""

    def cause(self) -> str:
        prefix = f"{self.kind} " if self.kind else ""
        return f"{prefix}must be {_type_name(self.expected_type)}, not {_type_name(self.gotten_type)}"
