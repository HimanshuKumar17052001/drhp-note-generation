import json
import uuid
import boto3
import inspect
from functools import wraps
from fastapi import Request, Response
from datetime import datetime
import os
from dotenv import load_dotenv
from pydantic import BaseModel

load_dotenv()

# Load environment variables
AWS_REGION_NAME = os.getenv("AWS_REGION_NAME", "ap-south-1")  # fallback default
ENV_TYPE = os.getenv("ENV_TYPE", "dev")  # Default to dev environment
S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME", f"drhp-assets-{ENV_TYPE}-onfi")

# Initialize S3 client using IAM role
# Explicitly use the default credential provider chain which will check:
# 1. Environment variables
# 2. Shared credential file (~/.aws/credentials)
# 3. IAM role for Amazon EC2/ECS
s3_client = boto3.client(
    "s3",
    region_name=AWS_REGION_NAME
)


def serialize_response(obj):
    """Helper function to serialize response objects for logging."""
    try:
        # Handle Pydantic BaseModel
        if isinstance(obj, BaseModel):
            return obj.model_dump()
        
        # Handle FastAPI Response objects
        if isinstance(obj, Response):
            return {
                "status_code": obj.status_code,
                "headers": dict(obj.headers),
                "media_type": getattr(obj, 'media_type', None),
                "response_type": type(obj).__name__
            }
        
        # Handle dictionaries and lists
        if isinstance(obj, dict):
            return obj
        
        if isinstance(obj, list):
            return obj
        
        # For other objects, try to convert to string
        return str(obj)
    
    except Exception as e:
        return f"Failed to serialize response: {str(e)} (type: {type(obj).__name__})"


def log_to_s3(func):
    @wraps(func)
    async def wrapper(*args, **kwargs):
        request: Request = kwargs.get("request")
        request_data = {}
        response_data = {}
        error_message = None

        try:
            if request:
                try:
                    request_data = await request.json()
                except Exception:
                    request_data = await request.body()
                    request_data = request_data.decode("utf-8")
        except Exception as e:
            request_data = f"Failed to parse request body: {str(e)}"

        try:
            response = await func(*args, **kwargs)
            response_data = serialize_response(response)
            return response
        except Exception as e:
            error_message = str(e)
            raise
        finally:
            log_id = str(uuid.uuid4())
            timestamp = datetime.utcnow().isoformat()
            s3_key = f"drhp-list-{ENV_TYPE}/application/{datetime.utcnow().date()}/{log_id}.json"

            log_entry = {
                "id": log_id,
                "timestamp": timestamp,
                "path": str(request.url) if request else "unknown",
                "method": request.method if request else "unknown",
                "headers": dict(request.headers) if request else {},
                "request": request_data,
                "response": response_data,
                "error": error_message
            }

            try:
                s3_client.put_object(
                    Bucket=S3_BUCKET_NAME,
                    Key=s3_key,
                    Body=json.dumps(log_entry, indent=2),
                    ContentType="application/json"
                )
            except Exception as s3_error:
                print(f"Failed to upload log to S3: {str(s3_error)}")

    return wrapper


def log_schema_changes(collection_name):
    """
    Decorator to track changes to database models and log them to S3.
    
    Usage:
    @log_schema_changes("collection_name")
    def update_function(user_email, ...):
        # Your function that modifies the model
    
    The decorator will capture:
    - The collection being changed
    - Field changes (name, old value, new value, and CRUD operation)
    - The user email making the change
    - Timestamp of the operation
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Extract user email from arguments
            user_email = kwargs.get('user_email', 'unknown')
            
            # For tracking changes
            changes = []
            
            # Save the state before function execution
            old_state = {}
            doc = None
            
            # Try to identify the document being modified
            for arg in args:
                # Check if argument is a mongoengine Document
                if hasattr(arg, '_fields') and hasattr(arg, 'to_mongo'):
                    doc = arg
                    # Save the current state
                    old_state = {field: getattr(doc, field, None) for field in doc._fields}
                    break
            
            # Execute the original function
            result = func(*args, **kwargs)
            
            # If we found a document, compare states
            if doc:
                # Get new state after function execution
                new_state = {field: getattr(doc, field, None) for field in doc._fields}
                
                # Determine what changed
                for field, old_value in old_state.items():
                    new_value = new_state.get(field)
                    
                    # Check if value changed
                    if old_value != new_value:
                        # Determine action type (C, U, D)
                        action_type = "C" if old_value is None and new_value is not None else "U"
                        
                        # Add to changes list
                        changes.append({
                            "field_name": field,
                            "old_value": str(old_value),
                            "new_value": str(new_value),
                            "action_type": action_type
                        })
            
            # If there were changes, log to S3
            if changes:
                log_entry = {
                    "changed_collection": collection_name,
                    "changes": changes,
                    "user_making_change_email": user_email,
                    "operation_timestamp": datetime.utcnow().isoformat()
                }
                
                log_id = str(uuid.uuid4())
                s3_key = f"schema-changes/{datetime.utcnow().date()}/{log_id}.json"
                
                try:
                    s3_client.put_object(
                        Bucket=S3_BUCKET_NAME,
                        Key=s3_key,
                        Body=json.dumps(log_entry, indent=2),
                        ContentType="application/json"
                    )
                except Exception as s3_error:
                    print(f"Failed to upload schema change log to S3: {str(s3_error)}")
            
            return result
        return wrapper
    return decorator

# Helper functions for CRUD operations with schema change tracking
def log_document_changes(collection_name, document, user_email, action_type="C"):
    """
    Log document changes to S3.
    
    Args:
        collection_name: Name of the MongoDB collection
        document: MongoEngine document instance
        user_email: Email of the user making the change
        action_type: Type of action (C=Create, U=Update, D=Delete)
    """
    changes = []
    
    if action_type == "C":  # Create
        # For new documents, log all non-None fields as created
        for field_name, field_value in document._data.items():
            if field_value is not None:
                changes.append({
                    "field_name": field_name,
                    "old_value": "None",
                    "new_value": str(field_value),
                    "action_type": "C"
                })
    elif action_type == "D":  # Delete
        # For deleted documents, log all fields as deleted
        for field_name, field_value in document._data.items():
            if field_value is not None:
                changes.append({
                    "field_name": field_name,
                    "old_value": str(field_value),
                    "new_value": "None",
                    "action_type": "D"
                })
    
    # If there were changes, log to S3
    if changes:
        log_entry = {
            "changed_collection": collection_name,
            "changes": changes,
            "user_making_change_email": user_email,
            "operation_timestamp": datetime.utcnow().isoformat()
        }
        
        log_id = str(uuid.uuid4())
        s3_key = f"schema-changes/{datetime.utcnow().date()}/{log_id}.json"
        
        try:
            s3_client.put_object(
                Bucket=S3_BUCKET_NAME,
                Key=s3_key,
                Body=json.dumps(log_entry, indent=2),
                ContentType="application/json"
            )
            print(f"Schema change logged to S3: {s3_key}")
        except Exception as s3_error:
            print(f"Failed to upload schema change log to S3: {str(s3_error)}")

def save_document(document, user_email):
    """
    Save a document and log the creation to S3.
    
    Args:
        document: MongoEngine document to save
        user_email: Email of the user making the change
    
    Returns:
        The saved document
    """
    # Save the document first
    result = document.save()
    
    # Log the creation
    collection_name = document.__class__.__name__.lower()
    log_document_changes(collection_name, document, user_email, "C")
    
    return result

def update_document(document, user_email, **kwargs):
    """
    Update a document and log the changes to S3.
    
    Args:
        document: MongoEngine document to update
        user_email: Email of the user making the change
        **kwargs: Fields to update
        
    Returns:
        The updated document
    """
    # Save old state
    old_state = {field: getattr(document, field, None) for field in document._fields}
    
    # Update fields
    for field, value in kwargs.items():
        setattr(document, field, value)
    
    # Save the document
    result = document.save()
    
    # Track changes
    changes = []
    for field, old_value in old_state.items():
        new_value = getattr(document, field, None)
        if old_value != new_value:
            changes.append({
                "field_name": field,
                "old_value": str(old_value),
                "new_value": str(new_value),
                "action_type": "U"
            })
    
    # If there were changes, log to S3
    if changes:
        log_entry = {
            "changed_collection": document.__class__.__name__.lower(),
            "changes": changes,
            "user_making_change_email": user_email,
            "operation_timestamp": datetime.utcnow().isoformat()
        }
        
        log_id = str(uuid.uuid4())
        s3_key = f"schema-changes/{datetime.utcnow().date()}/{log_id}.json"
        
        try:
            s3_client.put_object(
                Bucket=S3_BUCKET_NAME,
                Key=s3_key,
                Body=json.dumps(log_entry, indent=2),
                ContentType="application/json"
            )
            print(f"Schema change logged to S3: {s3_key}")
        except Exception as s3_error:
            print(f"Failed to upload schema change log to S3: {str(s3_error)}")
    
    return result

def delete_document(document, user_email):
    """
    Delete a document and log the deletion to S3.
    
    Args:
        document: MongoEngine document to delete
        user_email: Email of the user making the change
        
    Returns:
        The result of the delete operation
    """
    # Log the deletion before actually deleting
    collection_name = document.__class__.__name__.lower()
    log_document_changes(collection_name, document, user_email, "D")
    
    # Delete the document
    return document.delete()


