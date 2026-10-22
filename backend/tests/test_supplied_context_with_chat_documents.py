"""A follow-up in a chat with an attached file is about the file.

After uploading a fixed-asset register and asking for the PPE note, "Prepare
the journal entry for this year's depreciation." was checked against the
previous MESSAGE (the word "this" pointed back), which holds no entries, so
Kriton asked the user to paste them. The follow-up does not re-send the file;
it is restored from the conversation, and the check ran before that.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.orchestration import service
from app.orchestration.schemas import AskKritonRequest, ConversationMessage


class _StopAfterTheCheck(Exception):
    pass


def _stop(*_args, **_kwargs):
    raise _StopAfterTheCheck


@pytest.mark.parametrize("chat_documents, checked", [(["doc-fixed-assets"], False), ([], True)])
async def test_the_entries_check_is_skipped_when_the_chat_has_a_file(monkeypatch, chat_documents, checked):
    from app.orchestration import input_requirements

    for name in dir(service):
        if name.startswith("audit_"):
            monkeypatch.setattr(service, name, AsyncMock())
    monkeypatch.setattr(service, "_finalise_and_return", AsyncMock())
    monkeypatch.setattr(service, "list_authorized_engagements", AsyncMock(return_value=[]))
    monkeypatch.setattr(service, "resolve_conversation_document_ids", AsyncMock(return_value=chat_documents))
    spy = MagicMock(return_value=None)
    monkeypatch.setattr(service, "missing_in_supplied_context", spy)
    # Stop the pipeline right after the check: nothing later is under test.
    monkeypatch.setattr(input_requirements, "needs_invoice_attachment", _stop)

    request = AskKritonRequest(
        query="Prepare the journal entry for this year's depreciation.",
        conversation_id="chat-1",
        conversation_history=[ConversationMessage(role="user", content="Prepare the property, plant and equipment note for the financial statements.")],
    )
    with pytest.raises(_StopAfterTheCheck):
        await service.ask_kriton(db=object(), sync_db=object(), actor_id="u", tenant_id="t", role="Accountant", request=request)
    assert spy.called is checked
