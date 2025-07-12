from fastapi import FastAPI, APIRouter, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from app.core.database import get_mongo_client, get_qdrant_client, initialize_clients
from app.api.endpoints.list_companies import router as companies_router
from app.api.endpoints.sebi_checklist import router as sebi_router
from app.api.endpoints.bse_checklist import router as bse_router
from app.api.endpoints.standard_checklist import router as standard_router
from app.api.endpoints.company_details import router as details_router
from app.api.endpoints.auth import router as auth_router
from app.api.endpoints.litigations import router as litigations_router
from app.api.endpoints.upload_drhp_to_blob import router as upload_drhp_router
from app.api.endpoints.change_checlist_status import router as change_checlist_status_router
from app.api.endpoints.processing_analytics import router as processing_analytics_router  
from app.api.endpoints.processing_status import router as processing_status_router
from app.api.endpoints.drhp_report import router as drhp_report_router
from app.models.schemas import User
from dotenv import load_dotenv
import os
import logging
import time
import uuid

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("app_debug.log")
    ]
)
logger = logging.getLogger("main")

load_dotenv()

app = FastAPI()

# Add middleware to log all requests
@app.middleware("http")
async def log_requests(request: Request, call_next):
    request_id = str(uuid.uuid4())
    logger.info(f"Request {request_id} started: {request.method} {request.url.path}")
    
    # Log headers (excluding auth)
    safe_headers = {k: v for k, v in request.headers.items() if k.lower() not in ['authorization']}
    logger.info(f"Request {request_id} headers: {safe_headers}")
    
    start_time = time.time()
    
    # Process request
    try:
        response = await call_next(request)
        process_time = time.time() - start_time
        
        logger.info(f"Request {request_id} completed: {response.status_code} in {process_time:.3f}s")
        
        return response
    except Exception as e:
        process_time = time.time() - start_time
        logger.error(f"Request {request_id} failed after {process_time:.3f}s: {str(e)}")
        raise

# CORS middleware configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"], 
    allow_headers=["*"], 
)

# Create API router with prefix
api_router = APIRouter()
# api_router = APIRouter(prefix="/backend")
# api_router = APIRouter(prefix="/api")

# Include all routers
api_router.include_router(companies_router)
api_router.include_router(sebi_router)
api_router.include_router(bse_router)
api_router.include_router(standard_router)
api_router.include_router(details_router)
api_router.include_router(auth_router)
api_router.include_router(litigations_router)
api_router.include_router(processing_status_router)
api_router.include_router(upload_drhp_router)
api_router.include_router(change_checlist_status_router)
api_router.include_router(processing_analytics_router)
api_router.include_router(drhp_report_router)

# Add root and health endpoints to the API router
@api_router.get("/")
async def root():
    logger.info("Root endpoint called")
    return {"message": "Welcome to the backend service!"}

@api_router.get("/health")
async def health_check():
    logger.info("Health check endpoint called")
    return {"status": "ok"}

# Include the API router in the main app
app.include_router(api_router)

@app.on_event("startup")
async def startup_event():
    try:
        # Initialize MongoDB and Qdrant connections
        initialize_clients()  # Call the new function to initialize clients

        logger.info("✅ MongoDB and Qdrant connections initialized")
        
        # Log all available routes for debugging
        routes = [{"path": route.path, "name": route.name, "methods": route.methods} for route in app.routes]
        # logger.info(f"Available routes: {routes}")
    except Exception as e:
        logger.error(f"❌ Startup error: {e}")

@app.on_event("shutdown")
async def shutdown_event():
    logger.info("🔴 Shutting down connections...")

# Log all routes at startup for debugging    
for route in app.routes:
    logger.info(f"Route available: {route.path}")
