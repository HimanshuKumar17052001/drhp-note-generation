from functools import wraps
from fastapi import Request, HTTPException, Depends
import jwt
import os
import logging
from app.models.schemas import User
import pandas as pd
import requests
from io import BytesIO
from collections import defaultdict

from app.core.database import get_mongo_client

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("auth_debug.log")
    ]
)
logger = logging.getLogger("auth_utils")

__all__ = ['login_required']

async def login_required(request: Request):
    # Log request path and method
    logger.info(f"Auth check for: {request.method} {request.url.path}")
    
    # Check if authorization header exists
    if 'authorization' not in request.headers:
        logger.error("Authorization header missing")
        raise HTTPException(status_code=401, detail="Token is missing - no authorization header")
    
    # Log all headers for debugging (excluding sensitive ones)
    safe_headers = {k: v for k, v in request.headers.items() if k.lower() not in ['authorization']}
    logger.info(f"Request headers: {safe_headers}")
    
    # Parse token from header
    auth_header = request.headers['authorization']
    logger.info(f"Authorization header format: {auth_header[:10]}...")
    
    token = None
    try:
        # Check if header starts with "Bearer "
        if not auth_header.startswith("Bearer "):
            logger.error("Authorization header does not start with 'Bearer '")
            raise HTTPException(status_code=401, detail="Invalid token format - missing Bearer prefix")
        
        token = auth_header.split(" ")[1]
        logger.info(f"Token extracted successfully, length: {len(token)}")
    except IndexError:
        logger.error("Failed to split authorization header")
        raise HTTPException(status_code=401, detail="Invalid token format - unable to extract token")

    if not token:
        logger.error("Token is empty after extraction")
        raise HTTPException(status_code=401, detail="Token is missing - empty token")

    try:
        # Log token details (first few chars only for security)
        token_preview = token[:10] + "..." if len(token) > 10 else token
        logger.info(f"Attempting to decode token: {token_preview}")
        
        # Decode token
        data = jwt.decode(
            token,
            "onfi-jwt-secret-key",  # Use environment variable or default for testing
            algorithms=["HS256"]
        )
        
        # Log successful decode and payload (excluding sensitive info)
        safe_data = {k: v for k, v in data.items() if k != 'password'}
        logger.info(f"Token decoded successfully: {safe_data}")
     
        # Get current user
        email = data.get('email')
        if not email:
            logger.error("No email found in token payload")
            raise HTTPException(status_code=401, detail="Invalid token - missing email claim")
            
        logger.info(f"Looking up user with email: {email}")
        current_user = User.objects(email=email).first()

        if not current_user:
            logger.error(f"No user found with email: {email}")
            raise HTTPException(status_code=401, detail="Invalid user - user not found in database")

        logger.info(f"User found: {current_user.username}")
        request.state.user = current_user
        return current_user

    except jwt.ExpiredSignatureError:
        logger.error("Token has expired")
        raise HTTPException(status_code=401, detail="Token has expired")
    except jwt.InvalidTokenError as e:
        logger.error(f"Invalid token: {str(e)}")
        raise HTTPException(status_code=401, detail=f"Invalid token - {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected error during authentication: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Authentication error: {str(e)}")

