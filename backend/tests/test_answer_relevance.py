"""An answer about a different topic than the question is caught (a VAT
question once got the previous turn's IFRS/US GAAP inventory answer)."""
from app.orchestration.answer_relevance import off_topic
from app.orchestration.conversation import conversation_prompt
from app.orchestration.schemas import ConversationMessage as M

VAT_Q = ("A business has sales of £120,000, purchases of £48,000 and operating expenses of £22,000 for the quarter. "
         "How much VAT do I owe, and can I deduct all my expenses?")
INVENTORY_A = ("**IFRS (IAS 2 – Inventories)**\n- Inventories are measured at the lower of cost and net realisable value [REF-9].\n"
               "- Cost of inventories includes purchase costs [REF-9].\n**US GAAP (ASC 330 – Inventory)**\n"
               "- Inventories are valued at the lower of cost or market [REF-15].")
VAT_A = ("Output VAT is due on taxable sales and input VAT on business purchases can be reclaimed with valid VAT "
         "invoices [REF-1]. I need your VAT registration status and whether the figures include VAT.")


def test_a_vat_question_answered_about_inventory_is_off_topic():
    assert off_topic(VAT_Q, INVENTORY_A)


def test_an_inventory_question_answered_with_vat_evidence_is_off_topic():
    assert off_topic("Compare IFRS and US GAAP inventory measurement, including write-down reversals.",
                     "VAT is charged at 20% [REF-1]. Input tax on purchases is reclaimed on the VAT return [REF-2]. "
                     "HMRC requires VAT invoices [REF-3].")


def test_answers_on_the_asked_topic_pass():
    assert not off_topic(VAT_Q, VAT_A)
    assert not off_topic("Compare IFRS and US GAAP inventory measurement.", INVENTORY_A)
    # A topic the question does not list in the vocabulary is never judged.
    assert not off_topic("What is accrual accounting?", INVENTORY_A)


def test_history_tells_the_model_to_answer_only_the_current_request():
    prompt = conversation_prompt([M(role="user", content="Compare IFRS and US GAAP inventory."),
                                  M(role="assistant", content=INVENTORY_A)])
    assert "Answer the CURRENT request only" in prompt
