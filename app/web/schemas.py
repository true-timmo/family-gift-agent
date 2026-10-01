"""Eingaben der API. Längenbegrenzungen hier; inhaltliche Prüfung in domain.values und den Services."""
from pydantic import BaseModel, Field


class NameIn(BaseModel):
    name: str = Field(max_length=60)


class RegisterIn(NameIn):
    email: str = Field(max_length=200)
    family_code: str = Field(max_length=100)


class VerifyIn(NameIn):
    code: str = Field(max_length=10)


class TokenIn(BaseModel):
    token: str = Field(max_length=100)


class InvitationIn(NameIn):
    email: str = Field(max_length=200)
    bestehend: bool = False      # True = „Einladen“/„Erneut“ bei einer vorhandenen Person in der Liste


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
