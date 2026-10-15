import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator

AppUserRole = Literal["admin", "ingenieur", "lecteur"]

# Shape minimale, PAS un check RFC complet : email-validator refuse les
# TLD « .local » (RFC 6762) alors qu'on les utilise en démo. La vraie
# sécurité est côté hash argon2id, pas côté syntaxe email.
_EMAIL_SHAPE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1)

    @field_validator("email")
    @classmethod
    def _email_shape(cls, v: str) -> str:
        v = v.strip().lower()
        if not _EMAIL_SHAPE.match(v):
            raise ValueError("Email mal formé")
        return v


class PublicUser(BaseModel):
    id: str
    email: str
    role: AppUserRole
    active: bool
    created_at: str


class LoginResponse(BaseModel):
    token: str
    token_type: Literal["Bearer"] = "Bearer"
    expires_at: str
    user: PublicUser
