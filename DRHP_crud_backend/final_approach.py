#!/usr/bin/env python3
"""
PDF to Qdrant Processor - Final Approach
========================================

This script provides a complete pipeline to:
1. Process PDF/DRHP files and extract structured JSON data
2. Generate hybrid embeddings (dense + sparse)
3. Upsert data into Qdrant vector database
4. Handle TOC detection and extraction

Features:
- Hybrid embeddings:
  * Dense embeddings (OpenAI): Page content only (semantic understanding)
  * Sparse embeddings (SPLADE): Facts + queries only (keyword matching)
- TOC content extraction and storage
- Parallel processing for efficiency
- Comprehensive error handling and logging
- Reusable JSON processing (skip PDF if JSON exists)
"""

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
import boto3

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


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
class Config:
    """Configuration class for the processor"""

    # Qdrant settings
    QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
    COLLECTION_NAME = "drhp_notes_testing"

    # OpenAI settings
    OPENAI_MODEL = "text-embedding-3-small"
    DENSE_VECTOR_SIZE = 1536

    # SPLADE settings
    SPARSE_EMBEDDING_URL = os.getenv(
        "SPARSE_EMBEDDING_URL", "http://52.7.81.94:8010/embed"
    )

    # AWS Bedrock settings
    AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
    BEDROCK_MODEL = os.getenv(
        "BEDROCK_MODEL", "anthropic.claude-3-sonnet-20240229-v1:0"
    )

    # Processing settings
    MAX_WORKERS = 5
    DPI = 200
    THRESHOLD = 245
    MAX_PAGES_TO_CHECK_TOC = 20

    # Batch settings
    QDRANT_BATCH_SIZE = 50


# ---------------------------------------------------------------------------
# Logging Setup
# ---------------------------------------------------------------------------
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

    logger = logging.getLogger(f"PDF_Processor_{company_name}")
    logger.setLevel(logging.INFO)

    return logger


# ---------------------------------------------------------------------------
# Main Processor Class
# ---------------------------------------------------------------------------
class PDFToQdrantProcessor:
    """
    Main processor class for converting PDF/DRHP files to Qdrant vectors
    """

    def __init__(self, company_name: str, collection_name: str = None):
        """
        Initialize the processor

        Args:
            company_name: Name of the company for logging and organization
            collection_name: Qdrant collection name (optional)
        """
        self.company_name = company_name
        self.collection_name = collection_name or Config.COLLECTION_NAME

        # Setup logging
        self.logger = setup_logging(company_name)

        # Initialize clients
        self._init_clients()

        # Processing statistics
        self.stats = {
            "pages_processed": 0,
            "embeddings_created": 0,
            "errors": 0,
            "start_time": None,
            "end_time": None,
            "toc_detected": False,
            "toc_page": None,
            "toc_entries": [],
        }

        self.logger.info(f"🚀 Initialized PDF to Qdrant processor for {company_name}")

    def _init_clients(self):
        """Initialize all required clients"""
        try:
            # Qdrant client
            self.qdrant = QdrantClient(url=Config.QDRANT_URL, timeout=60)
            self.logger.info(f"✅ Connected to Qdrant at {Config.QDRANT_URL}")

            # OpenAI client
            self.openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
            self.logger.info("✅ Initialized OpenAI client")

            # AWS Bedrock client
            self.bedrock_client = boto3.client(
                "bedrock-runtime", region_name=Config.AWS_REGION
            )
            self.logger.info(
                f"✅ Initialized AWS Bedrock client for region {Config.AWS_REGION}"
            )

        except Exception as e:
            self.logger.error(f"❌ Failed to initialize clients: {e}")
            raise

    def _generate_openai_embedding(self, text: str) -> List[float]:
        """Generate dense embedding using OpenAI"""
        try:
            response = self.openai_client.embeddings.create(
                model=Config.OPENAI_MODEL, input=text
            )
            return response.data[0].embedding
        except Exception as e:
            self.logger.error(f"❌ Error generating OpenAI embedding: {e}")
            raise

    def _generate_sparse_embedding(self, text: str) -> qmodels.SparseVector:
        """Generate sparse embedding using SPLADE service"""
        try:
            response = requests.post(
                Config.SPARSE_EMBEDDING_URL, json={"text": text}, timeout=10
            )
            response.raise_for_status()
            sparse_dict = response.json() or {}

            if sparse_dict:
                indices = [int(k) for k in sparse_dict.keys()]
                values = [float(v) for v in sparse_dict.values()]
                return qmodels.SparseVector(indices=indices, values=values)
            else:
                return qmodels.SparseVector(indices=[], values=[])

        except Exception as e:
            self.logger.error(f"❌ Error generating sparse embedding: {e}")
            return qmodels.SparseVector(indices=[], values=[])

    def _combine_facts_and_queries(self, page_info: dict) -> str:
        """Combine only facts and queries for sparse embedding"""
        parts = []

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

        Strategy:
        - Dense embedding: Uses page content only (for semantic understanding)
        - Sparse embedding: Uses facts + queries only (for keyword matching)

        Args:
            page_info: Dictionary containing page data with 'page_content', 'facts', 'queries'

        Returns:
            Tuple of (dense_vector, sparse_vector)
        """
        # Generate dense embedding for page content only (semantic understanding)
        dense_text = page_info.get("page_content", "")
        dense_vector = self._generate_openai_embedding(dense_text)

        # Generate sparse embedding for facts + queries only (keyword matching)
        facts_queries_text = self._combine_facts_and_queries(page_info)
        sparse_vector = self._generate_sparse_embedding(facts_queries_text)

        return dense_vector, sparse_vector

    def _generate_llm_answer(self, prompt: str, context: str) -> str:
        """
        Generate answer using AWS Bedrock LLM

        Args:
            prompt: The AI prompt from template
            context: Concatenated page content

        Returns:
            Generated answer from LLM
        """
        try:
            # Prepare the full prompt with context
            full_prompt = f"""Context from DRHP document:
{context}

{prompt}

Please provide a comprehensive answer based on the context above."""

            # Prepare request body for Bedrock
            request_body = {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 4000,
                "messages": [{"role": "user", "content": full_prompt}],
            }

            # Make request to Bedrock
            response = self.bedrock_client.invoke_model(
                modelId=Config.BEDROCK_MODEL, body=json.dumps(request_body)
            )

            # Parse response
            response_body = json.loads(response["body"].read())
            answer = response_body["content"][0]["text"]

            return answer

        except Exception as e:
            self.logger.error(f"❌ Error generating LLM answer: {e}")
            return f"Error generating answer: {str(e)}"

    def pdf_page_to_cv2_image(
        self, pdf_path: str, page_num: int, dpi: int = 200
    ) -> np.ndarray:
        """Convert PDF page to cv2 image"""
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
        """Convert cv2 image to bytes"""
        try:
            success, buf = cv2.imencode(".png", cv2_img)
            if not success:
                raise ValueError("Failed to encode image")
            return buf.tobytes()
        except Exception as e:
            self.logger.error(f"Error converting image to bytes: {e}")
            raise

    def detect_toc_page(
        self, pdf_path: str, max_pages_to_check: int = 20
    ) -> Optional[dict]:
        """
        Detect Table of Contents page and extract TOC content
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

    def process_pdf_to_json(self, pdf_path: str, force_reprocess: bool = False) -> str:
        """
        Process PDF and extract JSON data
        Returns path to the JSON file
        """
        self.logger.info(f"📄 Starting PDF processing: {pdf_path}")
        self.stats["start_time"] = time.time()

        try:
            # Check if JSON already exists
            existing_json_path = self._find_existing_json()
            if existing_json_path and not force_reprocess:
                self.logger.info(
                    "📁 Using existing JSON file - skipping PDF processing"
                )
                return existing_json_path

            # Detect TOC page first
            toc_page = self.detect_toc_page(pdf_path, Config.MAX_PAGES_TO_CHECK_TOC)

            # Update stats
            if toc_page:
                self.stats["toc_detected"] = True
                self.stats["toc_page"] = toc_page["page_number"]
                self.stats["toc_entries"] = toc_page["toc_entries"]

            # Process PDF pages
            self.logger.info("🔄 Processing PDF pages...")
            total_in, total_out = process_pdf_local(
                pdf_path=pdf_path,
                company_name=self.company_name,
                dpi=Config.DPI,
                threshold=Config.THRESHOLD,
                max_workers=Config.MAX_WORKERS,
            )

            self.logger.info(
                f"✅ PDF processing complete. Tokens - in: {total_in}, out: {total_out}"
            )

            # Find the output JSON file
            json_path = self._find_output_json()
            if not json_path:
                raise FileNotFoundError("No output JSON found")

            # Add TOC information to the JSON
            self.add_toc_to_json(json_path, toc_page)

            return json_path

        except Exception as e:
            self.logger.error(f"❌ Error in PDF processing: {e}")
            self.logger.error(traceback.format_exc())
            raise

    def _find_existing_json(self) -> Optional[str]:
        """Check if JSON file already exists"""
        try:
            base_dir = os.path.join(os.getcwd(), self.company_name, "temp_pages_json")
            if not os.path.exists(base_dir):
                return None

            json_files = [f for f in os.listdir(base_dir) if f.endswith("_pages.json")]
            if not json_files:
                return None

            json_path = os.path.join(base_dir, json_files[0])

            # Validate JSON file
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if not data:
                    return None

            self.logger.info(f"📁 Found existing JSON file: {json_path}")
            return json_path

        except Exception as e:
            self.logger.error(f"❌ Error checking existing JSON: {e}")
            return None

    def _find_output_json(self) -> Optional[str]:
        """Find the output JSON file after processing"""
        try:
            base_dir = os.path.join(os.getcwd(), self.company_name, "temp_pages_json")
            if not os.path.exists(base_dir):
                raise FileNotFoundError(f"Output directory not found: {base_dir}")

            json_files = [f for f in os.listdir(base_dir) if f.endswith("_pages.json")]
            if not json_files:
                raise FileNotFoundError(
                    "No output JSON found in temp_pages_json directory"
                )

            json_path = os.path.join(base_dir, json_files[0])
            self.logger.info(f"📁 Found output JSON: {json_path}")
            return json_path

        except Exception as e:
            self.logger.error(f"❌ Error finding output JSON: {e}")
            return None

    def add_toc_to_json(self, json_path: str, toc_page: Optional[dict]):
        """Add TOC information to the JSON file"""
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

    def ensure_qdrant_collection(self):
        """Ensure Qdrant collection exists with proper structure"""
        try:
            # Check if collection already exists
            if self.qdrant.collection_exists(self.collection_name):
                self.logger.info(
                    f"📊 Using existing Qdrant collection: {self.collection_name}"
                )
                return

            # Create new collection with hybrid vectors
            self.logger.info(
                f"🔄 Creating new Qdrant collection: {self.collection_name}"
            )
            self.qdrant.create_collection(
                collection_name=self.collection_name,
                vectors_config={
                    "dense": qmodels.VectorParams(
                        size=Config.DENSE_VECTOR_SIZE, distance=qmodels.Distance.COSINE
                    )
                },
                sparse_vectors_config={
                    "sparse": qmodels.SparseVectorParams(
                        index=qmodels.SparseIndexParams()
                    )
                },
            )
            self.logger.info(f"✅ Created Qdrant collection: {self.collection_name}")

        except Exception as e:
            self.logger.error(f"❌ Error ensuring Qdrant collection: {e}")
            raise

    def _collection_has_embeddings(self) -> bool:
        """Check if the collection exists and has embeddings (points)"""
        try:
            if not self.qdrant.collection_exists(self.collection_name):
                return False
            info = self.qdrant.get_collection(self.collection_name)
            return getattr(info, "points_count", 0) > 0
        except Exception as e:
            self.logger.error(f"Error checking collection embeddings: {e}")
            return False

    def upsert_json_to_qdrant(self, json_path: str):
        """
        Upsert JSON data to Qdrant with hybrid embeddings, only if needed.
        """
        self.logger.info("🔄 Checking collection status and handling embeddings...")

        try:
            # Check collection/embedding status
            collection_exists = self.qdrant.collection_exists(self.collection_name)
            has_embeddings = self._collection_has_embeddings()

            if collection_exists and has_embeddings:
                self.logger.info(
                    "✅ Collection exists and has embeddings - skipping embedding creation/upsert."
                )
                return
            elif collection_exists and not has_embeddings:
                self.logger.info(
                    "📁 Collection exists but is empty - will create embeddings and upsert."
                )
                self.ensure_qdrant_collection()  # Ensure structure is correct
            else:
                self.logger.info(
                    "📁 Collection does not exist - will create collection, embeddings, and upsert."
                )
                self.ensure_qdrant_collection()

            # Load JSON data
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            pdf_name = list(data.keys())[0]
            pages_data = data[pdf_name]

            # Get TOC info from metadata
            toc_info = None
            if "_metadata" in pages_data:
                metadata = pages_data["_metadata"]
                toc_info = {
                    "page_number": metadata.get("toc_page"),
                    "toc_entries": metadata.get("toc_entries", []),
                    "toc_text": metadata.get("toc_text", ""),
                }

            # Process pages in batches
            all_points = []
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

                    # Generate hybrid embeddings
                    dense_vector, sparse_vector = self._generate_hybrid_embeddings(
                        page_info
                    )

                    # Create point ID
                    point_id = str(
                        uuid.uuid5(uuid.NAMESPACE_DNS, f"{self.company_name}_{page_no}")
                    )

                    # Create point
                    point = qmodels.PointStruct(
                        id=point_id,
                        vector={"dense": dense_vector, "sparse": sparse_vector},
                        payload={
                            "company_name": self.company_name,
                            "page_number_pdf": page_no,
                            "page_content": content,
                            "page_number_drhp": page_info.get("page_number_drhp", ""),
                            "facts": page_info.get("facts", []),
                            "queries": page_info.get("queries", []),
                            "is_toc_page": (
                                toc_info is not None
                                and int(page_no) == toc_info.get("page_number")
                            ),
                        },
                    )

                    all_points.append(point)
                    pages_processed += 1

                except Exception as e:
                    self.logger.error(f"❌ Error processing page {page_no}: {e}")
                    self.stats["errors"] += 1
                    continue

            # Upsert points in batches
            if all_points:
                self.logger.info(
                    f"📊 Upserting {len(all_points)} points in batches of {Config.QDRANT_BATCH_SIZE}"
                )

                for i in range(0, len(all_points), Config.QDRANT_BATCH_SIZE):
                    batch = all_points[i : i + Config.QDRANT_BATCH_SIZE]
                    self.qdrant.upsert(
                        collection_name=self.collection_name, points=batch
                    )
                    self.logger.info(
                        f"✅ Upserted batch {i//Config.QDRANT_BATCH_SIZE + 1}/{(len(all_points) + Config.QDRANT_BATCH_SIZE - 1)//Config.QDRANT_BATCH_SIZE}"
                    )

                self.stats["pages_processed"] = pages_processed
                self.stats["embeddings_created"] = len(all_points)

                if toc_info:
                    self.logger.info(
                        f"✅ TOC page {toc_info['page_number']} marked in Qdrant"
                    )
            else:
                self.logger.warning("⚠️ No pages were successfully processed for Qdrant")

        except Exception as e:
            self.logger.error(f"❌ Error upserting to Qdrant: {e}")
            raise

    def process_complete(
        self, pdf_path: str, force_reprocess: bool = False
    ) -> Dict[str, Any]:
        """
        Complete processing pipeline: PDF → JSON → Qdrant
        """
        self.logger.info(f"🚀 Starting complete processing for: {self.company_name}")

        try:
            # Step 1: Process PDF to JSON
            json_path = self.process_pdf_to_json(pdf_path, force_reprocess)

            # Step 2: Upsert to Qdrant
            self.upsert_json_to_qdrant(json_path)

            # Update final stats
            self.stats["end_time"] = time.time()
            self.stats["total_processing_time"] = (
                self.stats["end_time"] - self.stats["start_time"]
            )

            # Return results
            results = {
                "company_name": self.company_name,
                "collection_name": self.collection_name,
                "json_path": json_path,
                "stats": self.stats,
                "status": "success",
            }

            self.logger.info("🎉 Complete processing finished!")
            self._print_summary(results)

            return results

        except Exception as e:
            self.logger.error(f"❌ Error in complete processing: {e}")
            self.logger.error(traceback.format_exc())
            raise

    def _print_summary(self, results: Dict[str, Any]):
        """Print processing summary"""
        stats = results["stats"]

        print("\n" + "=" * 60)
        print("🎉 PDF TO QDRANT PROCESSING COMPLETED!")
        print("=" * 60)
        print(f"🏢 Company: {self.company_name}")
        print(f"📊 Collection: {self.collection_name}")
        print(f"📄 JSON Path: {results['json_path']}")
        print(f"📈 Pages Processed: {stats['pages_processed']}")
        print(f"🔍 Embeddings Created: {stats['embeddings_created']}")
        print(f"❌ Errors: {stats['errors']}")
        print(f"⏱️ Processing Time: {stats.get('total_processing_time', 0):.2f} seconds")

        if stats.get("toc_detected", False):
            print(f"📋 TOC Page: {stats['toc_page']}")
            print(f"📋 TOC Entries: {len(stats['toc_entries'])}")
        else:
            print("📋 TOC: Not detected")

        print("=" * 60)


# ---------------------------------------------------------------------------
# Search System
# ---------------------------------------------------------------------------
class DRHPSearcher:
    """
    Search system for DRHP documents using template-based queries
    """

    def __init__(self, collection_name: str, company_name: str):
        """
        Initialize the searcher

        Args:
            collection_name: Qdrant collection name
            company_name: Company name for vector naming
        """
        self.collection_name = collection_name
        self.company_name = company_name

        # Setup logging
        self.logger = setup_logging(f"{company_name}_searcher")

        # Initialize clients
        self._init_clients()

        # Vector names
        self.dense_vector_name = "dense"
        self.sparse_vector_name = "sparse"

    def _init_clients(self):
        """Initialize required clients for search"""
        try:
            # Qdrant client
            self.qdrant = QdrantClient(url=Config.QDRANT_URL, timeout=60)
            self.logger.info(f"✅ Connected to Qdrant at {Config.QDRANT_URL}")

            # OpenAI client for dense embeddings
            self.openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
            self.logger.info("✅ Initialized OpenAI client")

            # AWS Bedrock client for LLM
            self.bedrock_client = boto3.client(
                "bedrock-runtime", region_name=Config.AWS_REGION
            )
            self.logger.info(
                f"✅ Initialized AWS Bedrock client for region {Config.AWS_REGION}"
            )

        except Exception as e:
            self.logger.error(f"❌ Failed to initialize search clients: {e}")
            raise

    def _generate_dense_embedding(self, text: str) -> List[float]:
        """Generate dense embedding using OpenAI"""
        try:
            response = self.openai_client.embeddings.create(
                model=Config.OPENAI_MODEL, input=text
            )
            return response.data[0].embedding
        except Exception as e:
            self.logger.error(f"❌ Error generating dense embedding: {e}")
            return [0.0] * Config.DENSE_VECTOR_SIZE

    def _generate_sparse_embedding(self, text: str) -> qmodels.SparseVector:
        """Generate sparse embedding using SPLADE service"""
        try:
            response = requests.post(
                Config.SPARSE_EMBEDDING_URL, json={"text": text}, timeout=10
            )
            response.raise_for_status()
            sparse_dict = response.json() or {}

            if sparse_dict:
                indices = [int(k) for k in sparse_dict.keys()]
                values = [float(v) for v in sparse_dict.values()]
                return qmodels.SparseVector(indices=indices, values=values)
            else:
                return qmodels.SparseVector(indices=[], values=[])

        except Exception as e:
            self.logger.error(f"❌ Error generating sparse embedding: {e}")
            return qmodels.SparseVector(indices=[], values=[])

    def _generate_llm_answer(self, prompt: str, context: str) -> str:
        """
        Generate answer using AWS Bedrock LLM

        Args:
            prompt: The AI prompt from template
            context: Concatenated page content

        Returns:
            Generated answer from LLM
        """
        try:
            # Prepare the full prompt with context
            full_prompt = f"""Context from DRHP document:
{context}

{prompt}

Please provide a comprehensive answer based on the context above."""

            # Prepare request body for Bedrock
            request_body = {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 4000,
                "messages": [{"role": "user", "content": full_prompt}],
            }

            # Make request to Bedrock
            response = self.bedrock_client.invoke_model(
                modelId=Config.BEDROCK_MODEL, body=json.dumps(request_body)
            )

            # Parse response
            response_body = json.loads(response["body"].read())
            answer = response_body["content"][0]["text"]

            return answer

        except Exception as e:
            self.logger.error(f"❌ Error generating LLM answer: {e}")
            return f"Error generating answer: {str(e)}"

    def _unwrap_point(self, obj: Any) -> Optional[qmodels.ScoredPoint]:
        """
        Recursively unwraps nested tuples to find a ScoredPoint object.
        """
        while isinstance(obj, tuple):
            if not obj:  # Handle empty tuple
                return None
            obj = obj[0]

        # After unwrapping, check if it's a ScoredPoint
        if isinstance(obj, qmodels.ScoredPoint):
            return obj

        return None

    def hybrid_search(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """
        Perform hybrid search using dense and sparse embeddings with RRF fusion

        Args:
            query: Search query string
            limit: Number of results to return

        Returns:
            List of search results with page content and metadata
        """
        try:
            self.logger.info(f"🔍 Searching for: '{query[:50]}...'")

            # Generate embeddings
            dense_vec = self._generate_dense_embedding(query)
            sparse_vec = self._generate_sparse_embedding(query)

            # Perform hybrid search with RRF fusion
            results = self.qdrant.query_points(
                collection_name=self.collection_name,
                prefetch=[
                    qmodels.Prefetch(
                        query=sparse_vec, using=self.sparse_vector_name, limit=50
                    ),
                    qmodels.Prefetch(
                        query=dense_vec, using=self.dense_vector_name, limit=limit
                    ),
                ],
                query=qmodels.FusionQuery(fusion=qmodels.Fusion.RRF),
                with_payload=True,
                limit=limit,
            )

            # Unwrap results
            if isinstance(results, tuple):
                results = results[0]

            # Process and format results
            formatted_results = []
            for point in results:
                unwrapped_point = self._unwrap_point(point)
                if unwrapped_point and unwrapped_point.payload:
                    formatted_results.append(
                        {
                            "page_num": unwrapped_point.payload.get("page_number_pdf"),
                            "pdf_page_num": unwrapped_point.payload.get(
                                "page_number_pdf"
                            ),
                            "drhp_page_num": unwrapped_point.payload.get(
                                "page_number_drhp", ""
                            ),
                            "content": unwrapped_point.payload.get("page_content", ""),
                            "facts": unwrapped_point.payload.get("facts", []),
                            "queries": unwrapped_point.payload.get("queries", []),
                            "score": unwrapped_point.score,
                            "is_toc": unwrapped_point.payload.get("is_toc_page", False),
                        }
                    )

            self.logger.info(f"✅ Found {len(formatted_results)} results")
            return formatted_results

        except Exception as e:
            self.logger.error(f"❌ Search failed: {e}")
            return []

    def search_with_template(self, template_path: str) -> Dict[str, Any]:
        """
        Search using the provided template JSON file

        Args:
            template_path: Path to the template JSON file

        Returns:
            Dictionary with search results organized by section and topic
        """
        try:
            # Load template
            with open(template_path, "r", encoding="utf-8") as f:
                template = json.load(f)

            self.logger.info(f"📋 Loaded template with {len(template)} sections")

            # Initialize results structure
            search_results = {
                "company_name": self.company_name,
                "collection_name": self.collection_name,
                "search_timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "sections": {},
            }

            # Process each section
            for section_name, queries in template.items():
                self.logger.info(f"🔍 Processing section: {section_name}")
                search_results["sections"][section_name] = {}

                # Process each query in the section
                for query_info in queries:
                    topic = query_info.get("Topics", "Unknown")
                    search_query = query_info.get("Search Query", "")
                    ai_prompt = query_info.get("AI Prompts", "")
                    expected_output = query_info.get("Expected Output", "single_string")

                    if not search_query:
                        self.logger.warning(f"⚠️ No search query for topic: {topic}")
                        continue

                    # Perform search
                    results = self.hybrid_search(search_query, limit=3)

                    # Concatenate page content for LLM
                    concatenated_content = ""
                    if results:
                        for result in results:
                            content = result.get("content", "")
                            if content:
                                concatenated_content += f"\n\nPage {result.get('page_num', 'N/A')}:\n{content}"

                    # Generate LLM answer if we have content and prompt
                    llm_answer = ""
                    if concatenated_content and ai_prompt:
                        self.logger.info(f"🤖 Generating LLM answer for topic: {topic}")
                        llm_answer = self._generate_llm_answer(
                            ai_prompt, concatenated_content
                        )

                    # Store results
                    search_results["sections"][section_name][topic] = {
                        "search_query": search_query,
                        "ai_prompt": ai_prompt,
                        "expected_output": expected_output,
                        "top_results": results,
                        "best_match": results[0] if results else None,
                        "concatenated_content": concatenated_content,
                        "llm_answer": llm_answer,
                    }

                    self.logger.info(
                        f"✅ Found {len(results)} results for topic: {topic}"
                    )

            return search_results

        except Exception as e:
            self.logger.error(f"❌ Template search failed: {e}")
            return {}

    def save_search_results(self, results: Dict[str, Any], output_path: str = None):
        """
        Save search results to JSON file

        Args:
            results: Search results dictionary
            output_path: Output file path (optional)
        """
        if not output_path:
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            output_path = f"search_results_{self.company_name}_{timestamp}.json"

        try:
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(results, f, indent=2, ensure_ascii=False)

            self.logger.info(f"💾 Search results saved to: {output_path}")
            return output_path

        except Exception as e:
            self.logger.error(f"❌ Failed to save search results: {e}")
            return None

    def get_best_pages_summary(self, results: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract a summary of best matching pages for each topic

        Args:
            results: Search results from template search

        Returns:
            Summary with best page numbers for each topic
        """
        summary = {
            "company_name": results.get("company_name"),
            "search_timestamp": results.get("search_timestamp"),
            "best_pages": {},
        }

        for section_name, section_data in results.get("sections", {}).items():
            summary["best_pages"][section_name] = {}

            for topic, topic_data in section_data.items():
                best_match = topic_data.get("best_match")
                if best_match:
                    summary["best_pages"][section_name][topic] = {
                        "page_num": best_match.get("page_num"),
                        "pdf_page_num": best_match.get("pdf_page_num"),
                        "drhp_page_num": best_match.get("drhp_page_num"),
                        "score": best_match.get("score"),
                        "content_preview": (
                            best_match.get("content", "")[:200] + "..."
                            if best_match.get("content")
                            else ""
                        ),
                        "llm_answer": topic_data.get("llm_answer", ""),
                    }
                else:
                    summary["best_pages"][section_name][topic] = None

        return summary


# ---------------------------------------------------------------------------
# Main Function
# ---------------------------------------------------------------------------
def main():
    """
    Main function to demonstrate the PDF to Qdrant processor
    Update the configuration variables below as needed
    """
    # ============================================================================
    # CONFIGURATION - Update these values as needed
    # ============================================================================

    # PDF and company information
    PDF_PATH = (
        r"C:\Users\himan\Downloads\1726054206064_451.pdf"  # Update with your PDF path
    )
    COMPANY_NAME = "Ather Energy Ltd"  # Update with your company name
    COLLECTION_NAME = "drhp_notes_testing"  # Update with your collection name

    # Processing options
    FORCE_REPROCESS = False  # Set to True to reprocess PDF even if JSON exists

    # ============================================================================
    # VALIDATION
    # ============================================================================

    # Check if PDF file exists
    if not os.path.exists(PDF_PATH):
        print(f"❌ PDF file not found: {PDF_PATH}")
        print("Please update the PDF_PATH variable with the correct path.")
        return None

    # Check environment variables
    if not os.getenv("OPENAI_API_KEY"):
        print("❌ OPENAI_API_KEY environment variable is required")
        print("Please set your OpenAI API key in the environment.")
        exit(1)

    if not os.getenv("QDRANT_URL"):
        print("❌ QDRANT_URL environment variable is required")
        print("Please set your Qdrant URL in the environment.")
        exit(1)

    # Check AWS credentials
    if not (os.getenv("AWS_ACCESS_KEY_ID") and os.getenv("AWS_SECRET_ACCESS_KEY")):
        print("❌ AWS credentials are required")
        print(
            "Please set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY in the environment."
        )
        exit(1)

    # ============================================================================
    # EXECUTION
    # ============================================================================

    print("🚀 PDF to Qdrant Processor")
    print("=" * 50)
    print(f"📄 PDF Path: {PDF_PATH}")
    print(f"🏢 Company: {COMPANY_NAME}")
    print(f"📊 Collection: {COLLECTION_NAME}")
    print(f"🔄 Force Reprocess: {FORCE_REPROCESS}")
    print("=" * 50)

    try:
        # Initialize processor
        processor = PDFToQdrantProcessor(
            company_name=COMPANY_NAME, collection_name=COLLECTION_NAME
        )

        # Process PDF to Qdrant
        results = processor.process_complete(PDF_PATH, force_reprocess=FORCE_REPROCESS)

        # Print summary
        processor._print_summary(results)

        return results

    except Exception as e:
        print(f"❌ Error in main: {e}")
        traceback.print_exc()
        return None


def process_and_search(
    pdf_path: str,
    template_path: str,
    company_name: str,
    collection_name: str = None,
    force_reprocess: bool = False,
):
    """
    Complete pipeline: Process PDF to Qdrant and then perform template-based search

    Args:
        pdf_path: Path to the PDF file
        template_path: Path to the template JSON file
        company_name: Name of the company
        collection_name: Qdrant collection name (optional)
        force_reprocess: Whether to force reprocessing of PDF
    """
    try:
        print("=" * 80)
        print(f"🚀 Starting complete pipeline for {company_name}")
        print("=" * 80)

        # Step 1: Process PDF to Qdrant
        print("\n📄 Step 1: Processing PDF to Qdrant...")
        processor = PDFToQdrantProcessor(company_name, collection_name)
        processing_results = processor.process_complete(pdf_path, force_reprocess)

        if processing_results.get("status") != "success":
            print("❌ PDF processing failed. Cannot proceed with search.")
            return None

        print("✅ PDF processing completed successfully!")

        # Step 2: Perform template-based search
        print("\n🔍 Step 2: Performing template-based search...")
        searcher = DRHPSearcher(collection_name or Config.COLLECTION_NAME, company_name)
        search_results = searcher.search_with_template(template_path)

        if not search_results:
            print("❌ Search failed.")
            return None

        print("✅ Search completed successfully!")

        # Step 3: Save results
        print("\n💾 Step 3: Saving results...")
        search_output_path = searcher.save_search_results(search_results)

        # Step 4: Generate summary
        print("\n📊 Step 4: Generating summary...")
        summary = searcher.get_best_pages_summary(search_results)
        summary_path = (
            f"search_summary_{company_name}_{time.strftime('%Y%m%d_%H%M%S')}.json"
        )

        with open(summary_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)

        print(f"✅ Summary saved to: {summary_path}")

        # Step 5: Print summary
        print("\n" + "=" * 80)
        print("📋 SEARCH SUMMARY")
        print("=" * 80)
        print(f"Company: {company_name}")
        print(f"Collection: {collection_name or Config.COLLECTION_NAME}")
        print(f"Search Timestamp: {summary.get('search_timestamp')}")
        print(f"Total Sections: {len(summary.get('best_pages', {}))}")

        for section_name, topics in summary.get("best_pages", {}).items():
            print(f"\n📑 {section_name}:")
            for topic, data in topics.items():
                if data:
                    print(
                        f"  • {topic}: Page {data.get('page_num')} (Score: {data.get('score', 'N/A'):.3f})"
                    )
                    if data.get("llm_answer"):
                        print(f"    Answer: {data.get('llm_answer', '')[:100]}...")
                else:
                    print(f"  • {topic}: No match found")

        print("\n" + "=" * 80)
        print("✅ Complete pipeline finished successfully!")
        print("=" * 80)

        return {
            "processing_results": processing_results,
            "search_results": search_results,
            "summary": summary,
            "search_output_path": search_output_path,
            "summary_path": summary_path,
        }

    except Exception as e:
        print(f"❌ Error in complete pipeline: {e}")
        traceback.print_exc()
        return None


if __name__ == "__main__":
    # ============================================================================
    # CONFIGURATION - Update these values as needed
    # ============================================================================

    # PDF and company information
    PDF_PATH = (
        r"C:\Users\himan\Downloads\1726054206064_451.pdf"  # Update with your PDF path
    )
    COMPANY_NAME = "Ather Energy Ltd"  # Update with your company name
    COLLECTION_NAME = "drhp_notes_testing"  # Update with your collection name

    # Template and processing options
    TEMPLATE_PATH = "drhp_search_template.json"  # Path to your search template
    FORCE_REPROCESS = False  # Set to True to reprocess PDF even if JSON exists

    # ============================================================================
    # VALIDATION
    # ============================================================================

    # Check if required files exist
    if not os.path.exists(PDF_PATH):
        print(f"❌ PDF file not found: {PDF_PATH}")
        print("Please update the PDF_PATH variable with the correct path.")
        exit(1)

    if not os.path.exists(TEMPLATE_PATH):
        print(f"❌ Template file not found: {TEMPLATE_PATH}")
        print("Please ensure the template JSON file exists.")
        exit(1)

    # Check environment variables
    if not os.getenv("OPENAI_API_KEY"):
        print("❌ OPENAI_API_KEY environment variable is required")
        print("Please set your OpenAI API key in the environment.")
        exit(1)

    if not os.getenv("QDRANT_URL"):
        print("❌ QDRANT_URL environment variable is required")
        print("Please set your Qdrant URL in the environment.")
        exit(1)

    # Check AWS credentials
    if not (os.getenv("AWS_ACCESS_KEY_ID") and os.getenv("AWS_SECRET_ACCESS_KEY")):
        print("❌ AWS credentials are required")
        print(
            "Please set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY in the environment."
        )
        exit(1)

    # ============================================================================
    # EXECUTION
    # ============================================================================

    print("🚀 DRHP Processing and Search Pipeline")
    print("=" * 60)
    print(f"📄 PDF Path: {PDF_PATH}")
    print(f"🏢 Company: {COMPANY_NAME}")
    print(f"📊 Collection: {COLLECTION_NAME}")
    print(f"📋 Template: {TEMPLATE_PATH}")
    print(f"🔄 Force Reprocess: {FORCE_REPROCESS}")
    print("=" * 60)

    try:
        # Run the complete pipeline
        results = process_and_search(
            pdf_path=PDF_PATH,
            template_path=TEMPLATE_PATH,
            company_name=COMPANY_NAME,
            collection_name=COLLECTION_NAME,
            force_reprocess=FORCE_REPROCESS,
        )

        if results:
            print(f"\n🎉 Pipeline completed successfully!")
            print(f"📁 Search results: {results['search_output_path']}")
            print(f"📊 Summary: {results['summary_path']}")

            # Additional information
            print(f"\n📈 Processing Stats:")
            stats = results["processing_results"]["stats"]
            print(f"  • Pages Processed: {stats.get('pages_processed', 0)}")
            print(f"  • Embeddings Created: {stats.get('embeddings_created', 0)}")
            print(
                f"  • Processing Time: {stats.get('total_processing_time', 0):.2f} seconds"
            )

            if stats.get("toc_detected", False):
                print(f"  • TOC Page: {stats.get('toc_page', 'N/A')}")

            print(f"\n🔍 Search Results:")
            summary = results["summary"]
            total_sections = len(summary.get("best_pages", {}))
            print(f"  • Total Sections: {total_sections}")

            # Count successful matches
            successful_matches = 0
            llm_answers_generated = 0
            for section_data in summary.get("best_pages", {}).values():
                for topic_data in section_data.values():
                    if topic_data is not None:
                        successful_matches += 1
                        if topic_data.get("llm_answer"):
                            llm_answers_generated += 1

            print(f"  • Successful Matches: {successful_matches}")
            print(f"  • LLM Answers Generated: {llm_answers_generated}")

            # Show sample LLM answers
            print(f"\n🤖 Sample LLM Answers:")
            answer_count = 0
            for section_name, topics in summary.get("best_pages", {}).items():
                for topic, data in topics.items():
                    if data and data.get("llm_answer") and answer_count < 3:
                        print(f"  • {section_name} - {topic}:")
                        print(f"    {data.get('llm_answer', '')[:150]}...")
                        answer_count += 1
                        print()

        else:
            print("\n❌ Pipeline failed!")
            exit(1)

    except KeyboardInterrupt:
        print("\n⚠️ Pipeline interrupted by user")
        exit(1)
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        traceback.print_exc()
        exit(1)
