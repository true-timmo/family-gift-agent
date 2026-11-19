"""Ein Software-„iPhone“ für Tests: erzeugt Passkeys und Anmelde-Unterschriften wie ein echtes Gerät."""
import base64
import hashlib
import json
import os
import struct

import cbor2
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


class SoftAuthenticator:
    def __init__(self, origin: str = "https://geschenke.nordhain-gmbh.de", rp_id: str = "geschenke.nordhain-gmbh.de"):
        self.origin, self.rp_id = origin, rp_id
        self.keys: dict[bytes, tuple[ec.EllipticCurvePrivateKey, bytes]] = {}   # credential id → (Schlüssel, user id)
        self.counter = 0

    def create(self, options: dict) -> dict:
        key = ec.generate_private_key(ec.SECP256R1())
        cred_id = os.urandom(16)
        self.keys[cred_id] = (key, unb64(options["user"]["id"]))
        numbers = key.public_key().public_numbers()
        cose = cbor2.dumps({1: 2, 3: -7, -1: 1, -2: numbers.x.to_bytes(32, "big"), -3: numbers.y.to_bytes(32, "big")})
        auth_data = (hashlib.sha256(options["rp"]["id"].encode()).digest() + bytes([0x45]) + struct.pack(">I", 0)
                     + bytes(16) + struct.pack(">H", len(cred_id)) + cred_id + cose)
        client = self._client_data("webauthn.create", options["challenge"])
        return {"id": b64(cred_id), "rawId": b64(cred_id), "type": "public-key", "clientExtensionResults": {},
                "authenticatorAttachment": "platform",
                "response": {"clientDataJSON": b64(client), "transports": ["internal"],
                             "attestationObject": b64(cbor2.dumps({"fmt": "none", "attStmt": {}, "authData": auth_data}))}}

    def get(self, options: dict, cred_id: bytes | None = None) -> dict:
        allowed = [unb64(c["id"]) for c in options.get("allowCredentials") or []]
        cred_id = cred_id or next(c for c in self.keys if not allowed or c in allowed)
        key, user_id = self.keys[cred_id]
        auth_data = hashlib.sha256(options["rpId"].encode()).digest() + bytes([0x05]) + struct.pack(">I", 0)
        client = self._client_data("webauthn.get", options["challenge"])
        signature = key.sign(auth_data + hashlib.sha256(client).digest(), ec.ECDSA(hashes.SHA256()))
        return {"id": b64(cred_id), "rawId": b64(cred_id), "type": "public-key", "clientExtensionResults": {},
                "authenticatorAttachment": "platform",
                "response": {"clientDataJSON": b64(client), "authenticatorData": b64(auth_data),
                             "signature": b64(signature), "userHandle": b64(user_id)}}

    def _client_data(self, kind: str, challenge: str) -> bytes:
        return json.dumps({"type": kind, "challenge": challenge, "origin": self.origin}).encode()
