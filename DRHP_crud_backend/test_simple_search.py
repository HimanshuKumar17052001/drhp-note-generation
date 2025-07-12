import os
from dotenv import load_dotenv

from baml_client import b
from baml_py import Collector

# Setup
load_dotenv()
os.environ["LITELLM_LOG"] = "ERROR"

# Create a collector
collector = Collector(name="collector-single-point")


def process_single_point(
    heading: str,
    subheading: str,
    drhp_info_location: str,
    particulars: str,
    ai_search_content: str,
    remarks: str,
    company_id: str,
):
    # Combine parts into one query
    parts = [heading, subheading, particulars, ai_search_content, remarks]
    query_text = " ".join(filter(None, map(str, parts)))

    # Step 1: Extract verdict query
    resp = b.ExtractRetrievalAndVerdictQueries(
        query_text, baml_options={"collector": collector}
    )
    verdict_query = resp.verdict_query

    # Step 2: Fetch DRHP chunks from company pages
    from app.models.schemas import Pages  # Import here to keep this script standalone

    seen_pages = set()
    page_chunks = []

    for sub_q in resp.hypothetical_factual_responses:
        results = Pages.search(
            query_text=str(sub_q),
            company_id=company_id,
            limit=2,
        )
        for r in results.points:
            pno = r.payload["page_number_pdf"]
            if pno not in seen_pages:
                seen_pages.add(pno)
                page_chunks.append(f"PAGE NUMBER : {pno}\n{r.payload['page_content']}")

    drhp_content = "\n\n".join(page_chunks)

    # Step 3: Extract final verdict
    verdict = b.ExtractFinalVerdict(
        drhp_content, verdict_query, baml_options={"collector": collector}
    )

    # Print results
    print("Status      :", verdict.flag_status.name.replace("_", " "))
    print("Reasoning   :", verdict.detailed_reasoning)
    print("Citations   :", verdict.citations or ["N/A"])
    print("Input tokens:", collector.last.usage.input_tokens or 0)
    print("Output tokens:", collector.last.usage.output_tokens or 0)


# Example usage
if __name__ == "__main__":
    process_single_point(
        heading="Financial Information",
        subheading="Restated Financials",
        drhp_info_location="Page 120-130",
        particulars="The company must have positive net worth in the last 3 years",
        ai_search_content="Net worth, profit after tax, equity capital",
        remarks="Ensure values are not negative",
        company_id="685e919b7e1217dab8b4300a",  # Replace with your target
    )
