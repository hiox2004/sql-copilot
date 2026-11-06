#!/bin/bash
# Download the CHALLENGER model for the bake-off (optional; ~2.5 GB). Run from repo root in Git Bash.
#   Qwen3-4B-Instruct-2507, GGUF Q4_K_M, Apache-2.0, from the community conversion unsloth/...-GGUF
#   (a re-pack of Qwen's weights; the license and base model are Qwen's). Pinned to one repo commit
#   and checked against the SHA-256 that Hugging Face publishes for the file.
# Lands in the gitignored models/ folder. Serve it with:
#   MODEL=models/qwen3-4b-instruct-2507/Qwen3-4B-Instruct-2507-Q4_K_M.gguf bash scripts/start_llama.sh
set -euo pipefail
HF_COMMIT="a06e946bb6b655725eafa393f4a9745d460374c9"
FILE="Qwen3-4B-Instruct-2507-Q4_K_M.gguf"
SHA="3605803b982cb64aead44f6c1b2ae36e3acdb41d8e46c8a94c6533bc4c67e597"
URL="https://huggingface.co/unsloth/Qwen3-4B-Instruct-2507-GGUF/resolve/${HF_COMMIT}/${FILE}"
DEST="models/qwen3-4b-instruct-2507"
mkdir -p "$DEST"
if [ -f "$DEST/$FILE" ] && [ "$(sha256sum "$DEST/$FILE" | cut -d' ' -f1)" = "$SHA" ]; then
  echo "already downloaded and verified"; exit 0
fi
curl -L --fail -sS -o "$DEST/$FILE.part" "$URL"
[ "$(sha256sum "$DEST/$FILE.part" | cut -d' ' -f1)" = "$SHA" ] || { echo "CHECKSUM MISMATCH, deleting"; rm -f "$DEST/$FILE.part"; exit 1; }
mv "$DEST/$FILE.part" "$DEST/$FILE"
echo "verified: $DEST/$FILE"
