import re
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator

from app.domains.identity.permissions import ASSIGNABLE_ROLES

# Same rule as the sign-up form (frontend/services/auth.service.ts).
_STRONG_PASSWORD = re.compile(r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d).{8,}$")


class UserPublic(BaseModel):
    id: str
    email: str
    first_name: str
    last_name: str
    full_name: str
    role: str
    tenant_id: str

    model_config = {"from_attributes": True}


class ProvisionRequest(BaseModel):
    """Body for POST /auth/provision. Email comes from the verified Supabase
    token, never trusted from here. Fields are optional so a Google
    first-sign-in (which supplies its own name via the token/OAuth profile)
    can call this with an empty body."""
    first_name: str = ""
    last_name: str = ""
    company_name: str = ""


class ProfileUpdateRequest(BaseModel):
    """Body for PATCH /auth/me — self-service profile edit. Partial-update
    semantics: only the fields present in the body are changed; omitted
    fields (None) are left exactly as they are, and full_name is rebuilt
    from whatever survives the merge. At least one field must be provided."""
    first_name: str | None = None
    last_name: str | None = None

    @model_validator(mode="after")
    def _require_some_name(self) -> "ProfileUpdateRequest":
        if not (self.first_name or self.last_name):
            raise ValueError("Provide a first name, last name, or both")
        return self


class RolePublic(BaseModel):
    id: str
    name: str
    description: str
    permissions_summary: str

    model_config = {"from_attributes": True}


class UserListItem(BaseModel):
    id: str
    email: str
    full_name: str
    role: str
    is_active: bool

    model_config = {"from_attributes": True}


def _require_assignable_role(role: str) -> str:
    """Only roles the permission registry knows may be assigned — anything
    else would create an account that silently carries zero permissions."""
    if role not in ASSIGNABLE_ROLES:
        raise ValueError(f"Unknown role. Choose one of: {', '.join(sorted(ASSIGNABLE_ROLES))}")
    return role


class UserCreateRequest(BaseModel):
    """No password → the user is invited by email and chooses their own
    (the default in the UI). A password → a confirmed account with that
    temporary password, for environments without outbound email."""
    email: EmailStr
    password: str | None = None
    full_name: str
    role: str

    @field_validator("role")
    @classmethod
    def _role_is_assignable(cls, role: str) -> str:
        return _require_assignable_role(role)

    @field_validator("password")
    @classmethod
    def _password_is_strong(cls, password: str | None) -> str | None:
        if password in (None, ""):
            return None
        if not _STRONG_PASSWORD.match(password):
            raise ValueError("Password must be at least 8 characters with an uppercase letter, a lowercase letter, and a number.")
        return password


class UserActiveUpdateRequest(BaseModel):
    is_active: bool


class UserRoleUpdateRequest(BaseModel):
    role: str

    @field_validator("role")
    @classmethod
    def _role_is_assignable(cls, role: str) -> str:
        return _require_assignable_role(role)


class UserCreatedResponse(UserListItem):
    invited: bool = False


# ── Elevated-access governance (identity/governance.py) ─────────────────────

class ImpersonationStartRequest(BaseModel):
    target_user_id: str
    reason: str = Field(min_length=1, max_length=500)
    minutes: int = 30


class ImpersonationSessionPublic(BaseModel):
    id: str
    target_user_id: str
    target_name: str
    target_email: str
    target_role: str
    reason: str
    started_at: datetime
    expires_at: datetime
    ended_at: datetime | None


class BreakGlassRequest(BaseModel):
    permissions: list[str] = Field(min_length=1)
    reason: str = Field(min_length=1, max_length=1000)
    duration_minutes: int = 60


class BreakGlassReviewRequest(BaseModel):
    notes: str = Field(min_length=1, max_length=2000)


class BreakGlassGrantPublic(BaseModel):
    id: str
    user_id: str
    user_name: str
    permissions: list[str]
    reason: str
    duration_minutes: int
    status: str
    requested_at: datetime
    approved_by: str | None
    activated_at: datetime | None
    expires_at: datetime | None
    ended_at: datetime | None
    reviewed_by: str | None
    reviewed_at: datetime | None
    review_notes: str | None
    needs_review: bool


class ServiceAccountCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=500)
    role: str
    owner_user_id: str


class ServiceAccountKeyCreateRequest(BaseModel):
    expires_in_days: int = 90


class ServiceAccountKeyPublic(BaseModel):
    id: str
    key_prefix: str
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None
    last_used_at: datetime | None

    model_config = {"from_attributes": True}


class ServiceAccountPublic(BaseModel):
    id: str
    name: str
    description: str
    role: str
    owner_user_id: str
    owner_name: str
    is_active: bool
    created_at: datetime
    keys: list[ServiceAccountKeyPublic]


class IssuedServiceAccountKey(BaseModel):
    """The plaintext key appears in this response only; it is never stored."""
    key: str
    key_info: ServiceAccountKeyPublic


class MfaStatus(BaseModel):
    """GET /auth/mfa/status — what the frontend needs to decide whether to
    prompt for enrolment: the policy, and this session's assurance level."""
    required_for_privileged: bool
    privileged_role: bool
    current_aal: str
