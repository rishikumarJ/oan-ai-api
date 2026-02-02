import jwt
from fastapi import Depends, HTTPException, status, Request, WebSocket
from fastapi.security import OAuth2PasswordBearer
from fastapi.security.utils import get_authorization_scheme_param
from helpers.utils import get_logger
from app.config import settings

logger = get_logger(__name__)

JWT_SECRET_KEY = settings.secret_key
JWT_ALGORITHM = "HS256"


class OptionalOAuth2PasswordBearer(OAuth2PasswordBearer):
    """OAuth2 scheme that's optional in development"""
    async def __call__(self, request: Request) -> str | None:
        if settings.environment == "development":
            authorization = request.headers.get("Authorization")
            if not authorization:
                return None
            scheme, param = get_authorization_scheme_param(authorization)
            if scheme.lower() != "bearer":
                return None
            return param
        return await super().__call__(request)


oauth2_scheme = OptionalOAuth2PasswordBearer(tokenUrl="api/auth/login")


def verify_token(token: str) -> dict:
    """Verify a JWT token and return the decoded payload."""
    try:
        payload = jwt.decode(
            token,
            JWT_SECRET_KEY,
            algorithms=[JWT_ALGORITHM],
            options={
                "verify_signature": True,
                "verify_exp": True,
            }
        )
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.InvalidTokenError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def get_current_user(token: str | None = Depends(oauth2_scheme)) -> str:
    """
    FastAPI dependency to get current authenticated user from JWT token.
    Returns the user's email extracted from the token.
    """
    if settings.environment == "development" and token is None:
        logger.info("Development environment detected - bypassing authentication")
        return "development_user"

    if token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = verify_token(token)
    email = payload.get("email") or payload.get("sub")
    if email is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token: no user identifier found",
            headers={"WWW-Authenticate": "Bearer"},
        )

    logger.info(f"Authenticated user: {email}")
    return email


async def get_current_user_ws(websocket: WebSocket) -> str:
    """
    WebSocket dependency to authenticate users via token query parameter.
    Usage: ws://host/ws?token=<jwt_token>
    """
    if settings.environment == "development":
        logger.info("Development environment detected - bypassing WebSocket authentication")
        return "development_user"

    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=4001, reason="Missing authentication token")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    try:
        payload = verify_token(token)
        email = payload.get("email") or payload.get("sub")
        if email is None:
            await websocket.close(code=4001, reason="Invalid token")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token",
            )
        logger.info(f"WebSocket authenticated user: {email}")
        return email
    except HTTPException:
        await websocket.close(code=4001, reason="Authentication failed")
        raise
