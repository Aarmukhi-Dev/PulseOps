import re

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.auth import authenticate_user, create_access_token, get_current_user, hash_password
from app.core.database import get_db
from app.models import User

router = APIRouter(prefix="/api/auth", tags=["authentication"])
_EMAIL_LOCAL = re.compile(r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+$")
_DOMAIN_LABEL = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")
MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 1024


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=1024)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        value = value.strip().lower()
        local, separator, domain = value.partition("@")
        if not separator or not local or not domain or "@" in domain or any(char.isspace() for char in value):
            raise ValueError("Enter a valid email address")
        return value


class RegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str = Field(min_length=1, max_length=120)
    email: str = Field(min_length=3, max_length=320)
    password: SecretStr = Field(min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_LENGTH)
    password_confirmation: SecretStr = Field(min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_LENGTH)

    @field_validator("display_name")
    @classmethod
    def normalize_display_name(cls, value: str) -> str:
        value = value.strip()
        if not value or any(ord(character) < 32 for character in value):
            raise ValueError("Display name must contain 1 to 120 printable characters")
        return value

    @field_validator("email")
    @classmethod
    def validate_and_normalize_email(cls, value: str) -> str:
        email = value.strip().lower()
        if len(email) > 320 or email.count("@") != 1 or any(character.isspace() for character in email):
            raise ValueError("Enter a valid email address")
        local_part, domain = email.split("@", 1)
        if (
            not local_part
            or len(local_part) > 64
            or not _EMAIL_LOCAL.fullmatch(local_part)
            or local_part.startswith(".")
            or local_part.endswith(".")
            or ".." in local_part
        ):
            raise ValueError("Enter a valid email address")
        try:
            ascii_domain = domain.encode("idna").decode("ascii")
        except UnicodeError as exc:
            raise ValueError("Enter a valid email address") from exc
        labels = ascii_domain.split(".")
        if (
            len(ascii_domain) > 253
            or len(labels) < 2
            or any(not _DOMAIN_LABEL.fullmatch(label) for label in labels)
            or not any(character.isalpha() for character in labels[-1])
        ):
            raise ValueError("Enter a valid email address")
        # Match the existing model/login/CLI policy: trim and lowercase the submitted address.
        return email

    @model_validator(mode="after")
    def validate_passwords(self) -> "RegisterRequest":
        password = self.password.get_secret_value()
        confirmation = self.password_confirmation.get_secret_value()
        if not password.strip():
            raise ValueError("Password cannot contain only whitespace")
        if password != confirmation:
            raise ValueError("Passwords do not match")
        return self


class UserRead(BaseModel):
    id: str
    email: str
    display_name: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserRead


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    user = authenticate_user(payload.email, payload.password, db)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password", headers={"WWW-Authenticate": "Bearer"})
    return TokenResponse(access_token=create_access_token(user.id), user=UserRead(id=str(user.id), email=user.email, display_name=user.display_name))


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, db: Session = Depends(get_db)) -> TokenResponse:
    existing = db.scalar(select(User).where(User.email == payload.email))
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="An account with this email already exists")

    user = User(
        email=payload.email,
        display_name=payload.display_name,
        password_hash=hash_password(payload.password.get_secret_value()),
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        # The unique email constraint closes the race between the pre-check and insert.
        if db.scalar(select(User).where(User.email == payload.email)) is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="An account with this email already exists",
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to create account",
        ) from exc

    db.refresh(user)
    return TokenResponse(
        access_token=create_access_token(user.id),
        user=UserRead(id=str(user.id), email=user.email, display_name=user.display_name),
    )


@router.get("/me", response_model=UserRead)
def me(user: User = Depends(get_current_user)) -> UserRead:
    return UserRead(id=str(user.id), email=user.email, display_name=user.display_name)
