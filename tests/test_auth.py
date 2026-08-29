import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from appstore_listing.connect.auth import (
    AUDIENCE,
    Credentials,
    TokenProvider,
    key_id_from_filename,
)
from appstore_listing.errors import CredentialsError


@pytest.fixture
def p8_key() -> str:
    key = ec.generate_private_key(ec.SECP256R1())
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()


def test_key_id_from_filename():
    assert key_id_from_filename("/keys/AuthKey_ABCD123456.p8") == "ABCD123456"
    assert key_id_from_filename("mykey.p8") is None


def test_token_is_a_valid_es256_jwt(p8_key: str):
    credentials = Credentials(key_id="ABCD123456", issuer_id="issuer-uuid", private_key=p8_key)
    token = TokenProvider(credentials).token()

    header = jwt.get_unverified_header(token)
    assert header["alg"] == "ES256"
    assert header["kid"] == "ABCD123456"

    claims = jwt.decode(token, options={"verify_signature": False}, audience=AUDIENCE)
    assert claims["iss"] == "issuer-uuid"
    assert claims["aud"] == AUDIENCE
    assert 0 < claims["exp"] - claims["iat"] <= 20 * 60


def test_token_is_cached(p8_key: str):
    provider = TokenProvider(Credentials(key_id="K", issuer_id="I", private_key=p8_key))
    assert provider.token() == provider.token()


def test_lifetime_over_twenty_minutes_is_rejected(p8_key: str):
    with pytest.raises(CredentialsError):
        TokenProvider(Credentials(key_id="K", issuer_id="I", private_key=p8_key), lifetime=3600)


def test_missing_pieces_are_reported(p8_key: str, tmp_path):
    with pytest.raises(CredentialsError, match="Key ID"):
        Credentials(key_id="", issuer_id="I", private_key=p8_key).validated()
    with pytest.raises(CredentialsError, match="Issuer ID"):
        Credentials(key_id="K", issuer_id="", private_key=p8_key).validated()
    with pytest.raises(CredentialsError, match="private key"):
        Credentials(key_id="K", issuer_id="I", private_key="nope").validated()
    with pytest.raises(CredentialsError, match="not found"):
        Credentials.from_p8_file(tmp_path / "missing.p8", "K", "I")


def test_key_id_inferred_from_apple_filename(p8_key: str, tmp_path):
    path = tmp_path / "AuthKey_ZZZZ999999.p8"
    path.write_text(p8_key)
    assert Credentials.from_p8_file(path, issuer_id="I").key_id == "ZZZZ999999"
