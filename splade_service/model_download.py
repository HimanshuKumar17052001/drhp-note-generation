#!/usr/bin/env python3
import os
import sys
from huggingface_hub import snapshot_download

model = os.getenv("MODEL_ID")
if not model:
    print("ERROR: MODEL_ID not set", file=sys.stderr)
    sys.exit(1)

# download the full repo into /opt/hf_cache/<model>
snapshot_download(
    repo_id=model,
    local_dir=f"/opt/hf_cache/{model}",
    local_dir_use_symlinks=False
)

print(f"✅ Downloaded {model} into /opt/hf_cache/{model}")
