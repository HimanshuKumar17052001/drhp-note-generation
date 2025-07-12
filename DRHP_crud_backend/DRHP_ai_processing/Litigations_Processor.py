
import sys
import os

# Get the absolute path to the project root (DRHP_crud_backend)
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(project_root)
import pandas as pd
import json
import mongoengine
from datetime import datetime
from app.models.schemas import PeopleAndEntities, Company
from litellm import completion
import instructor
import os
from dotenv import load_dotenv
load_dotenv()
#import litellm

#litellm.drop_params = True

print(f"Project root added to path: {project_root}")


import json
import requests
import pandas as pd
from datetime import datetime
from app.models.schemas import PeopleAndEntities, Company
from litellm import completion
import instructor
from duckduckgo_search import DDGS
from pydantic import BaseModel
from typing import List, Optional
from bson import ObjectId
import time
from markdownify import markdownify as md
from litellm import token_counter

class Case(BaseModel):
    case_source : str
    case_details : str
    
    
class Debarrment(BaseModel):
    reason_for_debarrment : str
    debarred_from : str
    debarred_till : str
    debarrement_source : str
    
    
class LitigationResponseNew(BaseModel):
    criminal_cases : Optional[List[Case]]
    capital_market_debarrments : Optional[Debarrment]
    adversial_orders : Optional[List[Debarrment]]
    
    
    
class LitigationResponse(BaseModel):
    summary: str
    any_cases_or_debarrments_from_market : bool
   


def connect_to_db():
    mongoengine.connect(
            db=os.getenv('MONGO_DB'),
            host=os.getenv('MONGO_URI'),
            alias='default'
        )    
def disconnect_from_db():
    mongoengine.disconnect()
    print("🔴 Disconnected from MongoDB")

def get_company(company_id):
    company = Company.objects(id=company_id).first()
    if not company:
        raise ValueError(f"Company not found with ID: {company_id}")
    return company

def bing_engine(entity_name, entity_company):
    query = f"Court cases against {entity_name} from {entity_company}"

    headers = {
        "Ocp-Apim-Subscription-Key": '1344549ecdc5471abf4e5eb9f49e629b'
    }

    params = {
        "q": query,
        "textDecorations": True,
        "textFormat": "HTML"
    }

    response = requests.get(
        "https://api.bing.microsoft.com/v7.0/search", 
        headers=headers,
        params=params
    )

    if response.status_code == 403:
        query = query.replace("site:topstockresearch.com", "site:groww.in")
        params["q"] = query
        response = requests.get(
            "https://api.bing.microsoft.com/v7.0/search", 
            headers=headers,
            params=params
        )

    response_json = response.json()
    web_pages = response_json.get("webPages", {}).get("value", [])

    all_content_string = ""
    count = 1
    for article in web_pages:
        url = article.get("url")
        snippet = article.get("snippet", "")
        
        if url:
            url_content = get_page_content(url)
            
            snippet_clean = md(snippet, strip=['a', 'img'])
            url_content_clean = md(url_content, strip=['a', 'img'])
            all_content_string += f"Source {count} : {url} \n"
            all_content_string += snippet_clean + "\n"
            all_content_string += url_content_clean + "\n"
            all_content_string += "\n"
            all_content_string += "--------------------------------" + "\n"
            count += 1
            
    return all_content_string

def r_jina_engine(bing_search_query, no_of_srcs=1):
    initial_urls = bing_engine(bing_search_query)[:no_of_srcs]
    if any('moneycontrol' in url.lower() for url in initial_urls):
        bing_search_query += " -site:moneycontrol.com"
        initial_urls = bing_engine(bing_search_query)[:no_of_srcs]
    bing_urls = initial_urls
    headers = {
        "Accept": "application/json",
        "X-Return-Format": "text",
    }
    result = ""
    for i, url in enumerate(bing_urls):
        try:
            response = requests.get(f"https://r.jina.ai/{url}", headers=headers)
            if response.status_code == 200:
                data = response.json()
                web_chunk = data['data']['text']
                if no_of_srcs == 1:
                    return web_chunk
                else:
                    link_name = f"Source {i+1}"
                    result += f"Text chunks for {link_name}[{url}]\n{web_chunk}\n\n"
            elif response.status_code != 402:
                print(f"Unexpected status code {response.status_code} for URL: {url}")
        except Exception as e:
            print(f"Error fetching data from {url}: {e}")
    return result


def get_page_content(url):
    """Fetch page content from a URL."""
    try:
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            return response.text[:5000]  # Limit text to avoid exceeding token limits
    except Exception as e:
        print(f"Error fetching content from {url}: {e}")
    return ""



from concurrent.futures import ThreadPoolExecutor, as_completed

def process_single_entity(entity, company, search_dict, llm_client):
    try:
        company_name = company.name
        entity_company = company_name
        print(f"🚀 Starting entity: {entity.name}")

        litigation_text = bing_engine(entity.name, entity_company)

        search_result = search_dict.get(entity.name.lower(), None)

        mistral_prompt = f"""Go through the following litigation text I found from the web search,
and give me a short summary of the cases and debarrments given in the text. Your response should be clear,
with the URL (VERY IMPORTANT TO SPECIFY THE URL IN YOUR RESPONSE), the source name, and the case details.

{litigation_text}
"""

        input_to_mistral_tokens = token_counter(
            model=os.getenv("LLM_MODEL_SUMMARIZER"),
            messages=[{"role": "user", "content": mistral_prompt}]
        )
        print(f"🔢 Input tokens to Mistral for {entity.name}: {input_to_mistral_tokens}")

        response = completion(
            model=os.getenv("LLM_MODEL_SUMMARIZER"),
            messages=[{"content": mistral_prompt, "role": "user"}]
        )
        summarized_response = response['choices'][0]['message']['content']
        print(f"✅ Mistral summary completed for {entity.name}")

        prompt = f"""
You are analyzing regulatory risk for a company filing its DRHP.
Below are details of a person/entity involved, along with related litigations and debarred information (if available).
Structure this information clearly and analyze potential risks.

Company Name: {company.name}
Corporate Identity Number: {company.corporate_identity_number}
DRHP File URL: {company.drhp_file_url}
Website: {company.website_link}

Entity Name: {entity.name}

Please ensure the entity name exactly matches the debarred name and the name in litigations. Only consider cases filed in Indian courts and from Indian websites. If the name of the entity differs even slightly, do not consider that case. PLEASE FOLLOW THIS STRICTLY. 
For example, do not consider cases mentioning only the company without the specific entity involved.

--- Litigation Cases (Web Search) ---
{summarized_response}

--- Debarred List Information ---
{search_result if search_result else "No debarred record found."}

Provide a structured summary. Please provide the summary of case details in the case details section, and wherever there is a null response, return "No debarrement found", "No litigation found," etc.
"""

        structured_response = llm_client.chat.completions.create(
            model=os.getenv("LLM_MODEL"),
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            response_model=LitigationResponseNew
        )

        is_criminal_empty = not structured_response.criminal_cases or len(structured_response.criminal_cases) == 0
        is_capital_market_empty = structured_response.capital_market_debarrments is None
        is_adversial_empty = not structured_response.adversial_orders or len(structured_response.adversial_orders) == 0

        entity.status = "NOT FLAGGED" if (is_criminal_empty and is_capital_market_empty and is_adversial_empty) else "FLAGGED"
        entity.summary_analysis = structured_response.model_dump()
        entity.save()

        print(f"🎉 Completed processing entity: {entity.name}")
    except Exception as e:
        print(f"❌ Error processing entity {entity.name}: {e}")

def process_people_and_entities(company):
    path = "/home/ubuntu/backend/DRHP_crud_backend/debarred_data/Debarred_Entities.json"
    # path = "/home/ubuntu/drhp-analyser-new/DRHP_crud_backend/debarred_data/Debarred_Entities.json"
    with open(path, "r") as f:
        search_dict = json.load(f)

    llm_client = instructor.from_litellm(completion)
    people_entities = list(PeopleAndEntities.objects(company_id=company))

    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = [
            executor.submit(process_single_entity, entity, company, search_dict, llm_client)
            for entity in people_entities
        ]

        for future in as_completed(futures):
            try:
                future.result()
            except Exception as e:
                print(f"❌ Error in future execution: {e}")

    print("✅ All people and entities processed successfully!")


# Example usage
if __name__ == "__main__":
    connect_to_db()
    company_id = "684bede4977846bf732b1dd3"  # Replace with actual company ID
    company = get_company(company_id)
    process_people_and_entities(company)
    disconnect_from_db()
