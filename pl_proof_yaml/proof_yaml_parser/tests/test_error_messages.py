import tempfile
import textwrap
from pathlib import Path

from ..errors import (
    BadTypeError,
    MissingFieldError,
    NameParseError,
    ParseError,
    UnsupportedValueError,
)
from ..parse import loads
from .helpers import TestCase


class TestErrorMessages(TestCase):
    def _write_yaml(self, yaml_text: str) -> Path:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        path = Path(tmpdir.name) / "bad.yaml"
        path.write_text(textwrap.dedent(yaml_text), encoding="utf-8")
        return path

    def _assert_message_parts(self, exc: Exception, *parts: str) -> None:
        message = str(exc)
        for part in parts:
            self.assertIn(part, message)

    def test_missing_step_message(self):
        path = self._write_yaml(
            """
            - problem: Missing step example.
              lines:
                1:
                  correct: contradiction
                  incorrect: contrapositive
            """
        )

        with self.assertRaises(MissingFieldError) as ctx:
            loads(path)

        self._assert_message_parts(
            ctx.exception,
            'Missing proof line attribute: "step"',
            "Proof 0 > Proof Line 1:",
            "step: ...",
            "^ try adding this here",
        )

    def test_bad_lines_type_message(self):
        path = self._write_yaml(
            """
            - problem: Bad lines type example.
              lines: 1
            """
        )

        with self.assertRaises(BadTypeError) as ctx:
            loads(path)

        self._assert_message_parts(
            ctx.exception,
            "lines must be a list or a dict, not a int",
            "Proof 0:",
            "Bad lines type example.",
            "Source:",
        )

    def test_bad_subgoal_lines_type_message(self):
        path = self._write_yaml(
            """
            - problem: Bad subgoal lines type example.
              lines:
                - subgoal: Case Even
                  lines: 1
            """
        )

        with self.assertRaises(BadTypeError) as ctx:
            loads(path)

        self._assert_message_parts(
            ctx.exception,
            "subgoal lines must be a list or a dict, not a int",
            "Proof 0 > Proof Subgoal 1:",
            "Case Even",
            "Source:",
        )

    def test_bad_depends_keyword_message(self):
        path = self._write_yaml(
            """
            - problem: Bad depends example.
              lines:
                1:
                  step: Proof by BLANK.
                  correct: contradiction
                  incorrect: contrapositive
                2:
                  step: Therefore BLANK.
                  correct: $x$
                  incorrect: $y$
                  depends:
                    previous: nope
            """
        )

        with self.assertRaises(UnsupportedValueError) as ctx:
            loads(path)

        self._assert_message_parts(
            ctx.exception,
            "Unsupported previous depends value: 'nope'",
            "Proof 0 > Proof Line 2:",
            "previous: nope",
        )

    def test_unknown_depends_variable_message(self):
        path = self._write_yaml(
            """
            - problem: Unknown depends variable example.
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
                  step: Therefore BLANK.
                  correct: $x$
                  incorrect: $y$
                  depends: $z$, 1
            """
        )

        with self.assertRaises(NameParseError) as ctx:
            loads(path)

        self._assert_message_parts(
            ctx.exception,
            "Unknown name",
            "z",
            "Proof 0 > Proof Line 3:",
            "$z$, 1",
        )

    def test_unknown_depends_names_message(self):
        path = self._write_yaml(
            """
            - problem: Unknown depends names example.
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
                  step: Therefore BLANK.
                  correct: $x$
                  incorrect: $y$
                  depends:
                    names: z, x
            """
        )

        with self.assertRaises(NameParseError) as ctx:
            loads(path)

        self._assert_message_parts(
            ctx.exception,
            "Unknown name",
            "z",
            "Proof 0 > Proof Line 3:",
            "names: z, x",
        )

    def test_bad_depends_lines_message(self):
        path = self._write_yaml(
            """
            - problem: Bad depends lines example.
              lines:
                1:
                  step: Proof by BLANK.
                  correct: contradiction
                  incorrect: contrapositive
                2:
                  step: Therefore BLANK.
                  correct: $x$
                  incorrect: $y$
                  depends:
                    lines: nope
            """
        )

        with self.assertRaises(UnsupportedValueError) as ctx:
            loads(path)

        self._assert_message_parts(
            ctx.exception,
            "Unsupported depends.lines value",
            "nope",
            "Proof 0 > Proof Line 2:",
            "lines: nope",
        )

    def test_bad_depends_lines_type_message(self):
        path = self._write_yaml(
            """
            - problem: Bad depends lines type example.
              lines:
                - step: A line.
                  depends:
                    lines: null
            """
        )

        with self.assertRaises(BadTypeError) as ctx:
            loads(path)

        self._assert_message_parts(
            ctx.exception,
            "depends.lines value must be a int or a list or a tuple or a str, not a NoneType",
            "Proof 0 > Proof Line 1:",
            "lines: null",
        )

    def test_boolean_previous_depends_is_not_an_integer(self):
        path = self._write_yaml(
            """
            - problem: Boolean previous depends example.
              lines:
                - step: A line.
                  depends:
                    previous: true
            """
        )

        with self.assertRaises(BadTypeError) as ctx:
            loads(path)

        self._assert_message_parts(
            ctx.exception,
            "previous depends value must be a int or a str, not a bool",
            "previous: true",
        )

    def test_boolean_depends_is_not_an_integer(self):
        path = self._write_yaml(
            """
            - problem: Boolean depends example.
              lines:
                - step: A line.
                  depends: true
            """
        )

        with self.assertRaises(BadTypeError) as ctx:
            loads(path)

        self._assert_message_parts(
            ctx.exception,
            "depends value must be a int or a dict or a list or a tuple or a str, not a bool",
            "depends: true",
        )

    def test_bad_dependents_refers_to_depends(self):
        path = self._write_yaml(
            """
            - problem: Bad depends example.
              lines:
                1:
                  step: Proof by BLANK.
                  correct: contradiction
                  incorrect: contrapositive
                  dependents: 2
                2:
                  step: hello
            """
        )

        with self.assertRaises(BadTypeError) as ctx:
            loads(path)

        self._assert_message_parts(
            ctx.exception,
            "dependents value must be a str, not a int",
            "Proof 0 > Proof Line 1:",
            "dependents: 2",
        )

    def test_circular_dependency_message(self):
        path = self._write_yaml(
            """
            - problem: Circular depends example.
              lines:
                1:
                  step: First line.
                  depends: 2
                2:
                  step: Second line.
                  depends: 1
            """
        )

        with self.assertRaises(ParseError) as ctx:
            loads(path)

        self._assert_message_parts(
            ctx.exception,
            "Circular dependency detected",
            "1 -> 2 -> 1",
            "Proof 0:",
        )
