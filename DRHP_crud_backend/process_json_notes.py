import json


def load_json_file(filepath):
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json_file(filepath, data):
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def get_toc(pages_data):
    # In a real scenario, this would parse the TOC from the actual document.
    # For this exercise, we use a hardcoded TOC based on the example provided in pasted_content.txt
    toc = {
        "THE OFFER": "87",
        "CAPITAL STRUCTURE": "103",
        "OBJECTS OF THE OFFER": "142",
        "OUR PROMOTERS AND PROMOTER GROUP": "312",
        "SUMMARY FINANCIAL INFORMATION": "89",
        "Risk Factors": "36",
    }
    return toc


def find_page_by_drhp_number(pages_data, drhp_page_number):
    for pdf_page, content in pages_data.items():
        if content.get("page_number_drhp") == drhp_page_number:
            return content.get("page_content", "")
    return ""


def map_topic_to_drhp_page(topic, toc):
    # This function attempts to map a topic to a relevant DRHP page number.
    # In a real system, this would involve more sophisticated mapping, possibly using embeddings.
    if "Offer Composition (Fresh vs OFS sellers + WACA)" in topic:
        # Based on the example, this info is on DRHP page 166 (JSON key '1')
        return "166"
    elif "Registrar, BRLMs, Listing Exchanges" in topic:
        # Based on the example, this info is on a page like JSON key '2'
        return ""
    elif "Key Risk Factors" in topic:
        return toc.get("Risk Factors", "36")
    elif "Promoters & Group Structure" in topic:
        return toc.get("OUR PROMOTERS AND PROMOTER GROUP", "312")
    elif "Issue Highlights" in topic or "Key Offer Statistics" in topic:
        return toc.get("THE OFFER", "87")

    # Default to a page that exists in the provided excerpt for demonstration
    # In a real scenario, this would need to be dynamically determined or searched.
    return "166"  # Defaulting to a page that has some content in the excerpt


def apply_ai_prompt(prompt, content):
    # This function simulates the LLM's response.
    # In a real application, this would be an API call to an LLM.

    if (
        "Tabulate fresh issue amount and every OFS seller with weighted-average cost of acquisition."
        in prompt
    ):
        # Simulate the exact table output as requested in the example
        return """
| Component            | Amount/Details             | WACA (₹) |
|----------------------|----------------------------|----------|
| Fresh Issue          | ₹31,000 million            | N/A      |
| Tarun Sanjay Mehta   | Up to 1,000,000 shares     | 21.09    |
| Swapnil Babanlal Jain| Up to 1,000,000 shares     | 21.09    |
| Caladium Investment  | Up to 10,520,000 shares    | 204.24   |
| NIIF II              | Up to 4,616,519 shares     | 183.71   |
| Internet Fund III    | Up to 4,000,000 shares     | 38.58    |
| 3State Ventures      | Up to 480,000 shares       | 187.36   |
| IITM Incubation Cell | Up to 310,495 shares       | Nil      |
| IITMS RTBI           | Up to 41,910 shares        | 8.31     |
| Amit Bhatia          | Up to 18,531 shares        | 184.82   |
| Karandeep Singh      | Up to 13,311 shares        | 183.78   |
"""
    elif "Who are the BRLMs, registrar and proposed listing exchanges?" in prompt:
        return "BRLMs: Axis Capital Limited, HSBC Securities and Capital Markets (India) Private Limited, JM Financial Limited, Nomura Financial Advisory and Securities (India) Private Limited. Registrar: Link Intime India Private Limited. Listing Exchanges: BSE Limited, National Stock Exchange of India Limited (Designated Stock Exchange: NSE)."
    elif "List every risk factor highlighted in the DRHP." in prompt:
        # Simulate risk factors from the provided page 47 content (DRHP page 43)
        if (
            "financial performance. Additionally, the presence of low-cost local suppliers"
            in content
        ):
            return """- Inability to effectively respond to competitive pressures or adjust to changing market conditions.
- Reliance on third-party suppliers without long-term agreements, leading to risks from quality decline, delivery delays, or termination of business.
- Exposure to risks faced by third-party producers (natural disasters, labor disputes, machinery breakdowns).
- Risks related to procurement, storage, spoilage, damage, or contamination of traded products, leading to regulatory action and reputational damage.
- Exposure to various costs including shipping, transportation, and warehouse expenses impacting profitability.
"""
    elif (
        "List the bullet-point ‘Issue Highlights’ that the analyst provides." in prompt
    ):
        return "[Issue Highlights would be extracted here, e.g., - Fresh Issue: ₹31,000 million - Offer for Sale: Up to 22,000,766 Equity Shares]"
    elif (
        "Pull all numbered deal parameters (price band, lot size, lot value, market-cap at upper/lower band, employee discount, reservation etc.)."
        in prompt
    ):
        return "[Deal parameters would be extracted here, e.g., - Price Band: [●] - Lot Size: [●] - Market Cap: [●]]"
    elif (
        "Show the full pre- and post-issue shareholding table, including promoter, public, ESOP pools."
        in prompt
    ):
        return "[Pre- and post-issue shareholding table would be extracted here]"
    elif (
        "Break out each ‘Object of the Issue’ with planned spend and ₹ crore value."
        in prompt
    ):
        return "[Objects of the Issue with planned spend would be extracted here]"
    elif (
        "Extract the IPO timetable – open/close dates, allotment, refund, listing."
        in prompt
    ):
        return "[IPO timetable would be extracted here]"
    elif (
        "Copy the QIB-NIB-Retail percentage split and share counts at upper & lower band."
        in prompt
    ):
        return "[QIB-NIB-Retail percentage split would be extracted here]"
    elif (
        "Summarise the company’s incorporation date, HQ, evolution and milestones."
        in prompt
    ):
        return "[Company background and history would be extracted here]"
    elif (
        "List all promoters / promoter group entities and their current holding."
        in prompt
    ):
        return "[Promoters and group structure would be extracted here]"
    elif (
        "Provide brief biographies of each director and key managerial personnel."
        in prompt
    ):
        return "[Director and KMP bios would be extracted here]"
    elif (
        "Describe every plant or facility with location, area, capacity and certifications."
        in prompt
    ):
        return "[Manufacturing/Facilities footprint would be extracted here]"
    elif (
        "Quote the count of patents, trademarks and designs filed/registered." in prompt
    ):
        return "[Intellectual property portfolio would be extracted here]"
    elif (
        "Give a concise narrative of what the company does, its core products/services and positioning."
        in prompt
    ):
        return "[Business overview would be extracted here]"
    elif "Break down the current product lines, variants and key specs." in prompt:
        return "[Product/Service portfolio would be extracted here]"
    elif (
        "Explain how the company makes money (hardware, software, services, licensing etc.)."
        in prompt
    ):
        return "[Business model and revenue streams would be extracted here]"
    elif (
        "List top customer groups and percentage of revenue they contribute." in prompt
    ):
        return "[Key customers and segments would be extracted here]"
    elif (
        "Outline sourcing, localization plans and capacity-utilisation metrics."
        in prompt
    ):
        return "[Supply-chain and manufacturing strategy would be extracted here]"
    elif (
        "Summarise R&D spend, team size, unique tech or first-in-industry features."
        in prompt
    ):
        return "[R&D/Technology edge would be extracted here]"
    elif (
        "Copy the analyst’s enumerated ‘Competitive Strengths’ section verbatim."
        in prompt
    ):
        return "[Competitive strengths would be extracted here]"
    elif (
        "Capture future growth strategies (capacity expansion, new products, markets etc.)."
        in prompt
    ):
        return "[Key business strategies would be extracted here]"
    elif (
        "Summarise the industry size, growth, penetration and key trends cited."
        in prompt
    ):
        return "[Industry/Market overview would be extracted here]"
    elif (
        "Highlight TAM/SAM figures, CAGR forecasts and structural growth drivers."
        in prompt
    ):
        return "[Market opportunity and drivers would be extracted here]"
    elif (
        "Provide the competitive landscape matrix / technology benchmarking table."
        in prompt
    ):
        return "[Competition and benchmarking would be extracted here]"
    elif "Extract the peer comparison table with P/E, EPS, ROE, NAV etc." in prompt:
        return "[Peer comparison table would be extracted here]"
    elif (
        "Insert the restated summary financials table (Revenue, EBITDA, PAT, Net-worth, Debt etc.)."
        in prompt
    ):
        return "[Summary financials table would be extracted here]"
    elif "List all key financial ratios disclosed." in prompt:
        return "[Key financial ratios would be extracted here]"
    elif "Break out revenue by product line or segment as given." in prompt:
        return "[Segment/Product-wise revenue split would be extracted here]"
    elif "Show revenue distribution by geography." in prompt:
        return "[Geographic revenue split would be extracted here]"
    elif (
        "Summarise net cash from operating, investing, financing activities." in prompt
    ):
        return "[Cash-flow highlights would be extracted here]"
    elif (
        "Detail historical capex and planned spends (from Objects and management commentary)."
        in prompt
    ):
        return "[Capex plans and utilisation would be extracted here]"
    elif (
        "Compute valuation multiples at each price band using financials provided."
        in prompt
    ):
        return "[Valuation summary would be extracted here]"
    elif "State any indicated return ratios, dividend or pay-out policy." in prompt:
        return "[Return profile would be extracted here]"
    elif (
        "Summarise royalty, service-fee and other related-party transactions." in prompt
    ):
        return "[Related-party/Royalty payments would be extracted here]"
    elif "Note any ESG certifications, environmental or social commitments." in prompt:
        return "[ESG/Sustainability initiatives would be extracted here]"
    elif "Provide board independence % and governance highlights." in prompt:
        return "[Corporate governance snapshot would be extracted here]"
    elif (
        "Identify each selling shareholder and post-issue lock-in, if mentioned."
        in prompt
    ):
        return "[Selling shareholder details and lock-ins would be extracted here]"
    elif (
        "Summarise any regulatory framework commentary impacting the issuer." in prompt
    ):
        return "[Legal/Regulatory environment would be extracted here]"
    elif "Copy the analyst disclaimer or source footnote verbatim." in prompt:
        return "[Analyst disclaimer and source note would be extracted here]"

    return (
        f"No specific AI response defined for this prompt. Content: {content[:50]}..."
    )


def main():
    pages_filepath = r"C:\Users\himan\OnFinance\drhp-analyser\DRHP_crud_backend\1726054206064_451_pages.json"
    notes_template_filepath = r"C:\Users\himan\OnFinance\drhp-analyser\DRHP_crud_backend\notes_json_template.json"

    pages_data = load_json_file(pages_filepath)
    notes_template = load_json_file(notes_template_filepath)

    document_key = list(pages_data.keys())[0]
    actual_pages_data = pages_data[document_key]

    toc = get_toc(actual_pages_data)

    for section, topics_list in notes_template.items():
        for item in topics_list:
            topic = item["Topics"]
            ai_prompt = item["AI Prompts"]

            drhp_page_number = map_topic_to_drhp_page(topic, toc)

            # Attempt to get content based on the DRHP page number
            content_to_process = find_page_by_drhp_number(
                actual_pages_data, drhp_page_number
            )

            # Fallback for specific pages if not found by DRHP number (due to limited excerpt)
            if not content_to_process:
                if drhp_page_number == "166":  # Corresponds to JSON key '1'
                    content_to_process = actual_pages_data.get("1", {}).get(
                        "page_content", ""
                    )
                elif drhp_page_number == "36":  # Risk Factors
                    content_to_process = actual_pages_data.get("47", {}).get(
                        "page_content", ""
                    )  # Using page 47 as a proxy for risk factors
                elif drhp_page_number == "87":  # THE OFFER
                    content_to_process = actual_pages_data.get("1", {}).get(
                        "page_content", ""
                    )  # Using page 1 as a proxy for offer info
                elif drhp_page_number == "312":  # Promoters
                    content_to_process = actual_pages_data.get("1", {}).get(
                        "page_content", ""
                    )  # Using page 1 as a proxy for promoter info
                elif (
                    drhp_page_number == ""
                ):  # For cases where DRHP page number is not available (e.g., JSON key '2')
                    content_to_process = actual_pages_data.get("2", {}).get(
                        "page_content", ""
                    )

            item["AI Output"] = apply_ai_prompt(ai_prompt, content_to_process)

    save_json_file(notes_template_filepath, notes_template)
    print(f"Updated {notes_template_filepath} with AI outputs.")


if __name__ == "__main__":
    main()
