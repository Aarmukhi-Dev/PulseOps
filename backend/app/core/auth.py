import base64
import hashlib
import hmac
import json
import time
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pwdlib import PasswordHash
from pwdlib.exceptions import PwdlibError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.models import User

_bearer = HTTPBearer(auto_error=False)
_password_hash = PasswordHash.recommended()
_issuer = "pulseops"
_audience = "pulseops-api"


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _decode_b64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


_jwt_header = _b64(b'{"alg":"HS256","typ":"JWT"}')


def _verify_password(password: str, hashed: str) -> bool:
    try:
        return _password_hash.verify(password, hashed)
    except (PwdlibError, ValueError):
        return False


def authenticate_user(email: str, password: str, db: Session) -> User | None:
    normalized_email = email.strip().lower()
    user = db.scalar(select(User).where(User.email == normalized_email))
    # Verify against a fixed dummy hash for unknown users to reduce timing-based enumeration.
    if user is None:
        _verify_password(password, _dummy_password_hash())
        return None
    password_matches = _verify_password(password, user.password_hash)
    if not user.is_active or not password_matches:
        return None
    return user


def _dummy_password_hash() -> str:
    # Created once per process; only used for timing equalization, never persisted.
    global _DUMMY_HASH
    if _DUMMY_HASH is None:
        _DUMMY_HASH = _password_hash.hash("pulseops-invalid-login-dummy-secret")
    return _DUMMY_HASH


_DUMMY_HASH: str | None = None


def create_access_token(user_id: UUID) -> str:
    now = datetime.now(UTC)
    payload = json.dumps({"sub": str(user_id), "iss": _issuer, "aud": _audience,
                          "iat": int(now.timestamp()),
                          "exp": int((now + timedelta(minutes=settings.jwt_access_token_expire_minutes)).timestamp())},
                         separators=(",", ":")).encode()
    encoded_payload = _b64(payload)
    signing_input = f"{_jwt_header}.{encoded_payload}"
    signature = hmac.new(settings.jwt_secret_key.encode(), signing_input.encode("ascii"), hashlib.sha256).digest()
    return f"{signing_input}.{_b64(signature)}"


def _decode_access_token(token: str) -> UUID:
    try:
        if len(token) > 4096:
            raise ValueError("token too large")
        header, encoded, signed = token.split(".", 2)
        if header != _jwt_header:
            raise ValueError("unsupported token algorithm")
        expected = hmac.new(settings.jwt_secret_key.encode(), f"{header}.{encoded}".encode("ascii"), hashlib.sha256).digest()
        if not hmac.compare_digest(expected, _decode_b64(signed)):
            raise ValueError("bad signature")
        claims = json.loads(_decode_b64(encoded))
        now = int(time.time())
        if claims.get("iss") != _issuer or claims.get("aud") != _audience:
            raise ValueError("bad token context")
        if not isinstance(claims.get("iat"), int) or not isinstance(claims.get("exp"), int):
            raise ValueError("bad token timestamps")
        if claims["iat"] > now + 30 or claims["exp"] <= now or claims["exp"] <= claims["iat"]:
            raise ValueError("expired token")
        return UUID(claims["sub"])
    except (ValueError, KeyError, TypeError, json.JSONDecodeError, UnicodeError):
        raise ValueError("invalid bearer token") from None


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise unauthorized
    try:
        user_id = _decode_access_token(credentials.credentials)
    except ValueError:
        raise unauthorized from None
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise unauthorized
    return user
