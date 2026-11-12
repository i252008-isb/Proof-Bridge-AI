from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import User


ROLE_FREELANCER = "freelancer"
ROLE_CLIENT = "client"
ROLE_REVIEWER = "reviewer"

PUBLIC_REGISTRATION_ROLES = (ROLE_FREELANCER, ROLE_CLIENT)
ALL_ROLES = (*PUBLIC_REGISTRATION_ROLES, ROLE_REVIEWER)

BCRYPT_MAX_PASSWORD_BYTES = 72


# ==========================================
# 1. PASSWORD HASHING
# ==========================================

def hash_password(password: str) -> str:
    password_bytes = password.encode("utf-8")

    if len(password_bytes) > BCRYPT_MAX_PASSWORD_BYTES:
        raise ValueError("Password cannot exceed 72 UTF-8 bytes.")

    hashed = bcrypt.hashpw(
        password_bytes,
        bcrypt.gensalt()
    )

    return hashed.decode("utf-8")


def verify_password(password: str, hashed_password: str) -> bool:
    password_bytes = password.encode("utf-8")

    if len(password_bytes) > BCRYPT_MAX_PASSWORD_BYTES:
        return False

    try:
        return bcrypt.checkpw(
            password_bytes,
            hashed_password.encode("utf-8")
        )
    except (ValueError, TypeError):
        return False


# Used only to spend the same bcrypt work when an email is unknown, so
# login timing does not reveal whether an account exists.
_DUMMY_PASSWORD_HASH = hash_password(
    "proofbridge-unknown-account-timing-placeholder"
)


def verify_login_password(
    password: str,
    stored_hash: str | None
) -> bool:
    """Verify a login password without leaking account existence by timing.

    A missing account still performs one bcrypt comparison against a
    throwaway hash, so the response time is comparable to a wrong password.
    """
    candidate_hash = stored_hash or _DUMMY_PASSWORD_HASH
    is_valid = verify_password(password, candidate_hash)

    return stored_hash is not None and is_valid


# ==========================================
# 2. JWT TOKEN CREATION
# ==========================================

def create_access_token(
    subject: int,
    expires_delta: timedelta | None = None
) -> str:
    now = datetime.now(timezone.utc)

    lifetime = (
        expires_delta
        if expires_delta is not None
        else timedelta(minutes=settings.ACCESS_TOKEN_MINUTES)
    )

    payload = {
        "sub": str(subject),
        "iat": now,
        "exp": now + lifetime
    }

    token = jwt.encode(
        payload,
        settings.SECRET_KEY,
        algorithm="HS256"
    )

    return token


# ==========================================
# 3. JWT AUTHENTICATION
# ==========================================

oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="/auth/login"
)


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
) -> User:

    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired authentication token.",
        headers={"WWW-Authenticate": "Bearer"}
    )

    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=["HS256"],
            options={"require": ["exp", "sub"]}
        )

        subject = payload.get("sub")

        if not isinstance(subject, str):
            raise credentials_exception

        user_id = int(subject)

    except (jwt.InvalidTokenError, ValueError, TypeError):
        raise credentials_exception

    user = db.get(User, user_id)

    if user is None:
        raise credentials_exception

    return user


# ==========================================
# 4. ROLE-BASED AUTHORIZATION
# ==========================================

def require_role(*allowed_roles: str):
    """Build a dependency that allows only the given user roles."""

    def role_checker(
        current_user: User = Depends(get_current_user)
    ) -> User:

        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to access this resource."
            )

        return current_user

    return role_checker
