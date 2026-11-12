
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.database import get_db
from app.models import User
from app.schemas import MessageResponse, UserCreate, UserResponse, Token
from app.security import (
    hash_password,
    verify_login_password,
    create_access_token,
    get_current_user
)


router = APIRouter(
    prefix="/auth",
    tags=["Authentication"]
)


# ==========================================
# 1. USER REGISTRATION
# ==========================================

@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED
)
def register_user(
    user_data: UserCreate,
    db: Session = Depends(get_db)
):
    # Normalize email
    email = user_data.email.lower()

    # Check whether email already exists
    existing_user = db.query(User).filter(
        User.email == email
    ).first()

    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists."
        )

    # Create database user
    new_user = User(
        name=user_data.name,
        email=email,
        password_hash=hash_password(user_data.password),
        role=user_data.role
    )

    db.add(new_user)

    try:
        db.commit()
        db.refresh(new_user)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists."
        )

    return new_user


# ==========================================
# 2. USER LOGIN
# ==========================================

@router.post("/login", response_model=Token)
def login_user(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
):
    # OAuth2 form uses "username" for the email address
    email = form_data.username.strip().lower()

    user = db.query(User).filter(
        User.email == email
    ).first()

    # Use the same error and comparable timing for unknown email and wrong
    # password so neither reveals whether an account exists.
    password_hash = user.password_hash if user is not None else None

    if not verify_login_password(form_data.password, password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password.",
            headers={"WWW-Authenticate": "Bearer"}
        )

    # Generate JWT
    access_token = create_access_token(user.id)

    return {
        "access_token": access_token,
        "token_type": "bearer"
    }


# ==========================================
# 3. GET CURRENT LOGGED-IN USER
# ==========================================

@router.get("/me", response_model=UserResponse)
def get_my_account(
    current_user: User = Depends(get_current_user)
):
    return current_user


# ==========================================
# 4. LOGOUT
# ==========================================

@router.post(
    "/logout",
    response_model=MessageResponse,
    dependencies=[Depends(get_current_user)]
)
def logout():
    """Stateless logout: the client must discard its access token."""
    return MessageResponse(
        message="Logged out. Discard the access token on the client."
    )
