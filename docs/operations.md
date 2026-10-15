# Operations

Running Horus in dev/staging/prod: deployment, monitoring, secrets, and the per-environment configuration matrix.

---

## Deployment and CI

### Repository branches

- **`main`** in [`Horus-EIP/horus`](https://github.com/Horus-EIP/horus): the working branch and the default branch. Start from it and open pull requests against it ([CONTRIBUTING.md](../CONTRIBUTING.md#branches)).  
- **`master`** in the Epitech repository: the graded copy. It receives `main` through a sync pull request after each batch of merged work; nobody commits there directly.  
- **Feature branches**: `issue-<number>-<short-description>`.  

This repository’s canonical remote is the project GitHub org; avoid unapproved mirrors.

---

### CI pipeline

Continuous integration is defined in **`.github/workflows/ci.yml`** at the repository root. It runs on every pull request, on pushes to `main` and to the Epitech repository's `master`, and by hand. A new commit on a pull request cancels that pull request's run still in progress; a run on a branch or by hand has a concurrency group of its own, so it is never cancelled or held back. The coverage summary job runs when a test job fails but not in a cancelled run (`!cancelled()`), so a superseded run ends at once. `ci.yml` and `eval-testset.yml` only read the repository and use no secret, so a pull request from a fork, which gets a read-only token and no secrets, runs every job; `tests/ci/test_workflow_triggers.py` checks the triggers, the concurrency group and this. The service and installer test jobs use the Python of the images, read from `src/services/PYTHON_VERSION` (3.11.17), which `tests/ci/test_image_python.py` checks against every `FROM python:` line. The bench-kit job runs on 3.10 and 3.13; the other jobs run tools, on Python **3.13**. Every action in every workflow file of the repository, nested ones included, is pinned by its full commit SHA, with its version in a comment, at a release that runs on Node 24, and every Linux job names its runner image, `ubuntu-24.04` (`ubuntu-22.04` in `desktop-release.yml`), so that GitHub moving `ubuntu-latest` does not change CI mid-sprint. `tests/ci/test_workflow_pins.py` checks both.

**Summary**

1. **`lint`**: `ruff check src tests scripts installer packaging` with ruff 0.16.6.
2. **`versions`**: the `tests/ci` unit tests, then `scripts/ci/check-versions.py` compares every version number with `VERSION`.
3. **`licences`**: the tests of the licence scripts, then `scripts/licences/third_party_notices.py --check` (fails when `THIRD_PARTY_NOTICES` or its data is out of date, including the list of GPL and LGPL system packages after a Dockerfile change) and `scripts/licences/check_licences.py` (fails on GPL, AGPL or SSPL among the Python packages, the web client's production dependencies and the desktop app's crates; LGPL is a warning; reviewed exceptions are in `scripts/licences/allowlist.yaml`).
4. **`test-mas`**: installs `src/services/mas/requirements.txt`, the CPU set, with `requirements-test.txt` (the test tools, which the images leave out), and fails if it brought in torch or a CUDA package. Then `pytest -c tests/mas/pytest.ini tests/mas -m "not requires_stack"`, with `tests/mas/test_integration.py` ignored and 85% coverage required. No service containers: SQLite, fakeredis and mocks stand in for Postgres, Redis and RabbitMQ, and the job copies `.env.example` to `src/infra/.env` for the tests that read settings.
5. **`test-agent`**: installs `src/services/agent/requirements-gpu.txt` and `requirements-test.txt` with `https://download.pytorch.org/whl/cpu` as an extra index, because its tests cover the in-process model code, and fails unless torch is the pinned CPU build. Then `tests/agent`, with 90% coverage required.
6. **`test-knowledge-store`**: installs `src/services/knowledge-store/requirements.txt` and `requirements-test.txt`, fails on torch or a CUDA package, downloads the BGE model into a cached `FASTEMBED_CACHE_PATH`, then `tests/knowledge_store` with 85% coverage required. `HORUS_REQUIRE_MODEL_TESTS=1` makes `unit/test_real_fastembed.py` fail rather than skip without the model, so real search with FastEmbed still runs in CI now that `e2e-mock` embeds with `llm-mock`.
7. **`test-installer`**: `pytest installer/tests` with PyYAML, with coverage of `installer/` and no gate. The release workflows run the same tests with `unittest` on the same Python.
8. **`test-llm-mock`**: `tests/llm_mock`, the unit tests of the mock model server, with 90% coverage required, then `tests/contract`, the model contract tests, on the mock: the chat requests of MAS and the agent and the embeddings requests of MAS and the knowledge store (see [Mock AI mode](mock-ai.md#tests)).
9. **`coverage-summary`**: each test job writes its suite, its lines covered, its lines and branches covered (in a job with a gate, the figure the gate compares with its minimum, the job log's `Total coverage`; `test-installer` has none) and its tests passed, failed and skipped to its own job summary with `scripts/ci/coverage-line.py`, even when its tests fail, and passes that line on as a job output. This job collects the five lines into the run summary and names any that did not arrive, so it needs no artifact.
10. **`e2e-mock`**: the end-to-end test, with no model at all. It checks `docker compose config` with and without the mock and monitoring-off overlays, builds every image of the stack (MAS, the agent, the knowledge store, the web client and `llm-mock`), and starts all of it with `docker-compose.mock.yml` and `docker-compose.monitoring-off.yml` (`HORUS_MOCK_LATENCY_MS=0`): `llm-mock` answers and embeds, spaCy and monitoring are off. It uploads `demo_assets/` to the knowledge store, runs `installer/smoke.py`, and fails unless its 9 steps pass with no warning (`scripts/ci/smoke-steps.py`), unless `/system/ai` says mock, mock embeddings, spaCy off and monitoring off, and if any service logged a model load: `scripts/ci/no-model-loads.py` reads each service's log for the lines FastEmbed, spaCy and the in-process language models write when they load, and requires the lines that say MAS and the knowledge store embed through a server and spaCy is off. Every `docker compose` call runs with `env -i`, so the workflow's test credentials never reach the stack. It writes its duration (build, start, smoke) to the job summary, needs no artifact, and repays ADR-005 B1.

The MAS, agent and knowledge-store jobs upload their coverage XML, junit XML and HTML report only when the job fails (`if: failure()`), kept 3 days, so a green run adds nothing to the artifact storage quota, which is shared across the organisation; the figures stay in each job's summary. The other test jobs upload nothing. Every upload step has `continue-on-error: true`: a full quota does not fail a job. `desktop-release.yml` keeps the app builds 7 days and the release zip 14, and its bundle job stops before building the zip when one platform's app did not arrive.

Apart from `e2e-mock`, which runs the stack with no model, tests that need the running stack are not run in CI. For exact steps and env overrides, read the workflow file: it remains the source of truth.

The **`cpu-images`** job builds the mas, agent and knowledge-store images through the CPU overlay (one runner per image). It fails if `pip list` in an image shows any `nvidia-*`, `cuda-*` or `triton` package, or any torch or sentence-transformers, since a CPU image installs a `requirements.lock` that pins no torch (`scripts/ci/check-cpu-image.py`). It writes each image's size and build time to the job summary. The **`cpu-build-wiring`** job runs first: `tests/ci/test_cpu_torch_build.py` checks the requirement sets, the Dockerfiles, the overlay and the `cpu-images` job without building anything.

The release images are built by a separate workflow, **`.github/workflows/images.yml`**, described under [Prebuilt images](#prebuilt-images).

---

### Prebuilt images

Testers and customers do not build the Horus images. `.github/workflows/images.yml` builds them, signs them and pushes them to a private registry, and the installer pulls them.

**Names.** `<registry>/horus-<service>:<version>-<flavor>` for `mas`, `agent`, `knowledge-store` and `web-client`, and `horus-llm-mock:<version>-cpu`, the mock model server of [mock AI mode](mock-ai.md), defined in `docker-compose.mock.yml`. `<version>` is `VERSION`; `<flavor>` is `cpu` for the `cpu-*` profiles and `gpu` for the others. Compose builds each name from `HORUS_REGISTRY`, `HORUS_VERSION` and the compose files: `docker-compose.yml` ends the tag in `-gpu`, and `docker-compose.cpu.yml`, which also selects the CPU requirement set (see [Local deployment with Docker](#local-deployment-with-docker)), ends it in `-cpu`. When `HORUS_REGISTRY` is unset, as in `.env.example`, the `image:` fields resolve to nothing and Compose keeps its local build names (`<project>-mas` and so on), so `docker compose up --build`, `stack-up.sh` and the `cpu-images` CI job build exactly as before. Every build also gets a commit tag, `sha-<12 hex digits>-<flavor>`.

**Workflow.** It runs on a `v*` tag and by hand. The `plan` job runs `tests/ci/test_release_images.py` and the installer tests, checks the version numbers and that the tag is `v` followed by `VERSION`, then picks the registry: the repository variable `HORUS_REGISTRY`, else the installer's default `ghcr.io/epitechpromo2027`. The `image` job builds each of the 4 app services in both flavors on its own runner, through the same compose files the profiles use, and `llm-mock` once, as `cpu`, through `docker-compose.mock.yml`. It rejects a CPU image that contains a CUDA package or any torch, pushes the commit tag and, only when the run's ref is the tag `v<VERSION>`, the version tag, then signs the digest and checks the signature. A run started by hand from a branch publishes commit tags only, so it can never replace a release.

| Setting (Settings > Secrets and variables > Actions) | Kind | Default |
|---|---|---|
| `HORUS_REGISTRY` | variable | `ghcr.io/epitechpromo2027`, the installer's default. Change it only together with the installer's `--registry`; the workflow warns when they differ. |
| `HORUS_REGISTRY_USERNAME` | variable | the account that started the run |
| `HORUS_REGISTRY_TOKEN` | secret | the run's `GITHUB_TOKEN` with `packages: write`, which is enough for GHCR |

On GHCR, check after the first release that each `horus-*` package under the organisation's Packages tab is **Private** and gives this repository write access.

**Signing.** cosign signs each digest keyless, with the workflow's GitHub OIDC identity: Fulcio issues a short-lived certificate for `https://github.com/<owner>/<repo>/.github/workflows/images.yml@<ref>` and Rekor records the signature. Keyless was chosen because there is no private key to store, rotate or leak: a stolen repository secret cannot sign an image, and each signature says which workflow, ref and commit produced the digest. The cost is that Rekor is a public log: the repository name, the workflow path, the ref, the commit SHA and the image digests become public, though no code or image content does. If that matters more than key management one day, switch to a key pair (`cosign generate-key-pair`, a `COSIGN_PRIVATE_KEY` secret, `--tlog-upload=false`) and ship the public key with the installer. The workflow installs cosign 3 through `sigstore/cosign-installer@v4.1.2`, which stores each signature as a Sigstore bundle; check an image by hand with cosign 3 or later:

```bash
cosign verify \
  --certificate-identity "https://github.com/Horus-EIP/horus/.github/workflows/images.yml@refs/tags/v0.1.2" \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  ghcr.io/epitechpromo2027/horus-mas:0.1.2-cpu
```

**GPL and LGPL sources.** The images contain GPL and LGPL packages from Debian and Alpine, so each release comes with the written offer in section 7 of `THIRD_PARTY_NOTICES`, also in `/usr/share/doc/horus/` in every image: for three years after we last distribute a version, its source on request. To answer a request, run `scripts/licences/fetch-gpl-sources.py` on the image concerned. It reads the package list from the image, downloads each source package (from snapshot.debian.org for Debian, the aports repository and the Alpine distfiles for Alpine), checks its hash and writes one tar archive with a `PACKAGES.tsv` and a `SOURCES.tsv`. Add `--dry-run` to see the list and the size first. It needs Docker and the network; the knowledge-store image needs about 350 MB.

```bash
python scripts/licences/fetch-gpl-sources.py ghcr.io/epitechpromo2027/horus-knowledge-store:0.1.2-cpu --out gpl-sources
```

When a Dockerfile's base image or the system packages of its final stage change, build the four CPU images and run `scripts/licences/third_party_notices.py --refresh system --image mas=IMAGE --image agent=IMAGE --image knowledge-store=IMAGE --image web-client=IMAGE` so that the list in `THIRD_PARTY_NOTICES` follows; `--check` fails until then.

**Installer.** By default it never builds:

1. It writes `HORUS_REGISTRY` (from `--registry`, the `HORUS_REGISTRY` variable, the previous install, or the default) and `HORUS_VERSION` to `.env`. Preflight checks that registry's host instead of PyPI, npm and Debian, and for GHCR also `pkg-containers.githubusercontent.com`, which serves the image layers: a proxy or firewall has to let both through. The `cpu-*` profiles need both GHCR hosts in any case, for the llama.cpp server image (see [Installer preflight](#installer-preflight)). It also writes `REDIS_PASSWORD`: a generated 64-hex-character password on a first install, and in place of the `redis_password` earlier releases shipped or an empty value; any other value is kept. When it changes, the `docker compose up -d` of step 4 recreates `redis`, `mas` and `agent` with it.
2. If it is given a token, it signs Docker in with `docker login <host> --username <user> --password-stdin`, the token on stdin. The token comes from `--registry-token-file PATH`, from `HORUS_REGISTRY_TOKEN` (with `HORUS_REGISTRY_USERNAME` or `--registry-user`), or from `registry-token.txt` next to START-HERE, written as `USERNAME:TOKEN` on one line. It never reaches `install-log.txt`, `.env` or `horus-profile.json`, and no flag takes the token itself, so it stays out of shell history and process lists. The bundle builder never archives a `registry-token.txt`. Docker keeps the sign-in in its credential store like any `docker login`; `docker logout ghcr.io` removes it. On GHCR the token is a personal access token (classic) with `read:packages`. A refused sign-in stops with exit code 47.
3. It pulls the Horus images first, then the third-party ones, one at a time with 3 tries each. It checks that each Horus image is really on the machine afterwards (`docker image inspect`), because `docker compose pull` can report success for a service that also has a `build:` section. When the registry refuses an image it stops at once with exit code 41 and says how to give it the token.
4. It starts the stack with `docker compose up -d --no-build`. `--start` and `--restart` also pass `--no-build` while `.env` has `HORUS_REGISTRY`. It then names the Horus images this install does not use, with the `docker image rm` command that frees their space: images an earlier source install built (`<project>-mas` and so on), and other releases or the other flavor of `<registry>/horus-*` (another tag of the image in use is left out). It removes nothing itself. At the end it offers to prune Docker's build cache when more than 1 GB of it is left from earlier source builds, as the source path does.

**Building from source.** `--build-from-source`, or `HORUS_BUILD_FROM_SOURCE=1`, is the contributors' path: the installer writes no `HORUS_REGISTRY` (and deactivates one left by a previous install), pulls only the third-party images, builds, and offers to prune the build cache at the end. `--no-build` skips the rebuild on a re-run. `stack-up.sh` also builds from source, with whatever `HORUS_REGISTRY` is in `.env`: in a checkout where the installer wrote one, its build takes the release image names and replaces the pulled images on this machine. Run the installer once with `--build-from-source` to go back to local names; the next prebuilt install pulls the release images again.

**Not done yet.**

- The images are linux/amd64 only. On Apple Silicon Docker runs them through emulation; the installer warns and suggests `--build-from-source`.
- The beta ZIP still ships the service source, which `--build-from-source` needs, and the agent service still bind-mounts `src/services/agent/app` over `/app`. On an installed stack the agent therefore runs the ZIP's copy of its code, which is the same commit as its image. Dropping both is step 1 of ADR-004's technical protection. The mount needs another home first: the repository's `.gitignore` keeps `docker-compose.override.yml` for personal overrides.
- The installer does not verify signatures itself; testers do not have cosign.
- The web client's `NEXT_PUBLIC_KNOWLEDGE_STORE_URL` and `NEXT_PUBLIC_KNOWLEDGE_STORE_API_PREFIX` are Next.js build arguments, so CI bakes them into the browser code of the image. On a prebuilt install, changing them in `.env` has no effect: install with `--build-from-source` to change them. Moving them to runtime configuration is a follow-up.
- Install time and peak disk with prebuilt images are not measured yet; the installer still asks for the 150 GB measured when the images were built locally.

---

### Local deployment with Docker

Build and run the full stack from the infra directory:

```bash
cd src/infra
bash init-env.sh       # once: creates .env with a generated JWT secret and Valkey password
docker compose up --build -d
```

Services are defined in **`src/infra/docker-compose.yml`**. See [Configuration](getting-started.md#12-factor-configuration-management) and [Monitoring](#monitoring-and-observability) for URLs and observability.

Every published port is bound to 127.0.0.1, `web-client` (3000) included; `HORUS_WEB_BIND=0.0.0.0` in `.env` publishes 3000 on every interface instead (table and what that means in [Network security](security.md#63-network-security)). The browser calls MAS (`ws://<page host>:8000`) and the knowledge store (`http://localhost:8080`) directly, so the web client works fully only in a browser on the machine that runs the stack.

On a machine without an NVIDIA GPU, add the CPU overlay. The installer does this for the `cpu-*` profiles by writing `COMPOSE_FILE` to `.env`:

```bash
docker compose -f docker-compose.yml -f docker-compose.cpu.yml up --build -d
```

The mas, agent and knowledge-store folders each hold two requirement sets: `requirements.txt`, the CPU set, with no torch, transformers or sentence-transformers (both embedders run on FastEmbed and ONNX Runtime), and `requirements-gpu.txt`, which is `-r requirements.txt` plus the in-process model stack and one pinned `torch==X`. Each Dockerfile picks the set from the build argument `TORCH_INDEX_URL`. The overlay sets it to `https://download.pytorch.org/whl/cpu` for mas, agent and knowledge_store, and that exact value installs `requirements.txt`: no torch at all. Without the overlay, the argument defaults to `https://pypi.org/simple`, and any value other than the CPU index installs `requirements-gpu.txt`: its pinned torch first, from that index (the CUDA build the GPU profiles use), then the rest of the set, which keeps that torch. The three GPU sets pin the same torch version; change them together. `src/services/mas/requirements-cpu.txt` is only `-r requirements.txt`, kept for scripts that name it.

#### The CPU model server

The overlay also adds `llm`: one llama-server (`ghcr.io/ggml-org/llama.cpp:server-b11382`) that serves Qwen3-4B-Instruct-2507 Q4_K_M to MAS and to every agent. The `cpu-*` profiles point both clients at it with `LLM_BACKEND=vllm` (the OpenAI-compatible client mode), `LLM_VLLM_URL=http://llm:8080/v1`, `LLM_VLLM_MODEL=qwen3-4b`, `LLM_VLLM_MAX_MODEL_LEN=8192` and `LLM_VLLM_TIMEOUT=900`. With that backend MAS and the agent load no model in-process and their entrypoints download none; MAS still loads its MiniLM skill embedder. The GPU profiles keep the `vllm` service.

- **Model file.** `models/manifest.json` lists it: id, version, file, size, SHA-256, minimum RAM, profiles and mirrors. The installer downloads the chosen profile's default model into `models/` (or `--models-dir`, which later runs read back from `.env`) after the images are pulled (or built) and before the first start, and checks it again on every `--start` and `--restart`: it resumes a `.part` file with HTTP `Range`, retries with a growing pause, moves to the next mirror after 3 failures in a row (6 on the last mirror), verifies the SHA-256 and renames the file in one step. A bad hash deletes the file and stops with exit code 45. The installer writes `HORUS_MODELS_DIR` and `LLM_GGUF_FILE`, `LLM_GGUF_URL`, `LLM_GGUF_SHA256`, `LLM_GGUF_SIZE` to `.env`; compose mounts `HORUS_MODELS_DIR` (default `../../models`) read-only into `llm` at `/models`. Details and the download size are in `scripts/models/README.md`.
- **Start order.** The one-shot service `llm-model` runs first (`src/infra/llm/fetch-model.sh`). It finds the file the installer verified and exits at once; without the installer it downloads the file into the same folder, resuming and checking the SHA-256. `llm` starts once it has exited successfully, and `mas` and `agent` wait for `llm` to be healthy (`GET /health`, 10 minute start window).
- **Server flags.** `--ctx-size` and `--alias` come from `LLM_VLLM_MAX_MODEL_LEN` and `LLM_VLLM_MODEL`, so server and clients cannot disagree. `--cache-type-k`, `--cache-type-v`, `--flash-attn` and `--cache-ram` come from `LLM_SERVER_CACHE_TYPE_K`, `LLM_SERVER_CACHE_TYPE_V`, `LLM_SERVER_FLASH_ATTN` and `LLM_SERVER_CACHE_RAM_MIB`, whose compose defaults are the `cpu-standard` values (f16, f16, `auto`, 1024); `cpu-lean` writes others (see [Hardware decision](#hardware-decision)). One slot (`--parallel 1`; other requests wait in its queue), `--load-mode mmap`, `--metrics`.
- **Resources.** `LLM_SERVER_THREADS` (default 4) is `--threads`; the installer writes the physical core count. It also writes `LLM_TORCH_INTRAOP_THREADS=1`, which MAS's MiniLM embedder (ONNX Runtime) takes as its thread count unless `MAS_EMBED_THREADS` is set, and `AGENT_TORCH_INTRAOP_THREADS=1`, which nothing reads in a CPU agent image because it has no torch. `LLM_SERVER_MEM_LIMIT` (default `6g`) is the memory ceiling, and the swap ceiling follows it unless `LLM_SERVER_MEMSWAP_LIMIT` is set. On the CPU, MAS defaults to `3g` and the agent to `4g`.
- **Network.** The port is not published to the host. llama-server runs without an API key because only the containers on `horus-net` reach it.

```bash
cd src/infra
docker compose logs llm-model
docker compose logs -f llm
docker compose exec llm curl -s localhost:8080/health
```

#### Hardware decision

The installer chooses the profile right after it has checked Python, Docker and Compose: before the disk, network and port checks, the registry sign-in, the file-access questions and every download (`decide_profile` in `installer/horus_install.py`).

1. **Probe.** OS, processor (with AVX2), RAM, disk, the host's GPU list and the memory Docker can use (`docker info --format '{{.MemTotal}}'`). Then, only when there is a GPU to try, the Docker GPU test (`nvidia-smi` in `nvidia/cuda:12.4.0-base-ubuntu22.04`, about 250 MB the first time).
2. **GPU or CPU.** A GPU profile when Docker can use an NVIDIA card with at least 6 GiB of VRAM. Otherwise a CPU profile, chosen on the memory Docker can use, or on the RAM when Docker does not say. The thresholds are those of [ADR-006](adr/ADR-006-low-ram-machines.md), whose status is Proposed: planning figures until the B-91 measurements confirm or move them.

   | Memory Docker can use | Profile | llama-server |
   |---|---|---|
   | 15.0 GiB or more | `cpu-standard` | `--ctx-size 8192`, f16 KV cache, `--flash-attn auto`, `--cache-ram 1024`, `mem_limit` 6g |
   | 13.5 to under 15.0 GiB | `cpu-lean` | the same model, `--ctx-size 4096`, q8_0 KV cache, `--flash-attn on`, `--cache-ram 256`, `mem_limit` 5g |
   | under 13.5 GiB | not supported | none |

   On Linux Docker can use all the RAM. On Windows Docker Desktop runs in WSL 2, which gets half of the RAM by default, and on macOS it gets what its settings give it.
3. **Not supported.** The installer stops with exit code 32 before anything large is downloaded. The screen lists what the machine has, what Horus needs and what to do: give Docker more memory (on Windows through WSL Settings > Memory and processor, or `memory=` under `[wsl2]` in `%UserProfile%\.wslconfig`, then `wsl --shutdown`; the installer never changes it), use a machine with an NVIDIA GPU or more RAM, or force a profile. With `--json-events` the same content is one `unsupported` event, which the desktop app shows on its own screen. `horus-profile.json` keeps it, so the app and `--start` show it again instead of "not installed", until a later run gets past the decision, even one that stops at a later step. The app's **I have run START-HERE again** button looks again. `--profile cpu-lean` or `--profile cpu-standard` still installs, with a warning.
4. **AVX2.** Read from the `flags` of `/proc/cpuinfo` on Linux, `sysctl hw.optional.avx2_0` on an Intel Mac and `IsProcessorFeaturePresent(40)` on Windows. Apple Silicon and other ARM processors are not checked: AVX2 is an x86 feature. Without it the installer warns on a CPU profile and goes on: the official llama.cpp build picks the CPU code at start, so llama-server still runs, slowly.
5. **Re-runs.** The installer writes `horus-profile.json` as soon as it has decided, and again with the settings once `.env` is written. It keeps a fingerprint of the RAM, the Docker memory and the GPU list. When the next run finds the same fingerprint and Docker could use the GPU last time, the GPU test is not repeated and its result decides again. A GPU test that failed always runs again, so a driver or toolkit fixed since is noticed. `--profile` still overrides.

The thresholds live in one place, `installer/profiles.py`: `CPU_STANDARD_MIN_GIB`, `CPU_LEAN_MIN_GIB`, and `CPU_LEAN_SUPPORTED`, which turns option B off (every machine under 15.0 GiB is then not supported) if the measurements reject the q8_0 cache. `--dry-run --simulate linux-cpu-8gb` (or `laptop-cpu-14gb`, `linux-cpu-16gb`, `windows-cpu-16gb`, `old-cpu-no-avx2`) shows each outcome without Docker. `--dry-run` without `--simulate` decides for this machine as the install would: it asks Docker how much memory it can use (`docker info`, which changes nothing), and falls back to the RAM when Docker does not answer.

#### Installer preflight

Before the hardware decision the installer checks Python 3.11 or newer, the Docker daemon and Compose; `--start` and `--restart` check Docker and Compose again. After the decision it checks the disk, the network and the ports (`installer/preflight.py`).

- **Compose version.** The compose files need Docker Compose **2.33.0** or newer, the newest of the features they use, each taken from the Compose release notes and the compose-go version each release ships:

  | Feature in the compose files | Supported since |
  |---|---|
  | `gpus: all` on a service (base file) | Compose 2.33.0 (compose-go 2.4.8; 2.30 to 2.32 accept only a list of device requests, older ones no `gpus` key) |
  | `depends_on` with `required: false` | Compose 2.20.2 |
  | the `!reset` tag (CPU overlay) | Compose 2.18.0 (compose-go 1.13.5) |
  | `${VAR:+...}` interpolation (image names) | Compose 2.8.0 (compose-go 1.3.0) |

  An older Compose stops the installer with exit code 13 and the update steps. A version string with no `x.y.z` in it (some builds print a commit hash) only gets a warning. The table is `COMPOSE_FEATURES` in `installer/preflight.py`; `installer/tests/test_preflight_requirements.py` fails when the compose files stop using one of these features.
- **Network.** The hosts every install needs (Docker Hub and Hugging Face), then the image source: PyPI, npm and Debian when building from source, or the registry of the prebuilt images (see [Prebuilt images](#prebuilt-images)). On a `cpu-*` profile it also checks the registry of the llama.cpp server image, `ghcr.io` and `pkg-containers.githubusercontent.com` by default, even when the Horus images come from elsewhere or are built from source. `LLM_SERVER_IMAGE`, from the environment or `src/infra/.env` as for Compose, moves that check to its own registry; an image on Docker Hub adds nothing. A host that serves both is checked once.
- **Ports.** Every port in `PORTS` (`installer/preflight.py`) must be free on 127.0.0.1 and ::1, or held by this install's own containers. Every port is published on 127.0.0.1 only, 3000 included unless `HORUS_WEB_BIND` says otherwise; `tests/ci/test_published_ports.py` fails when the compose file publishes a port that `PORTS` does not check.

#### Upgrades and uninstall

An install, a re-install, `--start` and the `up -d` that `--restart` falls back to start the stack with `docker compose up -d --remove-orphans` when `COMPOSE_PROJECT_NAME` names the project, in the environment or in `src/infra/.env` (`.env.example` sets `horus_betatest`). Compose then removes the containers of services the compose files no longer define: `promtail` and `redisinsight` after an upgrade, `llm` and `llm-model` after a switch to a GPU profile. Without the name Compose calls the project after the folder, `infra`, which another checkout can share, so the installer leaves the flag out and Compose only warns. It also leaves it out when `COMPOSE_IGNORE_ORPHANS` is true, in the environment or in `.env`, because Compose refuses the two together. A service whose Compose profile is off is not an orphan: `pgadmin` (`dev-tools`) and, on a CPU profile, `vllm` (`gpu`) keep their containers.

A new install generates the admin password, `SUPER_USER_PASSWORD` in `src/infra/.env`, as `init-env.sh` does, and shows it once, at the end of the install, under the login name; it never goes into `install-log.txt`. A re-install keeps a password that is already set, written back exactly as it was, quotes included. One that is still the shipped `admin`, or empty, is replaced by a generated one: the `docker compose up -d` that follows recreates `mas` and the agent with it, and MAS gives it to the admin account on that start if the account still has `admin`. An account whose password was changed in Horus is never touched. Once the stack is healthy the installer runs `docker compose exec -T mas python -m db.admin_account`, which prints `admin-account: ` followed by `created`, `replaced`, `matches`, `differs`, `shipped` or `refused`, never the password. The installer shows a generated password only when the account uses it; on `differs` it says to put the account's password in `SUPER_USER_PASSWORD`.

Agent workers use a separate MAS login (`SUPER_AGENT_USERNAME`, default `agent`, and `SUPER_AGENT_PASSWORD`), not the admin role. A new install or upgrade generates the agent password if it is missing or still the shipped value; it is stored in `src/infra/.env` and is not shown by the installer. For a direct update with an older `.env` that lacks these settings, MAS and Compose temporarily fall back to the existing admin password so the stack keeps starting; run the installer to replace that fallback with a dedicated generated secret. On startup MAS creates that account, or replaces its shipped `agent` password, without overwriting a password changed by an operator; it also enforces the `agent` role if the username already existed with another role. The installer checks it with `docker compose exec -T mas python -m db.agent_account`; the command prints only `agent-account: ` and an outcome (`created`, `replaced`, `matches`, `differs`, `shipped` or `refused`). If you start the stack by hand, run `bash src/infra/init-env.sh` before the first `docker compose up -d` so the generated value is present.

`--uninstall` runs `docker compose down --volumes --rmi all`, with `--remove-orphans` under the same rule. `--volumes` deletes the volumes the compose files declare now, for the services whose profile is on. Two kinds stay: a volume only an older version declared, and a volume only a service whose profile is off uses. The installer looks for the four it knows, by their Compose labels under the project name `docker compose config` resolves, so another project's volumes are never found: `<project>_redis_data` (Redis before Valkey), `<project>_redisinsight_data`, `<project>_pgadmin_data` and `<project>_vllm_hf_cache`, the GPU model weights, which a reinstall downloads again. The last two are left out when a service that is on uses them, as vLLM does on a GPU profile: `down --volumes` deletes them then. Before the stack comes down it lists the ones it found, each with its size (`docker system df --verbose`) and what it holds, asks one question for all of them, and deletes them after the stack is down if you answer yes. `--non-interactive`, or a run without a terminal, deletes nothing and prints the `docker volume rm` command. Without `COMPOSE_PROJECT_NAME` it looks for none. Any other volume of the project still there at the end is printed with its `docker volume rm` command.

`down` leaves the containers of services whose profile is off: `pgadmin` (`dev-tools`) and, after a switch to a CPU profile, the old `vllm` (`gpu`), with the network and the images they hold. So once `down` succeeds, the installer lists every container whose `com.docker.compose.project` label is the project name `docker compose config` resolves, removes them with `docker rm --force --volumes`, and runs the same `down` once more to free the network and the images. It does this only when `COMPOSE_PROJECT_NAME` is set, so a folder-named project, which another checkout can share, is never touched; containers of other projects and containers outside Compose do not carry the label. It does not use `COMPOSE_PROFILES` (`tests/ci` forbids it in the installer). Their named volumes, `pgadmin_data` and `vllm_hf_cache`, are in the question above.

---

### Production considerations

For production, teams commonly:

- Run behind a reverse proxy (for example NGINX) with TLS  
- Use managed PostgreSQL, Redis, and RabbitMQ where appropriate  
- Store secrets in a vault or orchestrator secrets, not in committed `.env` files  
- Tune resource limits, health checks, and autoscaling per environment  

Kubernetes, Docker Swarm, or cloud-specific runtimes are outside this document; adapt the same images and environment variables your Compose file uses.

---

## Monitoring and observability

This document describes the monitoring stack shipped with **`src/infra/docker-compose.yml`** (repository root): metrics (Prometheus), traces (Tempo, OTLP), and logs (Loki), all viewed in the web client's admin pages (`/admin/logs`, `/admin/metrics`, `/admin/traces`), plus admin UIs for data stores.

**Turning monitoring off.** `HORUS_MONITORING=on` or `off` in `src/infra/.env`. Unset, monitoring is off in [mock AI mode](mock-ai.md) and on in local mode; an explicit value wins in both. Off, the installer adds `docker-compose.monitoring-off.yml` last in `COMPOSE_FILE`:

- Prometheus, Loki, Tempo and Alloy get a profile nobody enables and 0 replicas, so they do not run; the web client no longer waits for them;
- MAS, the agent and the knowledge store get `OTEL_SDK_DISABLED=true` and `OTEL_ENABLED=false`: they export no trace and log no export error;
- the web client gets `HORUS_MONITORING=off`, and its logs, metrics and traces pages say "Monitoring is off on this install" and how to turn it on, instead of an error.

The installer applies a changed `HORUS_MONITORING` on the next `--start` or `--restart`, `--ai mock` and `--ai local` apply it too, and `--ai status` shows it. When it turns monitoring off it first stops the four services, since Compose leaves running a service its files no longer start. `--uninstall` offers their volumes and prints the command that deletes their images.

---

### Stack overview

| Layer | Components |
|-------|------------|
| Data stores | PostgreSQL, Valkey (service `redis`), RabbitMQ, ChromaDB (Knowledge Store volume) |
| Metrics | Prometheus scrapes MAS, Agent, and Knowledge Store `/metrics` endpoints; viewed at **`/admin/metrics`** in the web client |
| Traces | Grafana Tempo receives OTLP from application containers; viewed at **`/admin/traces`** in the web client (trace search + span waterfall) |
| Logs | Grafana Loki ingests stdout/stderr from **the Docker Compose services of this install** via Grafana Alloy (Docker service discovery, `observability/config.alloy`; Alloy lists only the containers whose `com.docker.compose.project` label is this install's Compose project, so other Compose projects and plain containers on the same Docker host are not read); viewed at **`/admin/logs`** in the web client |
| Visualization | Web client admin pages (`/admin/logs`, `/admin/metrics`, `/admin/traces`), backed by Loki, Prometheus, and Tempo; require the `admin` role |
| Admin UIs | RabbitMQ management plugin; PgAdmin as a development tool (Compose profile `dev-tools`); `valkey-cli` in the `redis` container for the cache |

The default Compose file does **not** include SigNoz, a standalone OpenTelemetry Collector service, PostgreSQL Exporter, or Metabase. If you add those services, extend this document accordingly.

#### Quick start

```bash
cd src/infra
docker compose up -d
```

PostgreSQL is started with `pg_stat_statements` preloading (see the `postgres` service `command` in Compose). If you change extension-related settings, restart the stack: `docker compose down && docker compose up -d`.

---

### Admin observability pages (web client)

Logs, metrics, and traces are viewed in the Next.js web client's admin pages. These require the `admin` role.

| Page | URL | Backend |
|------|-----|---------|
| Logs | http://localhost:3000/admin/logs | Loki |
| Metrics | http://localhost:3000/admin/metrics | Prometheus |
| Traces | http://localhost:3000/admin/traces | Tempo |

The **Metrics** page replicates the former "MAS Overview" dashboard: Task Queue Depth, Task Errors Rate, and Active Agents. The **Traces** page offers trace search and a span waterfall.

#### Backend datasources

The backends run **inside** the Docker network and are **not** published to the host by default:

- **Prometheus** at `http://prometheus:9090` (internal-only).
- **Tempo** at `http://tempo:3200` for trace queries (internal-only); only the Tempo OTLP ports `4317` / `4318` are published, on 127.0.0.1.
- **Loki** at `http://loki:3100` for log queries (internal-only; labels include `compose_service`, `compose_project`, `container`).

#### Log retention and integrity (Loki)

In **`src/infra/observability/loki.yaml`**, the compactor has **`retention_enabled: false`** (no automatic expiry of old logs) and **`limits_config.allow_deletes: false`** (the log-deletion API is off). Loki’s ingest path is append-only: existing lines are not updated in place through the query API.

That is **not** cryptographic immutability: anyone who can remove the Docker volume or files on disk can still destroy data. For strict write-once retention (for example compliance), use object storage with **Object Lock** (or an enterprise log archive) and restrict who can change buckets or Compose volumes.

#### Container log rotation (Docker)

Docker keeps each container's stdout/stderr in `json-file` logs, which `docker logs` and Alloy read. Every service takes the same `logging` block from the `x-logging` anchor at the top of its Compose file: at most `HORUS_LOG_MAX_FILE` files (default 10) of `HORUS_LOG_MAX_SIZE` (default `40m`) each, about 400 MB per container. When the last file is full, Docker deletes the oldest one.

- MAS writes the most: about 50 MB a day when idle on the GPU profile and about 120 MB a day under the installer's tests on the CPU profile (measured 2026-10-08), so `docker logs mas` goes back 3 to 7 days. An error that writes a traceback on every request writes far more: on 2026-09-09 MAS wrote about 500 MB in one hour, and at that rate the limit holds under an hour of MAS. Every other service writes under 5 MB a day.
- Loki keeps its own copy of every line Alloy shipped (retention is off, see above), including the lines Docker has rotated away. `/admin/logs` looks back at most 24 hours; older lines are read through Loki's API, for example `docker exec loki wget -qO- 'http://localhost:3100/loki/api/v1/query_range?query=%7Bcompose_service%3D%22mas%22%7D&start=<unix-ns>&end=<unix-ns>&limit=1000'`.
- To change the limits, set `HORUS_LOG_MAX_SIZE` and `HORUS_LOG_MAX_FILE` in `src/infra/.env`, then run `docker compose up -d`. Docker applies logging options only to the containers it creates, and `up -d` recreates the services whose configuration changed; `docker compose restart` does not.
- YAML anchors do not cross files, so `docker-compose.yml` and `docker-compose.cpu.yml` each define `x-logging: &logging`; `tests/ci/test_repository_wiring.py` (`LogRotation`) checks that the two stay the same and that every service uses the one in its own file.

---

### Prometheus

| Item | Value |
|------|--------|
| Scrape config (mounted in Compose) | **`src/infra/observability/prometheus.yaml`** |
| Jobs | `prometheus` (self), `mas-api`, `agent-api`, `knowledge-store`; on the CPU profiles also `llm` |
| CPU-only jobs | **`src/infra/observability/prometheus-llm.yaml`**, which only the CPU overlay mounts into `/etc/prometheus/scrape.d/`; `prometheus.yaml` reads that folder with `scrape_config_files`, so the GPU stack has no `llm` target to report down |

**Host access:** The `prometheus` service has **no** `ports:` mapping in the default Compose file. You cannot open `http://localhost:9090` on the host unless you add a port mapping. Use either:

- The web client **`/admin/metrics`** page, which reads from the Prometheus backend, or  
- **Docker**: `docker exec -it prometheus wget -qO- http://localhost:9090/api/v1/targets` (or add `9090:9090` under `prometheus` for local debugging only).

#### Verification

Inside the Docker network, targets should include `mas:8000`, `agent:8001`, and `knowledge_store:8080` when those services are up, and `llm:8080` (llama-server's `/metrics`, the `llamacpp:*` series) on the CPU profiles. There is no `postgres` scrape job in the default config.

---

### Tempo (distributed tracing)

| Item | Value |
|------|--------|
| OTLP gRPC (from apps) | `tempo:4317` inside the network; host ports `4317` / `4318` are published on 127.0.0.1, for a collector or a service run on this machine |
| App env | `OTEL_EXPORTER_OTLP_ENDPOINT=http://tempo:4317` (set per service in Compose) |

View traces in the web client **`/admin/traces`** page (trace search + span waterfall), backed by Tempo.

---

### Application metrics endpoints

When services run on the host (not only in Docker), raw Prometheus text format is available at:

| Service | URL (default local) |
|---------|---------------------|
| MAS | http://localhost:8000/metrics/ |
| Agent | http://localhost:8001/metrics/ |
| Knowledge Store | http://localhost:8080/metrics/ |

---

PgAdmin is a development tool: it starts only with `docker compose --profile dev-tools up`, and the installer never starts it. It ships with default credentials, so keep it off customer machines.

### PgAdmin 4

- **URL:** http://localhost:5433  
- **Credentials:** `PGADMIN_DEFAULT_EMAIL` and `PGADMIN_DEFAULT_PASSWORD` in `src/infra/.env`.

Register a server with host `postgres`, port `5432`, database `postgres` (or your `POSTGRES_DB`), using `POSTGRES_USER` / `POSTGRES_PASSWORD` from `.env`.

---

### Valkey (`redis` service)

From `src/infra`, `docker compose exec redis sh -c 'VALKEYCLI_AUTH="$REDIS_PASSWORD" valkey-cli'` opens `valkey-cli` with the password the container reads from `.env`, without putting it on the command line. `REDIS_PASSWORD` is generated by the installer and by `init-env.sh`, and the port answers on 127.0.0.1 only.

---

### RabbitMQ management

- **URL:** http://localhost:15672  
- **Credentials:** `RABBITMQ_USER` / `RABBITMQ_PASSWORD` in `.env`.

Monitor queues and connections for `mas` and `agent` consumers.

---

### Structured logging

#### Log format

Services can emit structured JSON logs (example shape):

```json
{
  "timestamp": "2026-01-12T10:30:00.000Z",
  "level": "INFO",
  "logger": "task",
  "message": "Task created: task-123",
  "module": "routes",
  "function": "create_new_task",
  "line": 260,
  "correlation_id": "550e8400-e29b-41d4-a716-446655440000",
  "extra": {
    "task_id": "task-123",
    "agent_id": "agent-456",
    "conversation_id": 1
  }
}
```

#### Correlation IDs

1. Incoming requests: `X-Request-ID` or `X-Correlation-ID` when present  
2. Otherwise: generated UUID  
3. Propagated downstream via headers  
4. Returned on responses where middleware supports it  

#### Log levels

| Level | Use |
|-------|-----|
| DEBUG | Verbose diagnostics |
| INFO | Normal operation |
| WARNING | Recoverable anomalies |
| ERROR | Failures requiring attention |
| CRITICAL | Severe failures |

#### Typical environment variables

```bash
LOG_LEVEL=INFO
JSON_LOGGING=true
```

---

### Metrics reference (MAS examples)

PromQL examples assume metric names exported by the MAS service; verify with `/metrics` if names differ.

```promql
rate(mas_http_requests_total[5m])
histogram_quantile(0.95, rate(mas_http_request_duration_seconds_bucket[5m]))
```

---

### Distributed tracing (application code)

Trace context is propagated via standard headers (for example W3C `traceparent` and correlation IDs) where instrumentation is enabled.

Example pattern (adjust imports to your service’s tracing module):

```python
from core.tracing import create_span, add_span_attributes

with create_span("my_operation", {"key": "value"}) as span:
    span.set_attribute("result", "success")
```

---

### Alerting

Alerting on Prometheus metrics is not configured in the minimal Compose defaults; wire your own rules into the Prometheus backend (for example via Alertmanager) if you need them. Suggested thresholds for your own rules:

| Signal | Warning | Critical |
|--------|---------|----------|
| Error rate | greater than 1% | greater than 5% |
| p95 latency | greater than 500 ms | greater than 2 s |
| Active agents | fewer than 2 | zero |
| Task queue depth | greater than 100 | greater than 500 |

---

### Environment variables reference

#### MAS (excerpt)

```bash
LOG_LEVEL=INFO
JSON_LOGGING=true
OTEL_ENABLED=true
OTEL_SERVICE_NAME=mas
OTEL_EXPORTER_OTLP_ENDPOINT=http://tempo:4317
OTEL_PYTHON_EXCLUDED_URLS=/health,/metrics,/rabbitmq/heartbeat,/agents/heartbeat/
TASK_TIMEOUT_SECONDS=300
```

In Docker Compose, `OTEL_EXPORTER_OTLP_ENDPOINT` points at the `tempo` service, not a separate OpenTelemetry Collector container.

#### Agent and Knowledge Store

Follow the same `OTEL_*` pattern as in Compose for each service; see service-specific env blocks in `docker-compose.yml`.

#### Models and monitoring (mock AI mode)

| Variable | Read by | Default | Meaning |
|---|---|---|---|
| `HORUS_MONITORING` | the installer, MAS (`/system/ai`), the web client | off in mock mode, on in local mode | `on` or `off`: whether Prometheus, Loki, Tempo and Alloy run and the services send traces. |
| `MAS_EMBED_URL`, `MAS_EMBED_MODEL` | MAS | unset; the MiniLM id | An OpenAI-compatible embeddings server (`POST <url>/embeddings`, 384 values per vector) instead of FastEmbed in MAS. |
| `KNOWLEDGE_STORE_EMBED_URL`, `KNOWLEDGE_STORE_EMBED_MODEL` | the knowledge store | unset; the bge-base id | The same for the knowledge store (768 values). Setting or clearing the URL, or naming another model, re-embeds the stored documents at the next start; a new URL for the same model does not. |
| `HORUS_SPACY` | the knowledge store, the agent, MAS (`/system/ai`) | `on` | `off` turns spaCy off: entities, topics and summaries come from regular expressions. |

[`docker-compose.mock.yml`](../src/infra/docker-compose.mock.yml) sets the embeddings URLs to `http://llm-mock:8080/v1` with the model `horus-mock`, and `HORUS_SPACY=off`.

---

### Performance impact

Observability adds small per-request overhead (logging, metrics, tracing). To reduce load in production: raise `LOG_LEVEL`, use trace sampling if configured in instrumentation, and reserve sufficient resources for Tempo and Prometheus volumes.

---

### Troubleshooting

#### `/admin/metrics` shows no Prometheus data

- Confirm `prometheus`, `mas`, `agent`, and `knowledge_store` containers are running.  
- Check the Prometheus targets directly: `docker exec -it prometheus wget -qO- http://localhost:9090/api/v1/targets`.  
- If Prometheus is unreachable from the web client, check the Docker network and **`src/infra/observability/prometheus.yaml`**.

#### Cannot open Prometheus on the host

- Expected with the default Compose file: add a host port for `prometheus` or use the `/admin/metrics` page / `docker exec` as described above.

#### No traces at `/admin/traces`

- Ensure `OTEL_ENABLED=true` and `OTEL_EXPORTER_OTLP_ENDPOINT=http://tempo:4317` for the service.  
- Check `docker logs tempo` and that the app container can resolve `tempo`.  
- A chat message shows up under the `mas` service as one trace whose root is `POST /tasks/new_task/`. That span is short: the request returns `202 {task_id}` at once, and routing runs afterwards in a background job that stays in the same trace. Its spans are children of the request span that start after it has ended: `route_task` (the router: rules, embeddings, then the constrained LLM fallback), then `publish horus.work.<type>`. Under `route_task`, `route_task_llm` wraps only the legacy routing prompt, when the router still has no answer, and `decompose_task` is the planner of a complex task: the two are siblings, not nested. The agent's spans, `knowledge_store_fetch_for_rag` among them, and its result post to MAS continue the same trace, with `aggregate_results` under the result request when the last step of a plan is combined with the others. Healthcheck probes, Prometheus scrapes and agent heartbeats are left out on purpose (`OTEL_PYTHON_EXCLUDED_URLS` in `docker-compose.yml`), and so are database or HTTP calls that MAS makes outside a request.

#### Connection refused from PgAdmin to the database

- From PgAdmin running in Docker, use host `postgres`, not `localhost`.

#### Slow query panels empty

- Confirm `pg_stat_statements` is loaded (`postgres` service command in Compose).  
- Test in SQL: `SELECT * FROM pg_stat_statements LIMIT 5;`

#### Logs not JSON

- Set `JSON_LOGGING=true` and restart the service.

---

### References

- [Prometheus documentation](https://prometheus.io/docs/)  
- [Grafana Tempo documentation](https://grafana.com/docs/tempo/latest/)  
- [Grafana Loki documentation](https://grafana.com/docs/loki/latest/)  
- [OpenTelemetry Python](https://opentelemetry.io/docs/languages/python/)

---

## Secrets Management Guide

This guide provides best practices for managing sensitive credentials and secrets across the Horus multi-agent system in different environments.

### Overview

Secrets include:
- Database passwords
- API keys
- JWT secret keys
- Encryption keys
- External service credentials
- OAuth tokens

**Golden Rule**: Never commit secrets to version control. Use `.env.example` as a template only.

### Local Development Setup

#### Step 1: Create Local `.env` Files

```bash
## Copy templates for each service
cp src/infra/.env.example src/infra/.env
cp src/services/mas/.env.example src/services/mas/.env
cp src/services/agent/.env.example src/services/agent/.env
cp src/services/knowledge-store/.env.example src/services/knowledge-store/.env
cp src/services/web-client/.env.example src/services/web-client/.env.local
```

#### Step 2: Fill in Development Values

**`src/infra/.env`** (Infrastructure secrets):

```env
## Use weak passwords for local development
POSTGRES_PASSWORD=devpassword123
REDIS_PASSWORD=devpassword123
RABBITMQ_PASSWORD=devpassword123

## Use a simple JWT secret for local development
JWT_SECRET_KEY=dev-secret-key-change-in-production

## Admin credentials: init-env.sh generates the password; MAS refuses an empty one or "admin"
SUPER_USER_USERNAME=admin
SUPER_USER_PASSWORD=<generated by init-env.sh>

PGADMIN_DEFAULT_PASSWORD=admin
```

#### Step 3: Git Configuration

Ensure `.env` files are ignored:

```bash
## .gitignore
.env
.env.local
.env.*.local
!.env.example
!.env.staging.example
!.env.production.example
```

Verify configuration:

```bash
git status
## Should NOT show .env files
```

### Staging Environment

#### Using Environment Variables

For staging deployments, use environment-specific `.env` files:

**`.env.staging`** (Not committed):

```env
## Staging database - dedicated staging database
POSTGRES_USER=staging_user
POSTGRES_PASSWORD=${STAGING_DB_PASSWORD}  # From CI/CD secrets
POSTGRES_DB=horus_staging

## Staging Redis with password
REDIS_PASSWORD=${STAGING_REDIS_PASSWORD}  # From CI/CD secrets
REDIS_HOST=staging-redis.internal

## RabbitMQ staging instance
RABBITMQ_PASSWORD=${STAGING_RABBITMQ_PASSWORD}  # From CI/CD secrets
RABBITMQ_HOST=staging-rabbitmq.internal

## JWT secret for staging
JWT_SECRET_KEY=${STAGING_JWT_SECRET}  # From CI/CD secrets

## LLM enabled in staging
LLM_AUTOINIT=1
```

#### CI/CD Integration (GitHub Actions)

Store secrets in GitHub repository settings and reference in workflows. An example (Horus has no deploy workflow):

```yaml
## .github/workflows/deploy-staging.yml
name: Deploy to Staging

on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    
    steps:
      - uses: actions/checkout@v3
      
      - name: Deploy to staging
        env:
          STAGING_DB_PASSWORD: ${{ secrets.STAGING_DB_PASSWORD }}
          STAGING_REDIS_PASSWORD: ${{ secrets.STAGING_REDIS_PASSWORD }}
          STAGING_JWT_SECRET: ${{ secrets.STAGING_JWT_SECRET }}
        run: |
          # Create .env from template and secrets
          cp src/infra/.env.example src/infra/.env
          
          # Inject secrets
          echo "POSTGRES_PASSWORD=${STAGING_DB_PASSWORD}" >> src/infra/.env
          echo "REDIS_PASSWORD=${STAGING_REDIS_PASSWORD}" >> src/infra/.env
          echo "JWT_SECRET_KEY=${STAGING_JWT_SECRET}" >> src/infra/.env
          
          # Deploy
          docker-compose -f src/infra/docker-compose.yml up -d
```

### Production Environment

#### Using Docker Secrets

For Docker Swarm deployments, use Docker Secrets:

```bash
## 1. Create secrets from files
docker secret create db_password <(echo "production_db_password_xyz")
docker secret create jwt_secret <(echo "production_jwt_secret_abc")
docker secret create redis_password <(echo "production_redis_password_def")
docker secret create rabbitmq_password <(echo "production_rabbitmq_password_ghi")

## 2. List created secrets
docker secret ls
```

Update `docker-compose.yml` for production:

```yaml
## src/infra/docker-compose.production.yml
version: '3.8'

services:
  postgres:
    image: postgres:15
    environment:
      POSTGRES_PASSWORD_FILE: /run/secrets/db_password
    secrets:
      - db_password
    volumes:
      - postgres_data:/var/lib/postgresql/data

  redis:
    image: valkey/valkey:9.1.2
    command: valkey-server --requirepass $(cat /run/secrets/redis_password)
    secrets:
      - redis_password

  mas:
    image: horus-mas:latest
    environment:
      JWT_SECRET_KEY_FILE: /run/secrets/jwt_secret
      POSTGRES_PASSWORD_FILE: /run/secrets/db_password
      REDIS_PASSWORD_FILE: /run/secrets/redis_password
    secrets:
      - db_password
      - jwt_secret
      - redis_password

secrets:
  db_password:
    external: true
  jwt_secret:
    external: true
  redis_password:
    external: true
  rabbitmq_password:
    external: true
```

#### Using HashiCorp Vault

For Kubernetes or advanced scenarios, use Vault:

```bash
## 1. Authenticate to Vault
vault login -method=kubernetes role=horus-app

## 2. Store secrets
vault kv put secret/horus/production \
  POSTGRES_PASSWORD="$(openssl rand -base64 32)" \
  JWT_SECRET_KEY="$(openssl rand -base64 64)" \
  REDIS_PASSWORD="$(openssl rand -base64 32)" \
  RABBITMQ_PASSWORD="$(openssl rand -base64 32)"

## 3. Retrieve secrets
vault kv get secret/horus/production
```

**Kubernetes Integration**:

```yaml
## k8s-secret-sync.yml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: vault-secret-sync
spec:
  schedule: "0 */6 * * *"  # Every 6 hours
  jobTemplate:
    spec:
      template:
        spec:
          serviceAccountName: vault-auth
          containers:
          - name: vault-sync
            image: vault:latest
            env:
            - name: VAULT_ADDR
              value: "https://vault.internal"
            - name: VAULT_ROLE
              value: "horus-app"
            volumeMounts:
            - name: vault-token
              mountPath: /var/run/secrets/kubernetes.io/serviceaccount
            command:
            - /bin/sh
            - -c
            - |
              TOKEN=$(cat /var/run/secrets/kubernetes.io/serviceaccount/token)
              vault write -tls-skip-verify auth/kubernetes/login role=horus-app jwt=$TOKEN
              vault kv get -tls-skip-verify secret/horus/production > /etc/secrets/.env
              kubectl patch secret horus-secrets --from-file=/etc/secrets/.env
          volumes:
          - name: vault-token
            projected:
              sources:
              - serviceAccountToken:
                  path: token
          restartPolicy: OnFailure
```

### Secret Rotation

#### Password Rotation Schedule

- **Development**: Not required
- **Staging**: Monthly
- **Production**: Every 90 days

#### Automated Rotation Script

```bash
#!/bin/bash
## scripts/rotate-secrets.sh

set -e

ENVIRONMENT=$1  # staging or production
VAULT_ADDR=${VAULT_ADDR:-https://vault.internal}

if [ -z "$ENVIRONMENT" ]; then
  echo "Usage: ./rotate-secrets.sh [staging|production]"
  exit 1
fi

echo "Rotating secrets for $ENVIRONMENT..."

## Generate new secrets
NEW_DB_PASSWORD=$(openssl rand -base64 32)
NEW_JWT_SECRET=$(openssl rand -base64 64)
NEW_REDIS_PASSWORD=$(openssl rand -base64 32)
NEW_RABBITMQ_PASSWORD=$(openssl rand -base64 32)

## Store in Vault
vault kv put "${VAULT_ADDR}/secret/horus/${ENVIRONMENT}" \
  POSTGRES_PASSWORD="$NEW_DB_PASSWORD" \
  JWT_SECRET_KEY="$NEW_JWT_SECRET" \
  REDIS_PASSWORD="$NEW_REDIS_PASSWORD" \
  RABBITMQ_PASSWORD="$NEW_RABBITMQ_PASSWORD"

echo "Secrets rotated successfully"
echo "Update deployment configurations with new secrets"

## For Docker Swarm
docker secret rm db_password || true
docker secret rm jwt_secret || true
docker secret rm redis_password || true
docker secret rm rabbitmq_password || true

docker secret create db_password <(echo "$NEW_DB_PASSWORD")
docker secret create jwt_secret <(echo "$NEW_JWT_SECRET")
docker secret create redis_password <(echo "$NEW_REDIS_PASSWORD")
docker secret create rabbitmq_password <(echo "$NEW_RABBITMQ_PASSWORD")

## Restart services
docker service update --force horus_mas
docker service update --force horus_agent
docker service update --force horus_knowledge_store

echo "Services restarted with new secrets"
```

### Secret Backup & Recovery

#### Backup Secrets

```bash
#!/bin/bash
## scripts/backup-secrets.sh

ENVIRONMENT=$1
BACKUP_DIR="./backups/secrets/$(date +%Y%m%d_%H%M%S)"

mkdir -p "$BACKUP_DIR"

## Backup from Vault
vault kv get -format=json "secret/horus/${ENVIRONMENT}" | \
  jq '.data.data' > "$BACKUP_DIR/${ENVIRONMENT}-secrets.json"

## Encrypt backup
openssl enc -aes-256-cbc -salt -in "$BACKUP_DIR/${ENVIRONMENT}-secrets.json" \
  -out "$BACKUP_DIR/${ENVIRONMENT}-secrets.json.enc" \
  -k "$(cat ~/.secret-backup-key)" && \
  rm "$BACKUP_DIR/${ENVIRONMENT}-secrets.json"

echo "Secrets backed up to $BACKUP_DIR"
```

#### Restore Secrets

```bash
#!/bin/bash
## scripts/restore-secrets.sh

ENVIRONMENT=$1
BACKUP_FILE=$2

if [ -z "$BACKUP_FILE" ]; then
  echo "Usage: ./restore-secrets.sh [staging|production] <backup-file>"
  exit 1
fi

## Decrypt backup
openssl enc -d -aes-256-cbc -in "$BACKUP_FILE" \
  -k "$(cat ~/.secret-backup-key)" | \
  vault kv put "secret/horus/${ENVIRONMENT}" @-

echo "Secrets restored from $BACKUP_FILE"
```

### Security Audit Checklist

- [ ] All `.env` files are in `.gitignore`
- [ ] No secrets committed in git history (`git log -p | grep -i password`)
- [ ] All services validate required secrets at startup
- [ ] Secrets are rotated on schedule
- [ ] Database audit logs track all connections
- [ ] API keys have expiration dates
- [ ] Backup of secrets stored separately
- [ ] Team members have access to secrets management system
- [ ] Secrets marked with environment (dev/staging/prod)
- [ ] Unused secrets removed regularly

### References

- [OWASP: Secrets Management](https://cheatsheetseries.owasp.org/cheatsheets/Secrets_Management_Cheat_Sheet.html)
- [12 Factor App: Config](https://12factor.net/config)
- [Docker Secrets](https://docs.docker.com/engine/swarm/secrets/)
- [HashiCorp Vault](https://www.vaultproject.io/)
- [GitHub: Secret Scanning](https://github.com/features/secret-scanning)

---

## Configuration Matrix: Development, Staging, Production

This document outlines environment-specific configuration values for the three main deployment environments.

### Quick Reference Matrix

| Variable | Development | Staging | Production |
|----------|-------------|---------|-----------|
| **DEBUG** | `true` | `false` | `false` |
| **LOG_LEVEL** | `DEBUG` | `INFO` | `WARN` |
| **NODE_ENV** | `development` | `production` | `production` |
| **Database** | Local container | RDS instance | RDS cluster (HA) |
| **Redis** | Local container | ElastiCache | ElastiCache (cluster) |
| **RabbitMQ** | Local container | Managed service | Managed service (cluster) |
| **CORS** | `["*"]` | `["https://staging.example.com"]` | `["https://app.example.com"]` |
| **TLS/HTTPS** | No | Yes | Yes (enforced) |
| **Secret Rotation** | Manual | Monthly | 90 days |

### Development Environment

#### Purpose
Local development and rapid iteration. Permissive security, debugging enabled.

#### Configuration Values

```env
## src/infra/.env (Development)
## ============================

## Server
DEBUG=true
LOG_LEVEL=DEBUG
NODE_ENV=development

## Database - Local container
POSTGRES_USER=admin
POSTGRES_PASSWORD=devpassword
POSTGRES_DB=horus_dev
DB_HOST=postgres
DB_PORT=5432

## Cache - Local container
REDIS_HOST=redis
REDIS_PORT=6379
REDIS_PASSWORD=devredis

## Message Queue - Local container
RABBITMQ_HOST=rabbitmq
RABBITMQ_PORT=5672
RABBITMQ_USER=guest
RABBITMQ_PASSWORD=guest

## Authentication
JWT_SECRET_KEY=dev-secret-key-change-in-production
JWT_ALGORITHM=HS256

## Initial Admin (init-env.sh generates the password; MAS refuses an empty one or "admin")
SUPER_USER_USERNAME=admin
SUPER_USER_PASSWORD=<generated by init-env.sh>

## Application
LLM_AUTOINIT=0

## PgAdmin (see src/infra/.env.example)
PGADMIN_DEFAULT_EMAIL=admin@admin.com
PGADMIN_DEFAULT_PASSWORD=admin

## Web client (implemented in src/services/web-client/utils/config.ts)
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_KNOWLEDGE_STORE_URL=http://localhost:8080
NEXT_PUBLIC_WS_URL=ws://localhost:8000

## Not used by the current web client config module (examples only if you extend the app):
## NEXT_PUBLIC_API_TIMEOUT, NEXT_PUBLIC_AUTH_ENABLED, NEXT_PUBLIC_ENABLE_* feature flags
```

#### Startup Commands

```bash
## Start all services
cd src/infra
docker compose up --build

## Logs
docker compose logs -f mas
docker compose logs -f agent
docker compose logs -f knowledge_store

## Stop all services
docker compose down
```

#### Database Initialization

```bash
## Admin user is created by MAS startup (entrypoint runs init_db). To re-run inside the mas container:
docker exec -it mas python -c "from db.init_setup import init_db; init_db()"

## Reset database (adjust user/database to match src/infra/.env)
docker exec -it postgres psql -U postgres -d mas_db -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
```

#### Debugging

```bash
## Access container shell
docker exec -it mas /bin/bash

## View logs with timestamps
docker compose logs --timestamps mas

## Monitor in real-time
docker stats
```

### Staging Environment

#### Purpose
Pre-production testing with realistic configuration, secret rotation enabled.

#### Infrastructure

```
┌─────────────────────────────────────────┐
│   AWS / Cloud Provider                  │
├─────────────────────────────────────────┤
│ ECS Cluster / Kubernetes                │
│  - MAS Service (2 instances)            │
│  - Agent Service (1 instance)           │
│  - Knowledge Store (1 instance)         │
│  - Web Client (CloudFront / CDN)        │
├─────────────────────────────────────────┤
│ RDS PostgreSQL (db.t3.small)            │
│ ElastiCache Redis (cache.t3.micro)      │
│ RabbitMQ Managed Instance               │
│ Secrets Manager (AWS)                   │
└─────────────────────────────────────────┘
```

#### Configuration Values

```env
## .env.staging (Not committed)
## =============================

## Server
DEBUG=false
LOG_LEVEL=INFO
NODE_ENV=production

## Database - AWS RDS
POSTGRES_USER=staging_admin
POSTGRES_PASSWORD=${STAGING_DB_PASSWORD}
POSTGRES_DB=horus_staging
DB_HOST=horus-staging-db.c9akciq32.us-east-1.rds.amazonaws.com
DB_PORT=5432

## Cache - AWS ElastiCache
REDIS_HOST=horus-staging-redis.xxxxxx.ng.0001.use1.cache.amazonaws.com
REDIS_PORT=6379
REDIS_PASSWORD=${STAGING_REDIS_PASSWORD}

## Message Queue - AWS MQ
RABBITMQ_HOST=horus-staging-mq.xxxxx.mq.us-east-1.amazonaws.com
RABBITMQ_PORT=5672
RABBITMQ_USER=staging_user
RABBITMQ_PASSWORD=${STAGING_RABBITMQ_PASSWORD}

## Authentication
JWT_SECRET_KEY=${STAGING_JWT_SECRET}
JWT_ALGORITHM=HS256

## Initial Admin
SUPER_USER_USERNAME=staging_admin
SUPER_USER_PASSWORD=${STAGING_ADMIN_PASSWORD}

## Application
LLM_AUTOINIT=1

## Web client
NEXT_PUBLIC_API_URL=https://staging-api.horus.example.com
NEXT_PUBLIC_KNOWLEDGE_STORE_URL=https://staging-knowledge.horus.example.com
NEXT_PUBLIC_WS_URL=wss://staging-api.horus.example.com

## TLS/Security
CORS_ORIGINS=https://staging.horus.example.com
TLS_ENABLED=true
TLS_CERT_PATH=/etc/ssl/staging-cert.pem
TLS_KEY_PATH=/etc/ssl/staging-key.pem
```

#### Deployment Process

```bash
## GitHub Actions Workflow (an example: Horus has no deploy workflow)
## .github/workflows/deploy-staging.yml

name: Deploy to Staging
on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Build Docker images
        run: |
          docker build -t horus-mas:staging src/services/mas/
          docker build -t horus-agent:staging src/services/agent/
          docker build -t horus-knowledge-store:staging src/services/knowledge-store/
          docker build -t horus-web-client:staging src/services/web-client/
      
      - name: Push to ECR
        run: |
          aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin $ECR_REGISTRY
          docker tag horus-mas:staging $ECR_REGISTRY/horus-mas:staging
          docker push $ECR_REGISTRY/horus-mas:staging
      
      - name: Update ECS services
        run: |
          aws ecs update-service --cluster horus-staging --service mas --force-new-deployment
```

#### Database Migrations

```bash
## Run migrations on staging
aws ecs run-task \
  --cluster horus-staging \
  --task-definition horus-migration:1 \
  --count 1 \
  --launch-type FARGATE \
  --overrides '{
    "containerOverrides": [{
      "name": "migration",
      "environment": [
        {"name": "DATABASE_URL", "value": "postgresql://..."}
      ]
    }]
  }'
```

### Production Environment

#### Purpose
Live production system. Minimal logging, high availability, vault-managed secrets, strict security.

#### Infrastructure (High Availability)

```
┌────────────────────────────────────────────────────────────────┐
│   AWS / Cloud Provider (Multi-AZ)                              │
├────────────────────────────────────────────────────────────────┤
│ ECS Cluster / Kubernetes (3+ AZ)                               │
│  - MAS Service (6+ instances, auto-scaling)                    │
│  - Agent Service (4+ instances, auto-scaling)                  │
│  - Knowledge Store (3+ instances)                              │
│  - Web Client (CloudFront CDN, edge locations)                 │
├────────────────────────────────────────────────────────────────┤
│ RDS PostgreSQL (db.r5.xlarge, Multi-AZ, read replicas)         │
│ ElastiCache Redis (cache.r5.large, cluster mode)               │
│ RabbitMQ Managed Cluster (3 nodes)                             │
│ AWS Secrets Manager (automatic rotation)                       │
│ AWS Certificate Manager (TLS)                                  │
│ CloudFront (CDN)                                               │
│ WAF (Web Application Firewall)                                 │
│ Application Load Balancer (multi-AZ)                           │
└────────────────────────────────────────────────────────────────┘
```

#### Configuration Values

```env
## .env.production (Stored in AWS Secrets Manager)
## ================================================

## Server
DEBUG=false
LOG_LEVEL=WARN
NODE_ENV=production

## Database - AWS RDS Multi-AZ
POSTGRES_USER=prod_admin
POSTGRES_PASSWORD=${vault:horus/production/db_password}
POSTGRES_DB=horus_prod
DB_HOST=horus-prod-primary.xxxxxx.us-east-1.rds.amazonaws.com
DB_HOST_READ=horus-prod-read-replica.xxxxxx.us-east-1.rds.amazonaws.com
DB_PORT=5432
DB_SSL=require
DB_POOL_SIZE=30
DB_POOL_MIN=10

## Cache - AWS ElastiCache Cluster Mode
REDIS_HOST=horus-prod-redis.xxxxxx.cache.amazonaws.com
REDIS_PORT=6379
REDIS_PASSWORD=${vault:horus/production/redis_password}
REDIS_CLUSTER_MODE=true
REDIS_SSL=true

## Message Queue - AWS MQ Cluster
RABBITMQ_HOST=b-1-horus-prod-mq.xxxxx.mq.us-east-1.amazonaws.com
RABBITMQ_PORT=5671
RABBITMQ_USER=prod_user
RABBITMQ_PASSWORD=${vault:horus/production/rabbitmq_password}
RABBITMQ_SSL=true

## Authentication
JWT_SECRET_KEY=${vault:horus/production/jwt_secret}
JWT_ALGORITHM=HS256
JWT_EXPIRATION=1200

## Initial Admin (disabled in production)
SUPER_USER_USERNAME=
SUPER_USER_PASSWORD=

## Application
LLM_AUTOINIT=1
RATE_LIMIT=1000
RATE_LIMIT_WINDOW=3600

## Web client
NEXT_PUBLIC_API_URL=https://api.horus.example.com
NEXT_PUBLIC_KNOWLEDGE_STORE_URL=https://knowledge.horus.example.com
NEXT_PUBLIC_WS_URL=wss://api.horus.example.com

## TLS/Security
CORS_ORIGINS=https://horus.example.com
TLS_ENABLED=true
TLS_CERT_PATH=/etc/ssl/prod-cert.pem
TLS_KEY_PATH=/etc/ssl/prod-key.pem

## Monitoring & Security
SENTRY_DSN=${vault:horus/production/sentry_dsn}
DATADOG_API_KEY=${vault:horus/production/datadog_key}
AUTH_AUDIT_LOG=true
COMPLIANCE_LOGGING=true
```

#### Deployment & Rollout

```bash
## Blue-Green Deployment Strategy
## .github/workflows/deploy-production.yml

name: Deploy to Production (Blue-Green)
on:
  release:
    types: [published]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Deploy to green environment
        run: |
          # Deploy to ECS "green" task definition
          aws ecs update-service \
            --cluster horus-prod-green \
            --service mas \
            --task-definition horus-mas:${{ github.run_id }} \
            --desired-count 6
      
      - name: Health checks (2 hours)
        run: |
          # Wait for green environment to stabilize
          # Run integration tests
          # Monitor error rates
          timeout 7200 bash -c 'until health-check-passes; do sleep 30; done'
      
      - name: Switch traffic (Blue to Green)
        run: |
          aws elbv2 modify-target-group \
            --target-group-arn $GREEN_TG_ARN \
            --matcher HttpCode=200-299
          
          # Update ALB to point to green
          aws elbv2 modify-listener \
            --listener-arn $LISTENER_ARN \
            --default-actions Type=forward,TargetGroupArn=$GREEN_TG_ARN
      
      - name: Monitor (30 minutes)
        run: |
          # Monitor error rates, latency, etc.
          # If issues detected, automatic rollback
          timeout 1800 bash -c 'monitor-metrics && rollback-if-needed'
```

#### Database Backup & Disaster Recovery

```bash
## Automated backups (AWS RDS handles this)
## Manual backup for critical operations
aws rds create-db-snapshot \
  --db-instance-identifier horus-prod-primary \
  --db-snapshot-identifier horus-prod-backup-$(date +%Y%m%d-%H%M%S)

## Verify backup
aws rds describe-db-snapshots \
  --snapshot-type manual \
  --query 'DBSnapshots[?DBInstanceIdentifier==`horus-prod-primary`]'
```

#### Security Hardening

```bash
## Network Security Groups
aws ec2 authorize-security-group-ingress \
  --group-id sg-xxxxxxxx \
  --protocol tcp \
  --port 443 \
  --cidr 0.0.0.0/0

## Disable SSH
aws ec2 revoke-security-group-ingress \
  --group-id sg-xxxxxxxx \
  --protocol tcp \
  --port 22 \
  --cidr 0.0.0.0/0

## Enable WAF
aws wafv2 create-web-acl \
  --region us-east-1 \
  --name horus-prod-waf \
  --default-action Block={} \
  --rules file://waf-rules.json
```

### Environment-Specific Health Checks

#### Development
- API responding on localhost:8000
- Services up (`docker ps`)

#### Staging
- Database connectivity
- RabbitMQ queue connection
- Redis cache connectivity
- API health endpoint: `GET /health`
- WebSocket connectivity: `WS /chat`

#### Production
- All of above, plus:
- Database replication lag < 100ms
- Error rate < 0.1%
- P99 latency < 500ms
- No secrets in logs
- Backup created in last 24h
- All services in at least 2 AZs

### Configuration Validation Checklist

- [ ] All `.env.example` files up-to-date
- [ ] Environment variables documented
- [ ] Secrets stored in vault/manager (not in `.env`)
- [ ] TLS/HTTPS enforced in staging/prod
- [ ] Database backup strategy tested
- [ ] Monitoring and alerting configured
- [ ] Logging doesn't contain secrets
- [ ] Rate limiting configured
- [ ] CORS restricted appropriately
- [ ] Load balancing configured
