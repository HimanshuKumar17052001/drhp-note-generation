import os
import tempfile
from dotenv import load_dotenv
from azure_blob_utils import get_blob_storage


def test_azure_blob_storage():
    """Test Azure Blob Storage functionality"""
    load_dotenv()

    try:
        # Initialize blob storage
        blob_storage = get_blob_storage()
        print("✅ Azure Blob Storage initialized successfully")

        # Create two test files
        test_content1 = "This is test file 1 for Azure Blob Storage integration"
        test_content2 = "This is test file 2 for Azure Blob Storage integration"
        test_blob_name1 = "test/test_file1.txt"
        test_blob_name2 = "test/test_file2.txt"

        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as f1:
            f1.write(test_content1)
            temp_file_path1 = f1.name
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as f2:
            f2.write(test_content2)
            temp_file_path2 = f2.name

        try:
            # Upload both test files
            blob_url1 = blob_storage.upload_file(temp_file_path1, test_blob_name1)
            print(f"✅ File 1 uploaded successfully: {blob_url1}")
            blob_url2 = blob_storage.upload_file(temp_file_path2, test_blob_name2)
            print(f"✅ File 2 uploaded successfully: {blob_url2}")

            # Check if both blobs exist
            exists1 = blob_storage.blob_exists(test_blob_name1)
            exists2 = blob_storage.blob_exists(test_blob_name2)
            print(f"Blob 1 exists: {exists1}")
            print(f"Blob 2 exists: {exists2}")

            # Download and verify content for both files
            download_path1 = temp_file_path1 + "_downloaded"
            download_path2 = temp_file_path2 + "_downloaded"
            blob_storage.download_file(test_blob_name1, download_path1)
            blob_storage.download_file(test_blob_name2, download_path2)

            with open(download_path1, "r") as f:
                downloaded_content1 = f.read()
            with open(download_path2, "r") as f:
                downloaded_content2 = f.read()

            if downloaded_content1 == test_content1:
                print("✅ File 1 download and content verification passed")
            else:
                print("❌ File 1 content verification failed")
            if downloaded_content2 == test_content2:
                print("✅ File 2 download and content verification passed")
            else:
                print("❌ File 2 content verification failed")

            # Read blob 1 content directly
            print("\nReading blob 1 content directly from Azure Blob Storage:")
            try:
                blob_client1 = blob_storage.container_client.get_blob_client(
                    test_blob_name1
                )
                stream1 = blob_client1.download_blob()
                blob_content1 = stream1.readall().decode("utf-8")
                print(f"Blob 1 content: {blob_content1}")
            except Exception as e:
                print(f"❌ Failed to read blob 1 content directly: {e}")

            # Read blob 2 content directly
            print("\nReading blob 2 content directly from Azure Blob Storage:")
            try:
                blob_client2 = blob_storage.container_client.get_blob_client(
                    test_blob_name2
                )
                stream2 = blob_client2.download_blob()
                blob_content2 = stream2.readall().decode("utf-8")
                print(f"Blob 2 content: {blob_content2}")
            except Exception as e:
                print(f"❌ Failed to read blob 2 content directly: {e}")

            # Clean up: delete only the first blob
            blob_storage.delete_blob(test_blob_name1)
            print("✅ Blob 1 deleted successfully")

            # Clean up local files
            os.unlink(temp_file_path1)
            os.unlink(temp_file_path2)
            os.unlink(download_path1)
            os.unlink(download_path2)

            # Check existence after deletion
            exists1_after = blob_storage.blob_exists(test_blob_name1)
            exists2_after = blob_storage.blob_exists(test_blob_name2)
            print(f"After deletion: Blob 1 exists: {exists1_after}")
            print(f"After deletion: Blob 2 exists: {exists2_after}")

            print(
                "\n🎉 Azure Blob Storage two-file test passed! (Blob 2 remains in storage)"
            )

        except Exception as e:
            print(f"❌ Test failed: {e}")
            # Clean up temp files
            if os.path.exists(temp_file_path1):
                os.unlink(temp_file_path1)
            if os.path.exists(temp_file_path2):
                os.unlink(temp_file_path2)
            raise

    except Exception as e:
        print(f"❌ Azure Blob Storage initialization failed: {e}")
        print(
            "Make sure you have set AZURE_STORAGE_CONNECTION_STRING in your .env file"
        )
        raise


if __name__ == "__main__":
    test_azure_blob_storage()
