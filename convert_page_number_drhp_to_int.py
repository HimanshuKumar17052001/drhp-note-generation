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


def convert_page_number_drhp_to_int():
    """Convert page_number_drhp from string to integer in pages collection."""
    try:
        # Connect to database
        MONGODB_URI, DB_NAME = connect_to_db()

        # Import after connection is established
        from pymongo import MongoClient

        # Connect using pymongo for direct operations
        client = MongoClient(MONGODB_URI)
        db = client[DB_NAME]

        print("Starting conversion of page_number_drhp from string to integer...")

        # Convert pages collection
        pages_collection = db.pages
        converted_count = 0
        error_count = 0
        skipped_count = 0

        print("\nProcessing pages collection...")

        # Find all documents where page_number_drhp is a string
        for doc in pages_collection.find({"page_number_drhp": {"$type": "string"}}):
            try:
                old_page_number = doc["page_number_drhp"]

                # Try to convert to integer
                try:
                    new_page_number = int(old_page_number)
                except (ValueError, TypeError):
                    # If conversion fails, set to 0
                    new_page_number = 0
                    print(
                        f"  ⚠️  Could not convert '{old_page_number}' to int, setting to 0"
                    )

                # Update the document
                pages_collection.update_one(
                    {"_id": doc["_id"]}, {"$set": {"page_number_drhp": new_page_number}}
                )
                converted_count += 1
                print(
                    f"  ✓ Updated page {doc.get('_id')}: '{old_page_number}' → {new_page_number}"
                )

            except Exception as e:
                error_count += 1
                print(f"  ✗ Error updating page {doc.get('_id')}: {e}")

        # Count documents that already have integer page_number_drhp
        integer_count = pages_collection.count_documents(
            {"page_number_drhp": {"$type": "int"}}
        )
        string_count = pages_collection.count_documents(
            {"page_number_drhp": {"$type": "string"}}
        )
        null_count = pages_collection.count_documents(
            {"page_number_drhp": {"$type": "null"}}
        )

        print(f"\n=== CONVERSION SUMMARY ===")
        print(f"Pages converted: {converted_count}")
        print(f"Errors: {error_count}")
        print(f"Already integer: {integer_count}")
        print(f"Still string: {string_count}")
        print(f"Null values: {null_count}")

        if error_count == 0 and string_count == 0:
            print("✅ All page_number_drhp values converted to integer successfully!")
        elif string_count > 0:
            print(f"⚠️  {string_count} documents still have string page_number_drhp")
        else:
            print("⚠️  Some conversions failed. Check the errors above.")

        # Close connection
        client.close()
        disconnect(alias="core")

    except Exception as e:
        print(f"Error during conversion: {e}")
        sys.exit(1)


def verify_conversion():
    """Verify that all page_number_drhp fields are now integer type."""
    try:
        # Connect to database
        MONGODB_URI, DB_NAME = connect_to_db()

        from pymongo import MongoClient

        # Connect using pymongo for direct operations
        client = MongoClient(MONGODB_URI)
        db = client[DB_NAME]

        print("\n=== VERIFICATION ===")

        # Check pages collection
        pages_collection = db.pages
        string_count = pages_collection.count_documents(
            {"page_number_drhp": {"$type": "string"}}
        )
        int_count = pages_collection.count_documents(
            {"page_number_drhp": {"$type": "int"}}
        )
        null_count = pages_collection.count_documents(
            {"page_number_drhp": {"$type": "null"}}
        )
        total_count = pages_collection.count_documents({})

        print(f"pages collection:")
        print(f"  Total documents: {total_count}")
        print(f"  String page_number_drhp: {string_count}")
        print(f"  Integer page_number_drhp: {int_count}")
        print(f"  Null page_number_drhp: {null_count}")

        if string_count == 0:
            print("✅ All page_number_drhp values are now integers!")
        else:
            print(f"⚠️  {string_count} documents still have string page_number_drhp")

        # Show some examples of current values
        print(f"\n=== SAMPLE VALUES ===")
        sample_docs = list(pages_collection.find().limit(5))
        for doc in sample_docs:
            page_id = doc.get("_id")
            page_number_drhp = doc.get("page_number_drhp")
            page_number_pdf = doc.get("page_number_pdf")
            print(
                f"  Page {page_id}: page_number_drhp={page_number_drhp} (type: {type(page_number_drhp).__name__}), page_number_pdf={page_number_pdf}"
            )

        # Close connection
        client.close()
        disconnect(alias="core")

    except Exception as e:
        print(f"Error during verification: {e}")
        sys.exit(1)


def show_statistics():
    """Show detailed statistics about page_number_drhp values."""
    try:
        # Connect to database
        MONGODB_URI, DB_NAME = connect_to_db()

        from pymongo import MongoClient

        # Connect using pymongo for direct operations
        client = MongoClient(MONGODB_URI)
        db = client[DB_NAME]

        print("\n=== DETAILED STATISTICS ===")

        # Check pages collection
        pages_collection = db.pages
        total_count = pages_collection.count_documents({})

        if total_count == 0:
            print("No documents found in pages collection.")
            return

        # Count by type
        string_count = pages_collection.count_documents(
            {"page_number_drhp": {"$type": "string"}}
        )
        int_count = pages_collection.count_documents(
            {"page_number_drhp": {"$type": "int"}}
        )
        null_count = pages_collection.count_documents(
            {"page_number_drhp": {"$type": "null"}}
        )
        missing_count = pages_collection.count_documents(
            {"page_number_drhp": {"$exists": False}}
        )

        print(f"Total pages: {total_count}")
        print(f"String page_number_drhp: {string_count}")
        print(f"Integer page_number_drhp: {int_count}")
        print(f"Null page_number_drhp: {null_count}")
        print(f"Missing page_number_drhp: {missing_count}")

        # Show some string examples that need conversion
        if string_count > 0:
            print(f"\n=== STRING VALUES TO CONVERT ===")
            string_docs = list(
                pages_collection.find({"page_number_drhp": {"$type": "string"}}).limit(
                    10
                )
            )
            for doc in string_docs:
                page_id = doc.get("_id")
                page_number_drhp = doc.get("page_number_drhp")
                page_number_pdf = doc.get("page_number_pdf")
                print(
                    f"  Page {page_id}: page_number_drhp='{page_number_drhp}' (string), page_number_pdf={page_number_pdf}"
                )

        # Close connection
        client.close()
        disconnect(alias="core")

    except Exception as e:
        print(f"Error during statistics: {e}")
        sys.exit(1)


if __name__ == "__main__":
    print("DRHP MongoDB Page Number DRHP Conversion Script")
    print("=" * 55)

    # Validate environment
    validate_env()

    # Ask user what to do
    print("\nWhat would you like to do?")
    print("1. Convert page_number_drhp from string to integer")
    print("2. Verify conversion results")
    print("3. Show detailed statistics")
    print("4. Both convert and verify")

    choice = input("\nEnter your choice (1, 2, 3, or 4): ").strip()

    if choice == "1":
        convert_page_number_drhp_to_int()
    elif choice == "2":
        verify_conversion()
    elif choice == "3":
        show_statistics()
    elif choice == "4":
        convert_page_number_drhp_to_int()
        verify_conversion()
    else:
        print("Invalid choice. Exiting.")
        sys.exit(1)
