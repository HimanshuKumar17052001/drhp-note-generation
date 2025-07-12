"""
StandardChecklistProcessor
‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾
* Uses **BAML** collectors just like the SEBI/BSE processors
* Searches **Pages** (not Section) with the parameter `query_text`
* Five parallel workers, each with its own Collector
* Leaves *all* checklist-number–specific branches (QR extraction, link check, etc.)
  intact – they are now executed inside each worker based on the original row index
"""

import sys, os, logging, threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional

import pandas as pd
import mongoengine
from dotenv import load_dotenv

# ── project / third-party ────────────────────────────────────────────────────
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(project_root)

from app.models.schemas import Company, Pages, StandardChecklist
from baml_client import b
from baml_py import Collector

# utilities that some checklist rows rely on
from DRHP_ai_processing.qr_extractor import QRCodeProcessor
from DRHP_ai_processing.extract_links_from_front_page import WebsiteLinkExtractor

# ── env & logging ────────────────────────────────────────────────────────────
load_dotenv()
os.environ["LITELLM_LOG"] = "ERROR"

logging.basicConfig(level=logging.ERROR)
logger = logging.getLogger("STANDARD_checklist_processor")
fh = logging.FileHandler("litellm_errors.log")
fh.setLevel(logging.ERROR)
fh.setFormatter(
    logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
)
logger.addHandler(fh)

print(f"Project root added to path: {project_root}")

# ── thread-safe counters ─────────────────────────────────────────────────────
_token_lock = threading.Lock()


class StandardChecklistProcessor:
    """
    Parallel BAML-powered standard-checklist scorer.
    """

    def __init__(self, company_id: str):
        self.company_id = company_id
        self.company = Company.objects(id=self.company_id).first()
        if not self.company:
            raise ValueError(f"Company not found with ID: {self.company_id}")

        self.input_tokens = 0
        self.output_tokens = 0

        # Five dedicated collectors → one per worker
        self.collectors = [
            Collector(name=f"collector-standard-checklist-{i}") for i in range(5)
        ]

    # ── Excel loader ────────────────────────────────────────────────────────
    def _load_standard_checklist(self) -> List[dict]:
        excel_path = r"C:\Users\himan\OnFinance\drhp-analyser\DRHP_crud_backend\Checklists\DRHP Requirements_13_JUNE_2025_modi.xlsx"
        # excel_path = "/home/ubuntu/drhp-analyser-new/DRHP_crud_backend/Checklists/DRHP Requirements_14_MAY_2025_modi.xlsx"

        xls = pd.ExcelFile(excel_path)
        if "Standard Questionnaire" not in xls.sheet_names:
            raise ValueError("Standard Questionnaire sheet not found")

        df = xls.parse("Standard Questionnaire")
        df.columns = df.columns.str.strip()
        df = df.rename(
            columns={
                "Heading": "heading",
                "Checks": "checklist_points",
                "Remarks": "remarks",
                "Expected Checks Description": "expected_checks",
            }
        )
        return df.to_dict("records")

    # ── DRHP content retrieval (Pages.search) ───────────────────────────────
    def _get_drhp_content(
        self,
        heading: str,
        checklist_points: str,
        remarks: str,
        expected_checks: str,
        collector: Collector,
    ) -> tuple[str, str]:
        # Build search query
        parts = []
        for part in (heading, checklist_points, remarks, expected_checks):
            if isinstance(part, float) and pd.isna(part):
                parts.append("")
            else:
                parts.append(str(part))
        query_txt = " ".join(filter(None, parts))

        resp = b.ExtractRetrievalAndVerdictQueries(
            query_txt, baml_options={"collector": collector}
        )

        # token bookkeeping
        in_tok = collector.usage.input_tokens if collector.usage else 0
        out_tok = collector.usage.output_tokens if collector.usage else 0
        with _token_lock:
            self.input_tokens += in_tok
            self.output_tokens += out_tok

        # Build page-chunk string using Pages.search
        seen = set()
        chunks = []
        for sub_q in resp.hypothetical_factual_responses:
            results = Pages.search(
                query_text=str(sub_q), company_id=self.company_id, limit=2
            )
            for r in results.points:
                pno = r.payload["page_number_pdf"]
                if pno not in seen:
                    seen.add(pno)
                    chunks.append(f"PAGE NUMBER : {pno}\n{r.payload['page_content']}")

        return resp.verdict_query, "\n\n".join(chunks)

    # ── Flag status via BAML.ExtractFinalVerdict ────────────────────────────
    def _get_flag_status(
        self, drhp_content: str, verdict_query: str, collector: Collector
    ) -> tuple[str, str, List[str]]:
        resp = b.ExtractFinalVerdict(
            drhp_content, verdict_query, baml_options={"collector": collector}
        )

        # token bookkeeping
        in_tok = collector.last.usage.input_tokens or 0
        out_tok = collector.last.usage.output_tokens or 0
        with _token_lock:
            self.input_tokens += in_tok
            self.output_tokens += out_tok

        return resp.flag_status, resp.detailed_reasoning, resp.citations or ["N/A"]

    # ── Worker for one checklist row ────────────────────────────────────────
    def _process_single_item(
        self, idx: int, item: dict, collector: Collector
    ) -> Optional[StandardChecklist]:
        """
        idx is 0-based → original checklist 'count' = idx + 1
        """
        count = idx + 1

        # Skip blank rows
        if not item.get("checklist_points", ""):
            return None

        # ---------- prepare drhp_content & verdict_query ----------
        drhp_content = ""
        verdict_query = item.get("checklist_points", "")

        # Special cases exactly as original numbering logic
        if count not in {3, 4, 5}:
            verdict_query, drhp_content = self._get_drhp_content(
                item.get("heading", ""),
                item.get("checklist_points", ""),
                item.get("remarks", ""),
                item.get("expected_checks", ""),
                collector,
            )

        elif count == 3:
            # QR-code extraction
            response = QRCodeProcessor(self.company.drhp_file_url).process_qr_from_pdf()
            drhp_content = (
                f"Extracted QR content: {response.get('qr_content')}\n"
                f"is_accessible: {response.get('is_accessible')}"
            )

        elif count == 4:
            # Website link extraction
            links = WebsiteLinkExtractor(
                self.company.drhp_file_url
            ).check_all_www_links()
            if links:
                drhp_content = (
                    "Extracted links and their working status:\n"
                    + "\n".join(
                        f"{e['link']} - {'✅' if e['is_working'] else '❌'}"
                        for e in links
                    )
                )
            else:
                drhp_content = "No website links found."

        # count == 5 keeps drhp_content = "" (per original behaviour)

        # ---------- run LLM verdict ----------
        flag_status, reasoning, pages = self._get_flag_status(
            drhp_content, verdict_query, collector
        )
        status_str = flag_status.name.replace("_", " ")  # "FLAGGED" or "NOT FLAGGED"
        drhp_pages = [
            page.page_number_drhp
            for page in Pages.objects(company=self.company, page_number_pdf__in=pages)
        ]
        page_info = ", ".join(drhp_pages) if drhp_pages else "N/A"

        return StandardChecklist(
            company_id=self.company,
            heading=item.get("heading", ""),
            checklist_points=item.get("checklist_points", ""),
            remarks=item.get("remarks", ""),
            summary_analysis=reasoning,
            status=status_str,
            page_number=page_info,
        )

    # ── Public API ──────────────────────────────────────────────────────────
    def process_standard_checklist(self) -> tuple[int, int]:
        items = self._load_standard_checklist()
        entries: List[StandardChecklist] = []

        def pick_collector(i: int) -> Collector:
            return self.collectors[i % len(self.collectors)]

        with ThreadPoolExecutor(max_workers=5) as pool:
            futures = [
                pool.submit(self._process_single_item, i, item, pick_collector(i))
                for i, item in enumerate(items)
            ]
            for fut in as_completed(futures):
                try:
                    doc = fut.result()
                    if doc:
                        entries.append(doc)
                except Exception as exc:
                    logger.error("Checklist worker failed", exc_info=exc)

        if entries:
            try:
                StandardChecklist.objects(company_id=self.company_id).delete()
            except Exception as e:
                logger.error(f"Error deleting existing StandardChecklist entries: {e}")

            StandardChecklist.objects.insert(entries)

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

        company_id = "67c6ac00030601897568b42f"  # ← your company ID
        print("🔄 Processing Standard checklist...")
        processor = StandardChecklistProcessor(company_id)
        inp, outp = processor.process_standard_checklist()
        print(f"✅ Standard checklist done. Tokens – in: {inp}, out: {outp}")

    except Exception as e:
        print(f"❌ Error: {e}")

    finally:
        mongoengine.disconnect()
        print("🔴 Disconnected from MongoDB")


if __name__ == "__main__":
    main()
