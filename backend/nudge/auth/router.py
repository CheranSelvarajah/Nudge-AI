from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from nudge.auth.deps import ensure_preferences, get_current_user
from nudge.auth.schemas import LoginRequest, RegisterRequest, TokenResponse, UserOut
from nudge.auth.security import create_access_token, hash_password, verify_password
from nudge.core.db import get_db
from nudge.core.models import User

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(body: RegisterRequest, db: Session = Depends(get_db)) -> TokenResponse:
    existing = db.query(User).filter(User.email == body.email.lower()).first()
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")
    user = User(
        email=body.email.lower(),
        password_hash=hash_password(body.password),
        timezone=body.timezone,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    ensure_preferences(db, user)
    token = create_access_token(user.id, extra={"email": user.email})
    return TokenResponse(access_token=token)


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    user = db.query(User).filter(User.email == body.email.lower()).first()
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    token = create_access_token(user.id, extra={"email": user.email})
    return TokenResponse(access_token=token)


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> User:
    return user


@router.post("/logout")
def logout(user: User = Depends(get_current_user)) -> dict[str, str]:
    # JWT is stateless; client discards token. Endpoint exists for UX symmetry.
    _ = user
    return {"status": "ok"}
