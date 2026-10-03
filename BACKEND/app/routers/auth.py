"""
Authentication router for IP-SAKTI Sahayak.
Handles user registration, login, and token management.
"""
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session
from app.database import get_db
from app.schemas import UserCreate, UserLogin, UserResponse, Token, APIResponse
from app.services import AuthService
from app.utils import verify_token, create_access_token, decode_token
from app.models import User

router = APIRouter(prefix="/api/auth", tags=["Authentication"])

# Cookie name for refresh token
REFRESH_COOKIE = "refresh_token"


@router.post("/register", response_model=APIResponse, status_code=201)
def register(
    user_data: UserCreate,
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Register a new user.

    Creates a new user account with default VIEWER role.

    Returns:
        APIResponse with user data on success
    """
    user = AuthService.register_user(db, user_data, request)

    return APIResponse(
        success=True,
        data=UserResponse.model_validate(user).model_dump(),
        message="User registered successfully"
    )


@router.post("/login", response_model=APIResponse)
def login(
    response: Response,
    credentials: UserLogin,
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Login user and return access token.

    Sets a refresh token cookie for token refresh.

    Returns:
        APIResponse with access token
    """
    token_data = AuthService.authenticate_user(
        db,
        credentials.email,
        credentials.password,
        request
    )

    # Set refresh token cookie
    refresh_token = create_access_token({"sub": str(credentials.email)})
    response.set_cookie(
        key=REFRESH_COOKIE,
        value=refresh_token,
        max_age=7 * 24 * 3600,  # 7 days
        httponly=True,
        secure=False,  # Set to True in production with HTTPS
        samesite="strict",
        path="/api/auth"
    )

    return APIResponse(
        success=True,
        data=token_data,
        message="Login successful"
    )


@router.post("/refresh", response_model=APIResponse)
def refresh_token(
    request: Request,
    response: Response,
    db: Session = Depends(get_db)
):
    """
    Refresh access token using refresh token cookie.

    Returns:
        APIResponse with new access token
    """
    token = request.cookies.get(REFRESH_COOKIE)
    if not token:
        raise HTTPException(
            status_code=401,
            detail="No refresh token provided"
        )

    # Decode refresh token
    payload = decode_token(token, "access")

    # Verify user exists
    user = db.query(User).filter(User.email == payload["sub"]).first()
    if not user:
        raise HTTPException(
            status_code=401,
            detail="User no longer exists"
        )

    # Create new access token
    access_token = create_access_token({"sub": str(user.id)})

    # Set new refresh token
    new_refresh_token = create_access_token({"sub": str(user.email)})
    response.set_cookie(
        key=REFRESH_COOKIE,
        value=new_refresh_token,
        max_age=7 * 24 * 3600,
        httponly=True,
        secure=False,
        samesite="strict",
        path="/api/auth"
    )

    return APIResponse(
        success=True,
        data={"access_token": access_token, "token_type": "bearer"},
        message="Token refreshed successfully"
    )


@router.get("/me", response_model=APIResponse)
def get_current_user(
    token_payload: dict = Depends(verify_token),
    db: Session = Depends(get_db)
):
    """
    Get current authenticated user.

    Returns:
        APIResponse with user data
    """
    user_id = int(token_payload["sub"])
    user = db.query(User).filter(User.id == user_id).first()

    if not user:
        raise HTTPException(
            status_code=404,
            detail="User not found"
        )

    return APIResponse(
        success=True,
        data=UserResponse.model_validate(user).model_dump(),
        message="User retrieved successfully"
    )


@router.post("/logout", response_model=APIResponse)
def logout(response: Response):
    """
    Logout user by clearing refresh token cookie.

    Returns:
        APIResponse confirming logout
    """
    response.delete_cookie(REFRESH_COOKIE, path="/api/auth")

    return APIResponse(
        success=True,
        message="Logged out successfully"
    )
