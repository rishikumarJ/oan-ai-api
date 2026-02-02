"""
Authentication Router

Handles user login and JWT token generation.
"""

import jwt
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, status
import bcrypt
from pydantic import BaseModel, EmailStr
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models.user import User
from app.config import settings
from helpers.utils import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["Authentication"])

# JWT settings
JWT_SECRET_KEY = settings.secret_key
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_DAYS = 365


class LoginRequest(BaseModel):
    """Login request schema"""
    email: EmailStr
    password: str


class LoginResponse(BaseModel):
    """Login response schema"""
    access_token: str
    token_type: str = "bearer"
    email: str
    message: str


class TokenPayload(BaseModel):
    """JWT token payload"""
    sub: str  # email
    email: str
    exp: datetime
    iat: datetime


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash"""
    return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))


def create_access_token(email: str) -> str:
    """Create a JWT access token"""
    now = datetime.utcnow()
    expire = now + timedelta(days=JWT_EXPIRATION_DAYS)

    payload = {
        "sub": email,
        "email": email,
        "exp": expire,
        "iat": now
    }

    token = jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)
    return token


@router.post("/login", response_model=LoginResponse)
async def login(
    request: LoginRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Authenticate user and return JWT token.

    - **email**: User's email address
    - **password**: User's password
    """
    logger.info(f"Login attempt for email: {request.email}")

    # Find user by email
    result = await db.execute(
        select(User).where(User.email == request.email)
    )
    user = result.scalar_one_or_none()

    if not user:
        logger.warning(f"Login failed: User not found - {request.email}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password"
        )

    # Verify password
    if not verify_password(request.password, user.hashed_password):
        logger.warning(f"Login failed: Invalid password - {request.email}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password"
        )

    # Check if user is active
    if not user.is_active:
        logger.warning(f"Login failed: User inactive - {request.email}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account is disabled"
        )

    # Generate JWT token
    access_token = create_access_token(user.email)

    logger.info(f"Login successful for: {request.email}")

    return LoginResponse(
        access_token=access_token,
        email=user.email,
        message="Login successful"
    )
