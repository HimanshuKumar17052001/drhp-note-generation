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


def convert_citations_to_int():
    """Convert citations array from strings to integers in checklist_outputs collection."""
    try:
        # Connect to database
        MONGODB_URI, DB_NAME = connect_to_db()

        # Import after connection is established
        from pymongo import MongoClient

        # Connect using pymongo for direct operations
        client = MongoClient(MONGODB_URI)
        db = client[DB_NAME]

        print("Starting conversion of citations from strings to integers...")

        # Convert checklist_outputs collection
        checklist_collection = db.checklist_outputs
        converted_count = 0
        error_count = 0
        skipped_count = 0

        print("\nProcessing checklist_outputs collection...")

        # Find all documents that have citations array with string values
        for doc in checklist_collection.find(
            {"citations": {"$exists": True, "$ne": None}}
        ):
            try:
                doc_id = doc["_id"]
                topic = doc.get("topic", "Unknown")
                old_citations = doc.get("citations", [])

                # Skip if citations is already empty or None
                if not old_citations:
                    skipped_count += 1
                    continue

                # Check if citations contains any strings
                has_strings = any(
                    isinstance(citation, str) for citation in old_citations
                )
                if not has_strings:
                    skipped_count += 1
                    continue

                # Convert string citations to integers
                new_citations = []
                conversion_errors = []

                for citation in old_citations:
                    if isinstance(citation, str):
                        try:
                            new_citation = int(citation)
                            new_citations.append(new_citation)
                        except (ValueError, TypeError):
                            # If conversion fails, skip this citation
                            conversion_errors.append(citation)
                            print(
                                f"    ⚠️  Could not convert citation '{citation}' to int, skipping"
                            )
                    else:
                        # Keep non-string values as they are
                        new_citations.append(citation)

                # Update the document
                checklist_collection.update_one(
                    {"_id": doc_id}, {"$set": {"citations": new_citations}}
                )
                converted_count += 1

                if conversion_errors:
                    print(
                        f"  ✓ Updated checklist {doc_id} ({topic}): {len(old_citations)} citations, {len(conversion_errors)} failed conversions"
                    )
                else:
                    print(
                        f"  ✓ Updated checklist {doc_id} ({topic}): {len(old_citations)} citations converted"
                    )

            except Exception as e:
                error_count += 1
                print(f"  ✗ Error updating checklist {doc.get('_id')}: {e}")

        # Count documents with different citation types
        total_count = checklist_collection.count_documents(
            {"citations": {"$exists": True}}
        )
        string_citations_count = checklist_collection.count_documents(
            {"citations": {"$elemMatch": {"$type": "string"}}}
        )
        int_citations_count = checklist_collection.count_documents(
            {"citations": {"$elemMatch": {"$type": "int"}}}
        )

        print(f"\n=== CONVERSION SUMMARY ===")
        print(f"Checklists processed: {converted_count}")
        print(f"Errors: {error_count}")
        print(f"Skipped (no conversion needed): {skipped_count}")
        print(f"Total with citations: {total_count}")
        print(f"Still have string citations: {string_citations_count}")
        print(f"Have integer citations: {int_citations_count}")

        if error_count == 0 and string_citations_count == 0:
            print("✅ All citations converted to integers successfully!")
        elif string_citations_count > 0:
            print(f"⚠️  {string_citations_count} documents still have string citations")
        else:
            print("⚠️  Some conversions failed. Check the errors above.")

        # Close connection
        client.close()
        disconnect(alias="core")

    except Exception as e:
        print(f"Error during conversion: {e}")
        sys.exit(1)


def verify_conversion():
    """Verify that all citations arrays contain only integers."""
    try:
        # Connect to database
        MONGODB_URI, DB_NAME = connect_to_db()

        from pymongo import MongoClient

        # Connect using pymongo for direct operations
        client = MongoClient(MONGODB_URI)
        db = client[DB_NAME]

        print("\n=== VERIFICATION ===")

        # Check checklist_outputs collection
        checklist_collection = db.checklist_outputs
        total_count = checklist_collection.count_documents(
            {"citations": {"$exists": True}}
        )
        string_citations_count = checklist_collection.count_documents(
            {"citations": {"$elemMatch": {"$type": "string"}}}
        )
        int_citations_count = checklist_collection.count_documents(
            {"citations": {"$elemMatch": {"$type": "int"}}}
        )

        print(f"checklist_outputs collection:")
        print(f"  Total with citations: {total_count}")
        print(f"  String citations: {string_citations_count}")
        print(f"  Integer citations: {int_citations_count}")

        if string_citations_count == 0:
            print("✅ All citations are now integers!")
        else:
            print(f"⚠️  {string_citations_count} documents still have string citations")

        # Show some examples of current citation values
        print(f"\n=== SAMPLE CITATIONS ===")
        sample_docs = list(
            checklist_collection.find({"citations": {"$exists": True}}).limit(5)
        )
        for doc in sample_docs:
            doc_id = doc.get("_id")
            topic = doc.get("topic", "Unknown")
            citations = doc.get("citations", [])
            citation_types = [type(citation).__name__ for citation in citations]
            print(
                f"  Checklist {doc_id} ({topic}): citations={citations} (types: {citation_types})"
            )

        # Close connection
        client.close()
        disconnect(alias="core")

    except Exception as e:
        print(f"Error during verification: {e}")
        sys.exit(1)


def show_statistics():
    """Show detailed statistics about citations arrays."""
    try:
        # Connect to database
        MONGODB_URI, DB_NAME = connect_to_db()

        from pymongo import MongoClient

        # Connect using pymongo for direct operations
        client = MongoClient(MONGODB_URI)
        db = client[DB_NAME]

        print("\n=== DETAILED STATISTICS ===")

        # Check checklist_outputs collection
        checklist_collection = db.checklist_outputs
        total_count = checklist_collection.count_documents({})
        has_citations = checklist_collection.count_documents(
            {"citations": {"$exists": True}}
        )

        if total_count == 0:
            print("No documents found in checklist_outputs collection.")
            return

        # Count by citation type
        string_citations_count = checklist_collection.count_documents(
            {"citations": {"$elemMatch": {"$type": "string"}}}
        )
        int_citations_count = checklist_collection.count_documents(
            {"citations": {"$elemMatch": {"$type": "int"}}}
        )
        empty_citations_count = checklist_collection.count_documents(
            {"citations": {"$size": 0}}
        )

        print(f"Total checklists: {total_count}")
        print(f"Have citations: {has_citations}")
        print(f"String citations: {string_citations_count}")
        print(f"Integer citations: {int_citations_count}")
        print(f"Empty citations: {empty_citations_count}")

        # Show some examples that still have string citations
        if string_citations_count > 0:
            print(f"\n=== CHECKLISTS WITH STRING CITATIONS ===")
            docs_with_strings = list(
                checklist_collection.find(
                    {"citations": {"$elemMatch": {"$type": "string"}}}
                ).limit(10)
            )
            for doc in docs_with_strings:
                doc_id = doc.get("_id")
                topic = doc.get("topic", "Unknown")
                citations = doc.get("citations", [])
                print(f"  Checklist {doc_id} ({topic}): citations={citations}")

        # Close connection
        client.close()
        disconnect(alias="core")

    except Exception as e:
        print(f"Error during statistics: {e}")
        sys.exit(1)


if __name__ == "__main__":
    print("DRHP MongoDB Citations Conversion Script")
    print("=" * 45)

    # Validate environment
    validate_env()

    # Ask user what to do
    print("\nWhat would you like to do?")
    print("1. Convert citations from strings to integers")
    print("2. Verify conversion results")
    print("3. Show detailed statistics")
    print("4. Both convert and verify")

    choice = input("\nEnter your choice (1, 2, 3, or 4): ").strip()

    if choice == "1":
        convert_citations_to_int()
    elif choice == "2":
        verify_conversion()
    elif choice == "3":
        show_statistics()
    elif choice == "4":
        convert_citations_to_int()
        verify_conversion()
    else:
        print("Invalid choice. Exiting.")
        sys.exit(1)
