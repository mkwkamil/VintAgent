"""Admin login endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from ..auth import create_access_token, require_admin, verify_credentials
from ..config import Settings, get_settings
from ..models import LoginRequest, TokenResponse

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, settings: Settings = Depends(get_settings)) -> TokenResponse:
    if not verify_credentials(payload.username, payload.password, settings):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Nieprawidłowy login lub hasło",
        )
    return TokenResponse(access_token=create_access_token(payload.username, settings), username=payload.username)


@router.get("/me")
def me(username: str = Depends(require_admin)) -> dict[str, str]:
    return {"username": username}
