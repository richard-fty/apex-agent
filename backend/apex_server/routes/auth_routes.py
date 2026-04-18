"""Auth routes: register, login, logout, me."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from slowapi import Limiter
from slowapi.util import get_remote_address

from apex_server.auth import SESSION_COOKIE, SESSION_TTL_SECONDS
from apex_server.deps import AppState, User, get_state, require_user


limiter = Limiter(key_func=get_remote_address)

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=8, max_length=128)


class LoginIn(BaseModel):
    username: str
    password: str


class UserOut(BaseModel):
    id: str
    username: str


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register(
    payload: RegisterIn,
    response: Response,
    state: AppState = Depends(get_state),
) -> UserOut:
    try:
        user = state.auth.create_user(
            username=payload.username, password=payload.password,
        )
    except ValueError:
        # Generic message — we don't leak whether the username is taken.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Registration failed",
        )
    # Auto-login on successful registration.
    token, expires_at = state.auth.create_session(user.id)
    _set_session_cookie(response, token)
    return UserOut(id=user.id, username=user.username)


@router.post("/login", response_model=UserOut)
@limiter.limit("5/minute")
def login(
    request: Request,
    payload: LoginIn,
    response: Response,
    state: AppState = Depends(get_state),
) -> UserOut:
    user = state.auth.authenticate(username=payload.username, password=payload.password)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )
    token, _ = state.auth.create_session(user.id)
    _set_session_cookie(response, token)
    return UserOut(id=user.id, username=user.username)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    request: Request,
    response: Response,
    state: AppState = Depends(get_state),
) -> Response:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        state.auth.delete_session(token)
    response.delete_cookie(SESSION_COOKIE)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(require_user)) -> UserOut:
    return UserOut(id=user.id, username=user.username)


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        samesite="lax",
        # NOTE: caller should flip Secure=True in production (behind TLS).
    )
