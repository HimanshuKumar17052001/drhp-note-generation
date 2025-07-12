import fitz 
import os
from typing import Tuple, Optional, List
import logging
from tenacity import retry, stop_after_attempt, wait_exponential, before_sleep_log
from litellm import completion
import instructor
from pydantic import BaseModel
import time
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()
logger = logging.getLogger(__name__)
llm_client = instructor.from_litellm(completion)

#now using pymupdf an fitx
class TOC(BaseModel):
    is_toc: bool

def check_if_toc_with_llm(page_text):
    """
    Use LLM to determine if a page is a Table of Contents page.
    Uses exponential backoff for retrying failed API calls.
    """
    system_prompt = """
        A Table of Contents (TOC) in a document typically contains :
        1. Has a heading that says "TABLE OF CONTENTS" or "CONTENTS"
        2. Contains a list of drhp sections and their page number, typical drhp sections are:
    
        I. GENERAL
        DEFINITIONS AND ABBREVIATIONS
        CERTAIN CONVENTIONS, USE OF FINANCIAL INFORMATION AND MARKET 
        DATA AND CURRENCY OF FINANCIAL PRESENTATION
        FORWARD LOOKING STATEMENTS 
        II. SUMMARY OF DRAFT RED HERRING PROSPECTUS 
        III. RISK FACTORS 
        IV. INTRODUCTION 
        THE ISSUE 
        SUMMARY OF OUR FINANCIAL STATEMENTS 
        GENERAL INFORMATION 
        CAPITAL STRUCTURE 
        OBJECTS OF THE ISSUE 
        BASIS FOR ISSUE PRICE 
        STATEMENT OF SPECIAL TAX BENEFITS 
        V. ABOUT THE COMPANY 
        INDUSTRY OVERVIEW 
        OUR BUSINESS 
        KEY INDUSTRY REGULATIONS AND POLICIES 
        HISTORY AND CORPORATE STRUCTURE 
        OUR MANAGEMENT 
        OUR PROMOTERS AND PROMOTER GROUP 
        DIVIDEND POLICY 
        VI. FINANCIAL INFORMATION OF THE COMPANY 
        RESTATED FINANCIAL STATEMENTS 
        MANAGEMENT'S DISCUSSION AND ANALYSIS OF FINANCIAL CONDITIONS AND 
        RESULTS OF OPERATIONS
        OTHER FINANCIAL INFORMATION 
        STATEMENT OF FINANCIAL INDEBTEDNESS 
        CAPITALISATION STATEMENT 
        VII. LEGAL AND OTHER INFORMATION 
        OUTSTANDING LITIGATIONS AND MATERIAL DEVELOPMENTS 
        GOVERNMENT AND OTHER APPROVALS 
        OUR GROUP COMPANY 
        OTHER REGULATORY AND STATUTORY DISCLOSURES 
        VIII. ISSUE RELATED INFORMATION 
        TERMS OF THE ISSUE 
        ISSUE STRUCTURE 
        ISSUE PROCEDURE 
        RESTRICTIONS ON FOREIGN OWNERSHIP OF INDIAN SECURITIES 
        IX. MAIN PROVISIONS OF ARTICLES OF ASSOCIATION OF OUR COMPANY 
        X. OTHER INFORMATION 
        MATERIAL CONTRACTS AND DOCUMENTS FOR INSPECTION 
        XI DECLARATION 

        3. Naming of sections is not always consistent, so you should not be too strict about the exact text of the sections, section name may vary a little bit here and there, but u need to identify the structure.
        You should identify a page as a TOC if it shows these characteristics.
    """
    
    user_prompt = f"""
    Please analyze the following page text and determine if it is a Table of Contents page, of a drhp document.
    
    Page text:
    {page_text}
    
    Is this a Table of Contents page?
    """
    max_retries = 5
    base_delay = 1  # Initial delay in seconds
    
    for attempt in range(max_retries):
        try:
            response = llm_client.chat.completions.create(
                model=os.getenv("LLM_MODEL"),
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                response_model=TOC,
                temperature=0.0
            )
            return response
        except Exception as e:
            if attempt == max_retries - 1:  # Last attempt
                print(f"Final error in LLM call after {max_retries} retries: {e}")
                raise  # Re-raise the exception after all retries are exhausted
            
            delay = base_delay * (2 ** attempt)  # Exponential backoff
            print(f"Attempt {attempt + 1} failed. Retrying in {delay} seconds... Error: {e}")
            time.sleep(delay)

def extract_text_from_pdf(pdf_path: str, max_pages: int = 10) -> List[Tuple[int, str]]:
    """
    Extract text from the first `max_pages` pages of a PDF using PyMuPDF.
    """
    extracted_text = []
    try:
        with fitz.open(pdf_path) as doc:
            for page_num in range(min(max_pages, doc.page_count)):
                page = doc[page_num]
                text = page.get_text()
                if text:
                    extracted_text.append((page_num + 1, text))
    except Exception as e:
        logger.error(f"Error extracting text from PDF: {str(e)}")
        raise
    return extracted_text

def extract_toc_pages(input_pdf_path: str, output_pdf_path: str) -> Tuple[Optional[int], Optional[int], Optional[str]]:
    """
    Extract and save Table of Contents (TOC) pages using PyMuPDF
    """
    print(f"\nProcessing PDF: {input_pdf_path}")
    
    try:
        # Step 1: Extract text from first 10 pages
        text_data = extract_text_from_pdf(input_pdf_path, max_pages=10)
        
        # For debugging
        with open("extracted_text_data.txt", "w", encoding='utf-8') as file:
            for page_num, text in text_data:
                file.write(f"Page {page_num}:\n{text}\n{'='*50}\n")
        
        # Step 2: Check each page with LLM until TOC is found
        start_page = None
        end_page = None
        
        for page_num, text in text_data:
            is_toc = check_if_toc_with_llm(text)
            if is_toc.is_toc:
                print(f"{page_num} is a toc page")
                if start_page is None:
                    start_page = page_num
                end_page = page_num
            else:
                print(f"{page_num} is not a toc page")
                if start_page is not None:
                    # We've found the end of the TOC section
                    break
        
        if start_page is None:
            print("\n❌ No Table of Contents (TOC) found in the document!")
            return None, None, None

        print(f"\n✅ TOC found from page {start_page} to {end_page}")

        # Step 3: Extract TOC pages to a new PDF
        try:
            doc = fitz.open(input_pdf_path)
            new_doc = fitz.open()
            
            # Copy TOC pages to new document
            for page_num in range(start_page - 1, end_page):
                new_doc.insert_pdf(doc, from_page=page_num, to_page=page_num)
            
            # Save the new document
            new_doc.save(output_pdf_path)
            new_doc.close()
            doc.close()
            
            print(f"\n🎉 Successfully extracted TOC content to {output_pdf_path}")
            return start_page, end_page, output_pdf_path

        except Exception as pdf_error:
            print(f"\n⚠️ Error in PDF processing: {str(pdf_error)}")
            return start_page, end_page, None

    except Exception as e:
        print(f"\n❌ Error in TOC extraction: {str(e)}")
        return None, None, None 

if __name__ == "__main__":
    try:
        # Get the absolute path to the current directory
        current_dir = os.path.dirname(os.path.abspath(__file__))
        file_name = "DRHP_Retaggio_20240104183702.pdf"
        file_path = os.path.join(current_dir, file_name)
        
        print(f"Current directory: {current_dir}")
        print(f"Looking for PDF at: {file_path}")
        
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"PDF file not found at path: {file_path}")
            
        uploader = UploadToBlob()
        print(f"Uploading file: {file_name}")
        
        # Open the file in binary read mode and pass the file object
        with open(file_path, 'rb') as file_obj:
            success, pdf_url = uploader.upload_to_blob(file_obj, file_name)
        
        if success:
            print(f"✅ Successfully uploaded PDF. URL: {pdf_url}")
            print("Starting DRHP extraction...")
            
            # Initialize MongoDB connection before running extraction
            connect(
                db=os.getenv('MONGO_DB'),
                host=os.getenv('MONGO_URI'),
                alias='default'
            )
            print("✅ Connected to MongoDB")
            
            # Create extractor with the S3 URL
            extractor = DRHPExtractor(pdf_url=pdf_url)
            
            # Run the extraction
            company = extractor.run()
            print(f"✅ DRHP extraction completed successfully! Company ID: {company.id}")
            
            # Disconnect from MongoDB
            connect().disconnect()
            print("✅ Disconnected from MongoDB")
            
        else:
            print(f"❌ Failed to upload PDF: {pdf_url}")

    except FileNotFoundError as e:
        print(f"❌ {str(e)}")
    except Exception as e:
        print(f"❌ Error during execution: {str(e)}")
        import traceback
        print(traceback.format_exc()) 
