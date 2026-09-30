"""Badges: real signed JWTs (RS256) carrying who the user is and which agent acts for them.

# STUB: the issuer. A real deployment gets user tokens from the company identity provider
# (Entra ID / Okta, SSO + MFA) and does the "agent on behalf of user" step with OAuth 2.0
# Token Exchange (RFC 8693). Everything downstream — verification at every hop, the `act`
# claim, entitlement checks — is the real thing. Swap = issuer URL + public keys.
"""
import json
import time
from functools import cache

import jwt
import yaml
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from harness.rules import ROOT

KEYS = ROOT / ".keys"
ISSUER = "stub-idp"
TTL = 3600


def _keypair() -> tuple[bytes, bytes]:
    priv_path, pub_path = KEYS / "issuer.pem", KEYS / "issuer.pub"
    if not priv_path.exists():  # ponytail: generated on first use, shared via a mounted folder
        KEYS.mkdir(exist_ok=True)
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        priv_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        pub_path.write_bytes(key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
    return priv_path.read_bytes(), pub_path.read_bytes()


@cache
def people() -> dict:
    return {p["id"]: p for p in json.loads((ROOT / "data" / "people.json").read_text())}


def registry() -> dict:
    return yaml.safe_load((ROOT / "harness" / "registry.yaml").read_text())["agents"]


def _sign(claims: dict) -> str:
    now = int(time.time())
    return jwt.encode({"iss": ISSUER, "iat": now, "exp": now + TTL, **claims}, _keypair()[0], algorithm="RS256")


def user_badge(user_id: str) -> str:
    p = people()[user_id]
    return _sign({"sub": user_id, "name": p["name"], "role": p["role"], "territory": p["territory"], "country": p["country"]})


def agent_badge(agent_id: str) -> str:
    a = registry()[agent_id]
    return _sign({"sub": agent_id, "version": a["version"], "certified_tier": a["certified_tier"]})


def exchange(user_token: str, agent_token: str) -> str:
    """Combined badge: the user stays the subject, the agent is the actor (RFC 8693 `act`)."""
    u, a = verify(user_token), verify(agent_token)
    if "act" in u or "act" in a:
        raise PermissionError("cannot exchange an already-delegated badge")
    user = {k: u[k] for k in ("sub", "name", "role", "territory", "country")}
    return _sign({**user, "act": {"sub": a["sub"], "version": a["version"], "certified_tier": a["certified_tier"]}})


def verify(token: str) -> dict:
    return jwt.decode(token, _keypair()[1], algorithms=["RS256"], issuer=ISSUER)


def from_header(authorization: str | None) -> dict:
    """Verify a `Bearer <badge>` header. Raises PermissionError if missing or invalid."""
    if not authorization or not authorization.startswith("Bearer "):
        raise PermissionError("missing badge")
    try:
        return verify(authorization.removeprefix("Bearer "))
    except jwt.PyJWTError as e:
        raise PermissionError(f"invalid badge: {e}") from e
