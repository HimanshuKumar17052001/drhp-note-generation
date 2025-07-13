import os
import sys
from datetime import datetime
from dotenv import load_dotenv
from mongoengine import connect, disconnect
from bson import ObjectId

# Load environment variables
load_dotenv()


def validate_env():
    """Validate that all required environment variables are set."""
    required_vars = ["DRHP_MONGODB_URI"]
    missing = [v for v in required_vars if not os.getenv(v)]
    if missing:
        print(f"Missing required environment variables: {', '.join(missing)}")
        sys.exit(1)
    print("All required environment variables are set.")


def connect_to_db():
    """Connect to MongoDB database."""
    try:
        # Disconnect if already connected with this alias
        disconnect(alias="core")

        MONGODB_URI = os.getenv("DRHP_MONGODB_URI")
        DB_NAME = os.getenv("DRHP_DB_NAME", "DRHP_NOTES")

        connect(alias="core", host=MONGODB_URI, db=DB_NAME)
        print(f"Connected to MongoDB at {MONGODB_URI}, DB: {DB_NAME}")
        return MONGODB_URI, DB_NAME
    except Exception as e:
        print(f"MongoDB connection error: {e}")
        sys.exit(1)


def convert_company_id_to_objectid():
    """Convert company_id from string to ObjectId in both collections."""
    try:
        # Connect to database
        MONGODB_URI, DB_NAME = connect_to_db()

        # Import after connection is established
        from pymongo import MongoClient

        # Connect using pymongo for direct operations
        client = MongoClient(MONGODB_URI)
        db = client[DB_NAME]

        print("Starting conversion of company_id from string to ObjectId...")

        # Convert checklist_outputs collection
        checklist_collection = db.checklist_outputs
        checklist_count = 0
        checklist_errors = 0

        print("\nProcessing checklist_outputs collection...")
        for doc in checklist_collection.find({"company_id": {"$type": "string"}}):
            try:
                old_company_id = doc["company_id"]
                new_company_id = ObjectId(old_company_id)

                # Update the document
                checklist_collection.update_one(
                    {"_id": doc["_id"]}, {"$set": {"company_id": new_company_id}}
                )
                checklist_count += 1
                print(
                    f"  ✓ Updated checklist_outputs: {old_company_id} → {new_company_id}"
                )

            except Exception as e:
                checklist_errors += 1
                print(f"  ✗ Error updating checklist_outputs {doc.get('_id')}: {e}")

        # Convert final_markdown collection
        markdown_collection = db.final_markdown
        markdown_count = 0
        markdown_errors = 0

        print("\nProcessing final_markdown collection...")
        for doc in markdown_collection.find({"company_id": {"$type": "string"}}):
            try:
                old_company_id = doc["company_id"]
                new_company_id = ObjectId(old_company_id)

                # Update the document
                markdown_collection.update_one(
                    {"_id": doc["_id"]}, {"$set": {"company_id": new_company_id}}
                )
                markdown_count += 1
                print(
                    f"  ✓ Updated final_markdown: {old_company_id} → {new_company_id}"
                )

            except Exception as e:
                markdown_errors += 1
                print(f"  ✗ Error updating final_markdown {doc.get('_id')}: {e}")

        # Summary
        print(f"\n=== CONVERSION SUMMARY ===")
        print(
            f"checklist_outputs: {checklist_count} updated, {checklist_errors} errors"
        )
        print(f"final_markdown: {markdown_count} updated, {markdown_errors} errors")
        print(f"Total: {checklist_count + markdown_count} documents updated")

        if checklist_errors == 0 and markdown_errors == 0:
            print("✅ All conversions completed successfully!")
        else:
            print("⚠️  Some conversions failed. Check the errors above.")

        # Close connection
        client.close()
        disconnect(alias="core")

    except Exception as e:
        print(f"Error during conversion: {e}")
        sys.exit(1)


def verify_conversion():
    """Verify that all company_id fields are now ObjectId type."""
    try:
        # Connect to database
        MONGODB_URI, DB_NAME = connect_to_db()

        from pymongo import MongoClient

        # Connect using pymongo for direct operations
        client = MongoClient(MONGODB_URI)
        db = client[DB_NAME]

        print("\n=== VERIFICATION ===")

        # Check checklist_outputs
        checklist_collection = db.checklist_outputs
        string_count = checklist_collection.count_documents(
            {"company_id": {"$type": "string"}}
        )
        objectid_count = checklist_collection.count_documents(
            {"company_id": {"$type": "objectId"}}
        )

        print(f"checklist_outputs:")
        print(f"  String company_id: {string_count}")
        print(f"  ObjectId company_id: {objectid_count}")

        # Check final_markdown
        markdown_collection = db.final_markdown
        string_count = markdown_collection.count_documents(
            {"company_id": {"$type": "string"}}
        )
        objectid_count = markdown_collection.count_documents(
            {"company_id": {"$type": "objectId"}}
        )

        print(f"final_markdown:")
        print(f"  String company_id: {string_count}")
        print(f"  ObjectId company_id: {objectid_count}")

        # Close connection
        client.close()
        disconnect(alias="core")

    except Exception as e:
        print(f"Error during verification: {e}")
        sys.exit(1)


if __name__ == "__main__":
    print("DRHP MongoDB Company ID Conversion Script")
    print("=" * 50)

    # Validate environment
    validate_env()

    # Ask user what to do
    print("\nWhat would you like to do?")
    print("1. Convert company_id from string to ObjectId")
    print("2. Verify conversion results")
    print("3. Both convert and verify")

    choice = input("\nEnter your choice (1, 2, or 3): ").strip()

    if choice == "1":
        convert_company_id_to_objectid()
    elif choice == "2":
        verify_conversion()
    elif choice == "3":
        convert_company_id_to_objectid()
        verify_conversion()
    else:
        print("Invalid choice. Exiting.")
        sys.exit(1)
