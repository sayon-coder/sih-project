"""
JWT token handling utilities.
"""
import jwt
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any
from fastapi import HTTPException, Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from app.config import get_settings

settings = get_settings()
# auto_error=False so a missing token becomes a 401 (not the default 403),
# which is what the API contract and tests specify.
security = HTTPBearer(auto_error=False)


def create_token(
    data: Dict[str, Any],
    token_type: str,
    expires_delta: timedelta
) -> str:
    """
    Create a JWT token.

    Args:
        data: Payload data to encode
        token_type: Type of token ('access' or 'refresh')
        expires_delta: Time until expiration

    Returns:
        Encoded JWT token string
    """
    to_encode = data.copy()
    now = datetime.now(timezone.utc)

    to_encode.update({
        "type": token_type,
        "jti": uuid.uuid4().hex,
        "iat": now,
        "exp": now + expires_delta
    })

    encoded_jwt = jwt.encode(
        to_encode,
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm
    )

    return encoded_jwt


def create_access_token(data: Dict[str, Any]) -> str:
    """
    Create an access token.

    Args:
        data: Payload data (usually {'sub': email})

    Returns:
        Access token string
    """
    expires = timedelta(minutes=settings.access_token_expire_minutes)
    return create_token(data, "access", expires)


def create_refresh_token(data: Dict[str, Any]) -> str:
    """
    Create a refresh token.

    Args:
        data: Payload data (usually {'sub': email})

    Returns:
        Refresh token string
    """
    expires = timedelta(days=settings.refresh_token_expire_days)
    return create_token(data, "refresh", expires)


def decode_token(token: str, expected_type: str) -> Dict[str, Any]:
    """
    Decode and validate a JWT token.

    Args:
        token: JWT token string
        expected_type: Expected token type ('access' or 'refresh')

    Returns:
        Decoded payload

    Raises:
        HTTPException: If token is invalid or expired
    """
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm]
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=401,
            detail="Token has expired"
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=401,
            detail="Invalid token"
        )

    if payload.get("type") != expected_type:
        raise HTTPException(
            status_code=401,
            detail="Invalid token type"
        )

    return payload


def verify_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> Dict[str, Any]:
    """
    Verify an access token from Authorization header.
    Used as a dependency in protected routes.

    Args:
        credentials: HTTP Authorization credentials

    Returns:
        Decoded token payload

    Raises:
        HTTPException: 401 when the token is missing, invalid or expired.
    """
    if credentials is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return decode_token(credentials.credentials, "access")
