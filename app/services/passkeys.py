"""Anmeldung mit Face ID, Touch ID oder Fingerabdruck (Passkeys / WebAuthn).

Einrichten geht nur angemeldet. Das Gerät erzeugt ein Schlüsselpaar; der Server speichert nur den
öffentlichen Schlüssel. Beim Anmelden unterschreibt das Gerät – nach Face ID – einen Zufallswert vom Server.
Kein Code, keine Mail. Der Code per Mail bleibt als Ausweg.
"""
import base64
import json
import secrets
from urllib.parse import urlsplit

from webauthn import (generate_authentication_options, generate_registration_options, options_to_json,
                      verify_authentication_response, verify_registration_response)
from webauthn.helpers import bytes_to_base64url
from webauthn.helpers.structs import (AuthenticatorSelectionCriteria, PublicKeyCredentialDescriptor,
                                      ResidentKeyRequirement, UserVerificationRequirement)

from ..domain.errors import AuthenticationError, NotFoundError, PermissionDeniedError
from ..domain.models import Person
from ..storage import PasskeyChallengeRepository, PasskeyRepository, PersonRepository
from ..storage.database import now

_FAILED = "Die Anmeldung mit Face ID hat nicht geklappt. Bitte nochmal versuchen – oder einen Code per Mail anfordern."


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _challenge_of(credential: dict) -> str:
    """Der Zufallswert, den das Gerät unterschrieben hat (steht in clientDataJSON)."""
    try:
        client_data = json.loads(_b64decode(credential["response"]["clientDataJSON"]))
        return str(client_data["challenge"])
    except (KeyError, TypeError, ValueError) as e:
        raise AuthenticationError(_FAILED) from e


class PasskeyService:
    CHALLENGE_SECONDS = 300

    def __init__(self, passkeys: PasskeyRepository, challenges: PasskeyChallengeRepository,
                 persons: PersonRepository, app_url: str, rp_name: str = "Geschenke"):
        self._passkeys = passkeys
        self._challenges = challenges
        self._persons = persons
        self._origin = app_url.rstrip("/")
        self._rp_id = urlsplit(app_url).hostname or "localhost"
        self._rp_name = rp_name

    # --- Einrichten (angemeldet) ---

    def registration_options(self, person: Person) -> dict:
        if not person.email:
            raise PermissionDeniedError("Face ID gibt es nur mit eigener E-Mail-Adresse.")
        options = generate_registration_options(
            rp_id=self._rp_id, rp_name=self._rp_name, user_id=str(person.id).encode(), user_name=person.name,
            user_display_name=person.name, challenge=self._new_challenge("register", person.id),
            authenticator_selection=AuthenticatorSelectionCriteria(
                resident_key=ResidentKeyRequirement.REQUIRED, user_verification=UserVerificationRequirement.REQUIRED),
            exclude_credentials=self._descriptors(person.id))
        return json.loads(options_to_json(options))

    def register(self, person: Person, credential: dict, device: str) -> None:
        challenge = _challenge_of(credential)
        valid, owner = self._challenges.take(challenge, "register")
        if not valid or owner != person.id:
            raise AuthenticationError("Das Einrichten hat zu lange gedauert. Bitte nochmal versuchen.")
        try:
            verified = verify_registration_response(
                credential=credential, expected_challenge=_b64decode(challenge), expected_rp_id=self._rp_id,
                expected_origin=self._origin, require_user_verification=True)
        except Exception as e:      # Bibliothek wirft je nach Fehler unterschiedliche Klassen
            raise AuthenticationError("Face ID konnte nicht eingerichtet werden. Bitte nochmal versuchen.") from e
        self._passkeys.add(bytes_to_base64url(verified.credential_id), person.id, verified.credential_public_key,
                           verified.sign_count, device[:40])

    # --- Anmelden ---

    def has_passkey(self, person: Person) -> bool:
        return bool(self._passkeys.ids_of(person.id))

    def login_options(self, name: str | None) -> dict:
        """Mit Namen: nur die Passkeys dieser Person. Ohne: das Gerät bietet an, was es für diese Seite hat."""
        person = self._persons.by_name(name) if name else None
        if name and not (person and person.email and self.has_passkey(person)):
            raise NotFoundError("Für diesen Namen ist noch keine Anmeldung mit Face ID eingerichtet.")
        options = generate_authentication_options(
            rp_id=self._rp_id, challenge=self._new_challenge("login", person.id if person else None),
            allow_credentials=self._descriptors(person.id) if person else None,
            user_verification=UserVerificationRequirement.REQUIRED)
        return json.loads(options_to_json(options))

    def login(self, credential: dict) -> Person:
        challenge = _challenge_of(credential)
        valid, expected_person = self._challenges.take(challenge, "login")
        stored = self._passkeys.get(str(credential.get("id", "")))
        if not valid or not stored or expected_person not in (None, stored.person.id):
            raise AuthenticationError(_FAILED)
        try:
            verified = verify_authentication_response(
                credential=credential, expected_challenge=_b64decode(challenge), expected_rp_id=self._rp_id,
                expected_origin=self._origin, credential_public_key=stored.public_key,
                credential_current_sign_count=stored.sign_count, require_user_verification=True)
        except Exception as e:
            raise AuthenticationError(_FAILED) from e
        self._passkeys.used(stored.credential_id, verified.new_sign_count)
        return stored.person

    def revoke_all(self, person: Person) -> int:
        return self._passkeys.delete_all_for(person.id)

    def _new_challenge(self, purpose: str, person_id: int | None) -> bytes:
        challenge = secrets.token_bytes(32)
        self._challenges.add(bytes_to_base64url(challenge), purpose, person_id, now() + self.CHALLENGE_SECONDS)
        return challenge

    def _descriptors(self, person_id: int) -> list[PublicKeyCredentialDescriptor]:
        return [PublicKeyCredentialDescriptor(id=_b64decode(cid)) for cid in self._passkeys.ids_of(person_id)]
