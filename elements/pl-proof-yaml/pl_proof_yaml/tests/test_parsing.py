from types import SimpleNamespace
from typing import Any

import pytest

import pl_proof_yaml
from pl_proof_yaml import BlankDropdown


@pytest.fixture
def dropdown() -> BlankDropdown:
    return BlankDropdown(
        answers_name="proof-line-1-BLANK",
        label="line-1:BLANK",
        width_ch=5,
        choices=(
            {"text": "right", "correct": "true"},
            {"text": "wrong", "correct": "false"},
        ),
        allow_blank=True,
    )


def _parse_with_selected_block(
    monkeypatch: pytest.MonkeyPatch,
    dropdown: BlankDropdown,
    selected_inner_html: str,
    submitted_answers: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "submitted_answers": submitted_answers or {},
        "format_errors": {},
    }

    monkeypatch.setattr(
        pl_proof_yaml,
        "_build_parts",
        lambda _element_html, _data: (
            "<pl-order-blocks></pl-order-blocks>",
            [dropdown],
            None,
        ),
    )

    def parse_order_blocks(_element_html: str, parse_data: dict[str, Any]) -> None:
        parse_data["submitted_answers"]["proof"] = [
            {"inner_html": selected_inner_html}
        ]

    controllers = {
        "pl-order-blocks": SimpleNamespace(parse=parse_order_blocks),
        "pl-multiple-choice": SimpleNamespace(
            parse=lambda _element_html, _data: None
        ),
    }
    monkeypatch.setattr(
        pl_proof_yaml,
        "_load_element_controller",
        lambda element_name: controllers[element_name],
    )

    pl_proof_yaml.parse('<pl-proof-yaml answers-name="proof" />', data)
    return data


def test_parse_rejects_empty_dropdown_in_selected_block(
    monkeypatch: pytest.MonkeyPatch, dropdown: BlankDropdown
) -> None:
    data = _parse_with_selected_block(
        monkeypatch,
        dropdown,
        pl_proof_yaml._render_multiple_choice(dropdown),
    )

    assert data["format_errors"]["proof"] == (
        "All selection boxes in the submitted blocks must have an answer."
    )


def test_parse_allows_empty_dropdown_in_unselected_block(
    monkeypatch: pytest.MonkeyPatch, dropdown: BlankDropdown
) -> None:
    data = _parse_with_selected_block(monkeypatch, dropdown, "A block without a blank.")

    assert data["format_errors"] == {}


def test_parse_allows_answered_dropdown_in_selected_block(
    monkeypatch: pytest.MonkeyPatch, dropdown: BlankDropdown
) -> None:
    data = _parse_with_selected_block(
        monkeypatch,
        dropdown,
        pl_proof_yaml._render_multiple_choice(dropdown),
        {dropdown.answers_name: "0"},
    )

    assert data["format_errors"] == {}
