# Models for the CPU model server

On the `cpu-*` profiles one llama-server process, the `llm` service in `src/infra/docker-compose.cpu.yml`, serves the model to MAS and to every agent. Neither service loads a model in-process or downloads one. The GPU profiles keep vLLM.

The model file is listed in [`models/manifest.json`](../../models/manifest.json): its id, version, file name, size, SHA-256, the RAM it is sized for, the profiles that use it and the mirrors it downloads from. The installer reads the manifest and downloads the default model of the profile it chose. This file explains where the values come from, how the file reaches llama-server, and how to change it.

## llama.cpp build

| Item | Value |
|---|---|
| Server image | `ghcr.io/ggml-org/llama.cpp:server-b11382` |
| Image index digest | `sha256:559ac229adefe0f7e2d4e32f5222f26927b6bb8ba44b9db08e2544afebf41984` |
| Full image (conversion) | `ghcr.io/ggml-org/llama.cpp:full-b11382` |
| Build | b11382, commit `11fe02151f79c41d0d4af7da708755d73b9c0da6`, image built 2026-10-04 |

`b11382` is the newest build with a published image on 2026-10-05. llama.cpp publishes images once a day, so newer releases such as b11413 have no `server-` tag yet. Override the image with `LLM_SERVER_IMAGE` in `src/infra/.env`; keep the conversion script on the same build.

## The model in the manifest

Until we serve our own conversion, the manifest's only model is the community GGUF from unsloth. Its model card declares Apache 2.0, the licence of the base model `Qwen/Qwen3-4B-Instruct-2507`.

| Item | Value |
|---|---|
| Manifest id and version | `qwen3-4b-q4km` 1.0.0, the default of `cpu-standard` and `cpu-lean` |
| Repository | `unsloth/Qwen3-4B-Instruct-2507-GGUF` |
| Revision | `a06e946bb6b655725eafa393f4a9745d460374c9` |
| File | `Qwen3-4B-Instruct-2507-Q4_K_M.gguf` |
| Size | 2497281120 bytes (2.33 GiB) |
| SHA-256 | `3605803b982cb64aead44f6c1b2ae36e3acdb41d8e46c8a94c6533bc4c67e597` |
| Stored as | `models/qwen3-4b-instruct-2507-Q4_K_M.gguf`, next to the manifest |

The size and hash come from the Hugging Face API (`https://huggingface.co/api/models/unsloth/Qwen3-4B-Instruct-2507-GGUF/tree/main`, the `lfs` block of the file). The pinned `resolve` URL redirects to the Hugging Face CDN, which reports the same size and answers `Range` requests with `206 Partial Content` (checked 2026-10-05).

`min_ram_gb` is 16. `cpu-lean` machines get the same file for now, with a warning, until the CPU benchmark (B-91) decides what they get. The GPU profiles have no default: vLLM fetches its AWQ model itself.

`mirror_bases` is the slot for our own storage (open decision 3). It is empty today; each base URL listed there adds `<base>/<file>` as a mirror of every model, after the model's own `mirrors`.

## How the file reaches llama-server

The model lives in a folder on the host, `models/` at the top of the Horus folder unless the installer is given `--models-dir`. Compose mounts that folder read-only into `llm` at `/models`, and llama-server loads `/models/$LLM_GGUF_FILE`.

The installer's model manager (`installer/model_manager.py`, standard library only) fills it:

1. It runs after the images are built and before the first `docker compose up`, and again on every `--start` and `--restart`, which is when the desktop app sees it. It downloads only the default model of the chosen profile.
2. It writes to `<file>.part`. After any failure it resumes with an HTTP `Range` request from the bytes already on disk. It waits 10 s, then 20 s; after 3 failures in a row it moves to the next mirror. An attempt that delivered bytes resets that count, so a connection that keeps dropping but keeps delivering is never given up. A mirror that answers `404` or `403`, or serves a file of another size, is left at once.
3. At the end it checks the SHA-256, renames the file in one step and writes `<file>.sha256` with the hash. A wrong hash deletes the file and stops the install with a message that says so and gives both hashes (exit code 45). A file put together from several downloads is first fetched once more from the start.
4. It shows the total size, the speed and the time left: a console line every 15 s, and twice a second a `download` event on `--json-events`, which the desktop app shows as a progress bar.
5. It writes `HORUS_MODELS_DIR`, `LLM_GGUF_FILE`, `LLM_GGUF_URL`, `LLM_GGUF_SHA256` and `LLM_GGUF_SIZE` to `src/infra/.env`. A GPU reinstall comments them out.

`python installer/horus_install.py --download-model [--profile NAME] [--models-dir PATH]` runs only this step, without Docker.

Why a host folder and not the `llm_models` volume of B-90: there is one copy of the file, the one the installer checked; nothing has to be copied into Docker; `--uninstall` deletes the volumes but keeps the model, so a reinstall does not download it again; and a GGUF we convert ourselves is dropped next to the manifest. Not measured yet: on Docker Desktop for Windows the folder reaches the Linux VM through a file share, and how long llama-server takes to map 2.5 GB from it.

### Without the installer

`stack-up.sh`, or `docker compose -f docker-compose.yml -f docker-compose.cpu.yml up` from `src/infra`, works without the installer. The one-shot service `llm-model` stays for that case and for a file deleted by hand. It runs `src/infra/llm/fetch-model.sh` in the server image before `llm` starts, with the same folder mounted read-write:

1. A file whose `<file>.sha256` holds the expected hash, and whose size matches, is used as it is. The installer writes that file, so after an install the service exits at once.
2. Otherwise it downloads to `<file>.part` with curl, resuming from what is already there, and tries 5 times.
3. It checks the size and the SHA-256, then renames the file in one step. A wrong file is deleted and the start fails with a clear message.

Its defaults in `docker-compose.cpu.yml` are the manifest's `cpu-standard` entry (`installer/tests/test_cpu_model_server.py` keeps them equal); the installer's values in `src/infra/.env` override them. `HF_TOKEN` is sent when it is set; the installer sends it to `huggingface.co` only and never through a redirect. On Linux the files this service writes belong to root.

## The model we build ourselves (preferred)

```bash
scripts/models/convert-qwen3-4b-gguf.sh [work-folder]
```

Run it on Linux, macOS or WSL with Docker. It uses the pinned full image to download `Qwen/Qwen3-4B-Instruct-2507` at revision `cdbee75f17c01a7cc42f958dc650907174af0554`, converts it with `convert_hf_to_gguf.py` to a BF16 GGUF, quantizes it with `llama-quantize ... Q4_K_M`, and prints the file's size and SHA-256. It needs about 19 GB of free disk (8 GB of safetensors, 8 GB of BF16 GGUF, 2.5 GB of Q4_K_M). Our file is quantized without an importance matrix, so its hash differs from unsloth's.

To serve it, give the manifest entry the printed `size_bytes` and `sha256`, a new `version` and `source`, and `mirrors` that hold our file (or a `mirror_bases` entry), then copy the file into `models/` under the entry's `file` name and run the installer again. It checks the copied file instead of downloading one and writes the new values to `src/infra/.env`.

## Download size

| Profile | Before B-90 (measured 2026-09-05) | Now |
|---|---|---|
| CPU | 25.0 GB | about 16.6 GB, derived |
| GPU | 26.5 GB | 26.5 GB, unchanged by B-90 and B-95 |

The CPU figure is arithmetic on the measured one: minus the 3.10 GB `Qwen/Qwen2.5-1.5B-Instruct` router and the 8.06 GB `Qwen/Qwen3-4B-Instruct-2507` worker the containers no longer download (sizes from the Hugging Face API), plus the 2.50 GB GGUF and the 311 MB llama-server image (311,099,749 bytes: the compressed layers and config of the `linux/amd64` image of `server-b11382` on ghcr.io). The CPU-only torch wheels of B-87 lower it further by an amount not measured yet. A clean CPU install measures it: `docker system df` before and after, plus the size of `models/`.

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
