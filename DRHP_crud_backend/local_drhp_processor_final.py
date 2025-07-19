import os
import json
import logging
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional, Tuple, Dict, Any
from dotenv import load_dotenv
from pathlib import Path
import uuid
import requests

load_dotenv()

from DRHP_ai_processing.page_processor_local import process_pdf_local
from qdrant_client import QdrantClient, models as qmodels
from baml_client import b
from baml_py import Collector, Image
import pdfplumber
import fitz
import numpy as np
import cv2
import base64
import re
from openai import OpenAI
from azure_blob_utils import get_blob_storage


# Configure comprehensive logging with both file and console handlers
def setup_logging(company_name: str) -> logging.Logger:
    """Setup comprehensive logging for the processor"""
    # Create logs directory if it doesn't exist
    logs_dir = Path("logs")
    logs_dir.mkdir(exist_ok=True)

    # Create company-specific log file
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    log_filename = f"logs/{company_name}_{timestamp}.log"

    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler(log_filename, encoding="utf-8"),
            logging.StreamHandler(),
        ],
        force=True,
    )

    logger = logging.getLogger(f"DRHP_Processor_{company_name}")
    logger.setLevel(logging.INFO)

    return logger


# Thread-safe token counters
_token_lock = threading.Lock()


class LocalDRHPProcessor:
    def __init__(
        self,
        qdrant_url: str = None,
        collection_name: str = "drhp_notes_testing",
        max_workers: int = 5,
        company_name: str = "Unknown",
    ):
        self.qdrant_url = qdrant_url or os.getenv("QDRANT_URL", "http://localhost:6333")
        self.collection_name = collection_name
        self.company_name = company_name
        self.max_workers = max_workers

        # Setup logging
        self.logger = setup_logging(company_name)

        # Initialize Qdrant client with retry logic
        self._init_qdrant_client()

        # Initialize OpenAI client for embeddings
        self.openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

        # Dedicated collectors for parallel processing
        self.collectors = [
            Collector(name=f"collector-{company_name}-{i}") for i in range(max_workers)
        ]

        # Token counters
        self.input_tokens = 0
        self.output_tokens = 0

        # Processing statistics
        self.stats = {
            "pages_processed": 0,
            "queries_processed": 0,
            "errors": 0,
            "start_time": None,
            "end_time": None,
            "embeddings_created": False,
            "embeddings_reused": False,
        }

    def _init_qdrant_client(self, max_retries: int = 3):
        """Initialize Qdrant client with retry logic"""
        for attempt in range(max_retries):
            try:
                self.qdrant = QdrantClient(url=self.qdrant_url, timeout=60)
                # Test connection
                self.qdrant.get_collections()
                self.logger.info(
                    f"Successfully connected to Qdrant at {self.qdrant_url}"
                )
                return
            except Exception as e:
                self.logger.warning(
                    f"Qdrant connection attempt {attempt + 1} failed: {e}"
                )
                if attempt == max_retries - 1:
                    self.logger.error(
                        f"Failed to connect to Qdrant after {max_retries} attempts"
                    )
                    raise
                time.sleep(2**attempt)  # Exponential backoff

    def _generate_openai_embedding(self, text: str) -> List[float]:
        """
        Generate embedding using OpenAI's text-embedding-3-small model
        """
        try:
            response = self.openai_client.embeddings.create(
                model="text-embedding-3-small", input=text
            )
            return response.data[0].embedding
        except Exception as e:
            self.logger.error(f"❌ Error generating OpenAI embedding: {e}")
            raise

    def _generate_sparse_embedding(self, text: str) -> qmodels.SparseVector:
        """
        Generate sparse embedding using the hosted SPLADE service
        """
        try:
            sparse_url = os.getenv(
                "SPARSE_EMBEDDING_URL", "http://52.7.81.94:8010/embed"
            )

            response = requests.post(sparse_url, json={"text": text}, timeout=10)
            response.raise_for_status()
            sparse_dict = response.json() or {}

            if sparse_dict:
                indices = [int(k) for k in sparse_dict.keys()]
                values = [float(v) for v in sparse_dict.values()]
                return qmodels.SparseVector(indices=indices, values=values)
            else:
                self.logger.warning(
                    "Empty sparse embedding response, returning empty vector"
                )
                return qmodels.SparseVector(indices=[], values=[])

        except Exception as e:
            self.logger.error(f"❌ Error generating sparse embedding: {e}")
            return qmodels.SparseVector(indices=[], values=[])

    def _combine_text_for_embedding(self, page_info: dict) -> str:
        """
        Combine page content, facts, and queries for embedding
        """
        parts = []

        # Add page content
        content = page_info.get("page_content", "")
        if content.strip():
            parts.append(content)

        # Add facts
        facts = page_info.get("facts", [])
        if facts:
            facts_text = " ".join([str(fact) for fact in facts])
            parts.append(facts_text)

        # Add queries
        queries = page_info.get("queries", [])
        if queries:
            queries_text = " ".join([str(query) for query in queries])
            parts.append(queries_text)

        return " ".join(parts)

    def _generate_hybrid_embeddings(
        self, page_info: dict
    ) -> Tuple[List[float], qmodels.SparseVector]:
        """
        Generate both dense and sparse embeddings for a page
        """
        # Combine all text content
        combined_text = self._combine_text_for_embedding(page_info)

        # Generate dense embedding for page content only
        dense_text = page_info.get("page_content", "")
        dense_vector = self._generate_openai_embedding(dense_text)

        # Generate sparse embedding for combined content (facts + queries + content)
        sparse_vector = self._generate_sparse_embedding(combined_text)

        return dense_vector, sparse_vector

    def pdf_page_to_cv2_image(
        self, pdf_path: str, page_num: int, dpi: int = 200
    ) -> np.ndarray:
        """Convert PDF page to cv2 image with error handling"""
        try:
            doc = fitz.open(pdf_path)
            page = doc.load_page(page_num - 1)
            pix = page.get_pixmap(dpi=dpi)
            img_np = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
                (pix.height, pix.width, pix.n)
            )
            if pix.n == 4:
                img_np = cv2.cvtColor(img_np, cv2.COLOR_RGBA2BGR)
            else:
                img_np = cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR)
            doc.close()
            return img_np
        except Exception as e:
            self.logger.error(f"Error converting PDF page {page_num} to image: {e}")
            raise

    def img_to_bytes(self, cv2_img: np.ndarray) -> bytes:
        """Convert cv2 image to bytes with error handling"""
        try:
            success, buf = cv2.imencode(".png", cv2_img)
            if not success:
                raise ValueError("Failed to encode image")
            return buf.tobytes()
        except Exception as e:
            self.logger.error(f"Error converting image to bytes: {e}")
            raise

    def detect_toc_page(
        self, pdf_path: str, company_name: str, max_pages_to_check: int = 20
    ) -> Optional[dict]:
        """
        Detect Table of Contents page and extract TOC content using BAML with comprehensive error handling
        Returns a dict with page number and TOC content, or None if not found
        """
        self.logger.info("🔍 Detecting Table of Contents page...")

        try:
            with pdfplumber.open(pdf_path) as pdf:
                total_pages = len(pdf.pages)
                pages_to_check = min(max_pages_to_check, total_pages)

            self.logger.info(f"Checking first {pages_to_check} pages for TOC...")

            for page_num in range(1, pages_to_check + 1):
                try:
                    self.logger.debug(f"Checking page {page_num} for TOC...")

                    # Convert page to image
                    cv2_img = self.pdf_page_to_cv2_image(pdf_path, page_num)
                    img_bytes = self.img_to_bytes(cv2_img)
                    b64 = base64.b64encode(img_bytes).decode()
                    baml_img = Image.from_base64("image/png", b64)

                    # Check if this is a TOC page using BAML
                    toc_result = b.ExtractTableOfContents(baml_img)
                    if toc_result.isTocPage:
                        self.logger.info(f"✅ TOC detected at page {page_num}")

                        # Extract TOC content
                        toc_content_result = b.ExtractTocContent(baml_img)

                        return {
                            "page_number": page_num,
                            "toc_entries": toc_content_result.toc_entries,
                            "toc_text": toc_content_result.toc_text,
                        }

                except Exception as e:
                    self.logger.warning(f"Error checking TOC for page {page_num}: {e}")
                    continue

            self.logger.warning(
                f"❌ No TOC page detected in first {pages_to_check} pages"
            )
            return None

        except Exception as e:
            self.logger.error(f"Error in TOC detection: {e}")
            return None

    def process_pdf_locally(
        self,
        pdf_path: str,
        company_name: str,
        dpi: int = 200,
        threshold: int = 245,
        max_workers: int = 5,
    ) -> str:
        """
        Step 1: Process PDF locally using page_processor with comprehensive error handling
        Returns: Azure blob name of the output JSON file (for internal use only)
        """
        self.logger.info(f"📄 Starting PDF processing: {pdf_path}")
        self.stats["start_time"] = time.time()

        blob_storage = get_blob_storage()
        temp_blobs_to_cleanup = []
        company_id = company_name.replace(" ", "_")
        try:
            # Detect TOC page first
            toc_page = self.detect_toc_page(pdf_path, company_name)

            # Prepare temp blob names
            json_blob_name = (
                f"temp/{company_id}/temp_pages_json/{company_id}_pages.json"
            )
            temp_img_dir_blob_prefix = f"temp/{company_id}/temp_stripped_bottom_images/"

            # Call process_pdf (local-only, no MongoDB)
            self.logger.info("🔄 Processing PDF pages...")
            import tempfile
            import shutil

            with tempfile.TemporaryDirectory() as temp_dir:
                temp_company_dir = os.path.join(temp_dir, company_id)
                os.makedirs(temp_company_dir, exist_ok=True)
                temp_pages_json_dir = os.path.join(temp_company_dir, "temp_pages_json")
                temp_stripped_img_dir = os.path.join(
                    temp_company_dir, "temp_stripped_bottom_images"
                )
                os.makedirs(temp_pages_json_dir, exist_ok=True)
                os.makedirs(temp_stripped_img_dir, exist_ok=True)

                # Patch os.getcwd() to temp_dir for process_pdf_local
                orig_cwd = os.getcwd()
                os.chdir(temp_dir)
                try:
                    total_in, total_out = process_pdf_local(
                        pdf_path=pdf_path,
                        company_name=company_name,
                        dpi=dpi,
                        threshold=threshold,
                        max_workers=max_workers,
                    )
                finally:
                    os.chdir(orig_cwd)

                self.logger.info(
                    f"✅ PDF processing complete. Tokens - in: {total_in}, out: {total_out}"
                )

                # Find the output JSON file
                json_files = [
                    f
                    for f in os.listdir(temp_pages_json_dir)
                    if f.endswith("_pages.json")
                ]
                if not json_files:
                    raise FileNotFoundError(
                        "No output JSON found in temp_pages_json directory"
                    )
                local_json_path = os.path.join(temp_pages_json_dir, json_files[0])
                self.logger.info(f"📁 Found output JSON: {local_json_path}")

                # Add TOC information to the JSON
                self.add_toc_to_json(local_json_path, toc_page)

                # Upload JSON to Azure Blob Storage (internal use only, do not expose URL)
                try:
                    blob_storage.upload_file(local_json_path, json_blob_name)
                    self.logger.debug(
                        f"Uploaded temp JSON to Azure Blob Storage: {json_blob_name} (internal use only)"
                    )
                    temp_blobs_to_cleanup.append(json_blob_name)
                except Exception as e:
                    self.logger.error(
                        f"Failed to upload temp JSON to Azure Blob Storage: {e}"
                    )

                # Upload any PNGs in temp_stripped_bottom_images (internal use only)
                if os.path.exists(temp_stripped_img_dir):
                    for fname in os.listdir(temp_stripped_img_dir):
                        if fname.lower().endswith(".png"):
                            local_img_path = os.path.join(temp_stripped_img_dir, fname)
                            img_blob_name = f"{temp_img_dir_blob_prefix}{fname}"
                            try:
                                blob_storage.upload_file(local_img_path, img_blob_name)
                                self.logger.debug(
                                    f"Uploaded temp PNG to Azure Blob Storage: {img_blob_name} (internal use only)"
                                )
                                temp_blobs_to_cleanup.append(img_blob_name)
                            except Exception as e:
                                self.logger.error(
                                    f"Failed to upload temp PNG to Azure Blob Storage: {e}"
                                )

                # Return the Azure blob name of the JSON file (for internal use only)
                return json_blob_name

        except Exception as e:
            self.logger.error(f"❌ Error in PDF processing: {e}")
            self.logger.error(traceback.format_exc())
            raise
        finally:
            # Clean up temp blobs from Azure after use
            for blob_name in temp_blobs_to_cleanup:
                try:
                    blob_storage.delete_blob(blob_name)
                    self.logger.debug(f"Deleted temp blob from Azure: {blob_name}")
                except Exception as e:
                    self.logger.warning(f"Failed to delete temp blob from Azure: {e}")

    def add_toc_to_json(self, json_path: str, toc_page: Optional[dict]):
        """Add TOC page information and content to the JSON file with error handling"""
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            # Add TOC metadata and content
            pdf_name = list(data.keys())[0]
            data[pdf_name]["_metadata"] = {
                "toc_page": toc_page.get("page_number") if toc_page else None,
                "toc_entries": toc_page.get("toc_entries", []) if toc_page else [],
                "toc_text": toc_page.get("toc_text", "") if toc_page else "",
                "total_pages": len(data[pdf_name]),
                "processing_info": {
                    "toc_detected": toc_page is not None,
                    "toc_page_number": (
                        toc_page.get("page_number") if toc_page else None
                    ),
                    "toc_entries_count": (
                        len(toc_page.get("toc_entries", [])) if toc_page else 0
                    ),
                    "processing_timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "company_name": self.company_name,
                },
            }

            # Write back to file
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4, ensure_ascii=False)

            if toc_page:
                self.logger.info(
                    f"✅ Added TOC information to JSON: TOC page = {toc_page['page_number']}, {len(toc_page.get('toc_entries', []))} entries"
                )
            else:
                self.logger.info("✅ Added metadata to JSON (no TOC detected)")

        except Exception as e:
            self.logger.error(f"❌ Error adding TOC to JSON: {e}")
            raise

    def _validate_collection_structure(self) -> bool:
        """
        Validate that the collection has the required hybrid vector structure
        """
        try:
            collection_info = self.qdrant.get_collection(self.collection_name)

            # Check if collection has both dense and sparse vectors
            has_dense = "dense" in collection_info.config.params.vectors
            has_sparse = (
                hasattr(collection_info.config.params, "sparse_vectors")
                and "sparse" in collection_info.config.params.sparse_vectors
            )

            if not has_dense:
                self.logger.warning(
                    f"⚠️ Collection {self.collection_name} missing dense vectors"
                )
                return False

            if not has_sparse:
                self.logger.warning(
                    f"⚠️ Collection {self.collection_name} missing sparse vectors"
                )
                return False

            self.logger.info(
                f"✅ Collection {self.collection_name} has proper hybrid structure"
            )
            return True

        except Exception as e:
            self.logger.error(f"❌ Error validating collection structure: {e}")
            return False

    def _check_collection_has_embeddings(self) -> bool:
        """
        Check if the collection exists and has embeddings
        Returns True if collection exists and has points, False otherwise
        """
        try:
            if not self.qdrant.collection_exists(self.collection_name):
                self.logger.info(f"📁 Collection {self.collection_name} does not exist")
                return False

            # Get collection info to check point count
            collection_info = self.qdrant.get_collection(self.collection_name)
            point_count = collection_info.points_count

            if point_count > 0:
                self.logger.info(
                    f"📊 Collection {self.collection_name} exists with {point_count} embeddings"
                )
                return True
            else:
                self.logger.info(
                    f"📁 Collection {self.collection_name} exists but is empty"
                )
                return False

        except Exception as e:
            self.logger.error(f"❌ Error checking collection embeddings: {e}")
            return False

    def _recreate_collection_with_hybrid_structure(self):
        """
        Recreate the collection with proper hybrid vector structure
        """
        try:
            self.logger.info(
                f"🔄 Recreating collection {self.collection_name} with hybrid structure"
            )

            # Delete existing collection if it exists
            if self.qdrant.collection_exists(self.collection_name):
                self.qdrant.delete_collection(self.collection_name)
                self.logger.info(
                    f"🗑️ Deleted existing collection: {self.collection_name}"
                )

            # Create new collection with named dense vector
            self.qdrant.create_collection(
                collection_name=self.collection_name,
                vectors_config={
                    "dense": qmodels.VectorParams(
                        size=1536, distance=qmodels.Distance.COSINE
                    )
                },
            )

            self.logger.info(
                f"✅ Recreated collection {self.collection_name} with hybrid structure"
            )
            return True

        except Exception as e:
            self.logger.error(f"❌ Error recreating collection: {e}")
            return False

    def ensure_qdrant_collection(self):
        """Ensure Qdrant collection exists with error handling"""
        try:
            # Check if collection already exists
            if self.qdrant.collection_exists(self.collection_name):
                self.logger.info(
                    f"📊 Using existing Qdrant collection: {self.collection_name}"
                )
                return

            # Create new collection with named dense vector
            self.logger.info(
                f"🔄 Creating new Qdrant collection: {self.collection_name}"
            )
            self.qdrant.create_collection(
                collection_name=self.collection_name,
                vectors_config={
                    "dense": qmodels.VectorParams(
                        size=1536, distance=qmodels.Distance.COSINE
                    )
                },
            )
            self.logger.info(f"✅ Created Qdrant collection: {self.collection_name}")

        except Exception as e:
            self.logger.error(f"❌ Error ensuring Qdrant collection: {e}")
            raise

    def upsert_pages_to_qdrant(
        self, json_path: str, company_name: str, company_id: str
    ):
        """
        Step 2: Smart upsert - check collection status and handle accordingly
        """
        self.logger.info("🔄 Checking collection status and handling embeddings...")

        try:
            # Load the page data
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            pdf_name = list(data.keys())[0]
            toc_info = None
            if "_metadata" in data[pdf_name]:
                metadata = data[pdf_name]["_metadata"]
                toc_info = {
                    "page_number": metadata.get("toc_page"),
                    "toc_entries": metadata.get("toc_entries", []),
                    "toc_text": metadata.get("toc_text", ""),
                    "toc_entries_count": metadata.get("toc_entries_count", 0),
                }

            # Check collection status
            collection_has_embeddings = self._check_collection_has_embeddings()

            if collection_has_embeddings:
                # Case 1: Collection exists and has embeddings - skip embedding creation
                self.logger.info(
                    "✅ Collection exists with embeddings - skipping embedding creation"
                )
                self.stats["embeddings_created"] = False
                self.stats["embeddings_reused"] = True
                return
            else:
                # Case 2 & 3: Collection doesn't exist or is empty - create embeddings
                self.logger.info("🔄 Creating embeddings for pages...")
                self._create_embeddings_for_pages(
                    data[pdf_name], company_name, toc_info, company_id
                )
                self.stats["embeddings_created"] = True
                self.stats["embeddings_reused"] = False

        except Exception as e:
            self.logger.error(f"❌ Error in smart upsert: {e}")
            self.logger.error(traceback.format_exc())
            raise

    def _create_embeddings_for_pages(
        self,
        pages_data: dict,
        company_name: str,
        toc_info: Optional[dict],
        company_id: str,
    ):
        """
        Create dense embeddings for pages and upsert to Qdrant (no sparse, no facts/queries)
        """
        try:
            # Ensure collection exists with proper structure
            self.ensure_qdrant_collection()

            # Upsert each page
            points = []
            pages_processed = 0

            for page_no, page_info in pages_data.items():
                # Skip metadata
                if page_no == "_metadata":
                    continue

                try:
                    content = page_info.get("page_content", "")
                    if not content.strip():
                        self.logger.debug(f"Skipping empty page {page_no}")
                        continue

                    # Generate dense embedding only
                    dense_vector = self._generate_openai_embedding(content)

                    # Create a valid point ID using UUID
                    point_id = str(
                        uuid.uuid5(uuid.NAMESPACE_DNS, f"{company_name}_{page_no}")
                    )

                    points.append(
                        qmodels.PointStruct(
                            id=point_id,
                            vector={"dense": dense_vector},
                            payload={
                                "company_id": company_id,
                                "company_name": company_name,
                                "page_number_pdf": page_no,
                                "page_content": content,
                                "page_number_drhp": page_info.get(
                                    "page_number_drhp", ""
                                ),
                            },
                        )
                    )
                    pages_processed += 1

                except Exception as e:
                    self.logger.error(f"❌ Error processing page {page_no}: {e}")
                    self.stats["errors"] += 1
                    continue

            if points:
                self.qdrant.upsert(collection_name=self.collection_name, points=points)
                self.logger.info(
                    f"✅ Upserted {len(points)} pages to Qdrant (dense only)"
                )
                self.stats["pages_processed"] = pages_processed
            else:
                self.logger.warning("⚠️ No pages were successfully processed for Qdrant")

        except Exception as e:
            self.logger.error(f"❌ Error creating embeddings: {e}")
            raise

    def build_sophisticated_query(
        self,
        section_name: str,
        topic: str,
        ai_prompt: str = "",
        additional_context: str = "",
    ) -> str:
        """
        Build search query using only topic and section_name for better semantic search
        AI prompt is excluded from search query and will be used only for content analysis
        """
        try:
            # Only use topic and section_name for search query
            search_parts = []
            if section_name and isinstance(section_name, str) and section_name.strip():
                search_parts.append(section_name.strip())
            if topic and isinstance(topic, str) and topic.strip():
                search_parts.append(topic.strip())

            query_txt = " ".join(search_parts)
            self.logger.debug(
                f"🔍 Built search query (topic + section): {query_txt[:100]}..."
            )
            return query_txt
        except Exception as e:
            self.logger.error(f"❌ Error building search query: {e}")
            return f"{section_name} {topic}"

    def get_drhp_content_direct(
        self,
        section_name: str,
        topic: str,
        company_name: str,
        collector: Collector,
    ) -> str:
        """
        Direct DRHP content retrieval using simplified search approach
        Now uses only topic + section_name for search query (AI prompt excluded from search)
        """
        try:
            # Build search query using only topic and section_name
            search_query = f"{section_name} {topic}".strip()
            self.logger.debug(
                f"🔍 Searching with topic + section query: {search_query[:100]}..."
            )

            # Try hybrid search first, fallback to dense search if it fails
            try:
                # Generate hybrid embeddings for the search query
                dense_query_vector = self._generate_openai_embedding(search_query)
                sparse_query_vector = self._generate_sparse_embedding(search_query)

                self.logger.debug(
                    f"📊 Generated embeddings - Dense: {len(dense_query_vector)}, Sparse: {len(sparse_query_vector.indices)}"
                )

                # Use hybrid search with fusion - CORRECTED API USAGE
                results = self.qdrant.query_points(
                    collection_name=self.collection_name,
                    prefetch=[
                        # Sparse leg
                        qmodels.Prefetch(
                            query=sparse_query_vector, using="sparse", limit=50
                        ),
                        # Dense leg
                        qmodels.Prefetch(
                            query=dense_query_vector, using="dense", limit=10
                        ),
                    ],
                    query=qmodels.FusionQuery(fusion=qmodels.Fusion.RRF),
                    query_filter=qmodels.Filter(
                        must=[
                            qmodels.FieldCondition(
                                key="company_name",
                                match=qmodels.MatchValue(value=company_name),
                            )
                        ]
                    ),
                    with_payload=True,
                    limit=5,
                )

                # Handle the response properly - unwrap tuples if needed
                if isinstance(results, tuple):
                    # If results is a tuple, extract the first element
                    results = results[0] if results else []

                self.logger.debug(
                    f"🔍 Hybrid search returned {len(results) if results else 0} results"
                )

            except Exception as hybrid_error:
                self.logger.warning(
                    f"⚠️ Hybrid search failed, trying dense search: {hybrid_error}"
                )
                # Fallback to dense search - CORRECTED API USAGE
                dense_query_vector = self._generate_openai_embedding(search_query)
                results = self.qdrant.query_points(
                    collection_name=self.collection_name,
                    query_vector=dense_query_vector,  # Direct vector, not dict
                    query_filter=qmodels.Filter(
                        must=[
                            qmodels.FieldCondition(
                                key="company_name",
                                match=qmodels.MatchValue(value=company_name),
                            )
                        ]
                    ),
                    with_payload=True,
                    limit=5,
                )

                # Handle the response properly - unwrap tuples if needed
                if isinstance(results, tuple):
                    # If results is a tuple, extract the first element
                    results = results[0] if results else []

                self.logger.debug(
                    f"🔍 Dense search returned {len(results) if results else 0} results"
                )

            # Build content chunks
            chunks = []
            for hit in results:
                # Unwrap the point if it's wrapped in a tuple
                unwrapped_hit = self._unwrap_point(hit)
                if unwrapped_hit and unwrapped_hit.payload:
                    pno = unwrapped_hit.payload["page_number_pdf"]
                    content = unwrapped_hit.payload.get("page_content", "")
                    facts = unwrapped_hit.payload.get("facts", [])
                    queries = unwrapped_hit.payload.get("queries", [])

                    # Combine all content for better context
                    page_content = f"PAGE NUMBER : {pno}\n{content}"
                    if facts:
                        page_content += f"\n\nFACTS:\n" + "\n".join(
                            [f"- {fact}" for fact in facts]
                        )
                    if queries:
                        page_content += f"\n\nQUERIES:\n" + "\n".join(
                            [f"- {query}" for query in queries]
                        )

                    chunks.append(page_content)

            content = "\n\n".join(chunks)
            self.logger.debug(f"📄 Retrieved content length: {len(content)} characters")
            return content

        except Exception as e:
            self.logger.error(f"❌ Error in direct DRHP content retrieval: {e}")
            self.logger.error(f"🔍 Search query was: {search_query[:200]}...")
            return ""

    def get_ai_answer_direct(
        self, drhp_content: str, ai_prompt: str, collector: Collector
    ) -> Tuple[str, List[str]]:
        """
        Direct AI answer generation using the simplified approach
        """
        try:
            # Use the direct retrieval function from BAML
            resp = b.DirectRetrieval(
                ai_prompt, drhp_content, baml_options={"collector": collector}
            )

            # Token bookkeeping
            in_tok = collector.last.usage.input_tokens or 0
            out_tok = collector.last.usage.output_tokens or 0
            with _token_lock:
                self.input_tokens += in_tok
                self.output_tokens += out_tok

            return resp.ai_output, resp.relevant_pages

        except Exception as e:
            self.logger.error(f"❌ Error in direct AI answer generation: {e}")
            return f"Error generating answer: {str(e)}", []

    def process_single_query_simplified(
        self, idx: int, section_name: str, query_info: dict, company_name: str
    ) -> Optional[dict]:
        """
        Process a single query with simplified direct approach
        Now uses topic + section_name for search, AI prompt only for content analysis
        """
        try:
            topic = query_info.get("Topics", "")
            ai_prompt = query_info.get("AI Prompts", "")
            additional_context = query_info.get("Additional Context", "")

            if not ai_prompt:
                self.logger.debug(f"Skipping query without AI prompt: {topic}")
                return None

            # Pick collector for this worker
            collector = self.collectors[idx % len(self.collectors)]

            # Build search query (topic + section_name only)
            search_query = self.build_sophisticated_query(
                section_name, topic, ai_prompt, additional_context
            )

            self.logger.debug(f"🔍 Processing query: {topic}")
            self.logger.debug(f"📝 AI Prompt: {ai_prompt[:100]}...")
            self.logger.debug(
                f"🔗 Search query (topic + section): {search_query[:100]}..."
            )

            # Get DRHP content using direct approach (search query only)
            drhp_content = self.get_drhp_content_direct(
                section_name, topic, company_name, collector
            )

            self.logger.debug(
                f"📄 Retrieved content length: {len(drhp_content)} characters"
            )
            if len(drhp_content) == 0:
                self.logger.warning(f"⚠️ No content retrieved for query: {topic}")

            # Get AI answer using direct retrieval (AI prompt + content)
            answer, relevant_pages = self.get_ai_answer_direct(
                drhp_content, ai_prompt, collector
            )

            return {
                "Topics": topic,
                "AI Prompts": ai_prompt,
                "AI Output": answer,
                "Relevant Pages": relevant_pages,
                "Search Query": search_query,
                "DRHP Content Length": len(drhp_content),
                "Processing Status": "Success",
            }

        except Exception as e:
            self.logger.error(
                f"❌ Error processing query '{query_info.get('Topics', 'Unknown')}': {e}"
            )
            self.stats["errors"] += 1
            return {
                "Topics": query_info.get("Topics", ""),
                "AI Prompts": query_info.get("AI Prompts", ""),
                "AI Output": f"Error: {str(e)}",
                "Relevant Pages": [],
                "Search Query": "",
                "DRHP Content Length": 0,
                "Processing Status": "Error",
                "Error Details": str(e),
            }

    def process_queries_template_parallel(
        self,
        json_path: str,
        company_name: str,
        queries_template_path: str,
        output_path: str,
    ) -> Dict[str, Any]:
        """
        Step 3: Process queries template with parallel processing and sophisticated approach
        """
        self.logger.info(
            f"🔄 Processing queries template with {self.max_workers} parallel workers..."
        )

        try:
            # Debug collection contents first
            self._debug_collection_contents(company_name)

            # Load queries template
            with open(queries_template_path, "r", encoding="utf-8") as f:
                template = json.load(f)

            # Load page data to get TOC info
            with open(json_path, "r", encoding="utf-8") as f:
                page_data = json.load(f)

            pdf_name = list(page_data.keys())[0]
            toc_info = None
            if "_metadata" in page_data[pdf_name]:
                metadata = page_data[pdf_name]["_metadata"]
                toc_info = {
                    "page_number": metadata.get("toc_page"),
                    "toc_entries": metadata.get("toc_entries", []),
                    "toc_text": metadata.get("toc_text", ""),
                    "toc_entries_count": metadata.get("toc_entries_count", 0),
                }

            results = {
                "_metadata": {
                    "company_name": company_name,
                    "toc_info": toc_info,
                    "total_queries_processed": 0,
                    "processing_config": {
                        "max_workers": self.max_workers,
                        "collection_name": self.collection_name,
                    },
                    "processing_stats": self.stats,
                    "processing_timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                }
            }

            # Prepare all queries for parallel processing
            all_queries = []
            for section_name, queries in template.items():
                for query_info in queries:
                    all_queries.append((section_name, query_info))

            self.logger.info(f"📋 Total queries to process: {len(all_queries)}")

            # Process queries in parallel
            with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
                futures = [
                    pool.submit(
                        self.process_single_query_simplified,  # Use simplified approach
                        idx,
                        section_name,
                        query_info,
                        company_name,
                    )
                    for idx, (section_name, query_info) in enumerate(all_queries)
                ]

                # Collect results
                for future in as_completed(futures):
                    try:
                        result = future.result()
                        if result:
                            # Find the section for this result
                            for section_name, queries in template.items():
                                for query_info in queries:
                                    if (
                                        query_info.get("Topics") == result["Topics"]
                                        and query_info.get("AI Prompts")
                                        == result["AI Prompts"]
                                    ):
                                        if section_name not in results:
                                            results[section_name] = []
                                        results[section_name].append(result)
                                        results["_metadata"][
                                            "total_queries_processed"
                                        ] += 1
                                        break
                    except Exception as e:
                        self.logger.error(f"❌ Error collecting parallel result: {e}")
                        self.stats["errors"] += 1

            # Save results
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(results, f, indent=2, ensure_ascii=False)

            self.logger.info(f"✅ Results saved to: {output_path}")
            self.logger.info(
                f"📊 Total queries processed: {results['_metadata']['total_queries_processed']}"
            )
            self.logger.info(
                f"💾 Total tokens used - Input: {self.input_tokens}, Output: {self.output_tokens}"
            )

            return results

        except Exception as e:
            self.logger.error(f"❌ Error in parallel query processing: {e}")
            self.logger.error(traceback.format_exc())
            raise

    def _unwrap_point(self, obj: Any) -> Optional[qmodels.ScoredPoint]:
        """
        Recursively unwraps nested tuples to find a ScoredPoint object.

        The Qdrant client can sometimes return points wrapped in layers of tuples,
        e.g., ((ScoredPoint(...),),). This function safely navigates these
        structures to extract the core search result.
        """
        while isinstance(obj, tuple):
            if not obj:  # Handle empty tuple
                return None
            obj = obj[0]

        # After unwrapping, check if it's a ScoredPoint
        if isinstance(obj, qmodels.ScoredPoint):
            return obj

        return None

    def _find_existing_json(self, company_name: str) -> Optional[str]:
        """
        Check if JSON file already exists for the company
        Returns the path to existing JSON file or None if not found
        """
        try:
            base_dir = os.path.join(os.getcwd(), company_name, "temp_pages_json")
            if not os.path.exists(base_dir):
                self.logger.info(
                    f"📁 No existing temp_pages_json directory found for {company_name}"
                )
                return None

            json_files = [f for f in os.listdir(base_dir) if f.endswith("_pages.json")]
            if not json_files:
                self.logger.info(f"📁 No existing JSON files found in {base_dir}")
                return None

            # Use the first JSON file found
            json_path = os.path.join(base_dir, json_files[0])
            self.logger.info(f"📁 Found existing JSON file: {json_path}")

            # Validate that the JSON file is readable and has content
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if not data:
                    self.logger.warning(f"⚠️ Existing JSON file is empty: {json_path}")
                    return None

                # Check if it has the expected structure
                pdf_name = list(data.keys())[0]
                if (
                    not data[pdf_name] or len(data[pdf_name]) < 2
                ):  # At least 1 page + metadata
                    self.logger.warning(
                        f"⚠️ Existing JSON file has insufficient data: {json_path}"
                    )
                    return None

            self.logger.info(
                f"✅ Using existing JSON file with {len(data[pdf_name])} pages"
            )
            return json_path

        except Exception as e:
            self.logger.error(f"❌ Error checking existing JSON: {e}")
            return None

    def process_drhp_complete(
        self,
        pdf_path: str,
        company_name: str,
        queries_template_path: str,
        output_path: str = None,
        force_reprocess: bool = False,
    ) -> Dict[str, Any]:
        """
        Complete DRHP processing pipeline with enhanced parallel processing and comprehensive error handling
        """
        self.logger.info(f"🚀 Starting complete DRHP processing for: {company_name}")

        try:
            # Reset token counters and stats
            self.input_tokens = 0
            self.output_tokens = 0
            self.stats = {
                "pages_processed": 0,
                "queries_processed": 0,
                "errors": 0,
                "start_time": time.time(),
                "end_time": None,
                "embeddings_created": False,
                "embeddings_reused": False,
            }

            # Check if JSON file already exists
            existing_json_path = self._find_existing_json(company_name)

            if existing_json_path and not force_reprocess:
                self.logger.info(
                    "📁 Using existing JSON file - skipping PDF processing"
                )
                json_path = existing_json_path
                self.stats["pdf_processing_skipped"] = True
            else:
                self.logger.info("📄 No existing JSON found - starting PDF processing")
                # Step 1: Process PDF locally (includes TOC detection)
                json_path = self.process_pdf_locally(pdf_path, company_name)
                self.stats["pdf_processing_skipped"] = False

            # Step 2: Upsert to Qdrant
            self.upsert_pages_to_qdrant(json_path, company_name, company_name)

            # Step 3: Process queries template with parallel processing
            if output_path is None:
                output_path = os.path.join(
                    os.getcwd(), company_name, f"{company_name}_results.json"
                )

            results = self.process_queries_template_parallel(
                json_path, company_name, queries_template_path, output_path
            )

            # Update final stats
            self.stats["end_time"] = time.time()
            self.stats["total_processing_time"] = (
                self.stats["end_time"] - self.stats["start_time"]
            )
            results["_metadata"]["processing_stats"] = self.stats

            self.logger.info("🎉 Complete DRHP processing finished!")
            return results

        except Exception as e:
            self.logger.error(f"❌ Error in complete DRHP processing: {e}")
            self.logger.error(traceback.format_exc())
            raise

    def _debug_collection_contents(self, company_name: str):
        """
        Debug function to check what's actually in the collection
        """
        try:
            self.logger.info(f"🔍 Debugging collection contents for {company_name}...")

            # Check collection info
            collection_info = self.qdrant.get_collection(self.collection_name)
            self.logger.info(
                f"📊 Collection points count: {collection_info.points_count}"
            )

            if collection_info.points_count == 0:
                self.logger.error("❌ Collection is empty!")
                return

            # Get a few sample points using scroll with correct parameters
            sample_points = self.qdrant.scroll(
                collection_name=self.collection_name,
                scroll_filter=qmodels.Filter(
                    must=[
                        qmodels.FieldCondition(
                            key="company_name",
                            match=qmodels.MatchValue(value=company_name),
                        )
                    ]
                ),
                with_payload=True,
                limit=3,
            )[
                0
            ]  # scroll returns (points, next_page_offset)

            self.logger.info(
                f"📄 Found {len(sample_points)} sample points for {company_name}"
            )

            for i, point in enumerate(sample_points):
                self.logger.info(f"📋 Sample point {i+1}:")
                self.logger.info(
                    f"   - Page number: {point.payload.get('page_number_pdf', 'N/A')}"
                )
                self.logger.info(
                    f"   - Content length: {len(point.payload.get('page_content', ''))}"
                )
                self.logger.info(
                    f"   - Facts count: {len(point.payload.get('facts', []))}"
                )
                self.logger.info(
                    f"   - Queries count: {len(point.payload.get('queries', []))}"
                )

        except Exception as e:
            self.logger.error(f"❌ Error debugging collection: {e}")


def main():
    """
    Main function with all inputs configured directly in the code
    """
    try:
        print("🚀 Starting Local DRHP Processor")
        print("=" * 60)

        # ========================================
        # CONFIGURATION - SET YOUR VALUES HERE
        # ========================================

        # PDF file path
        PDF_PATH = r"C:\Users\himan\Downloads\Documents\Wakefit Innovations Limited-DRHP-1750993585.pdf"  # CHANGE THIS

        # Company name
        COMPANY_NAME = "Wakefit Innovations Limited"  # CHANGE THIS

        # Queries template JSON file
        QUERIES_TEMPLATE_PATH = os.path.join(
            os.path.dirname(__file__), "notes_json_template.json"
        )  # CHANGE THIS

        # Qdrant configuration
        QDRANT_URL = os.getenv(
            "QDRANT_URL", "http://localhost:6333"
        )  # CHANGE IF NEEDED
        QDRANT_COLLECTION = "drhp_notes_Wakefit Innovations Limited"  # CHANGE IF NEEDED

        # Processing configuration
        MAX_WORKERS = 5  # CHANGE THIS (recommended: 5-10)

        # Force reprocessing (set to True to regenerate JSON even if it exists)
        FORCE_REPROCESS = False  # CHANGE THIS if you want to reprocess PDF

        # Output path (optional - will auto-generate if None)
        OUTPUT_PATH = None  # Will be: ./{COMPANY_NAME}/{COMPANY_NAME}_results.json

        # ========================================
        # VALIDATION
        # ========================================

        print("📋 Validating inputs...")

        # Check if PDF exists
        if not os.path.exists(PDF_PATH):
            raise FileNotFoundError(f"PDF file not found: {PDF_PATH}")

        # Check if queries template exists
        if not os.path.exists(QUERIES_TEMPLATE_PATH):
            raise FileNotFoundError(
                f"Queries template not found: {QUERIES_TEMPLATE_PATH}"
            )

        # Validate company name
        if not COMPANY_NAME or not COMPANY_NAME.strip():
            raise ValueError("Company name cannot be empty")

        # Validate max workers
        if MAX_WORKERS < 1 or MAX_WORKERS > 20:
            raise ValueError("MAX_WORKERS must be between 1 and 20")

        # Check required environment variables
        if not os.getenv("OPENAI_API_KEY"):
            raise ValueError("OPENAI_API_KEY environment variable is required")

        if not os.getenv("SPARSE_EMBEDDING_URL"):
            print(
                "⚠️ SPARSE_EMBEDDING_URL not set, using default: http://52.7.81.94:8010/embed"
            )

        print("✅ All inputs validated successfully")

        # ========================================
        # PROCESSING
        # ========================================

        print(f"📄 PDF Path: {PDF_PATH}")
        print(f"🏢 Company: {COMPANY_NAME}")
        print(f"📋 Queries Template: {QUERIES_TEMPLATE_PATH}")
        print(f"🔧 Max Workers: {MAX_WORKERS}")
        print(f"🔄 Force Reprocess: {FORCE_REPROCESS}")
        print(f"🗄️ Qdrant URL: {QDRANT_URL}")
        print(f"📊 Qdrant Collection: {QDRANT_COLLECTION}")
        print("=" * 60)

        # Initialize processor
        processor = LocalDRHPProcessor(
            qdrant_url=QDRANT_URL,
            collection_name=QDRANT_COLLECTION,
            max_workers=MAX_WORKERS,
            company_name=COMPANY_NAME,
        )

        # Process DRHP
        results = processor.process_drhp_complete(
            pdf_path=PDF_PATH,
            company_name=COMPANY_NAME,
            queries_template_path=QUERIES_TEMPLATE_PATH,
            output_path=OUTPUT_PATH,
            force_reprocess=FORCE_REPROCESS,
        )

        # ========================================
        # RESULTS
        # ========================================

        final_output_path = OUTPUT_PATH or os.path.join(
            os.getcwd(), COMPANY_NAME, f"{COMPANY_NAME}_results.json"
        )

        print("\n" + "=" * 60)
        print("🎉 DRHP PROCESSING COMPLETED SUCCESSFULLY!")
        print("=" * 60)
        print(f"📄 PDF Processed: {PDF_PATH}")
        print(f"🏢 Company: {COMPANY_NAME}")
        print(f"📊 Results: {final_output_path}")
        print(f"🔧 Workers Used: {MAX_WORKERS}")
        print(
            f"📈 Queries Processed: {results['_metadata']['total_queries_processed']}"
        )
        print(f"📄 Pages Processed: {processor.stats['pages_processed']}")
        print(f"❌ Errors: {processor.stats['errors']}")
        print(
            f"⏱️ Processing Time: {processor.stats.get('total_processing_time', 0):.2f} seconds"
        )
        print(
            f"💾 Tokens Used: {processor.input_tokens} input, {processor.output_tokens} output"
        )
        if processor.stats.get("pdf_processing_skipped", False):
            print("📁 PDF Processing: Skipped (used existing JSON)")
        else:
            print("📄 PDF Processing: Completed (processed from scratch)")

        if processor.stats.get("embeddings_reused", False):
            print("🔍 Embeddings: Reused existing (no creation needed)")
        elif processor.stats.get("embeddings_created", False):
            print("🔍 Embeddings: Created new (collection was empty)")
        else:
            print("🔍 Embeddings: Status unknown")
        print("=" * 60)

    except FileNotFoundError as e:
        print(f"\n❌ ERROR: File not found - {e}")
        print("Please check the file paths in the configuration section.")
        return 1

    except ValueError as e:
        print(f"\n❌ ERROR: Invalid configuration - {e}")
        print("Please check the configuration values in the main function.")
        return 1

    except Exception as e:
        print(f"\n❌ ERROR: Unexpected error - {e}")
        print("Check the log files in the 'logs' directory for details.")
        return 1

    return 0


if __name__ == "__main__":
    exit_code = main()
    exit(exit_code)
