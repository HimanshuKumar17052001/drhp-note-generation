import json
import re
import os
import logging
from typing import Dict, List, Tuple, Optional
from datetime import datetime
from dotenv import load_dotenv
import boto3
from botocore.exceptions import ClientError, NoCredentialsError
from tenacity import retry, stop_after_attempt, wait_exponential

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler("document_analyzer.log")],
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()


class DocumentAnalyzer:
    """Class to analyze document content and generate answers based on topics and AI prompts."""

    def __init__(self, notes_template_path: str, pages_data_path: str):
        """
        Initialize the DocumentAnalyzer with paths to JSON files.

        Args:
            notes_template_path (str): Path to notes_json_template.json
            pages_data_path (str): Path to 1726054206064_451_pages.json

        Raises:
            FileNotFoundError: If JSON files are missing
            ValueError: If JSON files are invalid or empty
        """
        self.notes_template = self._load_json(notes_template_path, "Notes Template")
        self.pages_data = self._load_json(pages_data_path, "Pages Data")
        self.pdf_key = self._validate_pdf_key()
        self.doc_pages: List[Tuple[int, str]] = []
        self.subsection_ranges: List[Tuple[str, int, int]] = []

        # Comprehensive topic to subsection mapping
        self.topic_to_subsection: Dict[str, str] = {
            "Issue Highlights": "THE OFFER",
            "Key Offer Statistics (price band, lot size, market-cap, employee quota etc.)": "THE OFFER",
            "Capital Structure & Shareholding Pattern (pre- & post-issue)": "CAPITAL STRUCTURE",
            "Objects / Use of Proceeds": "OBJECTS OF THE OFFER",
            "Offer Composition (Fresh vs OFS sellers + WACA)": "THE OFFER",
            "Indicative Timetable": "THE OFFER",
            "Issue Break-up (QIB/NIB/RET buckets)": "THE OFFER",
            "Registrar, BRLMs, Listing Exchanges": "GENERAL INFORMATION",
            "Offer Expenses": "OBJECTS OF THE OFFER",
            "Lock-in Periods": "CAPITAL STRUCTURE",
            "Underwriting Agreements": "THE OFFER",
            "Green Shoe Option": "THE OFFER",
            "Price Band Details": "THE OFFER",
            "Employee Reservation": "THE OFFER",
            "Market Lot Size": "THE OFFER",
            "Company Background & History": "OUR BUSINESS",
            "Promoters & Group Structure": "OUR PROMOTERS AND PROMOTER GROUP",
            "Board of Directors & KMP Bios": "OUR MANAGEMENT",
            "Manufacturing / Facilities Footprint": "OUR BUSINESS",
            "Intellectual-Property Portfolio": "OUR BUSINESS",
            "Business Overview": "OUR BUSINESS",
            "Product / Service Portfolio": "OUR BUSINESS",
            "Business Model & Revenue Streams": "OUR BUSINESS",
            "Key Customers & Segments": "OUR BUSINESS",
            "Supply-Chain & Manufacturing Strategy": "OUR BUSINESS",
            "R&D / Technology Edge": "OUR BUSINESS",
            "Key Business Strategies": "OUR BUSINESS",
            "Industry / Market Overview": "INDUSTRY OVERVIEW",
            "Market Opportunity & Drivers": "INDUSTRY OVERVIEW",
            "Competition & Benchmarking": "INDUSTRY OVERVIEW",
            "Peer Comparison (listed comps)": "INDUSTRY OVERVIEW",
            "Financial Summary": "SUMMARY FINANCIAL INFORMATION",
            "Summary P&L, Balance Sheet, Cash-flow (3-5 yrs)": "FINANCIAL INFORMATION",
            "Key Ratios (EPS, RONW, ROCE, Debt-Equity)": "FINANCIAL INFORMATION",
            "Segment / Product-wise Revenue Split": "FINANCIAL INFORMATION",
            "Geographic Revenue Split": "FINANCIAL INFORMATION",
            "Cash-flow Highlights": "FINANCIAL INFORMATION",
            "Capex Plans & Utilisation": "OBJECTS OF THE OFFER",
            "Valuation Summary (implied market-cap, EV, P/E, EV/EBITDA)": "THE OFFER",
            "Return Profile (listing gains, dividend policy if any)": "DIVIDEND POLICY",
            "Key Risk Factors": "RISK FACTORS",
            "Related-Party / Royalty Payments": "RELATED PARTY TRANSACTIONS",
            "ESG / Sustainability Initiatives": "OUR BUSINESS",
            "Corporate Governance Snapshot": "OUR MANAGEMENT",
            "Selling Shareholder Details & Lock-ins": "CAPITAL STRUCTURE",
            "Legal / Regulatory Environment": "GOVERNMENT AND OTHER APPROVALS",
            "Analyst Disclaimer & Source Note": "DECLARATION",
        }

        # Retrieval prompt template
        self.prompt_template = """You are an expert financial analyst tasked with extracting specific information from an IPO prospectus. Your goal is to answer the following question or perform the specified task based on the provided document content. Follow these instructions:

1. **Task**: {ai_prompt}
2. **Context**: The document content below is from a specific section of an IPO prospectus. Use only this content to generate your answer.
3. **Content**:
{page_content}
4. **Instructions**:
   - Provide a clear, concise, and accurate answer based on the task.
   - If the task requires a table, format it as a markdown table with appropriate headers.
   - If the task requires a list, use bullet points.
   - If specific information (e.g., numbers, names) is requested, extract and present it exactly as it appears.
   - If the requested information is missing or unclear, state: "Information not found in the provided content."
   - Do not make assumptions or include external information.
   - Ensure the output is well-structured and easy to read.
5. **Output Format**:
   - For tabular data: Use a markdown table.
   - For lists: Use bullet points with clear descriptions.
   - For narrative answers: Use concise paragraphs.
   - Always include a brief explanation of how the answer was derived from the content.

**Output**:
[Your answer here]"""

        # Initialize AWS Bedrock client
        try:
            self.bedrock = boto3.client(
                "bedrock-runtime",
                region_name=os.getenv("AWS_REGION_NAME", "us-east-1"),
                aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
                aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
            )
            self.anthropic_version = os.getenv(
                "ANTHROPIC_VERSION", "bedrock-2023-05-31"
            )
            self._validate_model_id()
            logger.info("Successfully initialized AWS Bedrock client")
        except NoCredentialsError:
            logger.error("AWS credentials not found")
            raise
        except ValueError as e:
            logger.error(str(e))
            raise
        except Exception as e:
            logger.error(f"Failed to initialize Bedrock client: {e}")
            raise

    def _load_json(self, filepath: str, name: str) -> Dict:
        """Load a JSON file with error handling."""
        try:
            if not os.path.exists(filepath):
                raise FileNotFoundError(f"{name} file not found: {filepath}")
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not data:
                raise ValueError(f"{name} file is empty")
            logger.info(f"Successfully loaded {name} from {filepath}")
            return data
        except FileNotFoundError as e:
            logger.error(str(e))
            raise
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in {name} file: {e}")
            raise
        except Exception as e:
            logger.error(f"Error loading {name} file: {e}")
            raise

    def _validate_pdf_key(self) -> str:
        """Validate and return the PDF key from pages_data."""
        try:
            pdf_keys = list(self.pages_data.keys())
            if not pdf_keys:
                raise ValueError("No PDF keys found in pages data")
            if len(pdf_keys) > 1:
                logger.warning("Multiple PDF keys found; using the first one")
            return pdf_keys[0]
        except Exception as e:
            logger.error(f"Error validating PDF key: {e}")
            raise

    def _validate_model_id(self) -> None:
        """Validate the Bedrock model ID."""
        model_id = "anthropic.claude-3-5-sonnet-20240620-v1:0"
        try:
            bedrock_client = boto3.client(
                "bedrock",
                region_name=os.getenv("AWS_REGION_NAME", "us-east-1"),
                aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
                aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
            )
            response = bedrock_client.list_foundation_models()
            available_models = [
                model["modelId"] for model in response.get("modelSummaries", [])
            ]
            if model_id not in available_models:
                logger.error(
                    f"Invalid model ID: {model_id}. Available models: {available_models}"
                )
                raise ValueError(f"Model ID {model_id} is not available in Bedrock")
            logger.info(f"Validated model ID: {model_id}")
        except ClientError as e:
            logger.error(f"Error validating model ID: {e}")
            raise

    def _parse_toc(self) -> None:
        """Parse the Table of Contents to extract subsections and their page ranges."""
        try:
            toc_page = str(self.pages_data[self.pdf_key]["_metadata"]["toc_page"])
            toc_content = self.pages_data[self.pdf_key][toc_page]["page_content"]
            lines = toc_content.split("\n")
            subsections: List[Tuple[str, int]] = []

            # Regex to match subsection titles and page numbers
            pattern = re.compile(r"([A-Z &/]+) \.{3,} (\d+)")

            for line in lines:
                match = pattern.match(line.strip())
                if match:
                    title, page = match.group(1), int(match.group(2))
                    subsections.append((title, page))

            if not subsections:
                raise ValueError("No subsections found in TOC")

            # Determine page ranges
            for i in range(len(subsections)):
                title = subsections[i][0]
                start_page = subsections[i][1]
                end_page = (
                    subsections[i + 1][1] - 1 if i < len(subsections) - 1 else 522
                )
                self.subsection_ranges.append((title, start_page, end_page))

            logger.info(f"Parsed {len(self.subsection_ranges)} subsections from TOC")
        except KeyError as e:
            logger.error(f"TOC page or content missing: {e}")
            raise
        except Exception as e:
            logger.error(f"Error parsing TOC: {e}")
            raise

    def _build_page_mapping(self) -> None:
        """Build a mapping from document page numbers to PDF page keys."""
        try:
            for pdf_page, data in self.pages_data[self.pdf_key].items():
                if (
                    isinstance(data, dict)
                    and "page_number_drhp" in data
                    and data["page_number_drhp"]
                    and isinstance(data["page_number_drhp"], str)
                    and data["page_number_drhp"].isdigit()
                ):
                    doc_page = int(data["page_number_drhp"])
                    self.doc_pages.append((doc_page, pdf_page))
            self.doc_pages.sort(key=lambda x: x[0])
            if not self.doc_pages:
                raise ValueError("No valid document pages found")
            logger.info(f"Built mapping for {len(self.doc_pages)} document pages")
        except Exception as e:
            logger.error(f"Error building page mapping: {e}")
            raise

    def _get_content_for_range(self, start_page: int, end_page: int) -> str:
        """Extract content from pages within the given document page range."""
        try:
            relevant_pdf_pages = [
                pdf_page
                for doc_page, pdf_page in self.doc_pages
                if start_page <= doc_page <= end_page
            ]
            if not relevant_pdf_pages:
                logger.warning(f"No pages found for range {start_page}-{end_page}")
                return ""

            content = []
            for pdf_page in relevant_pdf_pages:
                try:
                    page_content = self.pages_data[self.pdf_key][pdf_page][
                        "page_content"
                    ]
                    content.append(page_content)
                except KeyError:
                    logger.warning(f"Page content missing for PDF page {pdf_page}")
                    continue

            combined_content = "\n".join(content)
            if len(combined_content) > 50000:
                logger.warning(
                    f"Content for range {start_page}-{end_page} truncated from {len(combined_content)} to 50000 characters"
                )
                combined_content = combined_content[:50000]
            logger.info(
                f"Extracted content from {len(relevant_pdf_pages)} pages for range {start_page}-{end_page}"
            )
            return combined_content
        except Exception as e:
            logger.error(f"Error extracting content: {e}")
            return ""

    @retry(
        stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10)
    )
    def _generate_answer(self, ai_prompt: str, content: str) -> str:
        """Generate an answer using the Bedrock Claude model."""
        if not content:
            logger.warning("No content provided for answer generation")
            return "Error: No content available to generate answer"

        model_id = os.getenv("LLM_MODEL", "anthropic.claude-3-5-sonnet-20241022-v2:0")
        input_text = self.prompt_template.format(
            ai_prompt=ai_prompt, page_content=content
        )

        try:
            body = {
                "anthropic_version": self.anthropic_version,
                "max_tokens": 2000,
                "temperature": 0.7,
                "top_p": 1.0,
                "messages": [{"role": "user", "content": input_text}],
            }
            response = self.bedrock.invoke_model(
                modelId=model_id,
                body=json.dumps(body),
                contentType="application/json",
                accept="application/json",
            )
            result = json.loads(response["body"].read().decode("utf-8"))
            answer = result.get("content", [{}])[0].get(
                "text", "Error: No text in response"
            )
            logger.info(f"Generated answer for prompt: {ai_prompt[:50]}...")
            return answer.strip()
        except ClientError as e:
            logger.error(f"Bedrock API error: {e.response['Error']['Message']}")
            return (
                f"Error: AI model invocation failed - {e.response['Error']['Message']}"
            )
        except json.JSONDecodeError:
            logger.error("Invalid JSON response from Bedrock API")
            return "Error: Invalid API response format"
        except Exception as e:
            logger.error(f"Error generating answer: {e}")
            return f"Error: {str(e)}"

    def process_notes(self) -> None:
        """Process all topics in the notes template and populate AI Output."""
        try:
            self._parse_toc()
            self._build_page_mapping()

            for section, topics_list in self.notes_template.items():
                logger.info(f"Processing section: {section}")
                if not isinstance(topics_list, list):
                    logger.warning(f"Invalid topics list in section {section}")
                    continue

                for topic_dict in topics_list:
                    topic = topic_dict.get("Topics", "")
                    ai_prompt = topic_dict.get("AI Prompts", "")
                    if not topic or not ai_prompt:
                        logger.warning(f"Missing topic or prompt in section {section}")
                        topic_dict["AI Output"] = "Error: Missing topic or prompt"
                        continue

                    subsection = self.topic_to_subsection.get(topic)
                    if not subsection:
                        logger.warning(f"No subsection mapping for topic: {topic}")
                        topic_dict["AI Output"] = (
                            "Error: No subsection mapping for topic"
                        )
                        continue

                    found = False
                    for title, start, end in self.subsection_ranges:
                        if title == subsection:
                            content = self._get_content_for_range(start, end)
                            answer = self._generate_answer(ai_prompt, content)
                            topic_dict["AI Output"] = answer
                            found = True
                            break

                    if not found:
                        logger.warning(f"Subsection not found: {subsection}")
                        topic_dict["AI Output"] = "Error: Subsection not found"

            logger.info("Completed processing all topics")
        except Exception as e:
            logger.error(f"Error processing notes: {e}")
            raise

    def _validate_output(self) -> None:
        """Validate that all topics have an AI Output field."""
        try:
            for section, topics_list in self.notes_template.items():
                if not isinstance(topics_list, list):
                    logger.warning(f"Invalid topics list in section {section}")
                    continue
                for topic_dict in topics_list:
                    if "AI Output" not in topic_dict:
                        logger.warning(
                            f"Missing AI Output for topic: {topic_dict.get('Topics', 'Unknown')}"
                        )
                        topic_dict["AI Output"] = "Error: Output not generated"
        except Exception as e:
            logger.error(f"Error validating output: {e}")
            raise

    def save_output(self, output_path: str) -> None:
        """Save the updated notes template to a JSON file."""
        try:
            self._validate_output()
            output_dir = os.path.dirname(output_path)
            if output_dir and not os.path.exists(output_dir):
                os.makedirs(output_dir)
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(self.notes_template, f, indent=4)
            logger.info(f"Saved updated notes to {output_path}")
        except OSError as e:
            logger.error(f"Error saving output file: {e}")
            raise
        except Exception as e:
            logger.error(f"Error saving output: {e}")
            raise


def main():
    """Main function to run the document analyzer."""
    start_time = datetime.now()
    logger.info(f"Starting document analysis at {start_time}")

    try:
        analyzer = DocumentAnalyzer(
            notes_template_path="notes_json_template.json",
            pages_data_path="1726054206064_451_pages.json",
        )
        analyzer.process_notes()
        output_path = (
            f'notes_json_template_filled_{start_time.strftime("%Y%m%d_%H%M%S")}.json'
        )
        analyzer.save_output(output_path)
        logger.info(f"Document analysis completed in {datetime.now() - start_time}")
    except Exception as e:
        logger.error(f"Program failed: {e}")
        exit(1)


if __name__ == "__main__":
    main()
