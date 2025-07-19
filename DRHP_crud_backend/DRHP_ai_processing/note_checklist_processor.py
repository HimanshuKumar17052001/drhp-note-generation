import sys
import os
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional
import json
import time
import random
import requests
import hashlib

import pandas as pd
from dotenv import load_dotenv
from qdrant_client import QdrantClient, models as qmodels
from openai import OpenAI  # or use Bedrock if you prefer
from qdrant_client.http import models as qm
from mongoengine import (
    connect,
    Document,
    StringField,
    IntField,
    ListField,
    DateTimeField,
    DoesNotExist,
    ReferenceField,  # <-- add this
)
from datetime import datetime
from collections import defaultdict
import tiktoken

# ── project / third-party ────────────────────────────────────────────────────
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(project_root)

from baml_client import b
from baml_py import Collector
from azure_blob_utils import get_blob_storage

# ── env & logging ────────────────────────────────────────────────────────────
load_dotenv()
os.environ["LITELLM_LOG"] = "ERROR"

# MongoDB connection (add your URI to .env as MONGODB_URI)
MONGODB_URI = os.getenv("MONGODB_URI")
DB_NAME = os.getenv("DB_NAME", "DRHP_NOTES")
connect(alias="core", host=MONGODB_URI, db=DB_NAME)


class Company(Document):
    meta = {"db_alias": "core", "collection": "company"}
    name = StringField(required=True)
    corporate_identity_number = StringField(required=True, unique=True)
    drhp_file_url = StringField(required=True)
    website_link = StringField()
    created_at = DateTimeField(default=datetime.utcnow)


# ChecklistOutput model
class ChecklistOutput(Document):
    meta = {"db_alias": "core", "collection": "checklist_outputs"}
    company_id = ReferenceField(Company, required=True)
    checklist_name = StringField(required=True)
    row_index = IntField(required=True)
    topic = StringField()
    section = StringField()
    ai_prompt = StringField()
    ai_output = StringField()
    citations = ListField(IntField())
    commentary = StringField()
    created_at = DateTimeField(default=datetime.utcnow)
    updated_at = DateTimeField(default=datetime.utcnow)


logging.basicConfig(level=logging.ERROR)
logger = logging.getLogger("DRHP_note_checklist_processor")
file_handler = logging.FileHandler("litellm_errors.log")
file_handler.setLevel(logging.ERROR)
formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

print(f"Project root added to path: {project_root}")

# ── thread-safe counters ─────────────────────────────────────────────────────
_token_lock = threading.Lock()


class DRHPNoteChecklistProcessor:
    """
    Processes the DRHP Note Checklist for one company,
    using BAML (Collectors) in parallel to score each row.
    """

    def __init__(
        self,
        excel_path: str,
        collection_name: str,
        company_id: str = None,
        checklist_name: str = None,
    ):
        # If excel_path is an Azure blob URL, download it to a temp file
        if (
            excel_path.startswith("https://")
            and ".blob.core.windows.net/" in excel_path
        ):
            blob_storage = get_blob_storage()
            import tempfile
            import uuid

            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx")
            blob_name = excel_path.split(".blob.core.windows.net/")[1]
            try:
                blob_storage.download_file(blob_name, temp_file.name)
                self.excel_path = temp_file.name
                self._temp_checklist_file = temp_file.name
                logging.info(
                    f"Downloaded checklist from Azure Blob Storage: {excel_path} -> {temp_file.name}"
                )
            except Exception as e:
                logging.error(
                    f"Failed to download checklist from Azure Blob Storage: {e}"
                )
                raise
        else:
            self.excel_path = excel_path
            self._temp_checklist_file = None
        self.collection_name = collection_name
        self.qdrant = QdrantClient(url=os.getenv("QDRANT_URL"))
        self.openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        # Extract company name from collection_name (supports both 'drhp_notes_' and 'rhp_notes_' prefixes)
        from bson import ObjectId

        if company_id:
            self.company_id = company_id
            self.company_doc = Company.objects.get(id=ObjectId(company_id))
        else:
            if collection_name.startswith("drhp_notes_"):
                company_name = (
                    collection_name.replace("drhp_notes_", "").replace("_", " ").strip()
                )
            elif collection_name.startswith("rhp_notes_"):
                company_name = (
                    collection_name.replace("rhp_notes_", "").replace("_", " ").strip()
                )
            else:
                company_name = collection_name.replace("_", " ").strip()
            try:
                company_doc = Company.objects.get(name=company_name)
                self.company_doc = company_doc
                self.company_id = str(company_doc.id)
                print(
                    f"[INFO] Found company_id for '{company_name}': {self.company_id}"
                )
            except DoesNotExist:
                logger.error(
                    f"[ERROR] Company '{company_name}' not found in MongoDB. Checklist outputs will not be linked."
                )
                raise ValueError(
                    f"Company '{company_name}' not found in MongoDB. Cannot proceed."
                )
        self.checklist_name = checklist_name or os.path.basename(self.excel_path)

    def __del__(self):
        # Clean up temp checklist file if it was downloaded
        if hasattr(self, "_temp_checklist_file") and self._temp_checklist_file:
            try:
                os.remove(self._temp_checklist_file)
                logging.info(
                    f"Deleted temp checklist file: {self._temp_checklist_file}"
                )
            except Exception as e:
                logging.warning(f"Failed to delete temp checklist file: {e}")

    def _generate_dense_embedding(self, text: str):
        for attempt in range(5):  # Retry up to 5 times
            try:
                response = self.openai_client.embeddings.create(
                    model="text-embedding-3-small", input=text
                )
                return response.data[0].embedding
            except Exception as e:
                print(f"❌ OpenAI embedding error (attempt {attempt+1}): {e}")
                time.sleep(1 * (attempt + 1))  # Linear backoff
        print(
            f"Failed to get embedding for text after multiple retries: {text[:100]}..."
        )
        return None

    def _dense_search(self, query: str, limit: int = 8):
        """Performs dense vector search in Qdrant using only dense embeddings, with retry logic."""
        dense_vec = self._generate_dense_embedding(query)
        if dense_vec is None:
            print("[WARN] Could not generate dense vector for search.")
            return []
        for attempt in range(5):
            try:
                results = self.qdrant.query_points(
                    collection_name=self.collection_name,
                    query=dense_vec,
                    limit=limit,
                    with_payload=True,
                    using="dense",
                )
                return results.points
            except Exception as e:
                print(f"❌ Qdrant dense search error (attempt {attempt+1}): {e}")
                if attempt < 4:
                    time.sleep(2**attempt)  # Exponential backoff
                else:
                    print("[ERROR] Qdrant dense search failed after multiple retries.")
        return []

    def _generate_llm_answer(self, prompt: str, context: str) -> str:
        # Truncate context to fit within model's max tokens
        full_prompt = (
            "You are a DRHP expert with a strong understanding of DRHP documents, the company, and its industry. "
            "Your task is to extract relevant information accurately from the provided markdown content and user prompt, while adhering strictly to the instructions.\n\n"
            f"Context:\n{context}\n\n"
            f"Prompt:\n{prompt}\n\n"
            "Instructions:\n"
            "- Begin the answer directly with the extracted content. Do not include any introductory or explanatory text.\n"
            "- Use only information explicitly present in the context. Do not infer or add content from outside the provided context.\n"
            "- If the required information is not found in the context, respond with 'No answer found'.\n"
            "- Preserve the original wording, data, and structure exactly as they appear in the context.\n"
            "- For tables, extract values precisely as shown—do not perform any calculations or modify the data.\n"
            "- If a value is listed as 'N/A' or '-', reproduce it exactly.\n"
            "- For paragraph-based content, write a clear and complete summary using only the facts provided.\n"
            "- For bullet points, present concise and accurate points that fully capture all relevant information.\n"
            "- Ensure that no details present in the context are missed—review the entire context to capture all applicable data.\n"
            "- Ensure the answer is presented in the correct format as implied by the context (e.g., table, bullets, paragraph).\n"
            "- Do not wrap responses in quotation marks or code formatting such as ``` or '''.\n"
            "- Do not restructure or reformat tables or lists—maintain the original layout if it aids clarity.\n"
            "- Correct any spelling or grammatical errors found in the context when presenting the output.\n"
            "- Always include all available names, dates, numbers, company names, and other specific identifiers exactly as shown.\n"
            "- The output representation in prompt should be followed, do not add the [As in DRHP] in the output. as it is to indicate that take the values and figures from the DRHP.\n\n"
            "Answer:"
        )

        for attempt in range(10):  # up to 10 attempts
            try:
                # Add random jitter to avoid burst
                time.sleep(random.uniform(0.5, 2.0))
                response = self.openai_client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[{"role": "user", "content": full_prompt}],
                    max_tokens=2048,
                )
                return response.choices[0].message.content.strip()
            except Exception as e:
                logger.error(f"OpenAI GPT-4o-mini error (attempt {attempt+1}): {e}")
                print(f"❌ OpenAI GPT-4o-mini error (attempt {attempt+1}): {e}")
                time.sleep(2**attempt)  # Exponential backoff
        return "Error: Unable to generate answer after retries."

    def _generate_commentary(self, ai_output: str) -> str:
        """
        Generate a 10-line expert DRHP commentary based on the AI output.
        Commentary should be descriptive, opinionated, and avoid forbidden phrases.
        """
        prompt = (
            "You are a DRHP expert. Based on the following context, write a commentary in 10 lines. "
            "The commentary should describe the AI output, and if financial data is present, describe the trends and patterns in the numbers. "
            "The points and paragraphs should be descriptive about the AI output and the tone should be opinionated but not too positive or too negative. "
            "The commentary tone and words and sub-text should not be recommending in nature, very neutral words, just for the reader to get to know the facts and trends not any recommendation, the user can make informed decision on its own."
            "Do not use explanatory words or sentences like 'Based on...', 'With context too...', 'The AI output...', 'AI Output states...' and similar starting phrases and do not use phrases like 'The overall...', 'In conclusion...', 'To conclude...', 'Conclusion is...', or similar in the last paragraph. "
            "Directly start with the commentary content, the main content not the introduction. "
            "Do not use any bullet points, just write a paragraph. "
            "Do not use any markdown formatting, just plain text. "
            "\n\nContext:\n" + ai_output + "\n\nCommentary:"
        )
        for attempt in range(5):
            try:
                response = self.openai_client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=1024,
                )
                return response.choices[0].message.content.strip()
            except Exception as e:
                print(f"❌ Commentary LLM error (attempt {attempt+1}): {e}")
                time.sleep(2**attempt)
        return "No Commentary"

    def process(self):
        # Support both Excel and CSV files
        if self.excel_path.lower().endswith(".csv"):
            df = pd.read_csv(self.excel_path)
        else:
            df = pd.read_excel(self.excel_path)
        output_column_name = "AI Outputs"
        citations_column_name = "Citations"
        commentary_column_name = "Commentary"
        df[output_column_name] = ""
        df[citations_column_name] = ""
        df[commentary_column_name] = ""
        results = [None] * len(df)
        citations_results = [None] * len(df)
        commentary_results = [None] * len(df)
        # --- Profiling ---
        t0 = time.time()
        # --- Step 1: Prepare all search queries (for batch embedding) ---
        all_facts = []
        fact_row_map = []  # (row_idx, fact_idx_in_row)
        row_facts = [None] * len(df)

        def baml_query_worker(idx, row):
            topic = str(row.get("Topic", ""))
            section = str(row.get("Section for search", ""))
            keywords = str(row.get("Keywords", ""))
            ai_prompt = str(row.get("AI Prompts", ""))
            if not ai_prompt:
                return idx, []
            search_query = " ".join([topic, section, keywords]).strip()
            try:
                baml_resp = b.ExtractRetrievalAndVerdictQueries(search_query)
                hypo_facts = baml_resp.hypothetical_factual_responses
                if not hypo_facts:
                    hypo_facts = [search_query]
            except Exception:
                hypo_facts = [search_query]
            return idx, hypo_facts

        with ThreadPoolExecutor(max_workers=20) as executor:
            futures = [
                executor.submit(baml_query_worker, idx, row)
                for idx, row in df.iterrows()
            ]
            for future in as_completed(futures):
                idx, hypo_facts = future.result()
                row_facts[idx] = hypo_facts
        for idx, facts in enumerate(row_facts):
            for fact in facts:
                all_facts.append(fact)
                fact_row_map.append(idx)
        t1 = time.time()
        print(f"[PROFILE] BAML + query prep: {t1-t0:.2f}s")
        # --- Step 2: Batch OpenAI embedding for all facts ---
        embeddings = []
        batch_size = 1000  # OpenAI supports up to 2048
        for i in range(0, len(all_facts), batch_size):
            batch = all_facts[i : i + batch_size]
            for attempt in range(5):
                try:
                    response = self.openai_client.embeddings.create(
                        model="text-embedding-3-small", input=batch
                    )
                    embeddings.extend([e.embedding for e in response.data])
                    break
                except Exception as e:
                    print(f"[OpenAI] Embedding batch error (attempt {attempt+1}): {e}")
                    time.sleep(2**attempt)
        t2 = time.time()
        print(f"[PROFILE] OpenAI embedding: {t2-t1:.2f}s")
        # --- Step 3: Batch Qdrant search for all facts ---
        qdrant_results = [[] for _ in range(len(all_facts))]

        def qdrant_worker(start, end):
            for i in range(start, end):
                dense_vec = embeddings[i]
                for attempt in range(5):
                    try:
                        results = self.qdrant.query_points(
                            collection_name=self.collection_name,
                            query=dense_vec,
                            limit=8,
                            with_payload=True,
                            using="dense",
                        )
                        qdrant_results[i] = results.points
                        break
                    except Exception as e:
                        print(
                            f"❌ Qdrant dense search error (attempt {attempt+1}): {e}"
                        )
                        if attempt < 4:
                            time.sleep(2**attempt)
                        else:
                            print(
                                "[ERROR] Qdrant dense search failed after multiple retries."
                            )

        # Parallelize Qdrant queries
        num_workers = 20
        chunk = (len(all_facts) + num_workers - 1) // num_workers
        threads = []
        for w in range(num_workers):
            start = w * chunk
            end = min((w + 1) * chunk, len(all_facts))
            t = threading.Thread(target=qdrant_worker, args=(start, end))
            t.start()
            threads.append(t)
        for t in threads:
            t.join()
        t3 = time.time()
        print(f"[PROFILE] Qdrant search: {t3-t2:.2f}s")
        # --- Step 4: Process each row in parallel (20 workers) ---
        commentary_cache = {}

        def process_row(idx, row):
            topic = str(row.get("Topic", ""))
            section = str(row.get("Section for search", ""))
            keywords = str(row.get("Keywords", ""))
            ai_prompt = str(row.get("AI Prompts", ""))
            if not ai_prompt:
                return idx, "", "", ""
            facts = row_facts[idx]
            dense_citations = set()
            all_dense_context = set()
            for j, fact in enumerate(facts):
                i = sum(len(row_facts[k]) for k in range(idx)) + j
                for r in qdrant_results[i]:
                    if hasattr(r, "payload") and r.payload:
                        content = r.payload.get("page_content", "")
                        page_num = r.payload.get("page_number_drhp", None)
                        if content:
                            all_dense_context.add(content)
                        if page_num is not None and str(page_num).strip():
                            dense_citations.add(str(page_num))
            # LLM answer with up to 3 retries if 'No answer found'
            final_output = "No answer found"
            for attempt in range(3):
                if all_dense_context:
                    dense_context = "\n\n---\n\n".join(all_dense_context)
                    answer = self._generate_llm_answer(ai_prompt, dense_context)
                    if answer.strip().lower() not in [
                        "no answer found",
                        "no answer found.",
                    ]:
                        final_output = answer
                        break
                    else:
                        final_output = answer
                else:
                    final_output = "No answer found"
                    break

            def safe_int(x):
                try:
                    return int(x)
                except Exception:
                    return float("inf")

            if str(final_output).strip().lower() in [
                "no answer found",
                "no answer found.",
            ]:
                citations_str = "No Citations"
                commentary = "No Commentary"
            else:
                citations_str = ",".join(
                    sorted((str(x) for x in dense_citations), key=safe_int)
                )
                # Commentary deduplication
                output_hash = hashlib.sha256(final_output.encode("utf-8")).hexdigest()
                if output_hash in commentary_cache:
                    commentary = commentary_cache[output_hash]
                else:
                    commentary = self._generate_commentary(final_output)
                    commentary_cache[output_hash] = commentary
            return idx, final_output, citations_str, commentary

        t4 = time.time()
        print(f"[PROFILE] Pre-row processing: {t4-t3:.2f}s")
        with ThreadPoolExecutor(max_workers=20) as executor:
            futures = [
                executor.submit(process_row, idx, row) for idx, row in df.iterrows()
            ]
            for future in as_completed(futures):
                idx, output, citations, commentary = future.result()
                results[idx] = output
                citations_results[idx] = citations
                commentary_results[idx] = commentary
        t5 = time.time()
        print(f"[PROFILE] Row processing: {t5-t4:.2f}s")
        # Enforce: if AI output is 'No answer found', citations and commentary must be 'No Citations' and 'No Commentary'
        for i, output in enumerate(results):
            if str(output).strip().lower() in ["no answer found", "no answer found."]:
                citations_results[i] = "No Citations"
                commentary_results[i] = "No Commentary"
        df[output_column_name] = results
        df[citations_column_name] = citations_results
        df[commentary_column_name] = commentary_results
        # --- Step 5: Bulk MongoDB upsert ---
        bulk_ops = []
        for idx, (output, citations, commentary) in enumerate(
            zip(results, citations_results, commentary_results)
        ):
            topic = str(df.iloc[idx].get("Topic", ""))
            section = str(df.iloc[idx].get("Section for search", ""))
            ai_prompt = str(df.iloc[idx].get("AI Prompts", ""))

            # Convert citations string to list of integers
            citations_list = []
            if citations and citations.lower() != "no citations":
                for citation in citations.split(","):
                    citation = citation.strip()
                    if citation and citation.lower() != "no citations":
                        try:
                            citations_list.append(int(citation))
                        except (ValueError, TypeError):
                            logger.warning(
                                f"Could not convert citation '{citation}' to int, skipping"
                            )
                            continue

            ChecklistOutput.objects(
                company_id=self.company_doc,
                checklist_name=self.checklist_name,
                row_index=idx,
            ).update_one(
                set__ai_output=output,
                set__citations=citations_list,
                set__topic=topic,
                set__section=section,
                set__ai_prompt=ai_prompt,
                set__updated_at=datetime.utcnow(),
                set__commentary=commentary,
                upsert=True,
            )
        t6 = time.time()
        print(f"[PROFILE] MongoDB upsert: {t6-t5:.2f}s")
        # Generate base output path
        base_out_path = (
            os.path.splitext(self.excel_path)[0]
            + "_with_outputs_"
            + self.collection_name.replace("drhp_notes_", "")
        )
        out_path = base_out_path + ".xlsx"
        counter = 1
        # Check if file exists and increment suffix if needed
        while os.path.exists(out_path):
            out_path = f"{base_out_path}({counter}).xlsx"
            counter += 1
        df.to_excel(out_path, index=False)
        print(f"\n✅ Successfully saved results to {out_path}")
        print(f"[PROFILE] Total time: {time.time()-t0:.2f}s")


# ── CLI entrypoint ───────────────────────────────────────────────────────────
def main():
    try:
        excel_path = r"C:\Users\himan\Downloads\IPO_Notes_Generation_Checklist.xlsx"  # or your uploaded file
        collection_name = "rhp_notes_Anthem_Biosciences_Limited"  # set this as needed
        company_id = ""  # Set this to the correct company_id (ObjectId as string)
        checklist_name = os.path.basename(excel_path)
        processor = DRHPNoteChecklistProcessor(
            excel_path, collection_name, company_id, checklist_name
        )
        processor.process()

    except Exception as e:
        print(f"❌ Error: {e}")


if __name__ == "__main__":
    main()
