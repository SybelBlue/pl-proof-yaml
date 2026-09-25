import lxml.html
import pytest
from pyfakefs.fake_filesystem import FakeFilesystem

import pl_proof_yaml

from .helpers import MODULE_PATH


def _booly_attrib(elem: lxml.html.HtmlElement, attr: str) -> bool:
    v = elem.get(attr)
    return v is not None and str(v).lower() not in ("", "false", "0")


def _render(
    fs: FakeFilesystem,
    source: str,
    *,
    attributes: str = "",
    proof_file: str = "proofs/example.proof",
):
    """Render a proof from an isolated, course-shaped filesystem."""
    fs.add_real_directory(MODULE_PATH.parent, read_only=True)
    fs.create_file(f"/course/serverFilesCourse/{proof_file}", contents=source)
    data = {
        "options": {
            "server_files_course_path": "/course/serverFilesCourse",
            "client_files_course_path": "/course/clientFilesCourse",
            "question_path": "/course/questions/example",
        }
    }
    element_html = (
        f'<pl-proof-yaml answers-name="proof" proof-file="{proof_file}"'
        f" {attributes}></pl-proof-yaml>"
    )
    return lxml.html.fragment_fromstring(
        pl_proof_yaml.render(element_html, data),
        create_parent="rendered-root",  # type: ignore
    )


def test_render_emits_ordering_and_dag_metadata(fs: FakeFilesystem):
    root = _render(
        fs,
        """problem: Show that the result follows.
lines:
  - step: Establish the hypothesis.
  - step: Apply the theorem.
    depends: 1
    distractors:
      - Reverse the implication.
distractors:
  - Assume the conclusion.
""",
    )

    order_blocks = root.xpath(".//pl-order-blocks")
    assert len(order_blocks) == 1
    assert order_blocks[0].attrib == {
        "answers-name": "proof",
        "grading-method": "dag",
        "source-blocks-order": "random-sections",
    }

    answers = order_blocks[0].xpath("./pl-answer")
    assert [_booly_attrib(answer, "correct") for answer in answers] == [
        True,
        True,
        False,
        False,
    ]
    assert [answer.get("tag") for answer in answers] == [
        "line-1",
        "line-2",
        "distractor-line-2-1",
        "distractor-global-1",
    ]
    assert answers[1].get("depends") == "line-1"
    assert answers[2].get("distractor-for") == "line-2"
    assert answers[3].get("distractor-for") is None


def test_render_emits_alternative_dependency_groups(fs: FakeFilesystem):
    root = _render(
        fs,
        """problem: Show that the result follows.
lines:
  - step: First route.
  - step: Second route, part one.
  - step: Second route, part two.
    depends: 2
  - step: Finish either route.
    depends:
      anyOf:
        - 1
        - [2, 3]
  - step: Use the finish and specifically the first route.
    depends: [1, 4]
""",
    )

    answers = root.xpath(".//pl-order-blocks/pl-answer")
    assert answers[3].get("depends") == "line-1|line-3"
    assert answers[4].get("depends") == "line-1,line-4"


def test_render_reduces_an_impossible_alternative(fs: FakeFilesystem):
    with pytest.warns(UserWarning, match="Explicit keyed line maps"):
        root = _render(
            fs,
            """problem: Use the viable route.
lines:
  1:
    step: Choose either route.
    depends:
      anyOf: [2, 3]
  2:
    step: This route loops back and cannot be satisfied.
    depends: 1
  3: This route is viable.
""",
        )

    answers = root.xpath(".//pl-order-blocks/pl-answer")
    assert answers[0].get("depends") == "line-3"
    assert answers[1].get("depends") == "line-1"


def test_rendered_dropdown_has_unique_choices_and_expected_identity(
    fs: FakeFilesystem,
):
    root = _render(
        fs,
        """problem: Complete the proof.
lines:
  - step: Choose TERM here.
    blanks:
      TERM:
        correct: longest choice
        incorrect: [short, longest choice, short]
""",
    )

    dropdowns = root.xpath(".//pl-multiple-choice")
    assert len(dropdowns) == 1
    dropdown = dropdowns[0]
    assert {k: v for k, v in dropdown.attrib.items() if k != "hide-letter-keys"} == {
        "answers-name": "proof-line-1-TERM",
        "display": "dropdown",
        "order": "random",
        "size": "14",
    }
    assert _booly_attrib(dropdown, "hide-letter-keys")
    choices = dropdown.xpath("./pl-answer")
    assert [
        (choice.text_content(), _booly_attrib(choice, "correct")) for choice in choices
    ] == [
        ("longest choice", True),
        ("short", False),
    ]
    rendered_line = root.xpath(".//pl-order-blocks/pl-answer")[0].text_content()
    assert "Choose " in rendered_line
    assert " here." in rendered_line


def test_paired_distractors_allow_blank_for_their_group_dropdowns(
    fs: FakeFilesystem,
):
    root = _render(
        fs,
        """problem: Complete the proof.
lines:
  - step: Choose BLANK.
    correct: right
    incorrect: wrong
    distractors:
      - step: Reject BLANK.
        correct: no
        incorrect: yes
  - step: Keep BLANK.
    correct: this
    incorrect: that
""",
    )

    dropdowns = root.xpath(".//pl-multiple-choice")
    assert [_booly_attrib(dropdown, "allow-blank") for dropdown in dropdowns] == [
        True,
        True,
        False,
    ]


def test_unpaired_distractors_allow_blank_for_all_dropdowns(fs: FakeFilesystem):
    root = _render(
        fs,
        """problem: Complete the proof.
lines:
  - step: Choose BLANK.
    correct: right
    incorrect: wrong
distractors:
  - step: Reject BLANK.
    correct: no
    incorrect: yes
""",
    )

    dropdowns = root.xpath(".//pl-multiple-choice")
    assert len(dropdowns) == 2
    assert all(_booly_attrib(dropdown, "allow-blank") for dropdown in dropdowns)


def test_no_distractors_omit_allow_blank_for_lines_and_subgoals(
    fs: FakeFilesystem,
):
    root = _render(
        fs,
        """problem: Complete the proof.
lines:
  - step: Start with BLANK.
    correct: first
    incorrect: second
  - step: Consider case BLANK.
    correct: even
    incorrect: odd
    subgoal:
      - step: Derive BLANK.
        correct: result
        incorrect: contradiction
      - step: Conclude BLANK.
        correct: success
        incorrect: failure
""",
    )

    dropdowns = root.xpath(".//pl-multiple-choice")
    assert len(dropdowns) == 4
    assert all(not _booly_attrib(dropdown, "allow-blank") for dropdown in dropdowns)


def test_render_escapes_line_content_but_preserves_problem_markup(
    fs: FakeFilesystem,
):
    root = _render(
        fs,
        """problem: Prove <strong>this claim</strong>.
lines:
  - 'Use <em>literal markup</em> & finish.'
""",
    )

    problem = root.xpath(
        './/*[contains(concat(" ", normalize-space(@class), " "), '
        '" problem-statement ")]'
    )[0]
    assert problem.xpath(".//strong")[0].text == "this claim"
    answer = root.xpath(".//pl-order-blocks/pl-answer")[0]
    assert answer.xpath(".//em") == []
    assert "Use <em>literal markup</em> & finish." in answer.text_content()


def test_render_respects_proof_index_visibility_and_forwarded_options(
    fs: FakeFilesystem,
):
    root = _render(
        fs,
        """- problem: First problem
  lines: [First line]
- problem: Second problem
  lines: [Second line]
""",
        proof_file="proofs/example.proofs",
        attributes=(
            'proof-index="1" hide-problem-statement="true" '
            'grading-method="ranking" source-blocks-order="alphabetized" '
            'partial-credit="none" inline="true" allow-blank="false"'
        ),
    )

    assert (
        root.xpath(
            './/*[contains(concat(" ", normalize-space(@class), " "), '
            '" problem-statement ")]'
        )
        == []
    )
    order_blocks = root.xpath(".//pl-order-blocks")[0]
    assert order_blocks.get("grading-method") == "ranking"
    assert order_blocks.get("source-blocks-order") == "alphabetized"
    assert order_blocks.get("partial-credit") == "none"
    assert _booly_attrib(order_blocks, "inline")
    assert not _booly_attrib(order_blocks, "allow-blank")
    answer = order_blocks.xpath("./pl-answer")[0]
    assert answer.text_content().strip() == "Second line"
    assert "tag" not in answer.attrib
    assert "depends" not in answer.attrib
    assert "distractor-for" not in answer.attrib
