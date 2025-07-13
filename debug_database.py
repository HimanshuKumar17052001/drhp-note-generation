#!/usr/bin/env python3
"""
Debug script to check database contents
"""

import os
import sys
from datetime import datetime
from dotenv import load_dotenv

# Add the backend directory to the Python path
sys.path.append(os.path.join(os.path.dirname(__file__), "DRHP_crud_backend"))

# Load environment variables
load_dotenv()

# Import MongoDB models
from mongoengine import connect, disconnect
from api import Company, FinalMarkdown


def check_database():
    """Check database contents"""
    try:
        # Connect to database
        MONGODB_URI = os.getenv("DRHP_MONGODB_URI")
        DB_NAME = os.getenv("DRHP_DB_NAME", "DRHP_NOTES")

        disconnect(alias="core")
        connect(alias="core", host=MONGODB_URI, db=DB_NAME)

        print("=== Database Debug Information ===")
        print(f"MongoDB URI: {MONGODB_URI}")
        print(f"Database: {DB_NAME}")
        print()

        # Check companies
        companies = Company.objects.all()
        print(f"Total companies in database: {len(companies)}")
        print()

        if companies:
            print("Companies:")
            for company in companies:
                print(f"  ID: {company.id}")
                print(f"  Name: {company.name}")
                print(f"  CIN: {company.corporate_identity_number}")
                print(f"  Status: {company.processing_status}")
                print(f"  Created: {company.created_at}")
                print()
        else:
            print("No companies found in database")
            print()

        # Check markdown documents
        markdown_docs = FinalMarkdown.objects.all()
        print(f"Total markdown documents: {len(markdown_docs)}")
        print()

        if markdown_docs:
            print("Markdown Documents:")
            for doc in markdown_docs:
                print(f"  Company ID: {doc.company_id}")
                print(f"  Company Name: {doc.company_name}")
                print(f"  Generated At: {doc.generated_at}")
                print(f"  Markdown Length: {len(doc.markdown)} characters")
                print()
        else:
            print("No markdown documents found in database")
            print()

        # Check specific company ID
        target_id = "687407dd927a7192cfabb784"
        print(f"Checking specific company ID: {target_id}")

        try:
            from bson import ObjectId

            company = Company.objects.get(id=ObjectId(target_id))
            print(f"  Company found: {company.name}")

            markdown_doc = FinalMarkdown.objects(company_id=company).first()
            if markdown_doc:
                print(f"  Markdown found: {len(markdown_doc.markdown)} characters")
            else:
                print("  No markdown document found for this company")
        except Exception as e:
            print(f"  Error checking company: {e}")

        print()
        print("=== End Debug Information ===")

    except Exception as e:
        print(f"Error connecting to database: {e}")
    finally:
        try:
            disconnect(alias="core")
        except:
            pass


if __name__ == "__main__":
    check_database()
