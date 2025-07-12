from qdrant_client import QdrantClient
from qdrant_client.http import models
import os
import uuid
import litellm
import os
from dotenv import load_dotenv
load_dotenv()

import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

#TODO: Please priyesh add ur creds here
   

def create_qdrant_collection(qdrant_client, collection_name):
    """
    Creates a Qdrant collection if it doesn't exist.
    Adds optimized indexes for faster retrieval & filtering.
    """
    print("Setting collection name: ", collection_name)
    
    if not qdrant_client.collection_exists(collection_name):
        qdrant_client.create_collection(
            collection_name=collection_name,
            vectors_config=models.VectorParams(
                size=1024,
                distance=models.Distance.COSINE
            ),
        )
        
        # ✅ Create index on `object_id`
        qdrant_client.create_payload_index(
            collection_name=collection_name,
            field_name="object_id",
            field_schema=models.PayloadSchemaType.KEYWORD
        )

        # ✅ Create index on `chunk` (full-text search support)
        qdrant_client.create_payload_index(
            collection_name=collection_name,
            field_name="chunk",
            field_schema=models.PayloadSchemaType.TEXT,
            wait=True
        )

        # ✅ Create index on `company_id` (for filtering searches by company)
        qdrant_client.create_payload_index(
            collection_name=collection_name,
            field_name="company_id",
            field_schema=models.PayloadSchemaType.KEYWORD
        )

        # ✅ Create index on `section_name` (useful for section-wise searches)
        qdrant_client.create_payload_index(
            collection_name=collection_name,
            field_name="section_name",
            field_schema=models.PayloadSchemaType.KEYWORD
        )

        print(f"✅ Created collection {collection_name} with optimized indexes.")

    else:
        print(f"Collection {collection_name} already exists.")




def generate_vector(query: str) -> list:
    try:
        if not query or not isinstance(query, str):
            logger.warning("Invalid input for vector generation")
            return [0.0] * 1024

        formatted_input = query.strip()[:8000]
        if not formatted_input:
            logger.warning("Empty string after stripping whitespace - cannot generate embeddings")
            return [0.0] * 1024

        
        response = litellm.embedding(
            model="bedrock/amazon.titan-embed-text-v2:0",
            input=[formatted_input],
        )
        # print("this is the response",response)
        # response.data is a list of Embedding objects with an .embedding attribute
        if getattr(response, "data", None):
            first = response.data[0]
            if hasattr(first, "embedding"):
                return first.embedding

        logger.error(f"Unexpected response structure: {response!r}")
        return [0.0] * 1024

    except Exception as e:
        logger.error(f"Error generating vector: {str(e)}")
        return [0.0] * 1024


def write_to_qdrant(qdrant_client,obj_id, collection_name, chunks):
    vectors = [generate_vector(chunk) for chunk in chunks]    
    points = [
        models.PointStruct(
            id=str(uuid.uuid4()),
            vector=vector,
            payload={
                "object_id": str(obj_id),
                "chunk": chunk
            }
        )
        for idx, (vector, chunk) in enumerate(zip(vectors, chunks))
    ]
    qdrant_client.upsert(
        collection_name=collection_name,
        points=points
    )

def get_collection_name(class_name) -> str:
    snake_case = class_name[0].lower()
    for char in class_name[1:]:
        if char.isupper():
            snake_case += '_' + char.lower()
        else:
            snake_case += char
    print("this is the collection name for qdrant",class_name)
    return "os_" + snake_case
    # return "test_db"
    
if __name__ == "__main__":
    # Test the function
    test_text = "hello world"
    result = generate_vector(test_text)
    print(f"Input text: {test_text}")
    print(f"Vector length: {len(result)}")
    print(f"First few values: {result[:50]}")