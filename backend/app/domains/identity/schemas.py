from pydantic import BaseModel, EmailStr, model_validator


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


class UserCreateRequest(BaseModel):
    email: EmailStr
    password: str
    full_name: str
    role: str


class UserActiveUpdateRequest(BaseModel):
    is_active: bool
