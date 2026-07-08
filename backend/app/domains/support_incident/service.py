from datetime import datetime, timezone
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.domains.support_incident.models import SecurityIncident, SupportTicket
from app.domains.support_incident.schemas import TicketCreateRequest
from app.domains.risk_safety.models import SafetyEvent


def _now() -> datetime:
    return datetime.now(timezone.utc)


def list_tickets(db: Session, tenant_id: str) -> list[SupportTicket]:
    return db.query(SupportTicket).filter(SupportTicket.tenant_id == tenant_id).all()


def create_ticket(
    db: Session, tenant_id: str, created_by: str, payload: TicketCreateRequest
) -> SupportTicket:
    ticket = SupportTicket(
        tenant_id=tenant_id,
        category=payload.category,
        severity=payload.severity,
        query_id=payload.query_id,
        created_by=created_by,
    )
    db.add(ticket)
    db.commit()
    db.refresh(ticket)
    return ticket


def update_ticket_status(
    db: Session, tenant_id: str, ticket_id: str, status: str
) -> SupportTicket | None:
    ticket = db.query(SupportTicket).filter(SupportTicket.id == ticket_id, SupportTicket.tenant_id == tenant_id).first()
    if ticket is None:
        return None
    ticket.status = status
    db.commit()
    db.refresh(ticket)
    return ticket


# --- Security Incidents ---

def auto_create_security_incident(
    db: Session, query_id: str, source: str, user_id: str, tenant_id: str
) -> SecurityIncident:
    """Synchronously creates a security incident (called from Risk Safety domain)."""
    incident = SecurityIncident(
        tenant_id=tenant_id,
        title=f"Auto-generated incident from {source}",
        severity="High" if source == "RESTRICTED_CONTROL_BYPASS" else "Medium",
        containment_status="OPEN",
        source=source,
        query_id=query_id,
        restricted_sub_class=source,
        timeline=[{
            "timestamp": _now().isoformat(),
            "actor": "system",
            "action": "created",
            "note": f"Incident auto-created due to {source} from user {user_id}",
        }],
    )
    db.add(incident)
    db.commit()
    db.refresh(incident)
    return incident


def list_incidents(db: Session, tenant_id: str, status: str = None) -> list[SecurityIncident]:
    query = db.query(SecurityIncident).filter(SecurityIncident.tenant_id == tenant_id)
    if status:
        query = query.filter(SecurityIncident.containment_status == status)
    return query.order_by(SecurityIncident.opened_at.desc()).all()


def get_incident(db: Session, tenant_id: str, incident_id: str) -> SecurityIncident | None:
    return db.query(SecurityIncident).filter(
        SecurityIncident.id == incident_id, SecurityIncident.tenant_id == tenant_id
    ).first()


def update_incident(
    db: Session, tenant_id: str, incident_id: str, action: str, actor: str, note: str
) -> SecurityIncident | None:
    incident = get_incident(db, tenant_id, incident_id)
    if not incident:
        return None

    if action.upper() == "CONTAIN":
        incident.containment_status = "CONTAINED"
    
    new_timeline = list(incident.timeline or [])
    new_timeline.append({
        "timestamp": _now().isoformat(),
        "actor": actor,
        "action": action,
        "note": note,
    })
    incident.timeline = new_timeline
    db.commit()
    db.refresh(incident)
    return incident


def close_incident(
    db: Session, tenant_id: str, incident_id: str, resolver: str, resolution_note: str
) -> SecurityIncident | None:
    incident = get_incident(db, tenant_id, incident_id)
    if not incident:
        return None

    incident.containment_status = "RESOLVED"
    incident.resolved_at = _now()
    incident.resolution_note = resolution_note
    
    new_timeline = list(incident.timeline or [])
    new_timeline.append({
        "timestamp": _now().isoformat(),
        "actor": resolver,
        "action": "CLOSED",
        "note": resolution_note,
    })
    incident.timeline = new_timeline

    # Log to Safety Event Ledger (ZL-T0-04 §15)
    db.add(SafetyEvent(
        event_type="security_incident_resolved",
        query_id=incident.query_id,
        payload={
            "incident_id": incident.id,
            "resolver": resolver,
            "resolution_note": resolution_note,
        }
    ))

    db.commit()
    db.refresh(incident)
    return incident


def get_incident_stats(db: Session, tenant_id: str) -> dict:
    incidents = list_incidents(db, tenant_id)
    total = len(incidents)
    open_count = sum(1 for i in incidents if i.containment_status == "OPEN")
    contained = sum(1 for i in incidents if i.containment_status == "CONTAINED")
    resolved = sum(1 for i in incidents if i.containment_status == "RESOLVED")
    critical = sum(1 for i in incidents if i.severity == "Critical")
    high = sum(1 for i in incidents if i.severity == "High")
    
    return {
        "total": total,
        "open": open_count,
        "contained": contained,
        "resolved": resolved,
        "critical": critical,
        "high": high,
    }
