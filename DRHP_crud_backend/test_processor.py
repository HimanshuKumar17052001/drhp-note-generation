import time
import os
import sys
from bson import ObjectId
from DRHP_ai_processing.SEBI_checklist_processor import SebiChecklistProcessor
from DRHP_ai_processing.Standard_checklist_processor import StandardChecklistProcessor
from DRHP_ai_processing.BSE_checklist_processor import BseChecklistProcessor
from DRHP_ai_processing.Litigations_Processor import process_people_and_entities, get_company
from app.models.schemas import Company, CostMap, UploadedDRHP, User
from bson import ObjectId
from mongoengine import connect, get_db, disconnect
from datetime import datetime
from litellm import completion, completion_cost, token_counter
from litellm import cost_per_token
from dotenv import load_dotenv
from app.utils.company_cleaner import CompanyCleaner
from DRHP_ai_processing.pdf_extractor_new import DRHPExtractor
# Load environment variables from .env file
from baml_client import b
from baml_py import Image

load_dotenv()



connect(db=os.getenv("MONGO_DB"), host=os.getenv("MONGO_URI"))

def get_oldest_pending_company():
    """Get oldest pending company using MongoEngine"""
    try:
        # Assuming you have an UploadedDRHP model with these fields
        company = UploadedDRHP.objects(
            processing_status="PENDING"
        ).order_by("+upload_timestamp").first()
        
        if not company:
            print("⚠️ No pending companies found in MongoDB!")
        else:
            print(f"✅ Found pending company: {company.company_name}, ID: {company.id}")
        
        return company
    except Exception as e:
        print(f"❌ Error fetching pending company: {e}")
        return None

def process_document():
    """Main function to process a single DRHP document."""
    oldest_pending_company = get_oldest_pending_company()
    
    if not oldest_pending_company:
        print("✅ No pending companies found. Sleeping for 3 minutes...")
        return
    
    print(f"🔍 Processing company: {oldest_pending_company.company_name}")
    
    start_time = time.time()
    start_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print("this is the starting time", start_time)


    total_input_tokens = 0
    total_output_tokens = 0


    try:
        print("🔄 Processing DRHP document...")
        try:
            pdf_url = oldest_pending_company.uploaded_file_url
            company_name = oldest_pending_company.company_name
            corporate_identity_number = oldest_pending_company.corporate_identity_number
        except Exception as e:
            print(f"❌ Error processing DRHP please reupload the document: {e}")
            CompanyCleaner("Error in EXTRACTION due to " + str(e))
            return
        
        print("this is the pdf_url", pdf_url)
        print("this is the company_name", company_name)
        print("this is the corporate_identity_number", corporate_identity_number)
        
        if not os.path.exists(pdf_url):
            # Check if file is in the new persistent location
            alternative_path = os.path.join(os.getcwd(), "app", "drhp_queue", os.path.basename(pdf_url))
            if os.path.exists(alternative_path):
                pdf_url = alternative_path
                print(f"Using file from persistent volume: {pdf_url}")
        extractor = DRHPExtractor(pdf_url=pdf_url, corporate_identity_number=corporate_identity_number, company_name=company_name)
        result, input_tokens, output_tokens = extractor.run()
        print("done till here")
        company_id = result.id
        total_input_tokens += input_tokens
        total_output_tokens += output_tokens
        print(f"✅ DRHP Processed - Company ID: {company_id}")
    except Exception as e:
        print(f"❌ Error processing DRHP please reupload the document: {e}")
        CompanyCleaner("Error in EXTRACTION due to " + str(e))
        return

 
    
    checklist_processors = {
        "SEBI Checklist": ("process_sebi_checklist", SebiChecklistProcessor),
        "BSE Checklist": ("process_bse_checklist", BseChecklistProcessor),
        "Standard Checklist": ("process_standard_checklist", StandardChecklistProcessor)
    }

    for checklist_name, (function_name, ProcessorClass) in checklist_processors.items():
        print(f"🔄 Processing {checklist_name}...")
        try:
            processor = ProcessorClass(company_id)

            if hasattr(processor, function_name):
                input_tokens, output_tokens = getattr(processor, function_name)()  
                total_input_tokens += input_tokens
                total_output_tokens += output_tokens
                print(f"✅ {checklist_name} processed successfully.")
            else:
                print(f"❌ Error: Function '{function_name}' not found in {ProcessorClass.__name__}")
        
        except Exception as e:
            print(f"❌ Error processing {checklist_name}: {e}")
            CompanyCleaner("Error in " + checklist_name + " due to " + str(e))
            return


    print("🔄 Processing Litigations...")
    try:
        company = get_company(company_id)
        process_people_and_entities(company)
        print("✅ Litigations processed successfully.")
    except Exception as e:
        print(f"❌ Error processing Litigations: {e}")
        CompanyCleaner("Error in Litigations due to " + str(e))
        return

    # Updating Processing Status
    try:
        oldest_pending_company.processing_status = "COMPLETED"
        oldest_pending_company.save()
        
        file_path = oldest_pending_company.uploaded_file_url
        if not os.path.exists(file_path):
            # Check if file is in the new persistent location
            file_path = os.path.join(os.getcwd(), "app", "drhp_queue", os.path.basename(file_path))
        
        if os.path.exists(file_path):
            os.remove(file_path)
            print(f"✅ Removed processed file: {file_path}")
        else:
            print(f"⚠️ File not found: {file_path}")
            
        print(f"✅ Status updated to COMPLETED for {oldest_pending_company.company_name}")
    except Exception as e:
        print(f"❌ Error updating processing status: {e}")
        CompanyCleaner("Error in updating processing status due to " + str(e))
        return
    
    end_time = time.time()
    end_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    total_duration = round(end_time - start_time, 2)
    
    print("this is the end time", end_time)
    print("this is the total duration for the complete process", total_duration)
    
    cost_input_prompt, cost_output_prompt = cost_per_token(
        model=os.getenv("LLM_MODEL"), 
        prompt_tokens=total_input_tokens, 
        completion_tokens=total_output_tokens
    )

    # Create and save cost map using MongoEngine
    cost_map = CostMap(
        company_id=company_id,
        total_input_cost_usd=cost_input_prompt,
        total_output_cost_usd=cost_output_prompt,
        total_processing_time=total_duration,
        uploaded_by=User.objects.first().id
    )
    cost_map.save()
    print("this is the cost_map id", cost_map.id)




if __name__ == "__main__":
    # Ensure database connections are established before starting the loop
    while True:
        start_time = time.time()  # Start time tracking
        start_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")  # Readable format

        print(f"\n⏳ Process started at: {start_timestamp}")

        process_document()  # Call the main processing function

        end_time = time.time()  # End time tracking
        end_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")  # Readable format
        total_duration = round(end_time - start_time, 2)  # Duration in seconds

        print(f"✅ Process completed at: {end_timestamp}")
        print(f"⏱️ Total Processing Time: {total_duration} seconds\n")

        print("added improved checklist criteria ---->> 17-02-2025")
        print("⏳ Sleeping for 3 minutes before next fetch...")
        time.sleep(180)

