#!/usr/bin/env python3
"""Benchmark end-to-end rendering of a pl-proof-yaml proof collection."""

from __future__ import annotations

import argparse
import statistics
import sys
from pathlib import Path
from time import perf_counter


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
ELEMENT_ROOT = REPOSITORY_ROOT / "elements/pl-proof-yaml"
DEFAULT_PROOF_FILE = Path("serverFilesCourse/public_examples.proofs")

sys.path.insert(0, str(ELEMENT_ROOT))

import pl_proof_yaml  # noqa: E402
from pl_proof_yaml.proof_yaml_parser import loads  # noqa: E402


def render_collection(proof_file: Path, proof_count: int) -> None:
    relative_proof_file = proof_file.relative_to(
        REPOSITORY_ROOT / "serverFilesCourse"
    )
    data = {
        "options": {
            "server_files_course_path": str(REPOSITORY_ROOT / "serverFilesCourse"),
            "client_files_course_path": str(REPOSITORY_ROOT / "clientFilesCourse"),
            "question_path": str(REPOSITORY_ROOT / "questions"),
        }
    }

    for proof_index in range(proof_count):
        element_html = (
            '<pl-proof-yaml answers-name="proof" '
            f'proof-file="{relative_proof_file}" proof-index="{proof_index}">'
            "</pl-proof-yaml>"
        )
        rendered = pl_proof_yaml.render(element_html, data)
        if "<pl-order-blocks" not in rendered:
            raise RuntimeError(f"Proof index {proof_index} did not render order blocks")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "proof_file",
        nargs="?",
        type=Path,
        default=DEFAULT_PROOF_FILE,
        help="proof collection relative to the repository root",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=5,
        help="number of measured collection renders (default: 5)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.iterations < 1:
        raise SystemExit("--iterations must be at least 1")

    proof_file = (REPOSITORY_ROOT / args.proof_file).resolve()
    server_files_course = (REPOSITORY_ROOT / "serverFilesCourse").resolve()
    if server_files_course not in proof_file.parents:
        raise SystemExit("proof_file must be inside serverFilesCourse")

    proof_count = len(loads(proof_file))
    if proof_count == 0:
        raise SystemExit(f"No proofs found in {proof_file}")

    samples: list[float] = []
    with pl_proof_yaml.debugging_mode(False):
        render_collection(proof_file, proof_count)
        for _ in range(args.iterations):
            started = perf_counter()
            render_collection(proof_file, proof_count)
            samples.append(perf_counter() - started)

    relative_path = proof_file.relative_to(REPOSITORY_ROOT)
    median = statistics.median(samples)
    print(f"Rendered {proof_count} proofs from {relative_path}")
    print(
        f"Median: {median:.3f}s per collection "
        f"({median / proof_count * 1000:.2f}ms per proof); "
        f"range: {min(samples):.3f}s-{max(samples):.3f}s"
    )


if __name__ == "__main__":
    main()
