"""Eingaben der API. Längenbegrenzungen hier; inhaltliche Prüfung in domain.values und den Services."""
from pydantic import BaseModel, Field


class NameIn(BaseModel):
    name: str = Field(max_length=60)


class LoginStartIn(NameIn):
    resend: bool = False      # True = neuen Code schicken, auch wenn der letzte noch gilt
    code: bool = False        # True = Code per Mail, auch wenn Face ID eingerichtet ist


class OptionalNameIn(BaseModel):
    name: str | None = Field(default=None, max_length=60)


class PasskeyIn(BaseModel):
    credential: dict          # Antwort des Geräts (WebAuthn, als JSON)
    device: str = Field(default="", max_length=40)


class RegisterIn(NameIn):
    email: str = Field(max_length=200)
    family_code: str = Field(max_length=100)


class VerifyIn(NameIn):
    code: str = Field(max_length=10)


class TokenIn(BaseModel):
    token: str = Field(max_length=100)


class InvitationIn(NameIn):
    email: str = Field(max_length=200)


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
