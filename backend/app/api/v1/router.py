from fastapi import APIRouter

from app.domains.identity.router import auth_router, users_router

api_v1_router = APIRouter()
api_v1_router.include_router(auth_router)
api_v1_router.include_router(users_router)
