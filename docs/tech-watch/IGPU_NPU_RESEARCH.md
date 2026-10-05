# Integrated GPUs and NPUs for the CPU profiles

**Date:** 2026-10-05
**Task:** dev plan B-101, a research spike. Nothing is built. This note says what trying each option would take, what can go wrong, and what to do next.
**Related:**

- [ADR-005](../adr/ADR-005-low-ram-machines.md): the memory budget of the CPU stack
- [benchmarks/README.md](../../benchmarks/README.md): the B-91 tools (`run-llama-bench.py`, `run-eval.py`, `compare-benchmarks.py`)
- [scripts/models/README.md](../../scripts/models/README.md): the pinned llama.cpp build and the model file
- B-100 (profiles), B-96 (embeddings on ONNX Runtime), B-99 (prompt layout for llama-server's prompt cache)

---

## Summary

- **Vulkan on an integrated GPU (iGPU) is worth one measured spike, on Linux only.** The official `server-vulkan` image runs the same llama-server build as the `llm` service. On a Linux host it only needs `/dev/dri` passed into the container. The public numbers (llama.cpp discussion #10879) put recent laptop iGPUs at hundreds of tokens per second for prompt reading on a 7B model, and prompt reading is the slow part of a CPU answer. There are no CPU rows to compare with, so the spike has to measure the CPU and the iGPU on the same laptop.
- **Windows has no container route today.** Docker Desktop passes only NVIDIA GPUs to containers. Inside WSL 2 the GPU is a Direct3D 12 device, and the official image has no Vulkan driver for it. A native `llama-server.exe` works, but it would take the model server out of Docker.
- **An iGPU does not save memory.** It uses the same RAM as the CPU. The ADR-005 thresholds do not move, and the weights may stop being memory the kernel can drop.
- **OpenVINO: do not try it yet.** The llama.cpp backend is marked work in progress, is Intel-only and has been validated on Core Ultra Series 1 and 2 only. Its fast GPU mode serves one session and, from its documented limits, loses llama-server's prompt cache. Its NPU mode needs small contexts. If the Vulkan spike runs on an Intel Core Ultra Series 2 laptop, add one llama-bench run with the OpenVINO image: it costs one command.
- **NPUs are not a route for the LLM for now.** The repository's earlier NPU work targeted the embedder ([below](#earlier-npu-work-in-this-repository)), and that stays a separate experiment.

## Where the CPU profiles stand

- **Who gets them.** The installer treats AMD, Intel and Apple GPUs as unsupported (`UNSUPPORTED_VENDORS` in `installer/hardware.py`), skips the CUDA test and picks a CPU profile. Every laptop with only an iGPU runs `cpu-standard` or `cpu-lean`.
- **What runs.** The `llm` service in `src/infra/docker-compose.cpu.yml`: `ghcr.io/ggml-org/llama.cpp:server-b11382`, Qwen3-4B-Instruct-2507 Q4_K_M (2.33 GiB), `--ctx-size 8192 --parallel 1 --load-mode mmap --cache-ram 1024 --threads N`. `LLM_SERVER_IMAGE` overrides the image of `llm` and of the `llm-model` download step.
- **Where the wait is.** The CPU profiles retrieve up to five passages under a 6,000-character cap, about 1,500 to 2,000 tokens, and the whole prompt is read before the first word of the answer (`AGENT_MAX_CONTEXT_CHARS` in `installer/profiles.py`). Reading a prompt is arithmetic-bound. Generating is bound by memory bandwidth. An iGPU brings more parallel arithmetic but uses the same memory, so the gain should be in prompt reading and small in generation.
- **What is measured.** Nothing on llama-server yet: B-91 delivered the tools and ADR-005, and its `cpu16` runs are still to do. The spike below does not need them, because it compares the CPU and the iGPU of one laptop.

## Earlier NPU work in this repository

The NPU work merged as `61ce28a` (*Npu acceleration research (#197)*) is about the GPU profile. It added the end-to-end pipeline benchmark `scripts/perf/benchmark-pipeline.py` (section "End-to-End LLM Pipeline Benchmark" of [scripts/perf/README.md](../../scripts/perf/README.md)). Its contention scenario measures how much knowledge-store embedding slows generation on the 8 GB card: the headroom an NPU embedder offload could win back. The runs are in [scripts/perf/results-archive/](../../scripts/perf/results-archive/), among them `pipeline-baseline-20260622-132319Z.md`, the BGE-on-CPU trial `pipeline-bge-cpu-20260622-162606Z.md` and `pipeline-rebaseline-contention-20260623-095307Z.md`. Their findings are not repeated here.

Two things changed since then. B-90 moved the LLM out of the Python services on the CPU profiles, and B-96 is moving both embedders to FastEmbed on ONNX Runtime. An NPU offload of the embedder would now go through ONNX Runtime's execution providers (FastEmbed's `TextEmbedding` takes a `providers` list), not through llama.cpp. On the CPU profiles the embedder competes with llama-server for CPU cores rather than for VRAM, and nobody has measured that contention yet.

## Option 1: llama-server with Vulkan

### The public numbers: llama.cpp discussion #10879

The thread was opened in December 2024 by a llama.cpp collaborator. It keeps a scoreboard of one fixed run: `llama-bench -ngl 100 -fa 0,1` on Llama 2 7B Q4_0 (3.56 GiB), reporting prompt processing of 512 tokens (pp512) and generation of 128 tokens (tg128) in tokens per second. Users post their results with the build, and the maintainer keeps one row per chip. Integrated GPUs are listed by CPU series. A selection of the laptop rows, without flash attention, read on 2026-10-05 and rounded:

| Scoreboard row | pp512 (t/s) | tg128 (t/s) |
|---|---:|---:|
| Intel Core Ultra 300 Series | 1,380 | 24.5 |
| AMD Ryzen AI Max+ 300 Series (a much larger APU than mainstream laptops) | 1,289 | 53.6 |
| Intel Core Ultra 200 Series | 865 | 24.4 |
| AMD Ryzen AI 300 Series | 479 | 22.4 |
| AMD Ryzen 7000 Series | 282 | 19.9 |
| AMD Ryzen 8000 Series | 267 | 19.8 |
| AMD Ryzen 6000 Series | 241 | 21.3 |
| Intel Core 1100 Series | 187 | 10.4 |
| Intel Core Ultra 100 Series | 186 | 8.2 |
| Intel Core 8000 Series | 25 | 3.4 |
| For scale, a laptop discrete GPU: Nvidia RTX 4060 Mobile | 2,136 | 59.5 |

What the thread tells us, and what it does not:

- **The rows rank chips; they are not a fixed benchmark.** Each row comes from a different user, build, driver and operating system. The Core Ultra 200 row was posted from Windows with Intel's driver (Arc 140V). The Core Ultra 300 row (Arc B390, also Windows) was measured on an 8B Llama model rather than the reference file.
- **There are no CPU-only rows.** The one same-machine comparison in the visible comments is a 2020 Tiger Lake laptop (i7-1185G7, Iris Xe). There, generation was faster with every layer left on the CPU (`-ngl 0`, about 9.9 t/s) than with every layer on the iGPU (about 7.3 t/s), while prompt reading was faster with every layer on the iGPU (about 42 against 31 t/s). A llama.cpp collaborator replied that `-ngl 0`, where only prompt processing goes to the GPU, is often a good setting for iGPUs.
- **Memory decides a lot.** The opening post warns that for iGPUs "memory speed and number of channels will greatly affect your inference speed". Two laptops with the same chip and different RAM will not match.
- **Flash attention depends on the chip.** With it, prompt reading on the AMD rows is 11 to 16% faster. On the Core Ultra 100 row it drops from 186 to 78 t/s, though from a different build. The ADR-005 lean option needs flash attention for its q8_0 V cache, so a lean run on an iGPU must be measured with flash attention on.
- **Our model is not the reference model.** The Q4_K_M file is 2.33 GiB against 3.56 GiB, and K-quants run different kernels from Q4_0. The table says which chips are worth trying. It does not predict our numbers.
- **Old Intel iGPUs are not worth the work.** The Core 8000 to Core 1100 and Core Ultra 100 rows are far below the Series 2 and 3 rows and the AMD rows, and the Tiger Lake comparison above favours the CPU.

### The image

| Tag | Index digest | Platforms | Download (amd64) |
|---|---|---|---:|
| `server-b11382` (the `llm` service today) | `sha256:559ac229adefe0f7e2d4e32f5222f26927b6bb8ba44b9db08e2544afebf41984` | amd64, arm64, s390x | 311 MB |
| `server-vulkan-b11382` | `sha256:431561ee79ee67b3980a02ff47ed9dc19496127643b75671d9789ef693ca57f9` | amd64, arm64 | 308 MB |
| `full-vulkan-b11382` (llama-bench) | `sha256:01025bab1c20092fe7d23ed4d1aaf5986da45ff279405aef5b8a559294c317aa` | amd64, arm64 | 845 MB |

Digests and sizes were read from the GitHub Container Registry on 2026-10-05. The download is the sum of the compressed layers in the amd64 manifest.

The image is built from `.devops/vulkan.Dockerfile` at b11382: Ubuntu 26.04 with Ubuntu's Mesa Vulkan drivers (RADV for AMD, ANV for Intel), and the same `llama-server` entrypoint and `/health` healthcheck as the CPU image. The `llm` command line works unchanged. With no GPU in the container it falls back to the CPU: llama.cpp skips Vulkan devices of the CPU type, such as Mesa's software rasterizer.

### Linux: pass `/dev/dri` into the container

With Docker Engine the container needs the GPU's device nodes. llama.cpp's build documentation passes `/dev/dri/renderD128` and a `/dev/dri/card*` node. llama-server runs as root in this image, so no `group_add` is needed; a non-root user would need the host's `render` group. For the spike, an override file in the style of ADR-005, added to `COMPOSE_FILE`:

```yaml
services:
  llm:
    image: ghcr.io/ggml-org/llama.cpp:server-vulkan-b11382
    devices:
      - /dev/dri:/dev/dri
```

- **Check the device first.** The host brings the kernel driver (`i915` or `xe` for Intel, `amdgpu` for AMD) and the image brings the user-space driver (Mesa from Ubuntu 26.04). A chip newer than that Mesa, or a host kernel too old for the chip, shows up as no GPU. Run `docker run --rm --device /dev/dri ghcr.io/ggml-org/llama.cpp:server-vulkan-b11382 --list-devices` and check that it lists the iGPU before measuring anything.
- **How many layers go to the iGPU.** `--n-gpu-layers` defaults to `auto` and `--fit on` adjusts it to the memory the device reports. On an iGPU that figure is whatever the driver reports for memory it shares with the CPU, so read in the load log how many layers were offloaded, and pass `--n-gpu-layers 99` for the test.
- **Loading flags interact with iGPUs.** In b11382 the Vulkan backend reports no `mmap` support for integrated GPUs, and the default `--load-mode auto` then turns `mmap` off. The `llm` service forces `--load-mode mmap`. A September 2026 regression (llama.cpp issue #28160) halved prompt reading on an AMD iGPU until lazy loading was turned off for iGPUs. Measure both load modes.
- **Docker Desktop for Linux is not a route.** It runs containers in a virtual machine, and Docker documents GPU access only for Windows with WSL 2 and NVIDIA.
- **Detection later (B-100 style).** `/dev/dri/renderD*` exists and the `--list-devices` probe above finds a GPU: the same shape as the CUDA test the installer already runs for NVIDIA.

### Windows and WSL 2

| Host | Vulkan on the iGPU from the `llm` container | Why |
|---|---|---|
| Linux, Docker Engine | Yes | `/dev/dri` passthrough, as above |
| Linux, Docker Desktop | No | containers run in a VM; no GPU access documented for it |
| Windows, Docker Desktop (WSL 2) | No, with the official image | Docker's GPU support is NVIDIA GPU paravirtualisation only. WSL 2 exposes GPUs as `/dev/dxg` (Direct3D 12), not `/dev/dri`. Vulkan on it needs Mesa's Dozen driver (`dzn`), which Ubuntu's `mesa-vulkan-drivers` for 26.04, and so the image, does not ship. |
| Windows, native `llama-server.exe` | Yes | the `llama-b11382-bin-win-vulkan-x64.zip` release (33 MB). The Core Ultra 200 and 300 rows above were measured on native Windows. |
| macOS | No | Docker cannot reach the Apple GPU (already in the installer's notes) |

The WSL 2 route has been tried by the community. llama.cpp discussion #26729 (August 2026) reports a self-built `dzn` on a Core Ultra 7 270K iGPU running at roughly two thirds of native Windows Vulkan speed (pp512 73.3 against 109.9 t/s on a 7B Q4_K_M). The same report notes that upstream flags `dzn` as non-conformant, that it exposes Vulkan 1.2 without matrix cores, and that failed loads held on to Direct3D 12 memory for a long time. For Horus that would mean building and maintaining our own image with our own Mesa, plus `--device /dev/dxg` and the WSL driver libraries mounted in. That is too much for a slower result.

A native `llama-server.exe` is the realistic Windows route, but it changes the architecture: the installer or the desktop shell starts and supervises a host process, MAS and the agent reach it through `host.docker.internal`, the port is opened on the host, and a binary is downloaded and hash-checked outside Docker. That needs its own ADR, and only if the Linux numbers show a gain worth it.

### What trying it needs

1. **A machine.** A Linux laptop with Docker Engine, 16 GB of RAM and an Intel Core Ultra Series 2 or an AMD Radeon 780M, 880M or 890M: the upper half of the scoreboard, and common in recent laptops. The development laptop (Ryzen AI 9 HX 370 with a Radeon 890M, Windows 11) can give the native Windows numbers without Docker. It also has an RTX 4070, and llama.cpp uses an integrated GPU only when it finds no discrete one, so select the iGPU with `-dev VulkanN` (from `--list-devices`).
2. **Model speed on one laptop,** with the stack stopped and the GGUF already in `models/`. The examples name a Radeon 780M laptop; put the real chip in the labels. Write one configuration per file: the `summary` rows of a llama-bench report have no layer-count or device column (the raw `results` rows do), so `compare-benchmarks.py` would mix two configurations stored in one file.
   - CPU only, the B-91 tool unchanged:
     ```bash
     python scripts/benchmarks/run-llama-bench.py --models-dir models \
       --model qwen3-4b-instruct-2507-Q4_K_M.gguf --cache-types-k f16 --cache-types-v f16 \
       --reference igpu-780m --label igpu-780m-cpu
     ```
   - All layers on the iGPU into one file, then the same with `-ngl 0` (generation on the CPU, prompt batches on the iGPU) into a second, and once more with `-ngl 99 -lm mmap` (the load mode the `llm` service passes) into a third:
     ```bash
     docker run --rm --device /dev/dri -v "$PWD/models:/models:ro" \
       ghcr.io/ggml-org/llama.cpp:full-vulkan-b11382 --bench \
       -m /models/qwen3-4b-instruct-2507-Q4_K_M.gguf \
       -p 512,2048 -n 128 -d 0,4096 -t 4,8 -ngl 99 -r 5 -o json > igpu-780m-vulkan.raw.json
     python scripts/benchmarks/run-llama-bench.py --from-json igpu-780m-vulkan.raw.json \
       --models-dir models --image ghcr.io/ggml-org/llama.cpp:full-vulkan-b11382 \
       --cache-types-k f16 --cache-types-v f16 --reference igpu-780m --label igpu-780m-vulkan
     ```
     `--image` puts the Vulkan image and its digest in the report. The matrix options must match what llama-bench ran, so that `run.matrix` tells the truth.
   - Native Windows (the development laptop): unzip the `win-vulkan` release, run `llama-bench.exe` with the same flags plus `-dev VulkanN`, and keep its bare JSON array: `compare-benchmarks.py` reads bare llama-bench arrays. `run-llama-bench.py` records Docker images and cannot hash through a native binary.
3. **In the stack** (Linux only): the override file above, `AGENT_RESPONSE_CACHE=0`, and `python scripts/eval/run-eval.py --label eval-igpu-780m-vulkan --reference igpu-780m --sample-resources`, against a CPU-only evaluation on the same laptop. The report records the image and the server arguments (`llama_cpp.server`). Also note the host's `MemAvailable` (`/proc/meminfo`) before the stack starts, after the model has loaded and at the end, because the GPU driver's memory may not appear in `docker stats` (see the risks).
4. **Go or stop.** These are planning values, to revisit after the first run, like ADR-005's margins:
   - Go on to the evaluation only if the iGPU reads pp2048 at least twice as fast as the same laptop's CPU.
   - Keep it only if the evaluation's median `summary.ttft_s` is at least 30% lower than CPU-only; the answer-correct and source-correct rates are each within 5 points; every question ends with an answer; there are no OOM kills or restarts; and the lowest `MemAvailable` is no more than 0.5 GiB below the CPU-only run's.
   - If it holds, B-100 can offer it as an opt-in on Linux (the detection above and the override), never as the default without a smoke test on a reference machine.

### Risks

- **No memory is saved, and the weights may get stickier.** The iGPU's memory is the system RAM. In b11382 the Vulkan backend does not report `buffer_from_host_ptr`, so offloaded weights are copied into buffers the Vulkan driver allocates instead of being used in place from the memory-mapped file. ADR-005 counts on the weights being file-backed: when memory runs short the kernel drops those pages and answers get slower, but nothing is killed. Driver memory may not be droppable, so a shortfall can become a failure. Whether the driver's memory is charged to the `llm` container's memory cgroup depends on the driver, so `mem_limit` may not cap it and `docker stats`, which ADR-005's measurement rule reads, may not show it. The host's `MemAvailable` catches it either way.
- **Less RAM for everything else.** Many laptops reserve part of the RAM for the iGPU in their firmware, before the operating system starts. ADR-005 already notes that such 16 GB machines report less than 15.0 GiB.
- **Shared power and bandwidth.** The iGPU and the CPU cores share one power budget and one memory bus. While llama-server works on the iGPU, the knowledge store, MAS and the agent have less of both. Only the evaluation shows the net effect.
- **Builds and drivers move the numbers.** One poster in the thread saw prompt reading on Xe2 iGPUs jump between llama.cpp builds, and the image tag pins both the build and the Mesa driver. Every build bump needs the llama-bench run again. For RADV, the thread asks users to set `RADV_PERFTEST=nogttspill`; check whether it matters on the chosen AMD laptop.
- **Answers can change.** GPU kernels round differently from the CPU's, so greedy answers may differ. The B-92 router's JSON output and the planned B-98 answer contract are enforced by llama.cpp's grammar sampling, which works on the logits whichever backend computed them, but quality has to be checked on the test set like any other change.
- **More to support.** One more image to pin, pull, test and explain, on Linux only. Horus ships for Windows, macOS and Linux (`packaging/README-FIRST.txt`), and on Windows and macOS none of this applies.

## Option 2: the OpenVINO backend

### Status

From `docs/backend/OPENVINO.md` at b11382. It was identical to `master` on 2026-10-05, last changed on 2026-10-03; the backend itself was merged in March 2026.

- The page opens with a note that performance and memory optimisations, accuracy validation, quantisation coverage and operator and model support are all work in progress.
- **Intel only:** Intel CPUs, Intel GPUs (integrated and discrete) and Intel NPUs. It says the backend has been "validated specifically on AI PCs" such as Core Ultra Series 1 and 2. The validation machine is a Core Ultra 5 238V (Lunar Lake) with 32 GB under Ubuntu 24.04.
- **Models:** the validated list includes `Qwen3-4B` Q4_K_M (the base model's GGUF, not our Instruct-2507 file, though it has the same architecture), passing on CPU, GPU and NPU. Newer families (Qwen3.5 on NPU, gemma-4-E4B on GPU) fail.
- **Images:** `server-openvino-b11382` (`sha256:50265c121d641f9f74673382e003439458c702da8f6b15fb28511b4531f8fd90`, amd64 only, 647 MB compressed) and `full-openvino-b11382` (`sha256:c42ea263ea17aa7c326239cd27ca77e4389fa67f405dfc1631eb13cbf32a579c`). The Dockerfile bundles OpenVINO 2026.4.1, Intel's GPU compute runtime and the NPU user-space driver. A Windows build ships as `llama-b11382-bin-win-openvino-2026.4.1-x64.zip`.
- **Docker:** the documented commands pass `--device /dev/dri` for the GPU or `--device /dev/accel` for the NPU, add the render group, and choose the device with `GGML_OPENVINO_DEVICE=GPU` or `NPU`. A device that is not there is an error, with no fallback to the CPU.
- **In the wild:** in the Vulkan thread above, the poster of the Core Ultra 300 row tried the OpenVINO backend in September 2026 and the model exited while loading, without an error code.

### What trying it would need

The same Intel Core Ultra Series 2 Linux laptop as the Vulkan spike. One llama-bench run in `full-openvino-b11382` with `--device /dev/dri` and `GGML_OPENVINO_DEVICE=GPU`, then one with `--device /dev/accel` and `NPU`. `-fa 1` is required, and the NPU needs an explicit small context. Keep each run in its own file as above. Only if those beat Vulkan on the same laptop: an override for `llm` with the `server-openvino` image, the device, the environment variables and a volume for `GGML_OPENVINO_CACHE_DIR` (compiled graphs), then the same evaluation.

### Limits that matter for Horus

- **Stateful mode or the prompt cache.** The page recommends `GGML_OPENVINO_STATEFUL_EXECUTION=1` for GPU speed. In that mode llama-server serves one chat session, and state save and restore, sequence rewind and context shift are unsupported. llama-server's prompt cache (`--cache-ram`) and its reuse of a shared prompt start are built on those, and B-99 lays out the agents' prompts for that reuse. Expect every request to read its whole prompt in stateful mode; stateless mode keeps the cache at the cost of the speed the page recommends stateful mode for.
- **Requantisation at load.** On CPU and GPU, `Q5_K` and `Q6_K` tensors are converted to an 8-bit format when the model loads. A Q4_K_M file usually keeps some tensors in `Q6_K`, so memory use is above the file size; `GGML_OPENVINO_REQUANT_KQUANT` can trade accuracy back for memory.
- **The NPU is a different machine.** Its main format is `Q4_0` (`Q6_K` is requantised to 4 bits) and it runs a static graph that reads prompts in fixed chunks (256 tokens by default). The page warns that large contexts can fail or run out of memory on the NPU, and its examples use 512 to 1,024 tokens where the `llm` service uses 8,192. It runs stateless only, with one sequence (`--parallel 1`, which the `llm` service already uses).
- **First-request latency.** Each graph is converted and compiled on first use. The compiled-model cache options help only when shapes repeat.
- **Reach.** Intel only, amd64 only, Linux for the containers. It does nothing for AMD laptops.

## Other routes seen, not evaluated

- **AMD NPUs (XDNA 2):** llama.cpp has no upstream backend for them. AMD's route is FastFlowLM: Ryzen AI chips with XDNA 2 NPUs, Windows and, since March 2026, Linux, with an OpenAI-compatible server (`flm serve`). Its orchestration code is MIT-licensed and its NPU kernels are free binaries. It would be a second model runtime next to llama-server, so it is out of scope for this spike.
- **Docker Model Runner:** Docker announced Vulkan support in October 2025, iGPUs included. It would put Docker's engine and release cycle in place of the llama.cpp build Horus pins and measures.

## Recommendation

1. **Build nothing now and add no profile.** This matches the plan.
2. **Vulkan: one spike on Linux, in the order above,** after or alongside the B-91 `cpu16` runs. llama-bench first: it costs one image pull with the GGUF already on disk, and it stops the spike early if prompt reading is not at least twice as fast. The evaluation runs only if it is. If both pass, B-100 gets an opt-in Vulkan variant of the CPU profiles on Linux: the same model and the same memory budget, not a new profile. Run the native Windows llama-bench on the development laptop as well, to know what a native `llama-server.exe` would gain before anyone writes that ADR.
3. **OpenVINO: watch, do not build.** Re-check when the work-in-progress note goes, when validation covers more than Core Ultra Series 1 and 2, or when stateful mode keeps the prompt cache. Until then, the only cost worth paying is the two extra llama-bench runs if the Vulkan spike uses an Intel Series 2 laptop.
4. **NPUs: not for the LLM.** An NPU embedder offload through ONNX Runtime stays with the earlier research and needs its own measurement on the CPU profiles first.

## Sources

Read on 2026-10-05. Numbers from these pages are summarised, not reproduced.

- Performance of llama.cpp with Vulkan, discussion #10879: https://github.com/ggml-org/llama.cpp/discussions/10879
- Vulkan on an Intel iGPU inside WSL 2 with Mesa `dzn`, discussion #26729: https://github.com/ggml-org/llama.cpp/discussions/26729
- llama.cpp OpenVINO backend: https://github.com/ggml-org/llama.cpp/blob/b11382/docs/backend/OPENVINO.md
- llama.cpp Docker images: https://github.com/ggml-org/llama.cpp/blob/master/docs/docker.md
- llama.cpp build guide, Vulkan and Docker: https://github.com/ggml-org/llama.cpp/blob/b11382/docs/build.md#vulkan
- Image recipes at b11382: https://github.com/ggml-org/llama.cpp/blob/b11382/.devops/vulkan.Dockerfile, https://github.com/ggml-org/llama.cpp/blob/b11382/.devops/openvino.Dockerfile
- Vulkan device selection and capabilities at b11382: https://github.com/ggml-org/llama.cpp/blob/b11382/ggml/src/ggml-vulkan/ggml-vulkan.cpp; the iGPU loading fallback: https://github.com/ggml-org/llama.cpp/blob/b11382/src/llama-model.cpp; issue #28160: https://github.com/ggml-org/llama.cpp/issues/28160
- llama-server and llama-bench options at b11382: https://github.com/ggml-org/llama.cpp/blob/b11382/tools/server/README.md, https://github.com/ggml-org/llama.cpp/blob/b11382/tools/llama-bench/README.md
- Release b11382 and its assets: https://github.com/ggml-org/llama.cpp/releases/tag/b11382
- Image digests and sizes: the `ghcr.io/ggml-org/llama.cpp` registry manifests
- Docker Desktop GPU support: https://docs.docker.com/desktop/features/gpu/
- Ubuntu 26.04 `mesa-vulkan-drivers` file list: https://packages.ubuntu.com/resolute/amd64/mesa-vulkan-drivers/filelist
- FastFlowLM: https://github.com/FastFlowLM/FastFlowLM
- Docker Model Runner and Vulkan: https://www.docker.com/blog/docker-model-runner-vulkan-gpu-support/
