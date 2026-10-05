# Models for the CPU model server

On the `cpu-*` profiles one llama-server process, the `llm` service in `src/infra/docker-compose.cpu.yml`, serves the model to MAS and to every agent. Neither service loads a model in-process or downloads one. The GPU profiles keep vLLM.

This file records the model and the llama.cpp build until the model manifest of B-95 exists. B-95 replaces the download described here with the installer's model manager.

## llama.cpp build

| Item | Value |
|---|---|
| Server image | `ghcr.io/ggml-org/llama.cpp:server-b11382` |
| Image index digest | `sha256:559ac229adefe0f7e2d4e32f5222f26927b6bb8ba44b9db08e2544afebf41984` |
| Full image (conversion) | `ghcr.io/ggml-org/llama.cpp:full-b11382` |
| Build | b11382, commit `11fe02151f79c41d0d4af7da708755d73b9c0da6`, image built 2026-10-04 |

`b11382` is the newest build with a published image on 2026-10-05. llama.cpp publishes images once a day, so newer releases such as b11413 have no `server-` tag yet. Override the image with `LLM_SERVER_IMAGE` in `src/infra/.env`; keep the conversion script on the same build.

## The model the stack downloads today

The interim path pulls the community GGUF from unsloth. Its model card declares Apache 2.0, the licence of the base model `Qwen/Qwen3-4B-Instruct-2507`.

| Item | Value |
|---|---|
| Repository | `unsloth/Qwen3-4B-Instruct-2507-GGUF` |
| Revision | `a06e946bb6b655725eafa393f4a9745d460374c9` |
| File | `Qwen3-4B-Instruct-2507-Q4_K_M.gguf` |
| Size | 2497281120 bytes (2.33 GiB) |
| SHA-256 | `3605803b982cb64aead44f6c1b2ae36e3acdb41d8e46c8a94c6533bc4c67e597` |
| Stored as | `qwen3-4b-instruct-2507-Q4_K_M.gguf` in the `llm_models` volume |

The size and hash come from the Hugging Face API (`https://huggingface.co/api/models/unsloth/Qwen3-4B-Instruct-2507-GGUF/tree/main`, the `lfs` block of the file).

The one-shot service `llm-model` runs `src/infra/llm/fetch-model.sh` in the server image before `llm` starts:

1. A file already verified for this hash and size is used as it is.
2. Otherwise it downloads to `<file>.part`, resuming from what is already there, and tries 5 times.
3. It checks the size and the SHA-256, then renames the file in one step. A wrong file is deleted and the start fails with a clear message.

`LLM_GGUF_URL`, `LLM_GGUF_SHA256` and `LLM_GGUF_SIZE` in `src/infra/.env` override the source. `HF_TOKEN` is sent when it is set.

## The model we build ourselves (preferred)

```bash
scripts/models/convert-qwen3-4b-gguf.sh [work-folder]
```

Run it on Linux, macOS or WSL with Docker. It uses the pinned full image to download `Qwen/Qwen3-4B-Instruct-2507` at revision `cdbee75f17c01a7cc42f958dc650907174af0554`, converts it with `convert_hf_to_gguf.py` to a BF16 GGUF, quantizes it with `llama-quantize ... Q4_K_M`, and prints the file's size and SHA-256. It needs about 19 GB of free disk (8 GB of safetensors, 8 GB of BF16 GGUF, 2.5 GB of Q4_K_M). Our file is quantized without an importance matrix, so its hash differs from unsloth's.

To serve it, copy it into the volume as `qwen3-4b-instruct-2507-Q4_K_M.gguf` and set `LLM_GGUF_SHA256` and `LLM_GGUF_SIZE` to the printed values. `llm-model` then checks the file instead of downloading one. Record the values here, or in the B-95 manifest once it exists.

## Memory

| Part | Plan | Shipped configuration |
|---|---|---|
| Weights | ~2.5 GB | 2.50 GB (2.33 GiB), memory-mapped (`--load-mode mmap`) |
| KV cache | ~1.1 GB at 8k, f16 | 36 layers x 8 KV heads x 128 x 2 (K and V) x 2 bytes x 8,192 tokens = 1.21 GB (1.13 GiB), `--ctx-size 8192 --parallel 1` |
| Compute buffers | "plus buffers" | a few hundred MB; llama-server prints the exact `CPU compute buffer size` at start |
| Prompt cache | not counted | up to 1 GiB (`--cache-ram 1024`; the default is 8 GiB) |
| Total | about 4 GB | about 4 GiB, up to 5 GiB with a full prompt cache, under `mem_limit` 6g (`LLM_SERVER_MEM_LIMIT`) |

Before this change the CPU profiles held about 12 GB of models: the 1.5B router in MAS (3.1 GB in bf16) and the 4B worker in the agent (8.1 GB in bf16). On the CPU, MAS now gets `mem_limit` 3g and the agent 4g. None of these numbers is measured yet; `docker stats` during the 100-question run (B-91) measures them.

## Measuring it on the 16 GB CPU machine

None of the numbers above has been measured. On the reference machine, after an install with a `cpu-*` profile:

```bash
cd src/infra
docker compose ps llm mas agent
docker stats --no-stream llm mas agent knowledge_store
docker compose logs mas | grep "Completed task"
docker compose logs agent | grep "Task processed"
docker compose logs llm | grep -i "buffer size"
```

`docker stats` must show `llm` as the only container holding a model (about 4 GiB) while MAS and the agent stay near their Python baseline; the MAS and agent log lines carry each task's peak RSS, and llama-server logs its KV and compute buffer sizes at start. For the timed run, use `scripts/eval/run-eval.py --sample-resources` as described in `benchmarks/README.md`, with `--llama-cpp-build b11382`.

## API key

llama-server runs without an API key. Its port is not published to the host and only the containers on `horus-net` reach it. The clients send no `Authorization` header.
