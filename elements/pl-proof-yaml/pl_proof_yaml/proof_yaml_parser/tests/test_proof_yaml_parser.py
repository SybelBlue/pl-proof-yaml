import tempfile
import textwrap
import warnings
from pathlib import Path

from pyfakefs.fake_filesystem_unittest import Patcher

from .. import yaml
from ..errors import ParseError
from ..linter import _glob_paths, _theorems_to_lint, _unkey_theorems
from ..parse import (
    DEFAULT_YAML_PATH,
    extract_line_identifiers,
    loads,
)
from ..types import keyed_iter
from .helpers import TestCase


def _fake_file(fs, path: Path, contents: str) -> Path:
    fs.create_file(path, contents=textwrap.dedent(contents))
    return path


def _extract_step_identifiers(step: str) -> list[str]:
    return extract_line_identifiers(step, ())


class TestProofYamlParser(TestCase):
    def test_step_identifier_extraction(self):
        cases = [
            ("$x_2 < 0$", ["x_2"]),
            ("$a,b,c \\in \\N$", ["a", "b", "c"]),
            ("$\\mathcal{U}$ contains $x$", ["U", "x"]),
            ("$x = x + 1$", ["x"]),
        ]

        for step, expected in cases:
            with self.subTest(step=step):
                self.assertEqual(_extract_step_identifiers(step), expected)

    def test_line_uses_and_defines(self):
        with Patcher() as patcher:
            path = _fake_file(
                patcher.fs,
                DEFAULT_YAML_PATH,
                """
                - problem: Synthetic dependency proof.
                  defaults:
                    depends: previous
                  lines:
                    - step: Proof by contradiction.
                    - step: Assume there are integers $a$ and $b$.
                    - step: Then $a + b = 0$.
                    - step: Therefore a contradiction follows.
                """,
            )
            theorem = loads(path)[0]

        self.assertEqual(theorem.lines[1].uses, ("a", "b"))
        self.assertEqual(theorem.lines[1].defines, ("a", "b"))
        self.assertEqual(theorem.lines[1].depends, frozenset({1}))
        self.assertEqual(theorem.lines[1].implicit_depends, frozenset())

        self.assertEqual(theorem.lines[2].uses, ("a", "b"))
        self.assertEqual(theorem.lines[2].defines, ())
        self.assertEqual(theorem.lines[2].depends, frozenset({2}))
        self.assertEqual(theorem.lines[2].implicit_depends, frozenset({1}))

        self.assertEqual(theorem.lines[3].depends, frozenset({3}))
        self.assertEqual(theorem.lines[3].implicit_depends, frozenset({1, 2}))

    def test_depends_keyword_desugaring(self):
        yaml_text = textwrap.dedent(
            """
            - problem: Keyword depends smoke test.
              lines:
                1:
                  step: Proof by BLANK.
                  correct: contradiction
                  incorrect: contrapositive
                2:
                  step: Assume $x$ is BLANK.
                  correct: even
                  incorrect: odd
                  depends: previous
                3:
                  step: Assume $y$ is BLANK.
                  correct: odd
                  incorrect: even
                  depends:
                    previous: 2
                4:
                  step: Therefore BLANK.
                  correct: $x$
                  incorrect: $y$
                  depends: all-previous
                5:
                  step: Hence BLANK.
                  correct: $y$
                  incorrect: $x$
                  depends:
                    previous: all
                6:
                  step: Finally BLANK.
                  correct: $z$
                  incorrect: $w$
                  depends:
                    - previous
                    - previous
            """
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "keyword_depends.yaml"
            path.write_text(yaml_text, encoding="utf-8")

            theorem = loads(path)[0]

        self.assertEqual(theorem.lines[1].depends, frozenset({1}))
        self.assertEqual(theorem.lines[1].implicit_depends, frozenset())
        self.assertEqual(theorem.lines[2].depends, frozenset({2}))
        self.assertEqual(theorem.lines[2].implicit_depends, frozenset({1}))
        self.assertEqual(theorem.lines[3].depends, frozenset({3}))
        self.assertEqual(theorem.lines[3].implicit_depends, frozenset({1, 2}))
        self.assertEqual(theorem.lines[4].depends, frozenset({4}))
        self.assertEqual(theorem.lines[4].implicit_depends, frozenset({1, 2, 3}))
        self.assertEqual(theorem.lines[5].depends, frozenset({5}))

    def test_rejects_alternative_when_all_paths_are_circular(self):
        with Patcher() as patcher:
            path = _fake_file(
                patcher.fs,
                DEFAULT_YAML_PATH,
                """
                - problem: Every alternative loops back to the first line.
                  lines:
                    1:
                      step: Choose either route.
                      depends:
                        anyOf: [2, 3]
                    2:
                      step: The first route loops back.
                      depends: 1
                    3:
                      step: The second route also loops back.
                      depends: 1
                """,
            )

            with self.assertRaisesRegex(
                ParseError,
                "All dependency alternatives for line 1 are circular",
            ):
                loads(path)

    def test_allows_circular_alternatives_with_novel_roots(self):
        yaml_text = textwrap.dedent(
            """
            - problem: 2-cycle with independent roots
              lines:
                0: Root One.
                1:
                  step: Circular One
                  depends: { anyOf: [0, 2] }
                2:
                  step: Circular Two
                  depends: { anyOf: [1, 3] }
                3: Root Two.
            """
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "keyword_depends.yaml"
            path.write_text(yaml_text, encoding="utf-8")

            theorem = loads(path)[0]

        self.assertEqual(
            {*theorem.lines[1].depends_any_of}, {frozenset({0}), frozenset({2})}
        )
        self.assertEqual(
            {*theorem.lines[2].depends_any_of}, {frozenset({1}), frozenset({3})}
        )

    def test_theorem_default_depends_is_applied(self):
        yaml_text = textwrap.dedent(
            """
            - problem: Theorem default depends smoke test.
              defaults:
                depends: previous
              lines:
                0:
                  step: First line.
                  depends: []
                1: Second line.
                2:
                  step: Third line.
                  depends: 0
            """
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "theorem_default_depends.yaml"
            path.write_text(yaml_text, encoding="utf-8")

            theorem = loads(path)[0]

        self.assertEqual(theorem.lines[0].depends, frozenset())
        self.assertEqual(theorem.lines[1].depends, frozenset({0}))
        self.assertEqual(theorem.lines[2].depends, frozenset({0}))

    def test_dependents_all_below_desugaring(self):
        yaml_text = textwrap.dedent(
            """
            - problem: Dependents all-below smoke test.
              lines:
                1:
                  step: Proof by BLANK.
                  correct: contradiction
                  incorrect: contrapositive
                  dependents: all-below
                2:
                  step: Assume $x$ is BLANK.
                  correct: even
                  incorrect: odd
                  depends: 1
                3:
                  step: Therefore $x$ is BLANK.
                  correct: even
                  incorrect: odd
                  depends: $x$
            - problem: Dependents all below smoke test.
              lines:
                1:
                  step: Proof by BLANK.
                  correct: contradiction
                  incorrect: contrapositive
                  dependents: all below
                2:
                  step: Assume $x$ is BLANK.
                  correct: even
                  incorrect: odd
                  depends: 1
                3:
                  step: Therefore $x$ is BLANK.
                  correct: even
                  incorrect: odd
                  depends: $x$
            """
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "dependents_all_below.yaml"
            path.write_text(yaml_text, encoding="utf-8")

            theorems = loads(path)

        for theorem in theorems:
            self.assertEqual(theorem.lines[1].depends, frozenset({1}))
            self.assertEqual(theorem.lines[1].implicit_depends, frozenset())
            self.assertEqual(theorem.lines[2].depends, frozenset({2}))
            self.assertEqual(theorem.lines[2].implicit_depends, frozenset({1}))

    def test_linter_prunes_all_below_redundant_depends(self):
        yaml_text = textwrap.dedent(
            """
            - problem: All-below linter smoke test.
              lines:
                1:
                  step: Proof by BLANK.
                  correct: contradiction
                  incorrect: contrapositive
                  dependents: all-below
                2:
                  step: Assume $x$ is BLANK.
                  correct: even
                  incorrect: odd
                  depends: 1
                3:
                  step: Therefore $x$ is BLANK.
                  correct: even
                  incorrect: odd
                  depends: 1
            """
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "all_below_linter.yaml"
            path.write_text(yaml_text, encoding="utf-8")

            parsed_theorems = loads(path)
            data = yaml.safe_load(path.read_text(encoding="utf-8"))

        converted = _unkey_theorems(data, parsed_theorems)  # type: ignore

        self.assertEqual(converted, 1)
        lines = data[0]["lines"]  # type: ignore
        assert self.assertIsInstance(lines, list)
        self.assertNotIn("depends", lines[1])
        self.assertNotIn("depends", lines[2])

    def test_linter_path_glob(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            directory = Path(tmpdir)
            first = directory / "a.yaml"
            second = directory / "b.yaml"
            ignored = directory / "notes.txt"
            for path in (first, second, ignored):
                path.write_text("", encoding="utf-8")

            self.assertEqual(
                _glob_paths(str(directory / "*.yaml")),
                [first, second],
            )

    def test_linter_accepts_single_proof(self):
        proof = {"problem": "A proof", "lines": []}

        self.assertEqual(_theorems_to_lint(proof, Path("example.proof")), [proof])

    def test_linter_accepts_manifest(self):
        manifest = {"proofs": ["example.proof"]}

        self.assertEqual(
            _theorems_to_lint(manifest, Path("example.manifest")),
            [],
        )

    def test_linter_keeps_symbolic_depends_even_if_all_below_covers_lines(self):
        yaml_text = textwrap.dedent(
            """
            - problem: Symbolic depends smoke test.
              lines:
                1:
                  step: Proof by BLANK.
                  correct: contradiction
                  incorrect: contrapositive
                2:
                  step: Assume $x$, $y$, and $n$ are BLANK.
                  correct: yes
                  incorrect: no
                  dependents: all-below
                3:
                  step: Assume $x-y$ is BLANK.
                  correct: yes
                  incorrect: no
                  depends: $x, y, n$
            """
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "symbolic_depends.yaml"
            path.write_text(yaml_text, encoding="utf-8")

            parsed_theorems = loads(path)
            data = yaml.safe_load(path.read_text(encoding="utf-8"))

        converted = _unkey_theorems(data, parsed_theorems)  # type: ignore

        self.assertEqual(converted, 1)
        lines = data[0]["lines"]  # type: ignore
        assert self.assertIsInstance(lines, list)
        self.assertEqual(lines[2]["depends"], "$x, y, n$")

    def test_linter_removes_line_level_default_redeclaration(self):
        yaml_text = textwrap.dedent(
            """
            - problem: Default depends redeclaration smoke test.
              defaults:
                depends: previous
              lines:
                1:
                  step: Proof by BLANK.
                  correct: contradiction
                  incorrect: contrapositive
                2:
                  step: BLANK integers $x$, $y$, and $n$.
                  correct: Assume there are three
                  incorrect: Consider three unspecified
                  depends: previous
                3:
                  step: Assume $x-y$ is BLANK.
                  correct: not divisible by $n$
                  incorrect: divisible by $n$
                  depends: $x, y, n$
            """
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "default_redeclaration.yaml"
            path.write_text(yaml_text, encoding="utf-8")

            parsed_theorems = loads(path)
            data = yaml.safe_load(path.read_text(encoding="utf-8"))

        converted = _unkey_theorems(data, parsed_theorems)  # type: ignore

        self.assertEqual(converted, 1)
        lines = data[0]["lines"]  # type: ignore
        assert self.assertIsInstance(lines, list)
        self.assertNotIn("depends", lines[1])
        self.assertEqual(lines[2]["depends"], "$x, y, n$")

    def test_depends_latex_name_resolution(self):
        yaml_text = textwrap.dedent(
            """
            - problem: Latex depends smoke test.
              lines:
                1:
                  step: Proof by BLANK.
                  correct: contradiction
                  incorrect: contrapositive
                2:
                  step: Assume $x_0$ is BLANK.
                  correct: even
                  incorrect: odd
                3:
                  step: Therefore $x_0$ is BLANK.
                  correct: even
                  incorrect: odd
                  depends: $x_0$, 1
            """
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "latex_depends.yaml"
            path.write_text(yaml_text, encoding="utf-8")

            theorem = loads(path)[0]

        self.assertEqual(theorem.lines[1].depends, frozenset())
        self.assertEqual(theorem.lines[1].implicit_depends, frozenset())
        self.assertEqual(theorem.lines[2].depends, frozenset({1, 2}))
        self.assertEqual(theorem.lines[2].implicit_depends, frozenset())

    def test_depends_names_desugaring(self):
        yaml_text = textwrap.dedent(
            """
            - problem: Depends names smoke test.
              lines:
                1:
                  step: Proof by BLANK.
                  correct: contradiction
                  incorrect: contrapositive
                2:
                  step: Assume $A$ is BLANK.
                  correct: set
                  incorrect: number
                3:
                  step: Assume $x_0$ is BLANK.
                  correct: even
                  incorrect: odd
                4:
                  step: Therefore BLANK.
                  correct: $A$
                  incorrect: $x_0$
                  depends: $A, x_0$
            """
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "depends_names.yaml"
            path.write_text(yaml_text, encoding="utf-8")

            theorem = loads(path)[0]

        self.assertEqual(theorem.lines[3].depends, frozenset({2, 3}))
        self.assertEqual(theorem.lines[3].implicit_depends, frozenset())

    def test_custom_define_label_resolution(self):
        yaml_text = textwrap.dedent(
            """
            - problem: Custom define label smoke test.
              lines:
                1:
                  step: Introduce the label.
                  defines: $hello label, x, y$
                2:
                  step: Use the label.
                  depends: $hello label, x, y$
            """
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "custom_define_label.yaml"
            path.write_text(yaml_text, encoding="utf-8")

            theorem = loads(path)[0]

        self.assertEqual(theorem.lines[0].defines, ("hello label", "x", "y"))
        self.assertEqual(theorem.lines[1].depends, frozenset({1}))

    def test_label_keyword_resolution(self):
        yaml_text = textwrap.dedent(
            """
            - problem: Label keyword smoke test.
              lines:
                - step: Introduce a reusable assumption.
                  label: assumption step
                - step: Use the reusable assumption.
                  depends: assumption step
            """
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "label_keyword.yaml"
            path.write_text(yaml_text, encoding="utf-8")

            theorem = loads(path)[0]

        self.assertEqual(theorem.lines[0].defines, ("assumption step",))
        self.assertEqual(theorem.lines[1].depends, frozenset({1}))

    def test_label_and_defines_conflict(self):
        yaml_text = textwrap.dedent(
            """
            - problem: Label conflict smoke test.
              lines:
                - step: Introduce a reusable assumption.
                  label: assumption step
                  defines: other step
            """
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "label_conflict.yaml"
            path.write_text(yaml_text, encoding="utf-8")

            with self.assertRaises(ParseError) as ctx:
                loads(path)

        self.assertIn("Use either `label` or `defines`, not both", str(ctx.exception))

    def test_subgoal_inherits_header_dependency(self):
        yaml_text = textwrap.dedent(
            """
            - problem: Subgoal inheritance smoke test.
              lines:
                - step: Proof by cases.
                - step: Case BLANK
                  correct: Even
                  incorrect: Odd
                  subgoal:
                    - step: Assume $n$ is even.
                    - step: Therefore $n^2$ is even.
                      depends: previous
            """
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "subgoal_inheritance.yaml"
            path.write_text(yaml_text, encoding="utf-8")

            theorem = loads(path)[0]

        self.assertEqual([line.id for line in theorem.lines], [1, 2, 3, 4])
        self.assertEqual(theorem.lines[1].step, "Case BLANK")
        self.assertEqual(theorem.lines[1].blanks[0].correct, "Even")
        self.assertEqual(theorem.lines[2].depends, frozenset({2}))
        self.assertEqual(theorem.lines[3].depends, frozenset({3}))
        self.assertEqual(theorem.lines[3].implicit_depends, frozenset({2}))
        self.assertEqual(theorem.subgoals[0].id, 2)
        subgoal = theorem.subgoals[0].subgoal
        assert self.assertIsNotNone(subgoal)
        self.assertEqual(subgoal.line_ids, (3, 4))

    def test_sibling_subgoals_ignore_previous_default_on_headers(self):
        yaml_text = textwrap.dedent(
            """
            - problem: Sibling subgoal smoke test.
              defaults:
                depends: previous
              lines:
                - step: Proof by cases.
                  depends: []
                - step: Case Even
                  subgoal:
                    - step: Assume $n$ is even.
                    - step: Therefore $n^2$ is even.
                - step: Case Odd
                  subgoal:
                    - step: Assume $n$ is odd.
                    - step: Therefore $n^2$ is odd.
            """
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "sibling_subgoals.yaml"
            path.write_text(yaml_text, encoding="utf-8")

            theorem = loads(path)[0]

        self.assertEqual([line.id for line in theorem.lines], [1, 2, 3, 4, 5, 6, 7])
        self.assertEqual(theorem.lines[1].depends, frozenset())
        self.assertEqual(theorem.lines[4].depends, frozenset())
        self.assertEqual(theorem.lines[2].depends, frozenset({2}))
        self.assertEqual(theorem.lines[5].depends, frozenset({5}))
        self.assertEqual(theorem.lines[3].depends, frozenset({3}))
        self.assertEqual(theorem.lines[6].depends, frozenset({6}))
        self.assertEqual([line.id for line in theorem.subgoals], [2, 5])

    def test_subgoal_inheritance_keeps_explicit_child_dependencies(self):
        yaml_text = textwrap.dedent(
            """
            - problem: Subgoal explicit dependency smoke test.
              lines:
                - step: Establish shared context.
                - step: Case Even
                  subgoal:
                    - step: Use the case and the shared context.
                      depends: 1
            """
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "subgoal_explicit_dependency.yaml"
            path.write_text(yaml_text, encoding="utf-8")

            theorem = loads(path)[0]

        self.assertEqual([line.id for line in theorem.lines], [1, 2, 3])
        self.assertEqual(theorem.lines[2].depends, frozenset({1, 2}))
        self.assertEqual(theorem.lines[2].implicit_depends, frozenset())

    def test_subgoal_inherits_existing_all_below_context(self):
        yaml_text = textwrap.dedent(
            """
            - problem: Subgoal all-below inheritance smoke test.
              lines:
                - step: Establish global context.
                  dependents: all-below
                - step: Case Even
                  subgoal:
                    - step: Use the case and global context.
            """
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "subgoal_all_below_inheritance.yaml"
            path.write_text(yaml_text, encoding="utf-8")

            theorem = loads(path)[0]

        self.assertEqual([line.id for line in theorem.lines], [1, 2, 3])
        self.assertEqual(theorem.lines[1].depends, frozenset({1}))
        self.assertEqual(theorem.lines[1].implicit_depends, frozenset())
        self.assertEqual(theorem.lines[2].depends, frozenset({2}))
        self.assertEqual(theorem.lines[2].implicit_depends, frozenset({1}))

    def test_nested_subgoal_inherits_outer_header(self):
        yaml_text = textwrap.dedent(
            """
            - problem: Nested subgoal smoke test.
              lines:
                - step: Outer
                  subgoal:
                    - step: Inner
                      subgoal:
                        - step: Inner proof line.
            """
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "nested_subgoal.yaml"
            path.write_text(yaml_text, encoding="utf-8")

            theorem = loads(path)[0]

        self.assertEqual([line.id for line in theorem.lines], [1, 2, 3])
        self.assertEqual(theorem.lines[1].depends, frozenset({1}))
        self.assertEqual(theorem.lines[2].depends, frozenset({2}))
        self.assertEqual(theorem.lines[2].implicit_depends, frozenset({1}))
        outer_subgoal = theorem.subgoals[0].subgoal
        inner_subgoal = theorem.subgoals[1].subgoal
        assert self.assertIsNotNone(outer_subgoal)
        assert self.assertIsNotNone(inner_subgoal)
        self.assertEqual(outer_subgoal.parent_id, None)
        self.assertEqual(inner_subgoal.parent_id, 1)

    def test_subgoal_blocks_replace_manual_indent(self):
        with Patcher() as patcher:
            path = _fake_file(
                patcher.fs,
                DEFAULT_YAML_PATH,
                """
                - problem: Synthetic subgoal proof.
                  lines:
                    - step: First subgoal.
                      subgoal:
                        - step: First detail.
                    - step: Second subgoal.
                      subgoal:
                        - step: Second detail.
                    - step: Third subgoal.
                      subgoal:
                        - step: Third detail.
                    - step: Fourth subgoal.
                      subgoal:
                        - step: Fourth detail.
                    - step: Fifth subgoal.
                      subgoal:
                        - step: Fifth detail.
                    - step: Sixth subgoal.
                      subgoal:
                        - step: Sixth detail.
                """,
            )
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        subgoal_count = 0

        def _assert_no_manual_indent(lines):
            nonlocal subgoal_count
            for _, line_yaml in keyed_iter(lines):
                assert self.assertIsInstance(line_yaml, dict)
                step = line_yaml.get("step")
                assert self.assertIsInstance(step, str)
                self.assertFalse(step.startswith("$~~~~$"))
                subgoal = line_yaml.get("subgoal")
                if subgoal is not None:
                    subgoal_count += 1
                    self.assertIsInstance(subgoal, (list, dict))
                    _assert_no_manual_indent(subgoal)

        for theorem in data:  # type: ignore
            lines = theorem.get("lines")
            if not isinstance(lines, (list, dict)):
                continue
            _assert_no_manual_indent(lines)

        self.assertEqual(subgoal_count, 6)

    def test_multiple_incorrect_answers_per_blank(self):
        yaml_text = textwrap.dedent(
            """
            - problem: Multiple incorrect answers smoke test.
              lines:
                - step: Proof by BLANK.
                  correct: contradiction
                  incorrect:
                    - induction
                    - contrapositive
                - step: Fill LEFT and RIGHT.
                  blanks:
                    LEFT:
                      correct: left
                      incorrect:
                        - wrong left
                        - also wrong left
                    RIGHT:
                      correct: right
                      incorrect: wrong right, also wrong right
            """
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "multiple_incorrect.yaml"
            path.write_text(yaml_text, encoding="utf-8")

            theorem = loads(path)[0]

        self.assertEqual(
            theorem.lines[0].blanks[0].incorrect,
            ["induction", "contrapositive"],
        )
        self.assertEqual(
            theorem.lines[1].blanks[0].incorrect,
            ["wrong left", "also wrong left"],
        )
        self.assertEqual(
            theorem.lines[1].blanks[1].incorrect,
            ["wrong right", "also wrong right"],
        )

    def test_top_level_blank_metadata_requires_one_blank(self):
        yaml_text = textwrap.dedent(
            """
            - problem: Ambiguous default BLANK smoke test.
              lines:
                - step: Fill BLANK and BLANK.
                  correct: first
                  incorrect: second
            """
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "ambiguous_blank.yaml"
            path.write_text(yaml_text, encoding="utf-8")

            with self.assertRaises(ParseError) as ctx:
                loads(path)

        self.assertIn("exactly one BLANK", str(ctx.exception))

    def test_top_level_blank_metadata_rejects_named_blanks(self):
        yaml_text = textwrap.dedent(
            """
            - problem: Mixed blank metadata smoke test.
              lines:
                - step: Fill BLANK and OTHER.
                  correct: default
                  blanks:
                    OTHER:
                      correct: other
            """
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "mixed_blank_metadata.yaml"
            path.write_text(yaml_text, encoding="utf-8")

            with self.assertRaises(ParseError) as ctx:
                loads(path)

        self.assertIn("cannot be mixed with `blanks`", str(ctx.exception))

    def test_proof_yaml_warns_on_keyed_line_maps(self):
        yaml_text = textwrap.dedent(
            """
            problem: Keyed proof file smoke test.
            lines:
              1:
                step: Proof by BLANK.
                correct: contradiction
                incorrect: induction
            """
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "keyed.proof.yaml"
            path.write_text(yaml_text, encoding="utf-8")

            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                theorem = loads(path)[0]

        self.assertEqual(theorem.lines[0].id, 1)
        self.assertTrue(
            any("Explicit keyed line maps are legacy" in str(w.message) for w in caught)
        )

    def test_split_proof_loading(self):
        first_proof = """
            problem: First synthetic proof.
            lines:
              - step: First proof line.
        """
        second_proof = """
            problem: Second synthetic proof.
            lines:
              - step: Second proof line.
        """
        with Patcher() as patcher:
            split_dir = DEFAULT_YAML_PATH.with_name("split_proofs")
            manifest_path = split_dir / "proofs.manifest"
            first_proof_path = split_dir / "first.proof.yaml"
            aggregate = yaml.safe_dump(
                [yaml.safe_load(first_proof), yaml.safe_load(second_proof)],
                sort_keys=False,
            )
            _fake_file(patcher.fs, DEFAULT_YAML_PATH, aggregate)  # type: ignore
            _fake_file(patcher.fs, split_dir / "first.proof.yaml", first_proof)
            _fake_file(patcher.fs, split_dir / "second.proof.yaml", second_proof)
            _fake_file(
                patcher.fs,
                manifest_path,
                """
                proofs:
                  - first.proof
                  - second.proof
                """,
            )

            original_theorems = loads(DEFAULT_YAML_PATH)
            manifest_theorems = loads(manifest_path)
            directory_theorems = loads(split_dir)
            first_theorem = loads(first_proof_path)

        self.assertEqual(len(manifest_theorems), len(original_theorems))
        self.assertEqual(len(directory_theorems), len(original_theorems))
        self.assertEqual(first_theorem, original_theorems[:1])
        self.assertEqual(manifest_theorems, original_theorems)
        self.assertEqual(directory_theorems, original_theorems)

    def test_manifest_proof_references_may_omit_yaml_suffix(self):
        yaml_text = textwrap.dedent(
            """
            problem: Short manifest proof reference smoke test.
            lines:
              - step: Proof by BLANK.
                correct: contradiction
                incorrect: induction
            """
        )
        manifest_text = textwrap.dedent(
            """
            proofs:
            - short-name.proof
            """
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            (tmp_path / "short-name.proof.yaml").write_text(yaml_text, encoding="utf-8")
            manifest_path = tmp_path / "manifest.manifest.yaml"
            manifest_path.write_text(manifest_text, encoding="utf-8")

            theorem = loads(manifest_path)[0]

        self.assertEqual(theorem.problem, "Short manifest proof reference smoke test.")

    def test_split_proofs_use_list_lines(self):
        with Patcher() as patcher:
            split_dir = DEFAULT_YAML_PATH.with_name("split_proofs")
            proof_path = _fake_file(
                patcher.fs,
                split_dir / "list-lines.proof.yaml",
                """
                problem: Synthetic list-lines proof.
                lines:
                  - step: A proof line.
                """,
            )
            data = yaml.safe_load(proof_path.read_text(encoding="utf-8"))
            self.assertIsInstance(data["lines"], list)  # type: ignore

    def test_depends_lines_desugaring(self):
        yaml_text = textwrap.dedent(
            """
            - problem: Depends lines smoke test.
              lines:
                1:
                  step: Proof by BLANK.
                  correct: contradiction
                  incorrect: contrapositive
                2:
                  step: Assume $x$ is BLANK.
                  correct: even
                  incorrect: odd
                3:
                  step: Assume $y$ is BLANK.
                  correct: odd
                  incorrect: even
                4:
                  step: Therefore BLANK.
                  correct: $x$
                  incorrect: $y$
                  depends:
                    lines: 1, 2, 3
            """
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "depends_lines.yaml"
            path.write_text(yaml_text, encoding="utf-8")

            theorem = loads(path)[0]

        self.assertEqual(theorem.lines[3].depends, frozenset({1, 2, 3}))
        self.assertEqual(theorem.lines[3].implicit_depends, frozenset())

    def test_depends_lines_and_names_desugaring(self):
        yaml_text = textwrap.dedent(
            """
            - problem: Depends mixed smoke test.
              lines:
                1:
                  step: Proof by BLANK.
                  correct: contradiction
                  incorrect: contrapositive
                2:
                  step: Assume $A$ is BLANK.
                  correct: set
                  incorrect: number
                3:
                  step: Assume $x_0$ is BLANK.
                  correct: even
                  incorrect: odd
                4:
                  step: Therefore BLANK.
                  correct: $A$
                  incorrect: $x_0$
                  depends:
                    lines: 1
                    names: A, x_0
            """
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "depends_mixed.yaml"
            path.write_text(yaml_text, encoding="utf-8")

            theorem = loads(path)[0]

        self.assertEqual(theorem.lines[3].depends, frozenset({1, 2, 3}))
        self.assertEqual(theorem.lines[3].implicit_depends, frozenset())
