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

import pandas as pd
from dotenv import load_dotenv
from qdrant_client import QdrantClient, models as qmodels
from openai import OpenAI
from qdrant_client.http import models as qm

# ── project / third-party ────────────────────────────────────────────────────
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(project_root)

from baml_client import b
from baml_py import Collector

# ── env & logging ────────────────────────────────────────────────────────────
load_dotenv()
os.environ["LITELLM_LOG"] = "ERROR"

logging.basicConfig(level=logging.ERROR)
logger = logging.getLogger("DRHP_dense_only_processor")
file_handler = logging.FileHandler("litellm_errors.log")
file_handler.setLevel(logging.ERROR)
formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

print(f"Project root added to path: {project_root}")

# ── thread-safe counters ─────────────────────────────────────────────────────
_token_lock = threading.Lock()


class DenseOnlyChecklistProcessor:
    """
    Processes the DRHP Note Checklist using only dense search with hypothetical responses.
    """

    def __init__(self, excel_path: str, collection_name: str):
        self.excel_path = excel_path
        self.collection_name = collection_name
        self.qdrant = QdrantClient(url=os.getenv("QDRANT_URL"))
        self.openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

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

    def _dense_search(self, query: str, limit: int = 5):
        """Performs dense vector search in Qdrant using only dense embeddings."""
        dense_vec = self._generate_dense_embedding(query)
        if dense_vec is None:
            print("[WARN] Could not generate dense vector for search.")
            return []
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
            print(f"❌ Qdrant dense search error: {e}")
            return []

    def _generate_hypothetical_response(
        self, topic: str, section: str, ai_prompt: str
    ) -> List[str]:
        """Generate hypothetical responses based on topic, section, and AI prompt."""
        search_query = f"{topic} {section}".strip()
        print(f"Generating hypothetical responses for: {search_query}")

        # Add a robust retry loop for the BAML call
        hypo_facts = None
        for attempt in range(5):  # Retry up to 5 times
            try:
                baml_resp = b.ExtractRetrievalAndVerdictQueries(search_query)
                hypo_facts = baml_resp.hypothetical_factual_responses
                if hypo_facts:
                    break  # Success
            except Exception as e:
                print(f"❌ BAML call error (attempt {attempt+1}): {e}. Retrying...")
                time.sleep(2 * (attempt + 1))  # Exponential backoff

        if not hypo_facts:
            print(
                "Warning: BAML did not generate hypothetical facts after retries. Using original query."
            )
            hypo_facts = [search_query]

        return hypo_facts

    def _generate_llm_answer(self, prompt: str, context: str) -> str:
        full_prompt = (
            "You are a seasoned analyst, with a deep understanding of the company and the industry. You know how to read DHRP IPO documents, and extract useful information from them. "
            "Your task is to craft an answer based on the markdown content provided and the prompt below, while sticking to the instructions provided. "
            f"Context:\n{context}\n\n"
            f"Prompt: {prompt}\n\n"
            "Instructions: Your answer should start directly with the extracted information or table, "
            "without any introductory or explanatory text. Do not write phrases like 'Here are the key dates...' or 'Based on the context...'. "
            "Just output the answer in a clear, concise, and direct format as if it is being pasted into a report. "
            "If the answer is not found in the context, return 'No answer found'. "
            "Please maintain the verbatim of the answer as it is in the context. "
            "In tables, extract the exact figures and numbers as they are in the context, do not do any calculations in order to manipulate the numbers. "
            "If the value is present in the content, then answer, if N/A or - in the table, then answer 'N/A' or '-'. "
            "For paragraphs, write a comprehensive paragraph around the context, just for facts don't make up any information, take the reference from the context itself. "
            "For bullet points, write crisp and clear bullet points. "
            "Don't hallucinate any information, any value, any number, any name, any date, anything apart from the context. "
            "Don't give the extraction between '''''' or ``````, and don't give the extraction between ```python or ```javascript or ```markdown, just give the answer as it is in the context. "
            "If there are any spelling mistakes in the context, or grammatical errors, correct them. "
            "Please stick to the instructions provided, in form of the prompt."
            "Please state the names, numbers, dates, addresses, company names"
            "Answer:"
        )
        for attempt in range(10):  # up to 10 attempts
            try:
                # Add random jitter to avoid burst
                time.sleep(random.uniform(0.5, 2.0))
                response = self.openai_client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[{"role": "user", "content": full_prompt}],
                    max_tokens=1024,
                )
                return response.choices[0].message.content.strip()
            except Exception as e:
                logger.error(f"OpenAI GPT-4o-mini error (attempt {attempt+1}): {e}")
                print(f"❌ OpenAI GPT-4o-mini error (attempt {attempt+1}): {e}")
                time.sleep(2**attempt)  # Exponential backoff
        return "Error: Unable to generate answer after retries."

    def _process_row(self, idx, row):
        topic = str(row.get("Topic", ""))
        section = str(row.get("Section for search", ""))
        ai_prompt = str(row.get("AI Prompts", ""))
        if not ai_prompt:
            print(f"Skipping row {idx+1} due to empty 'AI Prompts' column.")
            return idx, "", ""

        print(f"\n--- Processing Row {idx+1}: {topic} ---")

        # Generate hypothetical responses
        hypo_facts = self._generate_hypothetical_response(topic, section, ai_prompt)

        # Collect all context and citations from dense search
        all_context = set()
        all_citations = set()

        print(
            f"[INFO] Searching for {len(hypo_facts)} hypothetical facts for row {idx+1}..."
        )

        for fact in hypo_facts:
            # Dense search only
            dense_results = self._dense_search(fact, limit=5)
            for r in dense_results:
                if isinstance(r, tuple):
                    r = r[0]
                if hasattr(r, "payload") and r.payload:
                    content = r.payload.get("page_content", "")
                    page_num = r.payload.get("page_number_drhp", None)
                    if content:
                        all_context.add(content)
                    if page_num is not None and str(page_num).strip():
                        all_citations.add(str(page_num))

        # Generate final answer
        if all_context:
            combined_context = "\n\n---\n\n".join(all_context)
            final_output = self._generate_llm_answer(ai_prompt, combined_context)

            # Only add citations if answer is not "No answer found"
            if final_output.strip().lower() != "no answer found":

                def safe_int(x):
                    try:
                        return int(x)
                    except Exception:
                        return float("inf")  # Non-numeric values go last

                citations_str = ",".join(
                    sorted((str(x) for x in all_citations), key=safe_int)
                )
            else:
                citations_str = ""
        else:
            final_output = "No answer found"
            citations_str = ""

        print(
            f"--- Finished processing row {idx+1}. Output length: {len(final_output)} chars ---"
        )
        return idx, final_output, citations_str

    def process(self):
        # Support both Excel and CSV files
        if self.excel_path.lower().endswith(".csv"):
            df = pd.read_csv(self.excel_path)
        else:
            df = pd.read_excel(self.excel_path)

        output_column_name = "AI Outputs"
        citations_column_name = "Citations"
        df[output_column_name] = ""
        df[citations_column_name] = ""
        results = [None] * len(df)
        citations_results = [None] * len(df)

        # Increase concurrency for faster processing now that all network calls are resilient
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [
                executor.submit(self._process_row, idx, row)
                for idx, row in df.iterrows()
            ]
            for future in as_completed(futures):
                idx, output, citations = future.result()
                results[idx] = output
                citations_results[idx] = citations

        df[output_column_name] = results
        df[citations_column_name] = citations_results

        # Generate base output path
        base_out_path = (
            os.path.splitext(self.excel_path)[0]
            + "_dense_only_"
            + "_".join(self.collection_name.split("_")[-2:])
        )
        out_path = base_out_path + ".xlsx"
        counter = 1
        # Check if file exists and increment suffix if needed
        while os.path.exists(out_path):
            out_path = f"{base_out_path}({counter}).xlsx"
            counter += 1

        df.to_excel(out_path, index=False)
        print(f"\n✅ Successfully saved results to {out_path}")


# ── CLI entrypoint ───────────────────────────────────────────────────────────
def main():
    try:
        excel_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            "DRHP_crud_backend",
            "Checklists",
            "IPO_Notes_Checklist_AI_Final_prod_updated.xlsx",
        )
        collection_name = "drhp_notes_Wakefit Innovations Limited"  # set this as needed
        processor = DenseOnlyChecklistProcessor(excel_path, collection_name)
        processor.process()

    except Exception as e:
        print(f"❌ Error: {e}")


if __name__ == "__main__":
    main()
