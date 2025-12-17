"""Authentication router."""
from datetime import datetime, timedelta
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from passlib.context import CryptContext

from app.config import get_settings
from app.database import get_db_connection
from app.schemas.auth import (
    Token, TokenData, UserResponse, UserCreate, LoginRequest
)
from app.schemas.common import UserRole

logger = structlog.get_logger()
router = APIRouter()

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/token")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify password against hash."""
    return pwd_context.verify(plain_password, hashed_password)


def hash_password(password: str) -> str:
    """Hash a password."""
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    """Create JWT access token."""
    settings = get_settings()
    to_encode = data.copy()

    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.jwt_expire_minutes)

    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(
        to_encode, settings.jwt_secret, algorithm=settings.jwt_algorithm
    )
    return encoded_jwt


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    conn=Depends(get_db_connection)
) -> dict:
    """Get current user from JWT token."""
    settings = get_settings()
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(
            token, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
        )
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user = await conn.fetchrow(
        """
        SELECT id, username, email, display_name, role, is_active, last_login_at, created_at
        FROM users WHERE username = $1
        """,
        username
    )

    if user is None:
        raise credentials_exception

    if not user["is_active"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is disabled"
        )

    return dict(user)


async def require_role(roles: list[UserRole]):
    """Dependency to require specific roles."""
    async def role_checker(user: dict = Depends(get_current_user)):
        if user["role"] not in [r.value for r in roles]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions"
            )
        return user
    return role_checker


@router.post("/token", response_model=Token)
async def login_for_access_token(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    conn=Depends(get_db_connection)
):
    """OAuth2 compatible token login."""
    settings = get_settings()

    user = await conn.fetchrow(
        "SELECT * FROM users WHERE username = $1",
        form_data.username
    )

    if not user or not verify_password(form_data.password, user["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user["is_active"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is disabled"
        )

    # Update last login
    await conn.execute(
        "UPDATE users SET last_login_at = NOW() WHERE id = $1",
        user["id"]
    )

    access_token = create_access_token(
        data={"sub": user["username"], "role": user["role"]}
    )

    logger.info("User logged in", username=user["username"])

    return Token(
        access_token=access_token,
        token_type="bearer",
        expires_in=settings.jwt_expire_minutes * 60
    )


@router.post("/login", response_model=Token)
async def login(
    request: LoginRequest,
    conn=Depends(get_db_connection)
):
    """JSON login endpoint."""
    settings = get_settings()

    user = await conn.fetchrow(
        "SELECT * FROM users WHERE username = $1",
        request.username
    )

    if not user or not verify_password(request.password, user["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password"
        )

    if not user["is_active"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is disabled"
        )

    await conn.execute(
        "UPDATE users SET last_login_at = NOW() WHERE id = $1",
        user["id"]
    )

    access_token = create_access_token(
        data={"sub": user["username"], "role": user["role"]}
    )

    logger.info("User logged in", username=user["username"])

    return Token(
        access_token=access_token,
        token_type="bearer",
        expires_in=settings.jwt_expire_minutes * 60
    )


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(
    current_user: dict = Depends(get_current_user)
):
    """Get current user info."""
    return UserResponse(**current_user)


@router.post("/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    user: UserCreate,
    conn=Depends(get_db_connection),
    current_user: dict = Depends(get_current_user)
):
    """Create a new user (admin only)."""
    if current_user["role"] != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can create users"
        )

    # Check if username or email exists
    existing = await conn.fetchrow(
        "SELECT id FROM users WHERE username = $1 OR email = $2",
        user.username, user.email
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username or email already exists"
        )

    hashed = hash_password(user.password)

    new_user = await conn.fetchrow(
        """
        INSERT INTO users (username, email, password_hash, display_name, role)
        VALUES ($1, $2, $3, $4, $5)
        RETURNING id, username, email, display_name, role, is_active, last_login_at, created_at
        """,
        user.username, user.email, hashed, user.display_name, user.role.value
    )

    logger.info("User created", username=user.username, by=current_user["username"])

    return UserResponse(**dict(new_user))
