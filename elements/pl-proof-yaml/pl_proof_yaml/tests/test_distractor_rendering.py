from pathlib import Path

import pl_proof_yaml
from pl_proof_yaml.proof_yaml_parser import loads


def test_basic_distractors_render_as_incorrect_answers(tmp_path: Path):
    fixture = tmp_path / "distractors.proof"
    fixture.write_text(
        """problem: P
distractors:
  - Global distractor
lines:
  - step: Correct one
    distractors:
      - Associated distractor
  - step: Correct two
    depends: 1
""",
        encoding="utf-8",
    )
    proof = loads(fixture)[0]

    blocks, dropdowns = pl_proof_yaml._make_blocks_and_dropdowns(proof, "proof")

    assert dropdowns == []
    assert [(block.correct, block.parts[0]["text"]) for block in blocks] == [
        (True, "Correct one"),
        (False, "Associated distractor"),
        (True, "Correct two"),
        (False, "Global distractor"),
    ]
    assert blocks[2].depends == "line-1"
    assert blocks[1].distractor_for == "line-1"
    assert blocks[3].distractor_for is None

    html = pl_proof_yaml._render_order_blocks(
        {
            "answers_name": "proof",
            "grading_method": "dag",
            "blocks": [
                {
                    "parts": list(block.parts),
                    "correct": "true" if block.correct else "false",
                    "tag": block.tag,
                    "depends": block.depends,
                    "has_depends": bool(block.depends),
                    "distractor_for": block.distractor_for,
                    "emit_dag_attrs": True,
                }
                for block in blocks
            ],
        }
    )
    assert html.count('correct="true"') == 2
    assert html.count('correct="false"') == 2
    assert 'final="true"' not in html
    assert html.count('distractor-for="line-1"') == 1


def test_distractor_blanks_create_dropdown_parts(tmp_path: Path):
    fixture = tmp_path / "distractor-blanks.proof"
    fixture.write_text(
        """problem: P
lines:
  - step: Correct
    distractors:
      - step: False BLANK
        correct: value
        incorrect: other
""",
        encoding="utf-8",
    )

    blocks, dropdowns = pl_proof_yaml._make_blocks_and_dropdowns(
        loads(fixture)[0], "proof"
    )

    assert len(dropdowns) == 1
    assert dropdowns[0].answers_name == "proof-distractor-line-1-1-BLANK"
    assert blocks[1].correct is False
    assert blocks[1].distractor_for == "line-1"
    assert any("dropdown" in part for part in blocks[1].parts)
