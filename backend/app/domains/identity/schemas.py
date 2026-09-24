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
    """Body for PATCH /auth/me — self-service profile edit. At least one
    name field must be provided; both update the derived full_name."""
    first_name: str = ""
    last_name: str = ""

    @model_validator(mode="after")
    def _require_some_name(self) -> "ProfileUpdateRequest":
        if not self.first_name and not self.last_name:
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
