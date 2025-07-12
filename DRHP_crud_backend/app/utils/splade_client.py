# utils/splade_client.py
import os, logging, requests
from typing import Dict

# You can override these with env-vars if you like
_INTERNAL_URL = os.getenv("SPLADE_SERVICE_INTERNAL", "http://splade-service:8000/embed")
_EXTERNAL_URL = os.getenv("SPLADE_SERVICE_EXTERNAL", "http://localhost:8000/embed")

def splade_sparse(text: str, *, in_docker: bool = False) -> Dict[int, float]:
    """
    Return a {token_id: weight} dict from the SPLADE FastAPI service.
    • in_docker=False  → host expects service on localhost
    • in_docker=True   → host is another service in the same docker-compose network
    """
    url = _INTERNAL_URL if in_docker else _EXTERNAL_URL
    try:
        r = requests.post(url, json={"text": text}, timeout=10)
        r.raise_for_status()
        # keys come back as strings – convert to int
        return {int(k): float(v) for k, v in r.json().items()}
    except Exception as exc:
        logging.error(f"[SPLADE] request failed: {exc}")
        return {}          # fall back to an empty sparse vector
