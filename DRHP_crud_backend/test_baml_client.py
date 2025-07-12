#!/usr/bin/env python3
"""
Simple test script to verify BAML client configuration
Tests the BedrockClaudeIAM client with a basic prompt
"""

import os
import sys
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Add the current directory to Python path for BAML imports
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

try:
    from baml_client import b

    print("✅ Successfully imported BAML client")
except ImportError as e:
    print(f"❌ Failed to import BAML client: {e}")
    print("Make sure you have run: baml generate")
    sys.exit(1)


def test_bedrock_claude_client():
    """Test the BedrockClaudeIAM client with a simple prompt"""

    print("\n🧪 Testing BedrockClaudeIAM Client")
    print("=" * 50)

    # Test prompt and content
    test_prompt = "What is the main topic of this content?"
    test_content = "This is a test document about artificial intelligence and machine learning. It discusses various AI technologies and their applications in modern computing."

    try:
        print(f"📤 Sending test prompt: {test_prompt}")
        print(f"📄 Test content: {test_content[:50]}...")

        # Call the DirectRetrieval function which uses BedrockClaudeIAM
        response = b.DirectRetrieval(test_prompt, test_content)

        print(f"📥 AI Output: {response.ai_output}")
        print(f"📄 Relevant Pages: {response.relevant_pages}")
        print("✅ BAML client test successful!")

        return True

    except Exception as e:
        print(f"❌ BAML client test failed: {e}")
        print(f"Error type: {type(e).__name__}")

        # Check for common issues
        if "credentials" in str(e).lower():
            print("\n💡 Possible issue: AWS credentials not configured")
            print("Make sure you have AWS credentials set up:")
            print("  - AWS_ACCESS_KEY_ID")
            print("  - AWS_SECRET_ACCESS_KEY")
            print("  - AWS_REGION_NAME (should be us-east-1)")

        elif "model" in str(e).lower():
            print("\n💡 Possible issue: Model not available")
            print(
                "Check if the model 'us.anthropic.claude-sonnet-4-20250514-v1:0' is available in us-east-1"
            )

        elif "permission" in str(e).lower():
            print("\n💡 Possible issue: Insufficient permissions")
            print("Make sure your AWS credentials have permission to use Bedrock")

        return False


def test_titan_embedding_client():
    """Test the BedrockTitanEmbedIAM client with a simple text embedding"""

    print("\n🧪 Testing BedrockTitanEmbedIAM Client")
    print("=" * 50)

    # Test text for embedding
    test_text = "This is a test text for embedding generation."

    try:
        print(f"📤 Sending text for embedding: {test_text}")

        # Call the EmbedText function which uses BedrockTitanEmbedIAM
        response = b.EmbedText(test_text)

        print(f"📥 Embedding generated successfully!")
        print(f"📊 Embedding dimensions: {len(response.embedding)}")
        print(f"📊 First few values: {response.embedding[:5]}")
        print("✅ Titan embedding client test successful!")

        return True

    except Exception as e:
        print(f"❌ Titan embedding client test failed: {e}")
        print(f"Error type: {type(e).__name__}")

        # Check for common issues
        if "credentials" in str(e).lower():
            print("\n💡 Possible issue: AWS credentials not configured")
            print("Make sure you have AWS credentials set up:")
            print("  - AWS_ACCESS_KEY_ID")
            print("  - AWS_SECRET_ACCESS_KEY")
            print("  - AWS_REGION_NAME (should be us-east-1)")

        elif "model" in str(e).lower():
            print("\n💡 Possible issue: Model not available")
            print(
                "Check if the model 'amazon.titan-embed-text-v2:0' is available in us-east-1"
            )

        elif "permission" in str(e).lower():
            print("\n💡 Possible issue: Insufficient permissions")
            print("Make sure your AWS credentials have permission to use Bedrock")

        return False


def test_environment():
    """Test environment variables"""
    print("\n🔧 Testing Environment Configuration")
    print("=" * 50)

    required_vars = ["AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_REGION_NAME"]

    all_good = True

    for var in required_vars:
        value = os.getenv(var)
        if value:
            # Mask the secret key for security
            if "SECRET" in var:
                display_value = value[:4] + "*" * (len(value) - 8) + value[-4:]
            else:
                display_value = value
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
    print("🚀 BAML Client Test Script")
    print("=" * 60)

    # Test environment first
    env_ok = test_environment()

    if not env_ok:
        print(
            "\n⚠️ Environment issues detected. Please fix them before running the client test."
        )
        return 1

    # Test the Titan embedding client
    titan_ok = test_titan_embedding_client()

    # Test the BAML Claude client
    claude_ok = test_bedrock_claude_client()

    if titan_ok and claude_ok:
        print("\n🎉 All tests passed! Your BAML clients are working correctly.")
        return 0
    else:
        print("\n❌ Some client tests failed. Please check the error messages above.")
        return 1


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
