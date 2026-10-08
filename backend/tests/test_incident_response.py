"""Incident actions record the authenticated user, not a client-supplied name,
and a resolved incident cannot be acted on again (support_incident/router.py)."""
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.domains.identity.models import Tenant, User
from app.domains.support_incident.models import SecurityIncident
from app.domains.support_incident.router import post_incident_action, post_incident_close
from app.domains.support_incident.schemas import IncidentActionRequest, IncidentCloseRequest


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(engine)()
    session.add_all([
        Tenant(id="t1", name="T"), Tenant(id="t2", name="Other"),
        SecurityIncident(id="inc-1", tenant_id="t1", title="PII in an upload", severity="High",
                         containment_status="OPEN", source="PII_LEAK", timeline=[]),
    ])
    session.commit()
    yield session
    session.close()
    engine.dispose()


def _user(tenant_id="t1") -> User:
    return User(id="u1", tenant_id=tenant_id, email="naresh@example.com", full_name="Naresh Maruthi", role="Admin")


def test_timeline_records_the_signed_in_user_not_the_name_the_client_sent(db):
    incident = post_incident_action(
        "inc-1", IncidentActionRequest(action="CONTAIN", actor="Security Admin", note="Isolated the upload."),
        db=db, actor=_user(),
    )
    assert incident.containment_status == "CONTAINED"
    assert incident.timeline[-1]["actor"] == "Naresh Maruthi (Admin)"

    closed = post_incident_close(
        "inc-1", IncidentCloseRequest(resolver="Someone Else", resolution_note="Purged and notified."),
        db=db, actor=_user(),
    )
    assert closed.containment_status == "RESOLVED"
    assert closed.timeline[-1]["actor"] == "Naresh Maruthi (Admin)"


def test_actor_fields_may_be_omitted(db):
    incident = post_incident_action("inc-1", IncidentActionRequest(action="CONTAIN", note="n"), db=db, actor=_user())
    assert incident.timeline[-1]["actor"] == "Naresh Maruthi (Admin)"


def test_a_resolved_incident_cannot_be_contained_or_closed_again(db):
    post_incident_close("inc-1", IncidentCloseRequest(resolution_note="done"), db=db, actor=_user())
    for call in (
        lambda: post_incident_action("inc-1", IncidentActionRequest(action="CONTAIN", note="n"), db=db, actor=_user()),
        lambda: post_incident_close("inc-1", IncidentCloseRequest(resolution_note="again"), db=db, actor=_user()),
    ):
        with pytest.raises(HTTPException) as err:
            call()
        assert err.value.status_code == 409
    assert db.get(SecurityIncident, "inc-1").containment_status == "RESOLVED"


def test_another_tenants_incident_is_not_found(db):
    with pytest.raises(HTTPException) as err:
        post_incident_action("inc-1", IncidentActionRequest(action="CONTAIN", note="n"), db=db, actor=_user("t2"))
    assert err.value.status_code == 404
