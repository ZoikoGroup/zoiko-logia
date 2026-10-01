"""Expired attachments — kriton_workspace/documents.py and service.py.

Retrieval has always refused documents past their retention deadline
(`expires_at > CURRENT_TIMESTAMP`). Two places that feed it did not:

  - list_documents(), behind the saved-documents picker, offered expired
    documents for selection
  - the conversation-restore path re-attached them on every later turn

So a document could be picked, show a green chip with a real chunk count,
and then fail every question — while the message blamed file readability,
sending the reader to check a spreadsheet that was perfectly fine.
"""
from __future__ import annotations

from app.orchestration.service import _document_failure_message


def test_an_expired_document_is_named_in_the_message():
    text = _document_failure_message(["kriton-test-fixed-assets.xlsx"])
    assert "kriton-test-fixed-assets.xlsx" in text
    assert "retention period" in text
    assert "Upload the file again" in text


def test_the_message_warns_against_reselecting_the_same_copy():
    """The trap that cost the most time: re-picking from saved documents is
    not an upload, so it links the same dead record."""
    text = _document_failure_message(["a.xlsx"])
    assert "saved documents" in text.lower()


def test_several_expired_documents_are_listed_once_each():
    text = _document_failure_message(["a.xlsx", "b.pdf", "a.xlsx"])
    assert "These documents have" in text
    assert text.count("a.xlsx") == 1
    assert "b.pdf" in text


def test_a_genuinely_unreadable_document_keeps_the_original_wording():
    """Not every empty result is an expiry; when it is not, the advice to
    re-attach or choose another document is still the right advice."""
    text = _document_failure_message([])
    assert "retention period" not in text
    assert "could not retrieve readable evidence" in text


def test_list_documents_filters_on_expiry():
    """Guard on the query itself — the picker must not offer what retrieval
    will refuse."""
    import inspect

    from app.domains.kriton_workspace.documents import list_documents

    source = inspect.getsource(list_documents)
    assert "expires_at" in source, "the saved-documents picker lost its expiry filter"


def test_the_conversation_restore_path_filters_on_expiry():
    import inspect

    from app.domains.kriton_workspace.documents import resolve_conversation_document_ids

    source = inspect.getsource(resolve_conversation_document_ids)
    # Both branches — the explicit-ids one and the restore one — must filter.
    assert source.count("expires_at") >= 2, (
        "restoring a previous turn's attachments must apply the same expiry "
        "condition as attaching them explicitly"
    )
