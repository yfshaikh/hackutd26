"""Session-cookie auth with an in-memory user store.

Passwords are hashed with stdlib hashlib.scrypt. Roles are enforced server
side by the dependencies in main.py. In-memory is fine for the MVP.
"""
from __future__ import annotations

import hashlib
import os
import secrets
import uuid

from fastapi import Cookie, HTTPException

from . import config
from .models import Role, User, now_iso

COOKIE_NAME = "cc_session"

_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1


def _hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or os.urandom(16)
    dk = hashlib.scrypt(
        password.encode(), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=32
    )
    return f"{salt.hex()}${dk.hex()}"


def _verify_password(password: str, stored: str) -> bool:
    try:
        salt_hex, dk_hex = stored.split("$", 1)
    except ValueError:
        return False
    candidate = _hash_password(password, bytes.fromhex(salt_hex))
    # constant-time compare
    return secrets.compare_digest(candidate.split("$", 1)[1], dk_hex)


class _Record:
    def __init__(self, user: User, pw_hash: str) -> None:
        self.user = user
        self.pw_hash = pw_hash


class AuthStore:
    def __init__(self) -> None:
        self.users: dict[str, _Record] = {}          # user id -> record
        self.by_email: dict[str, str] = {}            # email -> user id
        self.sessions: dict[str, str] = {}            # token -> user id

    def seed_admin(self) -> None:
        if self.by_email:
            return
        self.create_user(
            name="Admin", email=config.ADMIN_EMAIL, role="admin", password=config.ADMIN_PASSWORD
        )

    def create_user(self, *, name: str, email: str, role: Role, password: str | None = None) -> User:
        email = email.strip().lower()
        if email in self.by_email:
            raise HTTPException(status_code=409, detail=f"A user with email {email} already exists")
        user = User(
            id=f"u-{uuid.uuid4().hex[:8]}",
            name=name,
            email=email,
            role=role,
            createdAt=now_iso(),
        )
        # Users created by an admin via /users get a random password they don't
        # use to log in for the MVP; the seeded admin uses the configured one.
        pw = password if password is not None else secrets.token_urlsafe(16)
        self.users[user.id] = _Record(user, _hash_password(pw))
        self.by_email[email] = user.id
        return user

    def authenticate(self, email: str, password: str) -> User | None:
        rec = self.users.get(self.by_email.get(email.strip().lower(), ""))
        if rec and _verify_password(password, rec.pw_hash):
            return rec.user
        return None

    def start_session(self, user_id: str) -> str:
        token = secrets.token_urlsafe(32)
        self.sessions[token] = user_id
        return token

    def end_session(self, token: str) -> None:
        self.sessions.pop(token, None)

    def user_for_token(self, token: str | None) -> User | None:
        if not token:
            return None
        uid = self.sessions.get(token)
        rec = self.users.get(uid) if uid else None
        return rec.user if rec else None

    def list_users(self) -> list[User]:
        return [r.user for r in self.users.values()]

    def set_role(self, user_id: str, role: Role) -> User:
        rec = self.users.get(user_id)
        if not rec:
            raise HTTPException(status_code=404, detail="No such user")
        rec.user.role = role
        return rec.user


auth = AuthStore()


def current_user(cc_session: str | None = Cookie(default=None)) -> User:
    user = auth.user_for_token(cc_session)
    if not user:
        raise HTTPException(status_code=401, detail="Not signed in")
    return user


def require_roles(*roles: str):
    def dep(cc_session: str | None = Cookie(default=None)) -> User:
        user = current_user(cc_session)
        if user.role not in roles:
            raise HTTPException(status_code=403, detail="Your role cannot perform this action")
        return user

    return dep
