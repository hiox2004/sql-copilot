#!/bin/bash
# Start the local model server (llama.cpp llama-server) on http://127.0.0.1:8080
# Run from the repo root in Git Bash:   bash scripts/start_llama.sh
# Stop with Ctrl+C. Needs scripts/setup_llama.sh to have been run once.
#
# -ngl 99   put all model layers on the GPU (4 GB VRAM is plenty for the 1.5B model)
# -c 8192   context window in tokens (prompt + answer)
# --host    127.0.0.1 only: reachable from this machine, not from the network
# Override the model with:  MODEL=path/to/file.gguf bash scripts/start_llama.sh
set -euo pipefail

LLAMA_TAG="b12175"
SERVER="tools/llama.cpp/${LLAMA_TAG}/llama-server.exe"
MODEL="${MODEL:-models/qwen3-4b-instruct-2507/Qwen3-4B-Instruct-2507-Q4_K_M.gguf}"  # fallback: models/qwen2.5-coder-1.5b-instruct/...

[ -f "$SERVER" ] || { echo "missing $SERVER: run  bash scripts/setup_llama.sh  first"; exit 1; }
[ -f "$MODEL" ] || { echo "missing $MODEL: run  bash scripts/setup_llama.sh  first"; exit 1; }

exec "$SERVER" -m "$MODEL" -ngl 99 -c 8192 --host 127.0.0.1 --port 8080
