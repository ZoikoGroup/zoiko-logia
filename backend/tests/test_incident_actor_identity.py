"""Incident timelines credit the signed-in user.

The Incident Response page used to send a fixed "Security Admin" as the
actor, and the backend stored it: every containment and resolution was
attributed to a name nobody holds. The actor now comes from the verified
user, and a client-sent name is ignored.
"""
from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.domains.identity.models import Tenant, User
from app.domains.support_incident.models import SecurityIncident
from app.domains.support_incident.router import post_incident_action, post_incident_close
from app.domains.support_incident.schemas import IncidentActionRequest, IncidentCloseRequest


def test_incident_actions_record_the_authenticated_user() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(engine)()
    db.add_all([Tenant(id="t1", name="Acme"),
                User(id="u1", tenant_id="t1", email="ada@example.com", full_name="Ada Lovelace", role="Admin")])
    db.add(SecurityIncident(id="inc-1", tenant_id="t1", title="Bypass attempt", source="CONTROL_BYPASS", timeline=[]))
    db.commit()
    user = db.get(User, "u1")

    post_incident_action("inc-1", IncidentActionRequest(action="CONTAIN", actor="Security Admin", note="Blocked"), db, user)
    incident = post_incident_close("inc-1", IncidentCloseRequest(resolver="Someone Else", resolution_note="Fixed"), db, user)

    assert [e["actor"] for e in incident.timeline] == ["Ada Lovelace", "Ada Lovelace"]
    assert incident.containment_status == "RESOLVED"
    # Older clients that still send no name are accepted.
    assert IncidentActionRequest(action="CONTAIN", note="x").actor is None
