from pathlib import Path

import pytest

from pl_proof_yaml.proof_yaml_parser import Distractor, loads
from pl_proof_yaml.proof_yaml_parser.errors import BadTypeError


def _load_proof(tmp_path: Path, source: str):
    path = tmp_path / "example.proof"
    path.write_text(source, encoding="utf-8")
    return loads(path)[0]


def test_global_and_associated_distractors_preserve_text_and_order(tmp_path: Path):
    proof = _load_proof(
        tmp_path,
        r"""
problem: Prove the claim.
distractors:
  - Global first with $x$ and BLANK
  - Global second
lines:
  - step: A correct line about $x$.
    distractors:
      - Associated first
      - Associated second
  - A second correct line.
""",
    )

    assert proof.distractors == (
        Distractor(r"Global first with $x$ and BLANK"),
        Distractor("Global second"),
    )
    assert proof.lines[0].distractors == (
        Distractor("Associated first"),
        Distractor("Associated second"),
    )
    assert proof.lines[1].distractors == ()
    assert [line.id for line in proof.lines] == [1, 2]
    assert [line.step for line in proof.lines] == [
        r"A correct line about $x$.",
        "A second correct line.",
    ]


def test_distractors_are_isolated_from_definitions_and_dependencies(tmp_path: Path):
    proof = _load_proof(
        tmp_path,
        r"""
problem: Prove the claim.
distractors:
  - A false statement about $z$.
lines:
  - step: Define $x$.
    distractors:
      - A false statement about $y$.
  - step: Use $x$.
    depends: $x$
""",
    )

    assert len(proof.lines) == 2
    assert proof.lines[0].defines == ("x",)
    assert proof.lines[1].depends == frozenset({1})
    assert all(
        "y" not in line.defines and "z" not in line.defines for line in proof.lines
    )


@pytest.mark.parametrize(
    "source, message",
    [
        (
            "problem: P\nlines: [A]\ndistractors: not-a-list\n",
            "proof distractors must be a list",
        ),
        (
            "problem: P\nlines:\n  - step: A\n    distractors:\n      - 42\n",
            "must be a str or a dict",
        ),
    ],
)
def test_malformed_distractors_have_context(tmp_path: Path, source: str, message: str):
    with pytest.raises(BadTypeError) as exc_info:
        _load_proof(tmp_path, source)

    error = str(exc_info.value)
    assert message in error
    assert "Proof 0" in error


def test_proof_without_distractors_keeps_empty_defaults(tmp_path: Path):
    proof = _load_proof(tmp_path, "problem: P\nlines: [A, B]\n")

    assert proof.distractors == ()
    assert all(line.distractors == () for line in proof.lines)


def test_distractors_support_shorthand_and_named_blanks(tmp_path: Path):
    proof = _load_proof(
        tmp_path,
        """problem: P
distractors:
  - step: Global BLANK
    correct: answer
    incorrect: decoy
lines:
  - step: Correct
    distractors:
      - step: Associated LEFT and RIGHT
        blanks:
          LEFT:
            correct: left
          RIGHT:
            correct: right
            incorrect: [wrong]
""",
    )

    assert [(blank.id, blank.correct) for blank in proof.distractors[0].blanks] == [
        ("BLANK", "answer")
    ]
    assert [blank.id for blank in proof.lines[0].distractors[0].blanks] == [
        "LEFT",
        "RIGHT",
    ]
