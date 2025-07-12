#!/usr/bin/env python3
"""
Test script to verify OpenAI embedding integration
"""

import os
import sys
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

try:
    from openai import OpenAI

    print("✅ Successfully imported OpenAI client")
except ImportError as e:
    print(f"❌ Failed to import OpenAI client: {e}")
    print("Make sure you have installed: pip install openai")
    sys.exit(1)


def test_openai_embedding():
    """Test OpenAI embedding generation"""

    print("\n🧪 Testing OpenAI Embedding Client")
    print("=" * 50)

    # Check for API key
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("❌ OPENAI_API_KEY not found in environment variables")
        print("Please set your OpenAI API key in the .env file")
        return False

    try:
        # Initialize OpenAI client
        client = OpenAI(api_key=api_key)

        # Test text for embedding
        test_text = "This is a test text for embedding generation using OpenAI."

        print(f"📤 Sending text for embedding: {test_text}")

        # Generate embedding
        response = client.embeddings.create(
            model="text-embedding-3-small", input=test_text
        )

        embedding = response.data[0].embedding

        print(f"📥 Embedding generated successfully!")
        print(f"📊 Embedding dimensions: {len(embedding)}")
        print(f"📊 First few values: {embedding[:5]}")
        print(f"📊 Last few values: {embedding[-5:]}")
        print("✅ OpenAI embedding test successful!")

        return True

    except Exception as e:
        print(f"❌ OpenAI embedding test failed: {e}")
        print(f"Error type: {type(e).__name__}")

        # Check for common issues
        if "api_key" in str(e).lower():
            print("\n💡 Possible issue: Invalid API key")
            print("Make sure your OPENAI_API_KEY is valid")

        elif "quota" in str(e).lower():
            print("\n💡 Possible issue: API quota exceeded")
            print("Check your OpenAI account usage")

        elif "model" in str(e).lower():
            print("\n💡 Possible issue: Model not available")
            print("Check if text-embedding-3-small is available in your region")

        return False


def test_environment():
    """Test environment variables"""
    print("\n🔧 Testing Environment Configuration")
    print("=" * 50)

    required_vars = ["OPENAI_API_KEY"]

    all_good = True

    for var in required_vars:
        value = os.getenv(var)
        if value:
            # Mask the API key for security
            display_value = value[:4] + "*" * (len(value) - 8) + value[-4:]
            print(f"✅ {var}: {display_value}")
        else:
            print(f"❌ {var}: Not set")
            all_good = False

    if all_good:
        print("✅ All required environment variables are set")
    else:
        print("❌ Some environment variables are missing")

    return all_good


def main():
    """Main test function"""
    print("🚀 OpenAI Embedding Test Script")
    print("=" * 60)

    # Test environment first
    env_ok = test_environment()

    if not env_ok:
        print(
            "\n⚠️ Environment issues detected. Please fix them before running the embedding test."
        )
        return 1

    # Test OpenAI embedding
    embedding_ok = test_openai_embedding()

    if embedding_ok:
        print("\n🎉 All tests passed! OpenAI embeddings are working correctly.")
        return 0
    else:
        print("\n❌ Embedding test failed. Please check the error messages above.")
        return 1


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
