"""Seed credentials come from the environment, never the repository (25 Oct
2026: one committed password unlocked both the demo account and the seeded
reviewer, so the reviewer could approve the demo account's submissions).
No database or network."""
import re
import typing
from pathlib import Path

import pytest

SEED = Path(__file__).resolve().parents[1] / "scripts" / "seed_dev_user.py"


def test_no_password_is_committed_in_the_seed_script():
    source = SEED.read_text()
    assert not re.search(r"(?i)password\w*\s*=\s*['\"][^'\"]+['\"]", source)


def test_the_module_still_imports_without_passwords(monkeypatch):
    monkeypatch.delenv("EVAL_PASSWORD", raising=False)
    monkeypatch.delenv("SEED_REVIEWER_PASSWORD", raising=False)
    from scripts.seed_dev_user import SOURCES                    # other tests import its reference data
    assert SOURCES


@pytest.mark.parametrize("demo, reviewer, message", [
    ("", "", "Set EVAL_PASSWORD and SEED_REVIEWER_PASSWORD"),
    ("one-value", "", "Set EVAL_PASSWORD and SEED_REVIEWER_PASSWORD"),
    ("same-value", "same-value", "must differ"),
])
def test_seeding_refuses_missing_or_shared_passwords(monkeypatch, demo, reviewer, message):
    from scripts.seed_dev_user import seed_passwords
    monkeypatch.setenv("EVAL_PASSWORD", demo)
    monkeypatch.setenv("SEED_REVIEWER_PASSWORD", reviewer)
    with pytest.raises(RuntimeError, match=message):
        seed_passwords()


def test_two_different_passwords_are_used(monkeypatch):
    from scripts.seed_dev_user import seed_passwords
    monkeypatch.setenv("EVAL_PASSWORD", "demo-value")
    monkeypatch.setenv("SEED_REVIEWER_PASSWORD", "reviewer-value")
    assert seed_passwords() == ("demo-value", "reviewer-value")


def test_market_data_annotations_resolve():
    from app.orchestration import market_data
    assert typing.get_type_hints(market_data._number_text)["value"] == typing.Optional[float]
