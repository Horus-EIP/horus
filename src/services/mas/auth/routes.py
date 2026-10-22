"""HTTP routes for registration, JWT login, and logout.

Tokens are issued by ``create_access_token`` (20-min TTL) and revoked via
a Redis blacklist keyed by the JWT's ``nonce``.
"""

from datetime import datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.exc import IntegrityError
from starlette import status

from auth.auth_tool_functions import (
    authenticate_user,
    bcrypt_context,
    create_access_token,
    get_current_user,
)
from auth.openapi_docs import (
    LOGOUT_RESPONSES,
    REGISTER_OPENAPI_EXTRA,
    REGISTER_RESPONSES,
    TOKEN_OPENAPI_EXTRA,
    TOKEN_RESPONSES,
)
from db.dependency import db_dependency
from db.models import Users
from db.redis_client import redis_db
from schemas.schemas import CreateUserRequest, Token

user_dependency = Annotated[dict, Depends(get_current_user)]

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post(
    "/register",
    summary="Register a new user account",
    description="Create a new user with a hashed password and store it in the database. Username must be unique across the system.",
    status_code=status.HTTP_201_CREATED,
    tags=["Authentication"],
    responses=REGISTER_RESPONSES,
    openapi_extra=REGISTER_OPENAPI_EXTRA,
)
async def create_user(db: db_dependency, create_user_request: CreateUserRequest):
    """Create a user with a bcrypt-hashed password. 409 if username exists."""
    create_user_model = Users(
        username=create_user_request.username,
        hashed_password=bcrypt_context.hash(create_user_request.password),
    )
    db.add(create_user_model)
    try:
        db.commit()
        db.refresh(create_user_model)
        return create_user_model
    except IntegrityError as e:
        db.rollback()
        error_message = str(e.orig)
        message = f"User Registration Error : {error_message}"
        raise HTTPException(status_code=409, detail=message)


@router.post(
    "/token",
    summary="Authenticate user and generate access token",
    description="Validates user credentials and returns a JWT token if authentication is successful. Token expires in 20 minutes. Returns Bearer token for API authorization.",
    response_model=Token,
    tags=["Authentication"],
    responses=TOKEN_RESPONSES,
    openapi_extra=TOKEN_OPENAPI_EXTRA,
)
async def login_for_access_token(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()], db: db_dependency
):
    """Validate OAuth2 password form credentials and return a JWT (20-min TTL)."""
    user = authenticate_user(form_data.username, form_data.password, db)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Could not validate User"
        )
    username = user.username
    user_id = user.id
    role = user.role
    token = create_access_token(username, user_id, timedelta(minutes=20), role)

    return {"access_token": token, "token_type": "bearer"}


@router.post(
    "/logout",
    summary="Log out user by invalidating JWT token",
    description="Adds the current JWT token to a Redis blacklist to prevent further use. The token remains blacklisted until its natural expiration time.",
    tags=["Authentication"],
    responses=LOGOUT_RESPONSES,
)
def user_logout(user: user_dependency):
    """Blacklist the current JWT in Redis until its natural expiration."""
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication Failed")

    exp = None

    exp = user.get("exp")

    if not exp:
        raise HTTPException(status_code=401, detail="Authentication Failed")
    
    nonce = user.get("nonce")

    ttl = exp - int(datetime.now().timestamp())
    if ttl > 0:
        redis_db.setex(f"jwt:blacklist:{nonce}", ttl, "revoked")

    return {"message": "Successfully logout"}
