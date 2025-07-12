import os
import json
from dotenv import load_dotenv

load_dotenv()

from DRHP_ai_processing.page_processor import extract_page_text
from baml_client import b
from baml_py import Collector

# --- CONFIG ---
PDF_PATH = r"C:\Users\himan\OnFinance\drhp-analyser\1726054206064_451.pdf"
COMPANY_NAME = "Ather Energy Ltd"
NOTES_JSON_PATH = os.path.join(os.path.dirname(__file__), "notes_json_template.json")
OUTPUT_JSON_PATH = os.path.join(
    os.path.dirname(__file__), "notes_json_with_output.json"
)


def extract_all_pages(pdf_path):
    import pdfplumber

    with pdfplumber.open(pdf_path) as pdf:
        total_pages = len(pdf.pages)
    pages_data = {}
    for pno in range(1, total_pages + 1):
        _, content = extract_page_text(pdf_path, pno)
        pages_data[str(pno)] = content
    return pages_data


def find_relevant_pages(pages_data, query, top_k=3):
    # Simple keyword search: rank by number of query words present
    query_words = set(query.lower().split())
    scored = []
    for pno, content in pages_data.items():
        content_words = set(content.lower().split())
        score = len(query_words & content_words)
        scored.append((score, pno, content))
    scored.sort(reverse=True)
    # Return top_k non-empty pages
    return [(pno, content) for score, pno, content in scored if score > 0][:top_k]


def process_notes_local(pdf_path, notes_json_path, output_json_path):
    # Step 1: Extract all pages locally
    print("Extracting all pages from PDF...")
    pages_data = extract_all_pages(pdf_path)
    print(f"Extracted {len(pages_data)} pages.")

    # Step 2: Load notes template
    with open(notes_json_path, "r", encoding="utf-8") as f:
        notes = json.load(f)

    results = {}

    for heading, subtopics in notes.items():
        results[heading] = []
        for sub in subtopics:
            subheading = sub["Topics"]
            ai_prompt = sub["AI Prompts"]

            # Find relevant pages (simple keyword search)
            relevant = find_relevant_pages(pages_data, ai_prompt)
            if not relevant:
                drhp_content = ""
            else:
                drhp_content = "\n\n".join(
                    [f"PAGE NUMBER : {pno}\n{content}" for pno, content in relevant]
                )

            # LLM call
            collector = Collector(name=f"collector-{heading}-{subheading}")
            # Use the AI prompt as the query
            resp = b.ExtractRetrievalAndVerdictQueries(
                ai_prompt, baml_options={"collector": collector}
            )
            verdict_query = resp.verdict_query

            verdict = b.ExtractFinalVerdict(
                drhp_content, verdict_query, baml_options={"collector": collector}
            )

            results[heading].append(
                {
                    "Topics": subheading,
                    "AI Prompts": ai_prompt,
                    "AI Output": getattr(
                        verdict, "llm_output", verdict.detailed_reasoning
                    ),
                }
            )

    with open(output_json_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\nResults written to {output_json_path}\n")


if __name__ == "__main__":
    process_notes_local(PDF_PATH, NOTES_JSON_PATH, OUTPUT_JSON_PATH)
