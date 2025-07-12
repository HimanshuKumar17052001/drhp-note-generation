from mongoengine import connect
from qdrant_client import QdrantClient
import os
from dotenv import load_dotenv
import mongoengine
from mongoengine import connect
from mongoengine.connection import get_db

load_dotenv()

mongo_client = None
qdrant_client = None

def get_mongo_client():
    return mongo_client  

def get_qdrant_client():
    return qdrant_client  

def initialize_clients():
    global mongo_client, qdrant_client
    try:
        mongo_url = os.getenv("MONGO_URI")
        print(f"Connecting to MongoDB at {mongo_url}")
        mongoengine.connect(
            db=os.getenv("MONGO_DB"),  # explicitly specify your DB name
            host=os.getenv("MONGO_URI")  # your MongoDB URI
        )
        db = get_db()
        print("this is the db", db)
        collections = db.list_collection_names()
        print("MongoDB collections available:", collections)
        
        mongo_client = True  
    except Exception as e:
        print(f"MongoDB connection ❌: {e}")
        mongo_client = None

    try:
        qdrant_url = os.getenv("QDRANT_URL")
        print(f"Connecting to Qdrant at {qdrant_url}")
        qdrant_client = QdrantClient(url=qdrant_url, timeout=60)
    except Exception as e:
        print(f"Qdrant connection ❌: {e}")
        qdrant_client = None


