"""Questions naming an IFRS standard get the passage of its official text
that answers them (the governed library holds no IFRS 18 or IAS 2)."""
from app.orchestration import official_standards
from app.orchestration.official_standards import best_passages, official_standard_excerpts

IAS2 = (
    "This Standard provides guidance on the determination of cost and its recognition as an expense, including any "
    "write-down to net realisable value. The objective of this Standard is to prescribe the accounting treatment for "
    "inventories. Inventories shall be measured at the lower of cost and net realisable value. "
    "A new assessment is made of net realisable value in each subsequent period. When the circumstances that "
    "previously caused inventories to be written down below cost no longer exist, the amount of the write-down is "
    "reversed (ie the reversal is limited to the amount of the original write-down). The amount of any reversal of "
    "any write-down of inventories shall be recognised as a reduction in the amount of inventories recognised as an "
    "expense in the period in which the reversal occurs. An entity shall disclose the accounting policies adopted."
)


def test_a_reversal_question_finds_the_reversal_paragraph_by_stem():
    question = "Can an inventory write-down be reversed when NRV increases?"
    assert "the amount of the write-down is reversed" in best_passages(IAS2, question, 700)
    # With room for one passage, the reversal rule ranks first — not the objective.
    tight = best_passages(IAS2, question, 260)
    assert "revers" in tight and "prescribe the accounting treatment" not in tight


def test_nothing_is_returned_when_nothing_matches():
    assert best_passages(IAS2, "What is the VAT registration threshold?", 400) == ""


async def test_only_named_standards_are_fetched_and_cited(monkeypatch):
    fetched = []

    async def fake_download(code):
        fetched.append(code)
        return IAS2 if code == "ias2" else ""

    monkeypatch.setattr(official_standards, "_download_standard", fake_download)
    official_standards._standard_cache.clear()
    sources = await official_standard_excerpts("Under IAS 2, can a write-down be reversed?")
    assert fetched == ["ias2"]
    assert sources[0].url.endswith("/ias2.html") and "reversed" in sources[0].snippet
    assert await official_standard_excerpts("What is accrual accounting?") == []
