from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from transformers import AutoTokenizer, AutoModelForMaskedLM
import torch
import os



MODEL_ID = os.getenv("MODEL_ID")
DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")

app = FastAPI(title="SPLADE sparse-embedding service")

class EmbedRequest(BaseModel):
    text: str

@app.on_event("startup")
def load_model():
    global tok, model
    tok = AutoTokenizer.from_pretrained(MODEL_ID)
    model = AutoModelForMaskedLM.from_pretrained(MODEL_ID).to(DEVICE)
    model.eval()

def splade_encode(sentence: str):
    with torch.no_grad():
        encoded = tok(sentence, return_tensors="pt", truncation=True, max_length=512).to(DEVICE)
        out = model(**encoded).logits[0]          # (seq_len, vocab)
        weights = torch.max(out, dim=0).values     # max-pooling
        sparse = torch.nn.functional.relu(weights) # ReLU keeps sparsity
        nz = sparse.nonzero().squeeze().tolist()
        return {int(i): float(sparse[i]) for i in nz}

@app.post("/embed")
def embed(req: EmbedRequest):
    if not req.text.strip():
        raise HTTPException(400, "Empty text")
    return splade_encode(req.text)


# ✅ Health check endpoint
@app.get("/health")
def health_check():
    return {"status": "ok"}