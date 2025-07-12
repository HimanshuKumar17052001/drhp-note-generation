# BAML Client Test Script

This script tests your BAML client configuration to ensure everything is working correctly before running the main DRHP processor.

## Prerequisites

1. **AWS Credentials**: Make sure you have AWS credentials configured:
   ```bash
   export AWS_ACCESS_KEY_ID="your_access_key"
   export AWS_SECRET_ACCESS_KEY="your_secret_key"
   export AWS_REGION_NAME="us-east-1"
   ```

2. **BAML Generated**: Ensure you have generated the BAML client:
   ```bash
   baml generate
   ```

3. **Dependencies**: Install required packages:
   ```bash
   pip install python-dotenv
   ```

## Running the Test

```bash
python test_baml_client.py
```

## What the Test Does

1. **Environment Check**: Verifies AWS credentials are set
2. **Titan Embedding Test**: Tests the `BedrockTitanEmbedIAM` client with text embedding
3. **Claude LLM Test**: Tests the `BedrockClaudeIAM` client with text generation

## Expected Output

If successful, you should see:
```
🚀 BAML Client Test Script
============================================================

🔧 Testing Environment Configuration
==================================================
✅ AWS_ACCESS_KEY_ID: AKIA...
✅ AWS_SECRET_ACCESS_KEY: ****...
✅ AWS_REGION_NAME: us-east-1
✅ All required environment variables are set

🧪 Testing BedrockTitanEmbedIAM Client
==================================================
📤 Sending text for embedding: This is a test text for embedding generation.
📥 Embedding generated successfully!
📊 Embedding dimensions: 1024
📊 First few values: [0.123, -0.456, 0.789, ...]
✅ Titan embedding client test successful!

🧪 Testing BedrockClaudeIAM Client
==================================================
📤 Sending test prompt: What is the main topic of this content?
📄 Test content: This is a test document about artificial intelligence...
📥 AI Output: The main topic of this content is artificial intelligence and machine learning...
📄 Relevant Pages: []
✅ BAML client test successful!

🎉 All tests passed! Your BAML clients are working correctly.
```

## Troubleshooting

### Common Issues:

1. **Import Error**: Run `baml generate` first
2. **Credentials Error**: Check your AWS credentials
3. **Model Error**: Verify the models are available in us-east-1
4. **Permission Error**: Ensure your AWS user has Bedrock permissions

### Models Being Tested:

- **Claude**: `us.anthropic.claude-sonnet-4-20250514-v1:0` (us-east-1)
- **Titan**: `amazon.titan-embed-text-v2:0` (us-east-1)

## Next Steps

Once the test passes, you can run the main DRHP processor:
```bash
python local_drhp_processor_final.py
``` 