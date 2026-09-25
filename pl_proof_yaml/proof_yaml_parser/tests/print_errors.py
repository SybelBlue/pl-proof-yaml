import textwrap
from pathlib import Path

from pyfakefs.fake_filesystem_unittest import Patcher

from ..errors import (
    BadTypeError,
    MissingFieldError,
    NameParseError,
    ParseError,
    UnrecognizedKeyError,
    UnsupportedValueError,
)
from ..parse import load


def main() -> None:
    examples = (
        (
            ParseError,
            """
            problem: Circular dependency
            lines:
              - step: First line.
                depends: 2
              - step: Second line.
                depends: 1
            """,
        ),
        (
            NameParseError,
            """
            problem: Unknown name
            lines:
              - step: A line.
                depends: $x$
            """,
        ),
        (
            UnsupportedValueError,
            """
            problem: Unsupported value
            lines:
              - step: A line.
                depends:
                  previous: next
            """,
        ),
        (
            UnrecognizedKeyError,
            """
            problem: Unrecognized key
            lines:
              - step: A line.
                answer: yes
            """,
        ),
        (
            MissingFieldError,
            """
            problem: Missing lines
            """,
        ),
        (
            BadTypeError,
            """
            problem: Bad lines type
            lines: one line
            """,
        ),
    )

    with Patcher() as patcher:
        for index, (expected_error, proof_yaml) in enumerate(examples):
            path = Path(f"/examples/error-{index}.proof")
            assert patcher.fs is not None
            patcher.fs.create_file(path, contents=textwrap.dedent(proof_yaml))
            try:
                load(path)
            except expected_error as error:
                print()
                print(f"--- {expected_error.__name__} ---")
                print(error)
            else:
                raise AssertionError(f"Expected {expected_error.__name__}")


if __name__ == "__main__":
    main()
