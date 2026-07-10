from fastapi import APIRouter

from app.domains.audit_ledger.router import router as audit_router
from app.domains.identity.router import auth_router, users_router
from app.domains.learning_cpd.router import router as learning_router
from app.domains.model_gateway.router import router as model_gateway_router
from app.domains.source_library.router import router as source_router
from app.domains.support_incident.router import router as support_router
from app.domains.evaluation.router import router as evaluation_router
from app.orchestration.router import router as orchestration_router
from app.orchestration.upload_router import router as upload_router

api_v1_router = APIRouter()
api_v1_router.include_router(auth_router)
api_v1_router.include_router(users_router)
api_v1_router.include_router(support_router)
api_v1_router.include_router(learning_router)
api_v1_router.include_router(source_router)
api_v1_router.include_router(model_gateway_router)
api_v1_router.include_router(evaluation_router, prefix="/evaluation", tags=["Evaluation & Release Gates"])
api_v1_router.include_router(audit_router)
api_v1_router.include_router(orchestration_router)
api_v1_router.include_router(upload_router)
