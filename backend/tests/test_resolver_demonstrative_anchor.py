"""A demonstrative ("that lease") beats "Now …" continuation (27 Oct 2026).

After a lease conversation and an unrelated break-even question, "Now
calculate … for that lease" was anchored to the break-even turn: "Now" was
read as continuing the latest exchange before "that lease" was looked up,
so the break-even scenario was sent and the lease was not. No model.
"""
from app.orchestration.conversation_resolver import resolve_conversation
from app.orchestration.schemas import ConversationMessage as M

LEASE = "We lease a warehouse: annual payments of £30,000 in arrears, discount rate 6%, lease term 5 years."
BREAKEVEN = "Separately: break-even for a product selling at £25 with variable cost £15 and fixed costs £50,000?"


def _history(*users):
    return [message for user in users for message in (M(role="user", content=user),
                                                      M(role="assistant", content=f"Answer to: {user[:40]}"))]


def _kept_users(query, history):
    return [m.content for m in resolve_conversation(query, history).history() if m.role == "user"]


def test_that_lease_after_an_unrelated_question_links_to_the_lease():
    kept = _kept_users("Now calculate the lease liability and first-year interest for that lease.",
                       _history(LEASE, BREAKEVEN))
    assert LEASE in kept and BREAKEVEN not in kept


def test_now_still_continues_the_latest_exchange_it_names():
    kept = _kept_users("Now calculate the break-even units for that product.", _history(LEASE, BREAKEVEN))
    assert BREAKEVEN in kept and LEASE not in kept


def test_now_without_a_demonstrative_still_continues_the_latest():
    kept = _kept_users("Now show the margin of safety.", _history(LEASE, BREAKEVEN))
    assert BREAKEVEN in kept


def test_that_lease_right_after_the_lease_is_unchanged():
    kept = _kept_users("Now calculate the first-year interest for that lease.", _history(BREAKEVEN, LEASE))
    assert LEASE in kept and BREAKEVEN not in kept
