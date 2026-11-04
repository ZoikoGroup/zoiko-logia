"""WF-01 A2: generate, record and verify as-built manifests.

collect(app) reads what the running application is: its routes and the
permission each enforces (from the route's dependencies), the git commit and
whether the tree is clean, the schema head, and flag names with a hash of
their value (never the value). Each requirement in
registry/wf01_requirement_map.json is mapped to its route and tests: MAPPED
when the route is served with the stated permission and every named test
exists, otherwise UNMAPPED with the reason. Verification is a separate
person's record and is refused for an uncommitted tree.
"""
from __future__ import annotations

import ast
import hashlib
import json
import subprocess
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.domains.admin_governance.governance_access import canonical_sha256, governance_error
from app.domains.identity.permissions import ALL_PERMISSIONS, WF01_PERMISSIONS
from app.domains.operations.asbuilt_models import AsBuiltManifest, AsBuiltMapping, AsBuiltVerification

BACKEND = Path(__file__).resolve().parents[3]
REPO = BACKEND.parent
REQUIREMENT_MAP = BACKEND / "registry" / "wf01_requirement_map.json"
_PERMISSIONS = ALL_PERMISSIONS | WF01_PERMISSIONS | {"governance.read", "evaluation.read", "source.read"}


def _git(*args: str) -> str | None:
    try:
        return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True, timeout=10, check=True).stdout.strip()
    except Exception:  # noqa: BLE001
        return None


def _route_permissions(dependant) -> set[str]:
    found: set[str] = set()
    for dependency in getattr(dependant, "dependencies", []):
        call = getattr(dependency, "call", None)
        for cell in getattr(call, "__closure__", None) or ():
            value = cell.cell_contents
            if isinstance(value, str) and value in _PERMISSIONS:
                found.add(value)
            # require_governance wraps require_permission: look one level in.
            for inner in getattr(value, "__closure__", None) or ():
                if isinstance(inner.cell_contents, str) and inner.cell_contents in _PERMISSIONS:
                    found.add(inner.cell_contents)
        found |= _route_permissions(dependency)
    return found


def _served(routes_) -> list[tuple[str, object]]:
    """(full path, route) for every route, including those of included routers,
    which this FastAPI keeps as _IncludedRouter branches resolved on demand."""
    out = []
    for route in routes_:
        if hasattr(route, "effective_route_contexts"):
            out += [(ctx.path, ctx.original_route) for ctx in route.effective_route_contexts()]
        else:
            out.append((getattr(route, "path", ""), route))
    return out


def routes(app) -> list[dict]:
    out = []
    for path, route in _served(app.routes):
        methods = sorted(m for m in (getattr(route, "methods", None) or ()) if m not in ("HEAD", "OPTIONS"))
        for method in methods:
            out.append({"method": method, "path": path,
                        "endpoint": f"{getattr(route.endpoint, '__module__', '')}.{getattr(route.endpoint, '__name__', '')}",
                        "permissions": sorted(_route_permissions(getattr(route, "dependant", None)))})
    return out


def _schema_head() -> str:
    try:
        from alembic.config import Config
        from alembic.script import ScriptDirectory
        heads = ScriptDirectory.from_config(Config(str(BACKEND / "alembic.ini"))).get_heads()
        return ",".join(sorted(heads))
    except Exception:  # noqa: BLE001
        return ""


def _flags() -> list[dict]:
    settings = get_settings()
    out = []
    for name in sorted(type(settings).model_fields):
        if not name.startswith("KRITON_") or name.endswith(("_KEY", "_SECRET", "_TOKEN")):
            continue
        value = str(getattr(settings, name))
        out.append({"name": name, "value_sha256": hashlib.sha256(value.encode()).hexdigest()[:16]})
    return out


def _test_exists(ref: str) -> bool:
    path, _, name = ref.partition("::")
    file = BACKEND / path
    if not file.exists():
        return False
    try:
        tree = ast.parse(file.read_text())
    except SyntaxError:
        return False
    return any(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name for node in ast.walk(tree))


def collect(app) -> dict:
    served = routes(app)
    index = {(r["method"], r["path"]): r for r in served}
    status_porcelain = _git("status", "--porcelain")
    mappings = []
    for req in json.loads(REQUIREMENT_MAP.read_text())["requirements"]:
        route = index.get((req["method"], req["path"]))
        missing_tests = [t for t in req["tests"] if not _test_exists(t)]
        reasons = []
        if route is None:
            reasons.append("route not served")
        elif req["permission"] and req["permission"] not in route["permissions"]:
            reasons.append(f"route does not enforce {req['permission']} (enforces {route['permissions']})")
        if missing_tests:
            reasons.append(f"tests not found: {missing_tests}")
        mappings.append({**{k: req[k] for k in ("requirement_id", "service", "method", "path", "permission")},
                         "flag": req.get("flag", ""), "test_refs": req["tests"],
                         "status": "UNMAPPED" if reasons else "MAPPED", "reason": "; ".join(reasons)})
    return {"commit_sha": _git("rev-parse", "HEAD"), "tree_clean": status_porcelain == "",
            "branch": _git("rev-parse", "--abbrev-ref", "HEAD") or "", "schema_head": _schema_head(),
            "environment": get_settings().KRITON_ENVIRONMENT, "flags": _flags(), "routes_total": len(served),
            "mappings": mappings}


async def record(db: AsyncSession, actor, manifest: dict, key: str) -> dict:
    replay = (await db.execute(select(AsBuiltManifest).where(AsBuiltManifest.idempotency_key == key))).scalar_one_or_none()
    if replay is not None:
        return await manifest_public(db, replay)
    content_sha = canonical_sha256(manifest)
    row = AsBuiltManifest(commit_sha=manifest["commit_sha"], tree_clean=manifest["tree_clean"], branch=manifest["branch"],
                          schema_head=manifest["schema_head"], environment=manifest["environment"], flags=manifest["flags"],
                          routes_total=manifest["routes_total"], content_sha256=content_sha, recorded_by=actor.id,
                          idempotency_key=key)
    db.add(row)
    await db.flush()
    for item in manifest["mappings"]:
        db.add(AsBuiltMapping(manifest_id=row.id, **item))
    await db.commit()
    return await manifest_public(db, row)


async def verify(db: AsyncSession, actor, manifest_id: str, *, decision: str, note: str, key: str) -> dict:
    replay = (await db.execute(select(AsBuiltVerification).where(AsBuiltVerification.idempotency_key == key))).scalar_one_or_none()
    if replay is not None:
        return {"id": replay.id, "decision": replay.decision, "manifest_id": replay.manifest_id}
    manifest = (await db.execute(select(AsBuiltManifest).where(AsBuiltManifest.id == manifest_id))).scalar_one_or_none()
    if manifest is None:
        raise governance_error("UNKNOWN_MANIFEST", "No such manifest.", 404)
    if manifest.recorded_by == actor.id:
        raise governance_error("INDEPENDENCE_REQUIRED", "The person who recorded a manifest cannot verify it.", 403)
    if decision not in ("VERIFIED", "REJECTED"):
        raise governance_error("INVALID_DECISION", "decision is VERIFIED or REJECTED.", 422)
    if decision == "VERIFIED":
        if not manifest.tree_clean or not manifest.commit_sha:
            raise governance_error("UNVERIFIABLE_UNCOMMITTED", "A manifest of an uncommitted tree cannot be verified.")
        unmapped = (await db.execute(select(AsBuiltMapping).where(AsBuiltMapping.manifest_id == manifest_id,
                                                                  AsBuiltMapping.status != "MAPPED"))).scalars().first()
        if unmapped is not None:
            raise governance_error("UNMAPPED_REQUIREMENTS", "Every requirement must be mapped before verification.")
    row = AsBuiltVerification(manifest_id=manifest_id, verifier_id=actor.id, decision=decision, note=note,
                              manifest_sha256=manifest.content_sha256, idempotency_key=key)
    db.add(row)
    await db.commit()
    return {"id": row.id, "decision": row.decision, "manifest_id": manifest_id}


async def manifest_public(db: AsyncSession, row: AsBuiltManifest) -> dict:
    mappings = list((await db.execute(select(AsBuiltMapping).where(AsBuiltMapping.manifest_id == row.id))).scalars())
    verification = (await db.execute(select(AsBuiltVerification).where(AsBuiltVerification.manifest_id == row.id)
                                     .order_by(AsBuiltVerification.created_at.desc()))).scalars().first()
    return {"id": row.id, "commit_sha": row.commit_sha, "tree_clean": row.tree_clean, "branch": row.branch,
            "schema_head": row.schema_head, "environment": row.environment, "routes_total": row.routes_total,
            "content_sha256": row.content_sha256, "recorded_by": row.recorded_by,
            "verification": verification.decision if verification else "NOT_RUN",
            "mappings": [{"requirement_id": m.requirement_id, "method": m.method, "path": m.path, "status": m.status,
                          "reason": m.reason, "test_refs": m.test_refs} for m in mappings]}


async def latest(db: AsyncSession) -> dict | None:
    row = (await db.execute(select(AsBuiltManifest).order_by(AsBuiltManifest.created_at.desc()))).scalars().first()
    return await manifest_public(db, row) if row else None
