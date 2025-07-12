from fastapi import APIRouter, HTTPException, Request, Response, Form
from app.models.schemas import User
import bcrypt
import jwt
import logging
from pydantic import BaseModel, EmailStr
import traceback
from app.utils.log_to_s3 import log_to_s3
import xml.etree.ElementTree as ET
import urllib.parse
import base64
from typing import Optional
import os
from dotenv import load_dotenv
load_dotenv()

base_url = os.getenv("BASE_URL")

# Configure logging
logger = logging.getLogger("auth_endpoints")

router = APIRouter()

class UserCreate(BaseModel):
    name: str
    username: str
    email: EmailStr
    password: str

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"

@router.post("/register", response_model=TokenResponse)
@log_to_s3
async def register_user(user_data: UserCreate):
    try:
        logger.info(f"Registration attempt for email: {user_data.email}")
        
        # Check if user already exists
        existing_user = User.objects(email=user_data.email).first()
        if existing_user:
            logger.warning(f"Registration failed: Email already registered: {user_data.email}")
            raise HTTPException(status_code=400, detail="Email already registered")
        
        # Hash the password
        hashed = bcrypt.hashpw(user_data.password.encode('utf-8'), bcrypt.gensalt())
        
        # Create new user
        new_user = User(
            name=user_data.name,
            username=user_data.username,
            email=user_data.email,
            password=hashed
        )
        new_user.save()
        logger.info(f"New user created: {user_data.email}")
        
        # Generate JWT token
        token = jwt.encode(
            {"email": user_data.email},
            "onfi-jwt-secret-key",
            algorithm="HS256"
        )
        
        logger.info(f"JWT token generated for user: {user_data.email}")
        return TokenResponse(access_token=token)
    
    except Exception as e:
        logger.error(f"Registration error for {user_data.email}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/login", response_model=TokenResponse)
@log_to_s3
async def login_user(user_data: UserLogin):
    try:
        logger.info(f"Login attempt for email: {user_data.email}")
        
        # Find user by email
        user = User.objects(email=user_data.email).first()
        
        if not user:
            logger.warning(f"Login failed: User not found for email: {user_data.email}")
            raise HTTPException(status_code=401, detail="Invalid email or password")
        
        logger.info(f"User found in database: {user.email}, skipping password validation...")
        
        # Generate JWT token
        token_payload = {"email": user_data.email}
        logger.info(f"Generating token with payload: {token_payload}")
        
        token = jwt.encode(
            token_payload,
            "onfi-jwt-secret-key",
            algorithm="HS256"
        )
        
        # Log token type for debugging
        token_type = type(token).__name__
        logger.info(f"Token generated successfully, type: {token_type}, length: {len(token)}")
        
        # Include a debug step to ensure token is properly formatted
        if isinstance(token, bytes):
            token = token.decode("utf-8")
            logger.info("Token was bytes, converted to string")
        
        # Add info about token usage
        logger.info("Token should be used with 'Bearer' prefix in Authorization header")
        
        return TokenResponse(access_token=token)
    
    except Exception as e:
        logger.error(f"Login error for {user_data.email}: {str(e)}")
        logger.error(f'Login error traceback: {traceback.format_exc()}')
        raise HTTPException(status_code=500, detail=str(e)) 

@router.post("/saml")
@log_to_s3
async def saml_signin(
    request: Request,
    SAMLResponse: Optional[str] = Form(None),
    RelayState: Optional[str] = Form(None)
):
    """
    Process SAML authentication response.
    
    This endpoint accepts x-www-form-urlencoded form data containing SAML credentials.
    It decodes the SAMLResponse and analyzes it for potential issues.
    """
    logger.info("Received SAML authentication request")
    
    # Check if SAMLResponse is provided
    if not SAMLResponse:
        logger.error("No SAMLResponse provided in the request")
        raise HTTPException(status_code=400, detail="Missing SAMLResponse in form data")
    
    try:
        # SAML responses are typically base64 encoded
        decoded_response = base64.b64decode(SAMLResponse).decode('utf-8')
        logger.info("Successfully decoded SAML response")
        with open("saml_response.xml", "w") as f:
            f.write(decoded_response)
        # print(decoded_response)
        
        root = ET.fromstring(decoded_response)
        logger.info("Successfully parsed SAML XML")

        namespaces = {
            'samlp': 'urn:oasis:names:tc:SAML:2.0:protocol',
            'saml': 'urn:oasis:names:tc:SAML:2.0:assertion'
        }
            
        # Extract email from NameID
        name_id = root.find('.//saml:NameID', namespaces)
        if name_id is not None:
            email = name_id.text
            print(f"\nExtracted email: {email}")
        else:
            print("\nNo email found in SAML response")
            
        # Check for common issues
        issues = []
            
        # Check if the response is a success
        status = root.find('.//samlp:StatusCode', namespaces)
        if status is not None and status.get('Value') != 'urn:oasis:names:tc:SAML:2.0:status:Success':
            issues.append(f"Authentication failed with status: {status.get('Value')}")
        
        # Check for assertion
        assertion = root.find('.//saml:Assertion', namespaces)
        if assertion is None:
            issues.append("No assertion found in SAML response")
        
        # Check for expiration
        conditions = root.find('.//saml:Conditions', namespaces)
        if conditions is not None:
            # Would check NotBefore and NotOnOrAfter attributes here
            pass
        
        # Check for required attributes (subject, attributes, etc.)
        subject = root.find('.//saml:Subject', namespaces)
        if subject is None:
            issues.append("No subject found in SAML response")
        
        # Return results
        if issues:
            return {
                "success": False,
                "issues": issues,
                "saml_response_summary": {
                    "response_type": root.tag,
                    "issuer": root.find('.//saml:Issuer', namespaces).text if root.find('.//saml:Issuer', namespaces) is not None else "Not found",
                    "email": email if name_id is not None else None
                }
            }
        else:
            redirect_url = f'{base_url}/auth/saml?email={email}'
            logger.info(f"Redirecting to: {redirect_url}")

            return Response(
                status_code=307,
                headers={"Location": redirect_url}
            )
            
    except Exception as e:
        logger.error(f"Error processing SAML response: {str(e)}")
        return {
            "success": False,
            "issues": [f"Failed to process SAML response: {str(e)}"],
            "raw_data_sample": SAMLResponse[:30] + "..." if len(SAMLResponse) > 30 else SAMLResponse
        }