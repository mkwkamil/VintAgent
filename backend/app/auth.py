"""Single-admin JWT authentication."""

from __future__ import annotations

import hmac
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import Settings, get_settings

ALGORITHM = "HS256"
bearer_scheme = HTTPBearer(auto_error=False)


def verify_credentials(username: str, password: str, settings: Settings) -> bool:
    user_ok = hmac.compare_digest(username, settings.admin_username)
    pass_ok = hmac.compare_digest(password, settings.admin_password)
    return user_ok and pass_ok


def create_access_token(username: str, settings: Settings) -> str:
    expire = datetime.now(tz=timezone.utc) + timedelta(hours=settings.jwt_expire_hours)
    return jwt.encode({"sub": username, "exp": expire}, settings.jwt_secret, algorithm=ALGORITHM)


def decode_access_token(token: str, settings: Settings) -> str:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sesja wygasła lub token jest nieprawidłowy",
        ) from exc

    username = payload.get("sub")
    if not username:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Nieprawidłowy token")
    return username


def require_admin(
    credentials: HTTPAuthorizationCredentials | None = Security(bearer_scheme),
    settings: Settings = Depends(get_settings),
) -> str:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Wymagane logowanie")
    return decode_access_token(credentials.credentials, settings)
