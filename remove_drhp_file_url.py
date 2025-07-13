import os
import sys
from datetime import datetime
from dotenv import load_dotenv
from mongoengine import connect, disconnect

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


def remove_drhp_file_url():
    """Remove drhp_file_url field from Company collection."""
    try:
        # Connect to database
        MONGODB_URI, DB_NAME = connect_to_db()

        # Import after connection is established
        from pymongo import MongoClient

        # Connect using pymongo for direct operations
        client = MongoClient(MONGODB_URI)
        db = client[DB_NAME]

        print("Starting removal of drhp_file_url field from Company collection...")

        # Remove drhp_file_url from company collection
        company_collection = db.company
        removed_count = 0
        error_count = 0

        print("\nProcessing company collection...")

        # Find all documents that have drhp_file_url field
        for doc in company_collection.find({"drhp_file_url": {"$exists": True}}):
            try:
                company_id = doc["_id"]
                company_name = doc.get("name", "Unknown")
                old_drhp_file_url = doc.get("drhp_file_url", "")

                # Remove the drhp_file_url field
                company_collection.update_one(
                    {"_id": company_id}, {"$unset": {"drhp_file_url": ""}}
                )
                removed_count += 1
                print(f"  ✓ Removed drhp_file_url from {company_name} ({company_id})")

            except Exception as e:
                error_count += 1
                print(f"  ✗ Error removing drhp_file_url from {doc.get('_id')}: {e}")

        # Count documents that still have drhp_file_url
        remaining_count = company_collection.count_documents(
            {"drhp_file_url": {"$exists": True}}
        )
        total_count = company_collection.count_documents({})

        print(f"\n=== REMOVAL SUMMARY ===")
        print(f"Companies processed: {removed_count}")
        print(f"Errors: {error_count}")
        print(f"Total companies: {total_count}")
        print(f"Still have drhp_file_url: {remaining_count}")

        if error_count == 0 and remaining_count == 0:
            print("✅ All drhp_file_url fields removed successfully!")
        elif remaining_count > 0:
            print(f"⚠️  {remaining_count} documents still have drhp_file_url field")
        else:
            print("⚠️  Some removals failed. Check the errors above.")

        # Close connection
        client.close()
        disconnect(alias="core")

    except Exception as e:
        print(f"Error during removal: {e}")
        sys.exit(1)


def verify_removal():
    """Verify that all drhp_file_url fields have been removed."""
    try:
        # Connect to database
        MONGODB_URI, DB_NAME = connect_to_db()

        from pymongo import MongoClient

        # Connect using pymongo for direct operations
        client = MongoClient(MONGODB_URI)
        db = client[DB_NAME]

        print("\n=== VERIFICATION ===")

        # Check company collection
        company_collection = db.company
        total_count = company_collection.count_documents({})
        remaining_count = company_collection.count_documents(
            {"drhp_file_url": {"$exists": True}}
        )

        print(f"company collection:")
        print(f"  Total documents: {total_count}")
        print(f"  Still have drhp_file_url: {remaining_count}")

        if remaining_count == 0:
            print("✅ All drhp_file_url fields have been removed!")
        else:
            print(f"⚠️  {remaining_count} documents still have drhp_file_url field")

        # Show some examples of current company documents
        print(f"\n=== SAMPLE COMPANY DOCUMENTS ===")
        sample_docs = list(company_collection.find().limit(5))
        for doc in sample_docs:
            company_id = doc.get("_id")
            company_name = doc.get("name", "Unknown")
            corporate_id = doc.get("corporate_identity_number", "Unknown")
            has_drhp_file_url = "drhp_file_url" in doc
            print(
                f"  Company {company_id}: {company_name} (CIN: {corporate_id}) - has drhp_file_url: {has_drhp_file_url}"
            )

        # Close connection
        client.close()
        disconnect(alias="core")

    except Exception as e:
        print(f"Error during verification: {e}")
        sys.exit(1)


def show_statistics():
    """Show detailed statistics about drhp_file_url field."""
    try:
        # Connect to database
        MONGODB_URI, DB_NAME = connect_to_db()

        from pymongo import MongoClient

        # Connect using pymongo for direct operations
        client = MongoClient(MONGODB_URI)
        db = client[DB_NAME]

        print("\n=== DETAILED STATISTICS ===")

        # Check company collection
        company_collection = db.company
        total_count = company_collection.count_documents({})

        if total_count == 0:
            print("No documents found in company collection.")
            return

        # Count by field existence
        has_drhp_file_url = company_collection.count_documents(
            {"drhp_file_url": {"$exists": True}}
        )
        no_drhp_file_url = company_collection.count_documents(
            {"drhp_file_url": {"$exists": False}}
        )

        print(f"Total companies: {total_count}")
        print(f"Have drhp_file_url: {has_drhp_file_url}")
        print(f"No drhp_file_url: {no_drhp_file_url}")

        # Show some examples that still have drhp_file_url
        if has_drhp_file_url > 0:
            print(f"\n=== COMPANIES WITH DRHP_FILE_URL ===")
            docs_with_url = list(
                company_collection.find({"drhp_file_url": {"$exists": True}}).limit(10)
            )
            for doc in docs_with_url:
                company_id = doc.get("_id")
                company_name = doc.get("name", "Unknown")
                drhp_file_url = doc.get("drhp_file_url", "")
                print(
                    f"  Company {company_id}: {company_name} - drhp_file_url: {drhp_file_url}"
                )

        # Close connection
        client.close()
        disconnect(alias="core")

    except Exception as e:
        print(f"Error during statistics: {e}")
        sys.exit(1)


if __name__ == "__main__":
    print("DRHP MongoDB Remove DRHP File URL Script")
    print("=" * 45)

    # Validate environment
    validate_env()

    # Ask user what to do
    print("\nWhat would you like to do?")
    print("1. Remove drhp_file_url field from Company collection")
    print("2. Verify removal results")
    print("3. Show detailed statistics")
    print("4. Both remove and verify")

    choice = input("\nEnter your choice (1, 2, 3, or 4): ").strip()

    if choice == "1":
        remove_drhp_file_url()
    elif choice == "2":
        verify_removal()
    elif choice == "3":
        show_statistics()
    elif choice == "4":
        remove_drhp_file_url()
        verify_removal()
    else:
        print("Invalid choice. Exiting.")
        sys.exit(1)
