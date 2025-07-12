import requests
import concurrent.futures
import random
import string
import time

# Endpoint URL
URL = "http://localhost:8000/embed"



# Generate random sentence
def random_sentence(length=5):
    words = ["yellow", "world", "test", "splade", "embedding", "fastapi", "openai", "python", "model", "huggingface"]
    return " ".join(random.choices(words, k=length))



# Send a single request
def send_request(i):
    sentence = random_sentence()
    try:
        response = requests.post(URL, json={"text": sentence})
        response.raise_for_status()
        print(f"[{i}] ✅ Success: {len(response.json())} non-zero tokens for: \"{sentence}\"")
    except Exception as e:
        print(f"[{i}] ❌ Failed: {e}")

# Run 10 concurrent requests
def main():
    start = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        executor.map(send_request, range(1, 11))
    print(f"Completed in {time.time() - start:.2f} seconds.")

if __name__ == "__main__":
    main()
