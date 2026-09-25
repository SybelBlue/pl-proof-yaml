from collections.abc import Iterable, Iterator, MutableMapping
from dataclasses import dataclass, field
from typing import Literal

type Linespan = tuple[int, int]
type LineId = int | str
type YamlKey = int | str

type YamlValue = None | float | YamlKey | YamlIterable
type YamlIterable = YamlDict | list[YamlValue]
type YamlDict = dict[YamlKey, YamlValue]

type Variable = str


def keyed_iter(yaml_iter: YamlIterable, start=1) -> Iterable[tuple[YamlKey, YamlValue]]:
    if isinstance(yaml_iter, list):
        return enumerate(yaml_iter, start=start)
    return yaml_iter.items()


@dataclass(slots=True, frozen=True)
class Blank:
    id: YamlKey
    correct: str
    incorrect: list[str] = field(default_factory=list)


@dataclass(slots=True, frozen=True)
class Distractor:
    step: str
    blanks: tuple[Blank, ...] = field(default_factory=tuple)


@dataclass(slots=True, frozen=True)
class Subgoal:
    line_ids: tuple[LineId, ...]
    parent_id: LineId | None = None


@dataclass(slots=True, frozen=True)
class Line:
    """A parsed proof line.

    Attributes:
        id: The line's numeric or author-defined identifier.
        step: The text displayed in the proof block.
        blanks: Dropdown blanks embedded in ``step``.
        depends: Direct dependencies used for graph validation. For an
            ``anyOf`` dependency, this is the union of all alternatives; use
            ``depends_any_of`` when rendering the dependency expression.
        implicit_depends: Transitive dependencies omitted from the rendered
            ``depends`` attribute because direct dependencies already imply
            them. For ``anyOf``, only dependencies implied by every
            alternative are included.
        depends_any_of: Direct dependency groups from ``depends.anyOf``. Each
            inner set is a conjunction, and the outer tuple is a disjunction.
            An empty tuple means the line uses ordinary ``depends`` instead.
        defines: Mathematical identifiers introduced by this line.
        uses: Mathematical identifiers occurring in the line or its answers.
        dependents: ``"all"`` when every later line in the scope implicitly
            depends on this line; otherwise ``None``.
        subgoal: Nested-proof metadata when this line heads a subgoal.
        distractors: Incorrect blocks associated specifically with this line.
    """

    id: LineId
    step: str
    blanks: tuple[Blank, ...] = field(default_factory=tuple)
    depends: frozenset[LineId] = field(default_factory=frozenset)
    implicit_depends: frozenset[LineId] = field(
        default_factory=frozenset, compare=False
    )
    depends_any_of: tuple[frozenset[LineId], ...] = field(
        default_factory=tuple, compare=False
    )
    defines: tuple[str, ...] = field(default_factory=tuple, compare=False)
    uses: tuple[str, ...] = field(default_factory=tuple, compare=False)
    dependents: Literal["all"] | None = field(default=None, compare=False)
    subgoal: Subgoal | None = field(default=None, compare=False)
    distractors: tuple[Distractor, ...] = field(default_factory=tuple, compare=False)

    @property
    def identifiers(self) -> tuple[str, ...]:
        return self.uses


@dataclass(slots=True, frozen=True)
class Proof:
    problem: str
    lines: list[Line] = field(default_factory=list)
    hint: str = ""
    distractors: tuple[Distractor, ...] = field(default_factory=tuple)

    @property
    def subgoals(self) -> list[Line]:
        return [line for line in self.lines if line.subgoal is not None]


@dataclass(slots=True, frozen=True)
class Def:
    line: Line
    first_use: LineId | None


@dataclass(slots=True, frozen=True)
class DefDict(MutableMapping[Variable, Line]):
    data: dict[Variable, Def] = field(default_factory=dict)

    def __getitem__(self, key: Variable) -> Line:
        return self.data[key].line

    def __setitem__(self, key: Variable, line: Line) -> None:
        self.data[key] = Def(line, None)

    def __delitem__(self, key: Variable) -> None:
        del self.data[key]

    def __len__(self) -> int:
        return len(self.data)

    def __iter__(self) -> Iterator[Variable]:
        return iter(self.data)

    def get_first_use_id(self, key: Variable) -> LineId | None:
        return self.data[key].first_use

    def set_first_use(self, key: Variable, line: Line | LineId) -> bool:
        def_ = self.data[key]
        if def_.first_use is not None:
            return False
        line_id = line.id if isinstance(line, Line) else line
        self.data[key] = Def(def_.line, line_id)
        return True
