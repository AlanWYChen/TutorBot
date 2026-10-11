"""Exercise the pinned SDK's real signature checks offline, with synthetic keys."""

from time import time
from types import SimpleNamespace
from unittest.mock import patch

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from firebase_admin import _token_gen, auth


def test_production_sdk_accepts_valid_signature_and_rejects_forgery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("FIREBASE_AUTH_EMULATOR_HOST", raising=False)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    wrong_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_pem = (
        key.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )
    now = int(time())
    claims = {
        "sub": "synthetic-student",
        "aud": "demo-tutorbot",
        "iss": "https://securetoken.google.com/demo-tutorbot",
        "iat": now,
        "exp": now + 3600,
        "auth_time": now,
    }
    verifier = _token_gen.TokenVerifier(SimpleNamespace(project_id="demo-tutorbot", options={}))

    def signed(payload: dict[str, object], signing_key: rsa.RSAPrivateKey = key) -> str:
        return jwt.encode(payload, signing_key, algorithm="RS256", headers={"kid": "test-key"})

    with patch("google.oauth2.id_token._fetch_certs", return_value={"test-key": public_pem}):
        assert verifier.verify_id_token(signed(claims))["uid"] == "synthetic-student"
        for token in [
            jwt.encode(claims, key="", algorithm="none"),
            signed(claims, wrong_key),
            signed({**claims, "exp": now - 120}),
            signed({**claims, "aud": "wrong"}),
            signed({**claims, "iss": "https://evil.invalid"}),
        ]:
            with pytest.raises(auth.InvalidIdTokenError):
                verifier.verify_id_token(token)
