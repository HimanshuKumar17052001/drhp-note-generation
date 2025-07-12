import sys, os, logging, threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional

import pandas as pd
import mongoengine
from dotenv import load_dotenv
from datetime import datetime
from enum import Enum               # still imported for Flag

# ── project / third-party ────────────────────────────────────────────────────
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(project_root)

from app.models.schemas import SebiChecklist, Company, Regulation, Pages, CostMap
from baml_client import b
from baml_py import Collector

# ── env & logging ────────────────────────────────────────────────────────────
load_dotenv()
os.environ["LITELLM_LOG"] = "ERROR"

logging.basicConfig(level=logging.ERROR)
logger = logging.getLogger('SEBI_checklist_processor')
fh = logging.FileHandler('litellm_errors.log')
fh.setLevel(logging.ERROR)
fh.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
logger.addHandler(fh)

print(f"Project root added to path: {project_root}")

# ── thread-safe counters ─────────────────────────────────────────────────────
_token_lock = threading.Lock()

class SebiChecklistProcessor:
    """
    Processes the SEBI ICDR eligibility-criteria checklist for one company.
    Now supports up-to-five parallel checklist queries.
    """

    # ───────────── init ─────────────
    def __init__(self, company_id: str):
        self.company_id      = company_id
        self.company         = Company.objects(id=self.company_id).first()
        if not self.company:
            raise ValueError(f"Company not found with ID: {self.company_id}")

        # global usage counters
        self.input_tokens    = 0
        self.output_tokens   = 0

        # create **five dedicated collectors**, one per worker thread
        self.collectors      = [
            Collector(name=f"collector-sebi-checklist-{i}") for i in range(5)
        ]

    # ───────────── private helpers ─────────────
    def _load_excel_data(self) -> List[dict]:
        excel_path = "/home/ubuntu/backend/DRHP_crud_backend/Checklists/DRHP Requirements_13_JUNE_2025_modi.xlsx"
        # excel_path = "/home/ubuntu/drhp-analyser-new/DRHP_crud_backend/Checklists/DRHP Requirements_14_MAY_2025_modi.xlsx"
        
        logger.info(f"Loading Excel from {excel_path}")

        df = pd.read_excel(excel_path, sheet_name="SEBI ICDR Eligibility Criteria")
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

    # ---------------------------------------------------------
    # NOTE: every call in this class receives *its own* collector
    #       (pulled from self.collectors by the caller)
    # ---------------------------------------------------------
    def _get_flag_status(self, drhp_content: str, verdict_query: str, collector):
        resp = b.ExtractFinalVerdict(
            drhp_content, verdict_query, baml_options={"collector": collector}
        )

        # token accounting (thread-safe)
        in_tok  = collector.last.usage.input_tokens  or 0
        out_tok = collector.last.usage.output_tokens or 0

        with _token_lock:
            self.input_tokens  += in_tok
            self.output_tokens += out_tok

        return (
            resp.flag_status,
            resp.detailed_reasoning,
            resp.citations or ["N/A"],
            collector.last.usage.input_tokens,
            collector.last.usage.output_tokens,
        )

    def _get_drhp_content(
        self,
        heading: str,
        subheading: str,
        drhp_info_location: str,
        particulars: str,
        ai_search_content: str,
        remarks: str,
        collector,
    ):
        parts = [
            str(p) if not (isinstance(p, float) and pd.isna(p)) else ""
            for p in (heading, subheading, particulars, ai_search_content, remarks)
        ]
        query = " ".join(filter(None, parts))

        resp = b.ExtractRetrievalAndVerdictQueries(
            query, baml_options={"collector": collector}
        )

        in_tok  = collector.last.usage.input_tokens  or 0
        out_tok = collector.last.usage.output_tokens or 0

        with _token_lock:
            self.input_tokens  += in_tok
            self.output_tokens += out_tok

        # build DRHP snippet pool
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

    # ───────────── parallel worker ─────────────
    def _process_single_item(self, item: dict, collector):
        """Run one checklist line; returns a SebiChecklist doc or None."""
        if pd.isna(item["particulars"]) or item["particulars"] == "":
            return None  # skip blank rows

        # 1) fetch relevant DRHP chunks
        verdict_q, drhp_content = self._get_drhp_content(
            item.get("heading", ""),
            item.get("sub_heading", ""),
            item.get("drhp_info_location", ""),
            item["particulars"],
            item.get("ai_search_content", ""),
            item.get("remarks", ""),
            collector,
        )

        # 2) score compliance
        flag_status, summary, pages, *_ = self._get_flag_status(
            drhp_content, verdict_q, collector
        )
        
        status_str = flag_status.name.replace("_", " ")  # "FLAGGED" or "NOT FLAGGED"
        
        drhp_pages = [page.page_number_drhp for page in Pages.objects(company=self.company, page_number_pdf__in=pages)]
        return SebiChecklist(
            company_id=self.company,
            regulation_mentioned=item["regulation"],
            particulars=item["particulars"],
            summary_analysis=summary,
            status=status_str,
            page_number=", ".join(drhp_pages) if drhp_pages else "N/A",
        )

    # ───────────── public API ─────────────
    def process_sebi_checklist(self):
        excel_items = self._load_excel_data()
        checklist_entries: list[SebiChecklist] = []

        # round-robin assign collectors so that each worker
        # always uses the same dedicated collector
        def pick_collector(idx: int):
            return self.collectors[idx % len(self.collectors)]

        with ThreadPoolExecutor(max_workers=5) as pool:
            futures = [
                pool.submit(self._process_single_item, item, pick_collector(i))
                for i, item in enumerate(excel_items)
            ]

            for f in as_completed(futures):
                try:
                    entry = f.result()
                    if entry:
                        checklist_entries.append(entry)
                except Exception as exc:
                    logger.error("Checklist worker failed", exc_info=exc)

        if checklist_entries:
            try:
                SebiChecklist.objects(company_id=self.company_id).delete()
            except Exception as e:
                logger.error(f"Error deleting existing SebiChecklist entries: {e}")

            SebiChecklist.objects.insert(checklist_entries)

        return self.input_tokens, self.output_tokens


# ── CLI entrypoint ───────────────────────────────────────────────────────────
def main():
    try:
        mongoengine.connect(
            db=os.getenv("MONGO_DB"),
            host=os.getenv("MONGO_URI"),
            alias="default",
        )

        company_id = "6842b4a6bc1317b8acda53ed"  # 🔁 your company ID
        print("🔄 Processing SEBI checklist...")
        processor = SebiChecklistProcessor(company_id)
        in_tok, out_tok = processor.process_sebi_checklist()
        print(f"✅ Done!  Total tokens — input: {in_tok}, output: {out_tok}")

    except Exception as e:
        print(f"❌ Error: {e}")

    finally:
        mongoengine.disconnect()
        print("🔴 Disconnected from MongoDB")


if __name__ == "__main__":
    main()
