# import os
# import json
# import logging
# import threading
# import time
# import traceback
# from concurrent.futures import ThreadPoolExecutor, as_completed
# from typing import List, Optional, Tuple, Dict, Any
# from dotenv import load_dotenv
# from pathlib import Path

# load_dotenv()

# from DRHP_ai_processing.page_processor_local import process_pdf_local
# from qdrant_client import QdrantClient, models as qmodels
# from baml_client import b
# from baml_py import Collector, Image
# import pdfplumber
# import fitz
# import numpy as np
# import cv2
# import base64
# import re


# # Configure comprehensive logging with both file and console handlers
# def setup_logging(company_name: str) -> logging.Logger:
#     """Setup comprehensive logging for the processor"""
#     # Create logs directory if it doesn't exist
#     logs_dir = Path("logs")
#     logs_dir.mkdir(exist_ok=True)

#     # Create company-specific log file
#     timestamp = time.strftime("%Y%m%d_%H%M%S")
#     log_filename = f"logs/{company_name}_{timestamp}.log"

#     # Configure logging
# logging.basicConfig(
#     level=logging.INFO,
#     format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
#         handlers=[
#             logging.FileHandler(log_filename, encoding="utf-8"),
#             logging.StreamHandler(),
#         ],
#         force=True,
#     )

#     logger = logging.getLogger(f"DRHP_Processor_{company_name}")
#     logger.setLevel(logging.INFO)

#     return logger


# # Thread-safe token counters
# _token_lock = threading.Lock()


# class LocalDRHPProcessor:
#     def __init__(
#         self,
#         qdrant_url: str = None,
#         collection_name: str = "drhp_notes_testing",
#         max_workers: int = 5,
#         company_name: str = "Unknown",
#     ):
#         self.qdrant_url = qdrant_url or os.getenv("QDRANT_URL", "http://localhost:6333")
#         self.collection_name = collection_name
#         self.company_name = company_name
#         self.max_workers = max_workers

#         # Setup logging
#         self.logger = setup_logging(company_name)

#         # Initialize Qdrant client with retry logic
#         self._init_qdrant_client()

#         # Dedicated collectors for parallel processing
#         self.collectors = [
#             Collector(name=f"collector-{company_name}-{i}") for i in range(max_workers)
#         ]

#         # Token counters
#         self.input_tokens = 0
#         self.output_tokens = 0

#         # Processing statistics
#         self.stats = {
#             "pages_processed": 0,
#             "queries_processed": 0,
#             "errors": 0,
#             "start_time": None,
#             "end_time": None,
#         }

#     def _init_qdrant_client(self, max_retries: int = 3):
#         """Initialize Qdrant client with retry logic"""
#         for attempt in range(max_retries):
#             try:
#                 self.qdrant = QdrantClient(url=self.qdrant_url, timeout=60)
#                 # Test connection
#                 self.qdrant.get_collections()
#                 self.logger.info(
#                     f"Successfully connected to Qdrant at {self.qdrant_url}"
#                 )
#                 return
#             except Exception as e:
#                 self.logger.warning(
#                     f"Qdrant connection attempt {attempt + 1} failed: {e}"
#                 )
#                 if attempt == max_retries - 1:
#                     self.logger.error(
#                         f"Failed to connect to Qdrant after {max_retries} attempts"
#                     )
#                     raise
#                 time.sleep(2**attempt)  # Exponential backoff

#     def pdf_page_to_cv2_image(
#         self, pdf_path: str, page_num: int, dpi: int = 200
#     ) -> np.ndarray:
#         """Convert PDF page to cv2 image with error handling"""
#         try:
#             doc = fitz.open(pdf_path)
#             page = doc.load_page(page_num - 1)
#             pix = page.get_pixmap(dpi=dpi)
#             img_np = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
#                 (pix.height, pix.width, pix.n)
#             )
#             if pix.n == 4:
#                 img_np = cv2.cvtColor(img_np, cv2.COLOR_RGBA2BGR)
#             else:
#                 img_np = cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR)
#             doc.close()
#             return img_np
#         except Exception as e:
#             self.logger.error(f"Error converting PDF page {page_num} to image: {e}")
#             raise

#     def img_to_bytes(self, cv2_img: np.ndarray) -> bytes:
#         """Convert cv2 image to bytes with error handling"""
#         try:
#         success, buf = cv2.imencode(".png", cv2_img)
#         if not success:
#             raise ValueError("Failed to encode image")
#         return buf.tobytes()
#         except Exception as e:
#             self.logger.error(f"Error converting image to bytes: {e}")
#             raise

#     def detect_toc_page(
#         self, pdf_path: str, company_name: str, max_pages_to_check: int = 20
#     ) -> Optional[int]:
#         """
#         Detect Table of Contents page using BAML with comprehensive error handling
#         Returns the page number where TOC is found, or None if not found
#         """
#         self.logger.info("🔍 Detecting Table of Contents page...")

#         try:
#         with pdfplumber.open(pdf_path) as pdf:
#             total_pages = len(pdf.pages)
#             pages_to_check = min(max_pages_to_check, total_pages)

#             self.logger.info(f"Checking first {pages_to_check} pages for TOC...")

#         for page_num in range(1, pages_to_check + 1):
#             try:
#                     self.logger.debug(f"Checking page {page_num} for TOC...")

#                 # Convert page to image
#                 cv2_img = self.pdf_page_to_cv2_image(pdf_path, page_num)
#                 img_bytes = self.img_to_bytes(cv2_img)
#                 b64 = base64.b64encode(img_bytes).decode()
#                 baml_img = Image.from_base64("image/png", b64)

#                 # Check if this is a TOC page
#                 toc_result = b.ExtractTableOfContents(baml_img)
#                 if toc_result.isTocPage:
#                         self.logger.info(f"✅ TOC detected at page {page_num}")
#                     return page_num

#             except Exception as e:
#                     self.logger.warning(f"Error checking TOC for page {page_num}: {e}")
#                 continue

#             self.logger.warning(
#                 f"❌ No TOC page detected in first {pages_to_check} pages"
#             )
#             return None

#         except Exception as e:
#             self.logger.error(f"Error in TOC detection: {e}")
#         return None

#     def process_pdf_locally(
#         self,
#         pdf_path: str,
#         company_name: str,
#         dpi: int = 200,
#         threshold: int = 245,
#         max_workers: int = 5,
#     ) -> str:
#         """
#         Step 1: Process PDF locally using page_processor with comprehensive error handling
#         Returns: path to the output JSON file
#         """
#         self.logger.info(f"📄 Starting PDF processing: {pdf_path}")
#         self.stats["start_time"] = time.time()

#         try:
#         # Detect TOC page first
#         toc_page = self.detect_toc_page(pdf_path, company_name)

#         # Call process_pdf (local-only, no MongoDB)
#             self.logger.info("🔄 Processing PDF pages...")
#         total_in, total_out = process_pdf_local(
#             pdf_path=pdf_path,
#             company_name=company_name,
#             dpi=dpi,
#             threshold=threshold,
#             max_workers=max_workers,
#         )

#             self.logger.info(
#                 f"✅ PDF processing complete. Tokens - in: {total_in}, out: {total_out}"
#         )

#         # Find the output JSON file
#         base_dir = os.path.join(os.getcwd(), company_name, "temp_pages_json")
#             if not os.path.exists(base_dir):
#                 raise FileNotFoundError(f"Output directory not found: {base_dir}")

#         json_files = [f for f in os.listdir(base_dir) if f.endswith("_pages.json")]
#         if not json_files:
#                 raise FileNotFoundError(
#                     "No output JSON found in temp_pages_json directory"
#                 )

#         json_path = os.path.join(base_dir, json_files[0])
#             self.logger.info(f"📁 Found output JSON: {json_path}")

#         # Add TOC information to the JSON
#         self.add_toc_to_json(json_path, toc_page)

#         return json_path

#         except Exception as e:
#             self.logger.error(f"❌ Error in PDF processing: {e}")
#             self.logger.error(traceback.format_exc())
#             raise

#     def add_toc_to_json(self, json_path: str, toc_page: Optional[int]):
#         """Add TOC page information to the JSON file with error handling"""
#         try:
#             with open(json_path, "r", encoding="utf-8") as f:
#                 data = json.load(f)

#             # Add TOC metadata
#             pdf_name = list(data.keys())[0]
#             data[pdf_name]["_metadata"] = {
#                 "toc_page": toc_page,
#                 "total_pages": len(data[pdf_name]),
#                 "processing_info": {
#                     "toc_detected": toc_page is not None,
#                     "toc_page_number": toc_page,
#                     "processing_timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
#                     "company_name": self.company_name,
#                 },
#             }

#             # Write back to file
#             with open(json_path, "w", encoding="utf-8") as f:
#                 json.dump(data, f, indent=4, ensure_ascii=False)

#             self.logger.info(f"✅ Added TOC information to JSON: TOC page = {toc_page}")

#         except Exception as e:
#             self.logger.error(f"❌ Error adding TOC to JSON: {e}")
#             raise

#     def ensure_qdrant_collection(self):
#         """Ensure Qdrant collection exists with error handling"""
#         try:
#         existing = {c.name for c in self.qdrant.get_collections().collections}
#         if self.collection_name not in existing:
#             self.qdrant.create_collection(
#                 collection_name=self.collection_name,
#                 vectors_config=qmodels.VectorParams(
#                     size=1024, distance=qmodels.Distance.COSINE
#                 ),
#             )
#                 self.logger.info(
#                     f"✅ Created Qdrant collection: {self.collection_name}"
#                 )
#             else:
#                 self.logger.info(
#                     f"📊 Using existing Qdrant collection: {self.collection_name}"
#                 )
#         except Exception as e:
#             self.logger.error(f"❌ Error ensuring Qdrant collection: {e}")
#             raise

#     def upsert_pages_to_qdrant(self, json_path: str, company_name: str):
#         """
#         Step 2: Upsert page vectors to Qdrant for semantic search with comprehensive error handling
#         """
#         self.logger.info("🔄 Upserting pages to Qdrant...")

#         try:
#         # Load the page data
#         with open(json_path, "r", encoding="utf-8") as f:
#             data = json.load(f)

#         pdf_name = list(data.keys())[0]
#         pages_data = data[pdf_name]

#         # Get TOC information
#         toc_page = None
#         if "_metadata" in pages_data:
#             toc_page = pages_data["_metadata"].get("toc_page")

#         self.ensure_qdrant_collection()

#         # Upsert each page
#         points = []
#             pages_processed = 0

#         for page_no, page_info in pages_data.items():
#             # Skip metadata
#             if page_no == "_metadata":
#                 continue

#                 try:
#             content = page_info.get("page_content", "")
#             if not content.strip():
#                         self.logger.debug(f"Skipping empty page {page_no}")
#                 continue

#             # Generate vector embedding
#                 vector = b.EmbedText(content).embedding
#                 points.append(
#                     qmodels.PointStruct(
#                         id=f"{company_name}_page_{page_no}",
#                         vector=vector,
#                         payload={
#                             "company_name": company_name,
#                             "page_number_pdf": page_no,
#                             "page_content": content,
#                                 "page_number_drhp": page_info.get(
#                                     "page_number_drhp", ""
#                                 ),
#                             "facts": page_info.get("facts", []),
#                             "queries": page_info.get("queries", []),
#                             "is_toc_page": (
#                                 toc_page is not None and int(page_no) == toc_page
#                             ),
#                         },
#                     )
#                 )
#                     pages_processed += 1

#             except Exception as e:
#                     self.logger.error(f"❌ Error processing page {page_no}: {e}")
#                     self.stats["errors"] += 1
#                 continue

#         if points:
#             self.qdrant.upsert(collection_name=self.collection_name, points=points)
#                 self.logger.info(f"✅ Upserted {len(points)} pages to Qdrant")
#             if toc_page:
#                     self.logger.info(f"📋 TOC page {toc_page} marked in Qdrant")

#                 self.stats["pages_processed"] = pages_processed
#             else:
#                 self.logger.warning("⚠️ No pages were successfully processed for Qdrant")

#         except Exception as e:
#             self.logger.error(f"❌ Error upserting pages to Qdrant: {e}")
#             self.logger.error(traceback.format_exc())
#             raise

#     def build_sophisticated_query(
#         self,
#         section_name: str,
#         topic: str,
#         ai_prompt: str,
#         additional_context: str = "",
#     ) -> str:
#         """
#         Enhanced query building - combines multiple fields like Standard_checklist_processor
#         """
#         try:
#         parts = []
#         for part in (section_name, topic, ai_prompt, additional_context):
#             if part and isinstance(part, str) and part.strip():
#                 parts.append(part.strip())

#         query_txt = " ".join(parts)
#             self.logger.debug(f"🔍 Built sophisticated query: {query_txt[:100]}...")
#         return query_txt
#         except Exception as e:
#             self.logger.error(f"❌ Error building query: {e}")
#             return f"{section_name} {topic} {ai_prompt}"

#     def get_drhp_content_sophisticated(
#         self, query_text: str, company_name: str, collector: Collector
#     ) -> Tuple[str, str]:
#         """
#         Enhanced DRHP content retrieval using BAML pattern from Standard_checklist_processor
#         """
#         try:
#             # Generate sub-queries using BAML
#             resp = b.ExtractRetrievalAndVerdictQueries(
#                 query_text, baml_options={"collector": collector}
#             )

#             # Token bookkeeping
#             in_tok = collector.usage.input_tokens if collector.usage else 0
#             out_tok = collector.usage.output_tokens if collector.usage else 0
#             with _token_lock:
#                 self.input_tokens += in_tok
#                 self.output_tokens += out_tok

#             # Build page-chunk string using Qdrant search
#             seen = set()
#             chunks = []

#             for sub_q in resp.hypothetical_factual_responses:
#                 try:
#                     # Use the correct EmbedText function
#                     query_vector = b.EmbedText(str(sub_q)).embedding
#                     hits = self.qdrant.search(
#                         collection_name=self.collection_name,
#                         query_vector=query_vector,
#                         query_filter=qmodels.Filter(
#                             must=[
#                                 qmodels.FieldCondition(
#                                     key="company_name",
#                                     match=qmodels.MatchValue(value=company_name),
#                                 )
#                             ]
#                         ),
#                         limit=2,
#                         with_payload=True,
#                     )

#                     for hit in hits:
#                         pno = hit.payload["page_number_pdf"]
#                         if pno not in seen:
#                             seen.add(pno)
#                             chunks.append(
#                                 f"PAGE NUMBER : {pno}\n{hit.payload['page_content']}"
#                             )

#                 except Exception as e:
#                     self.logger.warning(
#                         f"⚠️ Error searching for sub-query '{sub_q}': {e}"
#                     )
#                     continue

#             return resp.verdict_query, "\n\n".join(chunks)

#         except Exception as e:
#             self.logger.error(f"❌ Error in sophisticated DRHP content retrieval: {e}")
#             return query_text, ""

#     def get_ai_answer_sophisticated(
#         self, drhp_content: str, ai_prompt: str, collector: Collector
#     ) -> Tuple[str, List[str]]:
#         """
#         Enhanced AI answer generation with better error handling
#         """
#         try:
#             # Use the simple retrieval function instead of verdict
#             resp = b.SimpleRetrieval(
#                 drhp_content, ai_prompt, baml_options={"collector": collector}
#             )

#             # Token bookkeeping
#             in_tok = collector.last.usage.input_tokens or 0
#             out_tok = collector.last.usage.output_tokens or 0
#             with _token_lock:
#                 self.input_tokens += in_tok
#                 self.output_tokens += out_tok

#             # Extract answer and page numbers
#             answer = resp.ai_output
#             relevant_pages = resp.relevant_pages

#             return answer, relevant_pages

#         except Exception as e:
#             self.logger.error(f"❌ Error in AI answer generation: {e}")
#             return f"Error generating answer: {str(e)}", []

#     def process_single_query(
#         self, idx: int, section_name: str, query_info: dict, company_name: str
#     ) -> Optional[dict]:
#         """
#         Process a single query with sophisticated approach (like Standard_checklist_processor)
#         """
#         try:
#             topic = query_info.get("Topics", "")
#             ai_prompt = query_info.get("AI Prompts", "")
#             additional_context = query_info.get("Additional Context", "")

#             if not ai_prompt:
#                 self.logger.debug(f"Skipping query without AI prompt: {topic}")
#                 return None

#             # Pick collector for this worker
#             collector = self.collectors[idx % len(self.collectors)]

#             # Build sophisticated query
#             query_text = self.build_sophisticated_query(
#                 section_name, topic, ai_prompt, additional_context
#             )

#             # Get DRHP content using sophisticated approach
#             verdict_query, drhp_content = self.get_drhp_content_sophisticated(
#                 query_text, company_name, collector
#             )

#             # Get AI answer using simple retrieval
#             answer, relevant_pages = self.get_ai_answer_sophisticated(
#                 drhp_content,
#                 ai_prompt,
#                 collector,  # Use ai_prompt directly instead of verdict_query
#             )

#             return {
#                 "Topics": topic,
#                 "AI Prompts": ai_prompt,
#                 "AI Output": answer,
#                 "Relevant Pages": relevant_pages,
#                 "Query Text": query_text,
#                 "DRHP Content Length": len(drhp_content),
#                 "Processing Status": "Success",
#             }

#         except Exception as e:
#             self.logger.error(
#                 f"❌ Error processing query '{query_info.get('Topics', 'Unknown')}': {e}"
#             )
#             self.stats["errors"] += 1
#             return {
#                 "Topics": query_info.get("Topics", ""),
#                 "AI Prompts": query_info.get("AI Prompts", ""),
#                 "AI Output": f"Error: {str(e)}",
#                 "Relevant Pages": [],
#                 "Query Text": "",
#                 "DRHP Content Length": 0,
#                 "Processing Status": "Error",
#                 "Error Details": str(e),
#             }

#     def process_queries_template_parallel(
#         self,
#         json_path: str,
#         company_name: str,
#         queries_template_path: str,
#         output_path: str,
#     ) -> Dict[str, Any]:
#         """
#         Step 3: Process queries template with parallel processing and sophisticated approach
#         """
#         self.logger.info(
#             f"🔄 Processing queries template with {self.max_workers} parallel workers..."
#         )

#         try:
#         # Load queries template
#         with open(queries_template_path, "r", encoding="utf-8") as f:
#             template = json.load(f)

#         # Load page data to get TOC info
#         with open(json_path, "r", encoding="utf-8") as f:
#             page_data = json.load(f)

#         pdf_name = list(page_data.keys())[0]
#         toc_page = None
#         if "_metadata" in page_data[pdf_name]:
#             toc_page = page_data[pdf_name]["_metadata"].get("toc_page")

#         results = {
#             "_metadata": {
#                 "company_name": company_name,
#                 "toc_page": toc_page,
#                 "total_queries_processed": 0,
#                 "processing_config": {
#                     "max_workers": self.max_workers,
#                     "collection_name": self.collection_name,
#                 },
#                     "processing_stats": self.stats,
#                     "processing_timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
#             }
#         }

#         # Prepare all queries for parallel processing
#         all_queries = []
#         for section_name, queries in template.items():
#             for query_info in queries:
#                 all_queries.append((section_name, query_info))

#             self.logger.info(f"📋 Total queries to process: {len(all_queries)}")

#         # Process queries in parallel
#         with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
#             futures = [
#                 pool.submit(
#                         self.process_single_query_simplified,  # Use simplified approach
#                     idx,
#                     section_name,
#                     query_info,
#                     company_name,
#                 )
#                 for idx, (section_name, query_info) in enumerate(all_queries)
#             ]

#             # Collect results
#             for future in as_completed(futures):
#                 try:
#                     result = future.result()
#                     if result:
#                         # Find the section for this result
#                         for section_name, queries in template.items():
#                             for query_info in queries:
#                                 if (
#                                     query_info.get("Topics") == result["Topics"]
#                                     and query_info.get("AI Prompts")
#                                     == result["AI Prompts"]
#                                 ):
#                                     if section_name not in results:
#                                         results[section_name] = []
#                                     results[section_name].append(result)
#                                         results["_metadata"][
#                                             "total_queries_processed"
#                                         ] += 1
#                                     break
#                 except Exception as e:
#                         self.logger.error(f"❌ Error collecting parallel result: {e}")
#                         self.stats["errors"] += 1

#         # Save results
#         with open(output_path, "w", encoding="utf-8") as f:
#             json.dump(results, f, indent=2, ensure_ascii=False)

#             self.logger.info(f"✅ Results saved to: {output_path}")
#             self.logger.info(
#                 f"📊 Total queries processed: {results['_metadata']['total_queries_processed']}"
#         )
#             self.logger.info(
#                 f"💾 Total tokens used - Input: {self.input_tokens}, Output: {self.output_tokens}"
#         )

#         return results

#         except Exception as e:
#             self.logger.error(f"❌ Error in parallel query processing: {e}")
#             self.logger.error(traceback.format_exc())
#             raise

#     def get_drhp_content_direct(
#         self, ai_prompt: str, company_name: str, collector: Collector
#     ) -> str:
#         """
#         Direct DRHP content retrieval - simpler approach
#         """
#         try:
#             # Generate embedding for the AI prompt directly
#             query_vector = b.EmbedText(ai_prompt).embedding

#             # Search Qdrant for relevant content
#             hits = self.qdrant.search(
#                 collection_name=self.collection_name,
#                 query_vector=query_vector,
#                 query_filter=qmodels.Filter(
#                     must=[
#                         qmodels.FieldCondition(
#                             key="company_name",
#                             match=qmodels.MatchValue(value=company_name),
#                         )
#                     ]
#                 ),
#                 limit=5,  # Get more pages for better coverage
#                 with_payload=True,
#             )

#             # Build content chunks
#             chunks = []
#             for hit in hits:
#                 pno = hit.payload["page_number_pdf"]
#                 chunks.append(f"PAGE NUMBER : {pno}\n{hit.payload['page_content']}")

#             return "\n\n".join(chunks)

#         except Exception as e:
#             self.logger.error(f"❌ Error in direct DRHP content retrieval: {e}")
#             return ""

#     def get_ai_answer_direct(
#         self, drhp_content: str, ai_prompt: str, collector: Collector
#     ) -> Tuple[str, List[str]]:
#         """
#         Direct AI answer generation using the simplified approach
#         """
#         try:
#             # Use the direct retrieval function
#             resp = b.DirectRetrieval(
#                 ai_prompt, drhp_content, baml_options={"collector": collector}
#             )

#             # Token bookkeeping
#             in_tok = collector.last.usage.input_tokens or 0
#             out_tok = collector.last.usage.output_tokens or 0
#             with _token_lock:
#                 self.input_tokens += in_tok
#                 self.output_tokens += out_tok

#             return resp.ai_output, resp.relevant_pages

#         except Exception as e:
#             self.logger.error(f"❌ Error in direct AI answer generation: {e}")
#             return f"Error generating answer: {str(e)}", []

#     def process_single_query_simplified(
#         self, idx: int, section_name: str, query_info: dict, company_name: str
#     ) -> Optional[dict]:
#         """
#         Process a single query with simplified direct approach
#         """
#         try:
#             topic = query_info.get("Topics", "")
#             ai_prompt = query_info.get("AI Prompts", "")
#             additional_context = query_info.get("Additional Context", "")

#             if not ai_prompt:
#                 self.logger.debug(f"Skipping query without AI prompt: {topic}")
#                 return None

#             # Pick collector for this worker
#             collector = self.collectors[idx % len(self.collectors)]

#             # Build query text (for logging purposes)
#             query_text = self.build_sophisticated_query(
#                 section_name, topic, ai_prompt, additional_context
#             )

#             # Get DRHP content using direct approach
#             drhp_content = self.get_drhp_content_direct(
#                 ai_prompt, company_name, collector
#             )

#             # Get AI answer using direct retrieval
#             answer, relevant_pages = self.get_ai_answer_direct(
#                 drhp_content, ai_prompt, collector
#             )

#             return {
#                 "Topics": topic,
#                 "AI Prompts": ai_prompt,
#                 "AI Output": answer,
#                 "Relevant Pages": relevant_pages,
#                 "Query Text": query_text,
#                 "DRHP Content Length": len(drhp_content),
#                 "Processing Status": "Success",
#             }

#         except Exception as e:
#             self.logger.error(
#                 f"❌ Error processing query '{query_info.get('Topics', 'Unknown')}': {e}"
#             )
#             self.stats["errors"] += 1
#             return {
#                 "Topics": query_info.get("Topics", ""),
#                 "AI Prompts": query_info.get("AI Prompts", ""),
#                 "AI Output": f"Error: {str(e)}",
#                 "Relevant Pages": [],
#                 "Query Text": "",
#                 "DRHP Content Length": 0,
#                 "Processing Status": "Error",
#                 "Error Details": str(e),
#             }

#     def process_drhp_complete(
#         self,
#         pdf_path: str,
#         company_name: str,
#         queries_template_path: str,
#         output_path: str = None,
#     ) -> Dict[str, Any]:
#         """
#         Complete DRHP processing pipeline with enhanced parallel processing and comprehensive error handling
#         """
#         self.logger.info(f"🚀 Starting complete DRHP processing for: {company_name}")

#         try:
#             # Reset token counters and stats
#         self.input_tokens = 0
#         self.output_tokens = 0
#             self.stats = {
#                 "pages_processed": 0,
#                 "queries_processed": 0,
#                 "errors": 0,
#                 "start_time": time.time(),
#                 "end_time": None,
#             }

#         # Step 1: Process PDF locally (includes TOC detection)
#         json_path = self.process_pdf_locally(pdf_path, company_name)

#         # Step 2: Upsert to Qdrant
#         self.upsert_pages_to_qdrant(json_path, company_name)

#         # Step 3: Process queries template with parallel processing
#         if output_path is None:
#             output_path = os.path.join(
#                 os.getcwd(), company_name, f"{company_name}_results.json"
#             )

#         results = self.process_queries_template_parallel(
#             json_path, company_name, queries_template_path, output_path
#         )

#             # Update final stats
#             self.stats["end_time"] = time.time()
#             self.stats["total_processing_time"] = (
#                 self.stats["end_time"] - self.stats["start_time"]
#             )
#             results["_metadata"]["processing_stats"] = self.stats

#             self.logger.info("🎉 Complete DRHP processing finished!")
#         return results

#         except Exception as e:
#             self.logger.error(f"❌ Error in complete DRHP processing: {e}")
#             self.logger.error(traceback.format_exc())
#             raise


# def main():
#     """
#     Main function with all inputs configured directly in the code
#     """
#     try:
#         print("🚀 Starting Local DRHP Processor")
#         print("=" * 60)

#         # ========================================
#         # CONFIGURATION - SET YOUR VALUES HERE
#         # ========================================

#         # PDF file path
#         PDF_PATH = r"C:\Users\himan\Downloads\1726054206064_451.pdf"  # CHANGE THIS

#         # Company name
#         COMPANY_NAME = "Ather Energy Ltd"  # CHANGE THIS

#         # Queries template JSON file
#         QUERIES_TEMPLATE_PATH = os.path.join(
#             os.path.dirname(__file__), "notes_json_template.json"
#         )  # CHANGE THIS

#         # Qdrant configuration
#         QDRANT_URL = os.getenv(
#             "QDRANT_URL", "http://localhost:6333"
#         )  # CHANGE IF NEEDED
#         QDRANT_COLLECTION = "os_pages_1024_new"  # CHANGE IF NEEDED

#         # Processing configuration
#         MAX_WORKERS = 5  # CHANGE THIS (recommended: 5-10)

#         # Output path (optional - will auto-generate if None)
#         OUTPUT_PATH = None  # Will be: ./{COMPANY_NAME}/{COMPANY_NAME}_results.json

#         # ========================================
#         # VALIDATION
#         # ========================================

#         print("📋 Validating inputs...")

#         # Check if PDF exists
#         if not os.path.exists(PDF_PATH):
#             raise FileNotFoundError(f"PDF file not found: {PDF_PATH}")

#         # Check if queries template exists
#         if not os.path.exists(QUERIES_TEMPLATE_PATH):
#             raise FileNotFoundError(
#                 f"Queries template not found: {QUERIES_TEMPLATE_PATH}"
#             )

#         # Validate company name
#         if not COMPANY_NAME or not COMPANY_NAME.strip():
#             raise ValueError("Company name cannot be empty")

#         # Validate max workers
#         if MAX_WORKERS < 1 or MAX_WORKERS > 20:
#             raise ValueError("MAX_WORKERS must be between 1 and 20")

#         print("✅ All inputs validated successfully")

#         # ========================================
#         # PROCESSING
#         # ========================================

#         print(f"📄 PDF Path: {PDF_PATH}")
#         print(f"🏢 Company: {COMPANY_NAME}")
#         print(f"📋 Queries Template: {QUERIES_TEMPLATE_PATH}")
#         print(f"🔧 Max Workers: {MAX_WORKERS}")
#         print(f"🗄️ Qdrant URL: {QDRANT_URL}")
#         print(f"📊 Qdrant Collection: {QDRANT_COLLECTION}")
#         print("=" * 60)

#         # Initialize processor
#         processor = LocalDRHPProcessor(
#             qdrant_url=QDRANT_URL,
#             collection_name=QDRANT_COLLECTION,
#             max_workers=MAX_WORKERS,
#             company_name=COMPANY_NAME,
#         )

#         # Process DRHP
#         results = processor.process_drhp_complete(
#             pdf_path=PDF_PATH,
#             company_name=COMPANY_NAME,
#             queries_template_path=QUERIES_TEMPLATE_PATH,
#             output_path=OUTPUT_PATH,
#         )

#         # ========================================
#         # RESULTS
#         # ========================================

#         final_output_path = OUTPUT_PATH or os.path.join(
#             os.getcwd(), COMPANY_NAME, f"{COMPANY_NAME}_results.json"
#         )

#         print("\n" + "=" * 60)
#         print("🎉 DRHP PROCESSING COMPLETED SUCCESSFULLY!")
#         print("=" * 60)
#         print(f"📄 PDF Processed: {PDF_PATH}")
#         print(f"🏢 Company: {COMPANY_NAME}")
#         print(f"📊 Results: {final_output_path}")
#         print(f"🔧 Workers Used: {MAX_WORKERS}")
#         print(
#             f"📈 Queries Processed: {results['_metadata']['total_queries_processed']}"
#         )
#         print(f"📄 Pages Processed: {processor.stats['pages_processed']}")
#         print(f"❌ Errors: {processor.stats['errors']}")
#         print(
#             f"⏱️ Processing Time: {processor.stats.get('total_processing_time', 0):.2f} seconds"
#         )
#         print(
#             f"💾 Tokens Used: {processor.input_tokens} input, {processor.output_tokens} output"
#         )
#         print("=" * 60)

#     except FileNotFoundError as e:
#         print(f"\n❌ ERROR: File not found - {e}")
#         print("Please check the file paths in the configuration section.")
#         return 1

#     except ValueError as e:
#         print(f"\n❌ ERROR: Invalid configuration - {e}")
#         print("Please check the configuration values in the main function.")
#         return 1

#     except Exception as e:
#         print(f"\n❌ ERROR: Unexpected error - {e}")
#         print("Check the log files in the 'logs' directory for details.")
#         return 1

#     return 0


# if __name__ == "__main__":
#     exit_code = main()
#     exit(exit_code)
