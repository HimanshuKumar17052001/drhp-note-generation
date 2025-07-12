#!/usr/bin/env python3
import torch

# On CPU boxes, limit PyTorch to 1 thread per worker so it doesn't fight
# with Gunicorn’s worker processes.
torch.set_num_threads(1)
print("✅ PyTorch set_num_threads(1)")
