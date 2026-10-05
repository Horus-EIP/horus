#!/usr/bin/env bash
set -euo pipefail

image="${LLAMA_CPP_FULL_IMAGE:-ghcr.io/ggml-org/llama.cpp:full-b11382}"
repo="${QWEN_REPO:-Qwen/Qwen3-4B-Instruct-2507}"
revision="${QWEN_REVISION:-cdbee75f17c01a7cc42f958dc650907174af0554}"
work="$(mkdir -p "${1:-models-build}" && cd "${1:-models-build}" && pwd)"
name="qwen3-4b-instruct-2507"
quantized="$name-Q4_K_M.gguf"

in_image() {
  docker run --rm -e HF_TOKEN -v "$work:/work" "$@"
}

echo "llama.cpp image: $image"
echo "source model:    $repo @ $revision"
echo "work folder:     $work"

in_image --entrypoint python3 "$image" -c \
  "from huggingface_hub import snapshot_download; snapshot_download(repo_id='$repo', revision='$revision', local_dir='/work/hf')"

in_image "$image" --convert /work/hf --outtype bf16 --outfile "/work/$name-BF16.gguf"

in_image "$image" --quantize "/work/$name-BF16.gguf" "/work/$quantized" Q4_K_M

size="$(in_image --entrypoint stat "$image" -c %s "/work/$quantized")"
sha="$(in_image --entrypoint sha256sum "$image" "/work/$quantized" | cut -d ' ' -f 1)"

echo
echo "file:    $work/$quantized"
echo "size:    $size"
echo "sha256:  $sha"
