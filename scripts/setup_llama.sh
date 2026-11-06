#!/bin/bash
# Download and verify the local model-serving tools. Run from the repo root in Git Bash:
#     bash scripts/setup_llama.sh
#
# What it fetches (all pinned; every file is checked against a SHA-256 before it is used):
#   1. llama.cpp  build b12175, Windows x64, CUDA 12.4   (289 MB)  github.com/ggml-org/llama.cpp
#   2. CUDA 12.4 runtime DLLs for that build              (391 MB)  same release
#   3. Qwen2.5-Coder-1.5B-Instruct, GGUF Q4_K_M, Apache-2.0 (1.1 GB) huggingface.co/Qwen/...-GGUF
# Total about 1.8 GB. Re-running skips anything already present and valid.
#
# Trust model: the two llama.cpp hashes come from GitHub's release metadata and the model hash from
# Hugging Face's file metadata, both recorded on 2026-11-06 (trust on first download). Only the
# downloaded files are verified: start_llama.sh does not re-hash the extracted executable.
# Everything lands in gitignored folders: tools/llama.cpp/ and models/. Nothing outside the repo is changed.
# Why CUDA 12.4: the NVIDIA driver here (580.x) supports CUDA 13.0, and a 12.4 build runs on it.
# Fallback if the GPU build misbehaves: the Vulkan build (38 MB), see docs/setup.md.
set -euo pipefail

LLAMA_TAG="b12175"
BASE="https://github.com/ggml-org/llama.cpp/releases/download/${LLAMA_TAG}"
LLAMA_ZIP="llama-${LLAMA_TAG}-bin-win-cuda-12.4-x64.zip"
LLAMA_SHA="cc6d557c0e76077fc02f84a8ae4b22cbfdf040492e935d467736c308c39c0985"
CUDART_ZIP="cudart-llama-bin-win-cuda-12.4-x64.zip"
CUDART_SHA="8c79a9b226de4b3cacfd1f83d24f962d0773be79f1e7b75c6af4ded7e32ae1d6"

HF_COMMIT="f86cb2c1fa58255f8052cc32aeede1b7482d4361"
MODEL_FILE="qwen2.5-coder-1.5b-instruct-q4_k_m.gguf"
MODEL_URL="https://huggingface.co/Qwen/Qwen2.5-Coder-1.5B-Instruct-GGUF/resolve/${HF_COMMIT}/${MODEL_FILE}"
MODEL_SHA="cc324af070c2ecbfd324a30884d2f951a7ff756aba85cb811a6ec436933bb046"

TOOLS="tools/llama.cpp/${LLAMA_TAG}"
DOWNLOADS="tools/downloads"
MODELS="models/qwen2.5-coder-1.5b-instruct"
mkdir -p "$TOOLS" "$DOWNLOADS" "$MODELS"

verified() { # file expected_sha256
  [ -f "$1" ] && [ "$(sha256sum "$1" | cut -d' ' -f1)" = "$2" ]
}

fetch() { # url dest sha256
  if verified "$2" "$3"; then echo "ok (already downloaded): $2"; return; fi
  echo "downloading $(basename "$2") ..."
  curl -L --fail --retry 3 --progress-bar -o "$2.part" "$1"
  mv "$2.part" "$2"
  verified "$2" "$3" || { echo "CHECKSUM MISMATCH for $2: deleting it"; rm -f "$2"; exit 1; }
  echo "verified: $2"
}

fetch "${BASE}/${LLAMA_ZIP}"   "${DOWNLOADS}/${LLAMA_ZIP}"   "$LLAMA_SHA"
fetch "${BASE}/${CUDART_ZIP}"  "${DOWNLOADS}/${CUDART_ZIP}"  "$CUDART_SHA"
fetch "$MODEL_URL"             "${MODELS}/${MODEL_FILE}"     "$MODEL_SHA"

# A stamp records which verified zips were extracted. If it is missing or different (first run,
# interrupted extraction, new pinned build), extract again from the verified zips.
STAMP="${TOOLS}/.extracted-from"
EXPECTED_STAMP="${LLAMA_SHA} ${CUDART_SHA}"
if [ "$(cat "$STAMP" 2>/dev/null)" != "$EXPECTED_STAMP" ]; then
  echo "extracting llama.cpp and CUDA runtime into ${TOOLS} ..."
  rm -f "$STAMP"
  # python's zipfile: no extra tools needed (it also strips ../ and absolute paths).
  # The runtime DLLs must sit next to llama-server.exe.
  python -m zipfile -e "${DOWNLOADS}/${LLAMA_ZIP}" "$TOOLS"
  python -m zipfile -e "${DOWNLOADS}/${CUDART_ZIP}" "$TOOLS"
  echo "$EXPECTED_STAMP" > "$STAMP"
fi
[ -f "${TOOLS}/llama-server.exe" ] || { echo "llama-server.exe not found after extraction"; exit 1; }

echo
echo "Done. Start the server with:  bash scripts/start_llama.sh"
