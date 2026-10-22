"""Tenant/user scoped durable input memory, independent of model success.

Only the authenticated caller's own server-recorded user turns are loaded.
Assistant answers and client-supplied calculation snapshots are never facts.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
import re

from sqlalchemy import delete, select, update, or_
from sqlalchemy.exc import SQLAlchemyError

from app.domains.orchestration_state.models import ConversationTurn
from app.orchestration.schemas import ConversationMessage

logger = logging.getLogger(__name__)
MAX_TURNS = 64


def _new_financial_context(query):
    from app.orchestration.calculations.inventory_statement import _inventory_revision
    if _inventory_revision(query) is not None:
        return False
    return (len(re.findall(r'[£$€₹]\s*-?\d', query)) >= 2
            and not re.search(r'\b(?:original|same|keep|revised|now|previous answer)\b', query, re.I))


async def _restore_failed_session(db, tenant_id, user_id):
    if not db.is_active:
        await db.rollback()
        from app.core.database import restore_request_identity
        await restore_request_identity(db, tenant_id=tenant_id, user_id=user_id)


def _scope(tenant_id, user_id, conversation_id):
    return (ConversationTurn.tenant_id == tenant_id, ConversationTurn.user_id == user_id,
            ConversationTurn.conversation_id == conversation_id)


async def load_turns(db, *, tenant_id, user_id, conversation_id) -> list[ConversationTurn]:
    if not conversation_id or len(conversation_id) > 200:
        return []
    try:
        async with db.begin_nested():
            result = await db.execute(select(ConversationTurn).where(
                *_scope(tenant_id, user_id, conversation_id),
                ConversationTurn.expires_at > datetime.now(timezone.utc),
            ).order_by(ConversationTurn.created_at.desc(), ConversationTurn.id.desc()).limit(MAX_TURNS))
            return list(reversed(result.scalars().all()))
    except SQLAlchemyError as exc:
        await _restore_failed_session(db, tenant_id, user_id)
        logger.warning('Conversation memory unavailable (%s); using supplied history', type(exc).__name__)
        return []


def merge_history(history, turns) -> list[ConversationMessage]:
    # Retain a server-recorded structured statement baseline and its exact
    # revision instructions even after the browser drops earlier messages.
    latest = {}
    for turn in reversed(turns):
        if turn.snapshot.get('statement_baseline'):
            latest = turn.snapshot
            break
        if turn.snapshot.get('reset_statement_context'):
            break
    texts = [latest['statement_baseline']] if latest else []
    texts += latest.get('statement_revisions', [])
    from app.orchestration.calculations.inventory_statement import _inventory_revision
    # A revision rejected for invalid/ambiguous inputs never became an active
    # version. Replaying its raw text as an applied correction poisons later
    # valid follow-ups. Keep it in the ledger, not in calculation history.
    def rejected_revision(turn):
        status = turn.snapshot.get('task_state', {}).get('calculation_status')
        return status in {'clarification_required', 'undefined'} and _inventory_revision(turn.user_text) is not None
    texts += [t.user_text for t in turns[-12:] if not rejected_revision(t)]
    users = set(texts) | {t.user_text for t in turns if rejected_revision(t)}
    merged = [ConversationMessage(role='user', content=text) for text in dict.fromkeys(texts)]
    # Once the statement has a server baseline, a replayed browser "user"
    # message cannot silently replace it. Corrections belong in the current
    # query and are recorded as a new turn. Preserve older client-only input
    # for conversations that have not acquired a structured baseline yet.
    merged += [m for m in history if m.role != 'user' or (not latest and m.content not in users)]
    if len(merged) <= 12:
        return merged
    # Pin the structured baseline and revisions before retaining recent turns.
    pinned = min(1 + len(latest.get('statement_revisions', [])), 5) if latest else 0
    return merged[:pinned] + merged[-(12 - pinned):]


async def save_turn(db, *, tenant_id, user_id, conversation_id, query_id, user_text) -> None:
    if not conversation_id or len(conversation_id) > 200 or len(user_text) > 8000:
        return
    now = datetime.now(timezone.utc)
    try:
        async with db.begin_nested():
            existing = await db.scalar(select(ConversationTurn.id).where(
                *_scope(tenant_id, user_id, conversation_id), ConversationTurn.query_id == query_id))
            if existing:
                return
            db.add(ConversationTurn(tenant_id=tenant_id, user_id=user_id, conversation_id=conversation_id,
                                    query_id=query_id, user_text=user_text,
                                    snapshot={'reset_statement_context': True} if _new_financial_context(user_text) else {},
                                    created_at=now, expires_at=now + timedelta(days=30)))
            await db.flush()
            await db.execute(delete(ConversationTurn).where(
                *_scope(tenant_id, user_id, conversation_id), ConversationTurn.expires_at <= now
            ).execution_options(synchronize_session='fetch'))
            keep = select(ConversationTurn.id).where(*_scope(tenant_id, user_id, conversation_id)).order_by(
                ConversationTurn.created_at.desc(), ConversationTurn.id.desc()).limit(MAX_TURNS - 1)
            # Reserve one slot for the last structured state or explicit
            # context reset, rather than dropping it after 64 short questions.
            pinned = select(ConversationTurn.id).where(
                *_scope(tenant_id, user_id, conversation_id),
                or_(ConversationTurn.snapshot['calculation'].as_string().is_not(None),
                    ConversationTurn.snapshot['reset_statement_context'].as_boolean().is_(True)),
            ).order_by(ConversationTurn.created_at.desc(), ConversationTurn.id.desc()).limit(1).scalar_subquery()
            await db.execute(delete(ConversationTurn).where(
                *_scope(tenant_id, user_id, conversation_id), ConversationTurn.id.not_in(keep),
                or_(pinned.is_(None), ConversationTurn.id != pinned),
            ).execution_options(synchronize_session='fetch'))
        await db.commit()
    except SQLAlchemyError as exc:
        await _restore_failed_session(db, tenant_id, user_id)
        logger.warning('Conversation turn could not be retained (%s)', type(exc).__name__)


def snapshot_for(query, history, result, query_id) -> dict:
    from app.orchestration.calculations.statements import operating_statement, _SCENARIO_CHANGE
    from app.orchestration.numerical_facts import calculation_facts
    snapshot = {'version': 1, 'facts': [f.model_dump(mode='json') for f in calculation_facts(result, query_id)]}
    # Persist a descriptive contract in the existing scoped snapshot, without
    # granting authority to history or changing routing/planner policy.
    requested = [name for name, pattern in (
        ('formulas', r'\bformulas?|working\b'),
        ('table', r'\btable|side by side\b'),
        ('visual', r'\bchart|graph|plot\b'),
        ('explanation', r'\bexplain|why\b'),
        ('management_questions', r'\bquestions? management\b'),
    ) if re.search(pattern, query, re.I)]
    snapshot['task_state'] = {
        'task_type': result.formula_ids,
        'current_intent': query,
        'figure_version': query_id,
        'has_referenced_inputs': any(i.source_location != 'query' for i in result.inputs),
        'inputs': [i.model_dump(mode='json') for i in result.inputs],
        'calculation_dependencies': {'formulas': result.formula_ids, 'input_names': [i.name for i in result.inputs]},
        'derived_outputs': [o.model_dump(mode='json') for o in result.outputs],
        'assumptions_and_limits': result.notes,
        'clarification_reason': result.message if result.status == 'clarification_required' else None,
        'requested_sections': requested,
        # Calculation completion is not a claim that generated prose is complete.
        'calculation_status': result.status,
        'response_completion': 'pending_final_validation',
    }
    if _new_financial_context(query):
        snapshot['reset_statement_context'] = True
    if result.status != 'success':
        return snapshot
    snapshot['calculation'] = result.model_dump(mode='json')
    if result.formula_ids == ['operating_statement']:
        snapshot.update(statement_baseline=query, statement_revisions=[])
    elif result.formula_ids == ['operating_statement_scenario']:
        users = [m.content for m in history if m.role == 'user']
        for index in reversed(range(len(users))):
            if operating_statement(users[index]) is not None:
                rates = {}
                for text in [*users[index + 1:], query]:
                    for match in _SCENARIO_CHANGE.finditer(text):
                        rates[match['label'].lower()] = match['rate']
                snapshot.update(statement_baseline=users[index], statement_revisions=[
                    f'Increase {label} by {rate}%.' for label, rate in rates.items()])
                break
    return snapshot


def active_calculation(turns):
    """Last intact application calculation, not an assistant's assertion."""
    from app.orchestration.calculations.schemas import CalculationResult
    from pydantic import ValidationError
    for turn in reversed(turns):
        data = turn.snapshot.get('calculation')
        if data:
            try:
                result = CalculationResult.model_validate(data)
            except ValidationError:
                return None
            return result if result.status == 'success' and result.verification_status == 'passed' else None
        if turn.snapshot.get('reset_statement_context'):
            return None
    return None


def calculation_context(result):
    from app.orchestration.numerical_facts import calculation_facts
    if result is None:
        return ''
    lines = ['\nPreviously verified application results (conversation context, not current external rules). '
             'Use only where relevant to this follow-up. New instructions and changed inputs require recalculation:']
    lines += [f'{f.name}: {f.value} {f.currency or f.kind}'
              for f in calculation_facts(result, 'memory')
              if f.source == 'calculation']
    return '\n'.join(lines)


async def save_snapshot(db, *, tenant_id, user_id, conversation_id, query_id, snapshot) -> None:
    if not conversation_id:
        return
    try:
        async with db.begin_nested():
            await db.execute(update(ConversationTurn).where(
                *_scope(tenant_id, user_id, conversation_id), ConversationTurn.query_id == query_id,
            ).values(snapshot=snapshot))
        await db.commit()
    except SQLAlchemyError as exc:
        await _restore_failed_session(db, tenant_id, user_id)
        logger.warning('Conversation facts could not be retained (%s)', type(exc).__name__)


def active_visualization(turns):
    from app.orchestration.visualization.spec import VisualizationSpec
    from app.orchestration.visualization.validator import VisualizationValidator
    from pydantic import ValidationError
    for turn in reversed(turns):
        data = turn.snapshot.get('visualization')
        if data:
            try:
                spec = VisualizationSpec.model_validate(data)
            except ValidationError:
                return None
            # External evidence must be re-authorised by normal retrieval.
            return spec if not spec.sources and VisualizationValidator().validate(spec).passed else None
        state = turn.snapshot.get('task_state', {})
        if turn.snapshot.get('calculation') or turn.snapshot.get('reset_statement_context') or state.get('relation') == 'independent':
            return None
    return None


def active_calculation_state(turns):
    """Read the last server-validated typed state, retaining the root inputs."""
    from app.orchestration.calculations.schemas import CalculationTaskState
    from pydantic import ValidationError
    for turn in reversed(turns):
        data = turn.snapshot.get('calculation_state')
        if data:
            try:
                return CalculationTaskState.model_validate(data)
            except ValidationError:
                return None
        if turn.snapshot.get('calculation') or turn.snapshot.get('reset_statement_context'):
            return None
    return None
