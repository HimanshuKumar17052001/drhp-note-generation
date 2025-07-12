import sys
import os
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional

import pandas as pd
import mongoengine
from dotenv import load_dotenv

# ── project / third-party ────────────────────────────────────────────────────
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(project_root)

from app.models.schemas import BseChecklist, Company, Regulation, Pages
from baml_client import b
from baml_py import Collector

# ── env & logging ────────────────────────────────────────────────────────────
load_dotenv()
os.environ["LITELLM_LOG"] = "ERROR"

logging.basicConfig(level=logging.ERROR)
logger = logging.getLogger('BSE_checklist_processor')
file_handler = logging.FileHandler('litellm_errors.log')
file_handler.setLevel(logging.ERROR)
formatter = logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

print(f"Project root added to path: {project_root}")

# ── thread-safe counters ─────────────────────────────────────────────────────
_token_lock = threading.Lock()

class BseChecklistProcessor:
    """
    Processes the BSE Listing eligibility-criteria checklist for one company,
    using BAML (Collectors) in parallel to score each row.
    """

    def __init__(self, company_id: str):
        self.company_id    = company_id
        self.company       = Company.objects(id=self.company_id).first()
        if not self.company:
            raise ValueError(f"Company not found with ID: {self.company_id}")

        # Global usage counters
        self.input_tokens  = 0
        self.output_tokens = 0

        # Create five dedicated collectors, one per worker thread
        self.collectors = [
            Collector(name=f"collector-bse-checklist-{i}") for i in range(5)
        ]

    def _load_excel_data(self) -> List[dict]:
        excel_path = "/home/ubuntu/backend/DRHP_crud_backend/Checklists/DRHP Requirements_13_JUNE_2025_modi.xlsx"
        # excel_path = "/home/ubuntu/drhp-analyser-new/DRHP_crud_backend/Checklists/DRHP Requirements_14_MAY_2025_modi.xlsx"
        
        
        logger.info(f"Loading Excel from {excel_path}")
        df = pd.read_excel(excel_path, sheet_name="BSE Eligibility Criteria")
        df.columns = df.columns.str.strip()

        column_mapping = {
            "Sn.no": "sn_no",
            "Regulation": "regulation",
            "Particulars": "particulars",
            "Where we get Information in DRHP": "drhp_info_location",
            "Heading": "heading",
            "Sub- Heading": "sub_heading",
            "What AI search for in DRHP": "ai_search_content",
            "Remarks": "remarks",
        }

        missing = [c for c in column_mapping if c not in df.columns]
        if missing:
            raise ValueError(f"Missing required columns: {missing}")

        df = df.rename(columns=column_mapping)
        return df.to_dict("records")

    def _get_drhp_content(
        self,
        heading: str,
        subheading: str,
        drhp_info_location: str,
        particulars: str,
        ai_search_content: str,
        remarks: str,
        collector: Collector
    ) -> tuple[str, str]:
        """
        Retrieve relevant DRHP snippets via Section.search,
        then tokenize with BAML to build a verdict_query.
        """
        # Build a single query string from all parts
        parts = []
        for part in (heading, subheading, particulars, ai_search_content, remarks):
            if isinstance(part, float) and pd.isna(part):
                parts.append("")
            else:
                parts.append(str(part))
        query_text = " ".join(filter(None, parts))

        resp = b.ExtractRetrievalAndVerdictQueries(
            query_text,
            baml_options={"collector": collector}
        )

        # Safely update token totals
        in_tok  = collector.last.usage.input_tokens  or 0
        out_tok = collector.last.usage.output_tokens or 0
        with _token_lock:
            self.input_tokens  += in_tok
            self.output_tokens += out_tok

        # Collect page‐numbered chunks
        seen_pages = set()
        page_chunks = []
        for sub_q in resp.hypothetical_factual_responses:
            results = Pages.search(
                query_text=str(sub_q),
                company_id=str(self.company_id),
                limit=2,
            )
            for r in results.points:
                pno = r.payload["page_number_pdf"]
                if pno not in seen_pages:
                    seen_pages.add(pno)
                    chunk_text = r.payload["page_content"]
                    page_chunks.append(f"PAGE NUMBER : {pno}\n{chunk_text}")

        return resp.verdict_query, "\n\n".join(page_chunks)

       

    def _get_flag_status(
        self,
        drhp_content: str,
        verdict_query: str,
        collector: Collector
    ) -> tuple[str, str, List[str], int, int]:
        """
        Send DRHP content + verdict_query to BAML.ExtractFinalVerdict,
        parse the response, and update token counts.
        """
        resp = b.ExtractFinalVerdict(
            drhp_content,
            verdict_query,
            baml_options={"collector": collector}
        )

        # Safely update token totals
        in_tok  = collector.last.usage.input_tokens  or 0
        out_tok = collector.last.usage.output_tokens or 0
        with _token_lock:
            self.input_tokens  += in_tok
            self.output_tokens += out_tok

        citations = resp.citations or ["N/A"]
        return (
            resp.flag_status,
            resp.detailed_reasoning,
            citations,
            in_tok,
            out_tok,
        )

    def _process_single_item(
        self,
        item: dict,
        collector: Collector
    ) -> Optional[BseChecklist]:
        """
        Runs one row:
         1) _get_drhp_content → (verdict_query, drhp_chunks)
         2) _get_flag_status → BAML verdict
         3) Build a BseChecklist document (or None if no particulars)
        """
        if pd.isna(item.get("particulars", "")) or item["particulars"] == "":
            return None

        # 1) Retrieve DRHP content & verdict_query
        verdict_q, drhp_chunks = self._get_drhp_content(
            str(item.get("heading", "")),
            str(item.get("sub_heading", "")),
            str(item.get("drhp_info_location", "")),
            str(item["particulars"]),
            str(item.get("ai_search_content", "")),
            str(item.get("remarks", "")),
            collector,
        )

        # 2) Score compliance
        flag_status, reasoning, pages, _, _ = self._get_flag_status(
            drhp_chunks,
            verdict_q,
            collector
        )
        
        status_str = flag_status.name.replace("_", " ")  # "FLAGGED" or "NOT FLAGGED"

        drhp_pages = [page.page_number_drhp for page in Pages.objects(company=self.company, page_number_pdf__in=pages)]
        page_info = ", ".join(drhp_pages) if drhp_pages else "N/A"

        return BseChecklist(
            company_id=self.company,
            regulation_mentioned=item["regulation"],
            particulars=item["particulars"],
            summary_analysis=reasoning,
            status=status_str,
            page_number=page_info
        )

    def process_bse_checklist(self) -> tuple[int, int]:
        """
        Load the Excel rows, then spin up to five threads. Each thread
        uses its dedicated collector (from self.collectors) to process one row.
        Finally, bulk‐insert all BseChecklist documents and return token counts.
        """
        excel_items = self._load_excel_data()
        checklist_entries: List[BseChecklist] = []

        # round‐robin assignment of collectors
        def pick_collector(idx: int) -> Collector:
            return self.collectors[idx % len(self.collectors)]

        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [
                executor.submit(self._process_single_item, item, pick_collector(i))
                for i, item in enumerate(excel_items)
            ]

            for future in as_completed(futures):
                try:
                    entry = future.result()
                    if entry:
                        checklist_entries.append(entry)
                except Exception as exc:
                    logger.error("Checklist worker failed", exc_info=exc)

        if checklist_entries:
            try:
                BseChecklist.objects(company_id=self.company_id).delete()
            except Exception as e:
                logger.error(f"Error deleting existing BseChecklist entries: {e}")

            BseChecklist.objects.insert(checklist_entries)

        return self.input_tokens, self.output_tokens


# ── CLI entrypoint ───────────────────────────────────────────────────────────
def main():
    try:
        mongoengine.connect(
            db=os.getenv("MONGO_DB"),
            host=os.getenv("MONGO_URI"),
            alias="default",
        )
        print("✅ Connected to MongoDB")

        company_id = "68443a769478dd986f8fa268"  # Replace with your company ID
        print("🔄 Processing BSE checklist...")
        processor = BseChecklistProcessor(company_id)
        in_tok, out_tok = processor.process_bse_checklist()
        print(f"✅ BSE checklist complete!  Tokens – in: {in_tok}, out: {out_tok}")

    except Exception as e:
        print(f"❌ Error: {e}")

    finally:
        mongoengine.disconnect()
        print("🔴 Disconnected from MongoDB")


if __name__ == "__main__":
    main()
