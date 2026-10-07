# Horus AI

[![CI](https://github.com/EpitechPromo2027/G-EIP-600-BAR-6-1-eip-loup.marquez/actions/workflows/ci.yml/badge.svg?branch=Sprint%231_September2026_Tek5)](https://github.com/EpitechPromo2027/G-EIP-600-BAR-6-1-eip-loup.marquez/actions/workflows/ci.yml)
[![Python 3.11](https://img.shields.io/badge/python-3.11-blue.svg)](https://www.python.org/)
[![License: Proprietary](https://img.shields.io/badge/license-proprietary-red.svg)](LICENSE)

Horus answers questions about your organisation's documents. It runs on your own machine in Docker: specialised AI agents search the documents you give it and answer from them, citing the documents they used. An installer picks a setup that fits your hardware, from an NVIDIA GPU down to a CPU-only machine.

What Horus is not:

- **Not a cloud service.** Nothing is hosted for you. Horus runs on your machine and your documents stay there. The install downloads the container images and the language model once.
- **Not a general chatbot.** It is built to answer from the documents you give it.
- **Not open source.** Horus is proprietary. Using it needs a signed agreement (see [License](#license)).
- **Not finished.** Horus is a beta for invited testers. Its version is in `VERSION`.

## Requirements

| | |
|---|---|
| Docker | Docker Desktop or Docker Engine, running, with **Docker Compose 2.33.0 or newer** (`docker compose version`). The installer stops on an older Compose. |
| Python | 3.11 or newer, only to run the installer. |
| Free disk | **150 GB**. The installer checks this and stops below it. With an NVIDIA GPU 125 GB is enough: re-run with `--skip-disk-check`. It settles to about 130 GB (CPU) or 110 GB (GPU) after the install. These figures were measured when the images were built on a tester's machine; the download of the prebuilt images has not been measured yet. |
| With an NVIDIA GPU | Docker must be able to use the card (NVIDIA Container Toolkit; on Windows, WSL 2 and the NVIDIA driver). At least 6.0 GiB of VRAM. The installer picks `gpu-8g` from 6.0 to under 10.0 GiB, `gpu-16g` from 10.0 to under 17.0, `gpu-24g` from 17.0 to under 25.0, and `gpu-large` from 25.0. Only `gpu-8g` has been measured. AMD and Intel GPUs, and every Mac, run on the CPU. |
| Without a usable NVIDIA GPU | Memory Docker can use: **15.0 GiB** or more for `cpu-standard`, **13.5 to under 15.0 GiB** for `cpu-lean`. Under 13.5 GiB the installer stops before any large download and says what to change. On Windows Docker gets half of the RAM unless WSL is given more, so in practice that takes a 24 GB machine. These are the planning figures of [ADR-006](docs/adr/ADR-006-low-ram-machines.md), kept until the run on the 16 GB reference machine. A first run on a development laptop gives 10.5 GiB for `cpu-standard` by the ADR's rule. |
| Time | A first install that built the images took 1.5 to 2 hours. The beta installer downloads prebuilt images instead; that has not been timed yet. |

The prebuilt images are built for x86-64 only. On Apple Silicon Docker runs them through emulation.

## Install

### Testers: the beta bundle

You need the Horus-Beta ZIP and the access token we sent you.

1. Extract the whole ZIP into a folder.
2. Save the token in that folder as `registry-token.txt`, on one line: `USERNAME:TOKEN`.
3. Run the START-HERE file for your system:
   - Windows: double-click `START-HERE-Windows.bat`
   - macOS: right-click `START-HERE-macOS.command` and choose Open
   - Linux: `./START-HERE-Linux.sh`

The START-HERE files run `installer/horus_install.py`. It checks Docker, Compose, the disk, the network and the ports, picks a profile for your hardware, asks which folders Horus may read (read-only), downloads the prebuilt images and the model, and starts everything. It does not build anything. When it finishes, open http://localhost:3000 and sign in with the user name and password it prints.

- To see which profile it would pick without changing anything: `--dry-run`.
- To stop and keep your data: run your START-HERE file with `--stop`. To remove everything: `--uninstall` (this deletes the documents you added).
- If something goes wrong, send us `install-log.txt` and `horus-profile.json` from the same folder.

The full tester notes are in [packaging/README-FIRST.txt](packaging/README-FIRST.txt).

### Contributors: from the repository

Contributions need a signed Contributor Agreement first (see [Contributing](#contributing)).

The simplest way is the installer, which picks the profile and writes `src/infra/.env` for you, then builds the images on your machine:

```bash
git clone https://github.com/EpitechPromo2027/G-EIP-600-BAR-6-1-eip-loup.marquez.git
cd G-EIP-600-BAR-6-1-eip-loup.marquez
python installer/horus_install.py --build-from-source
```

Or, on a machine with an NVIDIA GPU, with Docker Compose directly:

```bash
cd src/infra
./init-env.sh             # creates .env from .env.example with a random JWT secret
docker compose up --build
```

Without a GPU the stack needs the CPU overlay (`docker-compose.cpu.yml`) and the CPU settings in `.env`: the model server URL `http://llm:8080/v1`, longer timeouts and a context size. The installer writes them; `python installer/horus_install.py --dry-run` prints them. The model file is listed in [`models/manifest.json`](models/manifest.json): the installer downloads it into `models/`, and without the installer the one-shot `llm-model` service fetches it ([the CPU model server](docs/operations.md#the-cpu-model-server)). See also [docs/getting-started.md](docs/getting-started.md) and [docs/operations.md](docs/operations.md#local-deployment-with-docker).

## Measured results

The 100-question test set (`tests/eval/testset.yaml`, version 1.0.0, over the five documents in `demo_assets/`), run on 2026-10-06 on a development laptop: AMD Ryzen AI 9 HX 370 (12 cores, AVX2), 64 GB of LPDDR5-7500, Docker Desktop on WSL 2 with 31 GiB. The GPU run used its NVIDIA GeForce RTX 4070 Laptop GPU (8 GB).

| Profile | Model server | Questions | Answers correct | Median time per answer |
|---|---|---:|---:|---:|
| `cpu-standard` | llama-server, Qwen3-4B-Instruct-2507 Q4_K_M | 100 | 93 | 18.2 s |
| `cpu-lean` | llama-server, same model, 4,096-token context, q8_0 KV cache | first 30 | 29 | 33.2 s |
| `gpu-8g` | vLLM, Qwen3-4B-Instruct-2507 AWQ | 100 | 96 | 2.97 s |

On the same first 30 questions `cpu-standard` got 28 right, with a median of 17.7 s. Answers are checked automatically; the two-reviewer check has not been done yet. This is not the 16 GB reference machine. The reports and how to run them: [benchmarks/README.md](benchmarks/README.md).

## Architecture

```mermaid
graph TB
    User([User]) -->|HTTP| Web[Web Client<br/>Next.js :3000]
    Web -->|REST / WebSocket| MAS[MAS Orchestrator<br/>FastAPI :8000]
    Web -->|REST| KS
    MAS -->|AMQP| RMQ[(RabbitMQ<br/>:5672)]
    RMQ -->|Task queue| Agent[Agent Service<br/>FastAPI :8001]
    Agent -->|REST| MAS
    Agent -->|REST| KS[Knowledge Store<br/>FastAPI :8080]
    KS --- Chroma[(ChromaDB)]
    MAS --- PG[(PostgreSQL<br/>:5432)]
    MAS --- Redis[(Valkey<br/>:6379)]
    MAS -->|OpenAI-compatible API| LLM[Model server<br/>vLLM on GPU, llama-server on CPU]
    Agent -->|OpenAI-compatible API| LLM
    MAS -.->|OTLP| Tempo[Tempo]
    Agent -.->|OTLP| Tempo
    KS -.->|OTLP| Tempo
    Tempo --- Admin[Web client<br/>/admin observability]
    Prometheus[Prometheus] --- Admin
    Loki[Loki] --- Admin
```

## Technology stack

| Layer | Technologies |
|-------|-------------|
| Frontend | TypeScript, Next.js 16, React 19, Tailwind CSS 4, Mantine 8 |
| Backend | Python 3.11 in the service images, FastAPI, SQLAlchemy 2, Alembic, Pydantic |
| Language model | Qwen3-4B-Instruct-2507: vLLM 0.23.0 (AWQ) on an NVIDIA GPU, llama.cpp llama-server b11382 (Q4_K_M GGUF) on the CPU |
| Retrieval | ChromaDB 1.5.2, FastEmbed 0.8.1 on ONNX Runtime (BAAI/bge-base-en-v1.5 in the knowledge store, all-MiniLM-L6-v2 for MAS routing), LangChain tools in the agent |
| Messaging | RabbitMQ 4.1 (pika) |
| Data | PostgreSQL, Valkey 9.1 (Redis protocol; the Compose service is still called `redis`) |
| Observability | Prometheus, Loki, Tempo, OpenTelemetry (viewed in the web client's `/admin` pages) |
| Auth | JWT + bcrypt, OAuth2 password flow, four roles (admin, manager, user, system) |
| Install | Python installer (`installer/`), Tauri desktop app (`desktop/`) |
| Testing | pytest, Vitest, Locust ([TESTING.md](TESTING.md)) |
| CI/CD | GitHub Actions: tests on Python 3.13 (knowledge store on 3.11), signed release images, desktop release |

## Repository structure

```
src/
  infra/                  Docker Compose files (GPU base + CPU overlay), configs, .env.example
  services/
    mas/                  MAS orchestrator (FastAPI)
    agent/                AI agent service (FastAPI)
    knowledge-store/      Document store + vector search (FastAPI + ChromaDB)
    web-client/           Dashboard (Next.js)
installer/                Beta installer: hardware profiles, preflight, model download
packaging/                START-HERE scripts, README-FIRST.txt, release notes, bundle builder
desktop/                  Desktop app (Tauri) that starts and stops Horus
models/                   Model manifest; the CPU model file lands here
benchmarks/               Measured results (JSON) and how to produce them
tests/                    pytest suites (MAS, agent, knowledge store, CI wiring) and the eval test set
scripts/                  Benchmarks, evaluation, load and resilience tests, integration checks
demo_assets/              The sample documents used by demos and the test set
docs/                     Project documentation (MkDocs site); adr/ holds the decision records
greenlight/               EIP greenlight deliverables
.github/workflows/        CI, eval test set, release images, desktop release
```

## Service ports

| Service | URL | Notes |
|---------|-----|-------|
| Web Client | http://localhost:3000 | Dashboard, chat, knowledge store UI |
| MAS API | http://localhost:8000 | Swagger at `/docs` |
| Agent | http://localhost:8001 | |
| Knowledge Store | http://localhost:8080 | Bound to 127.0.0.1 only. Swagger at `/docs` (`root_path` is only for proxies) |
| vLLM | http://localhost:18000 | GPU profiles only (`VLLM_HOST_PORT`). The CPU model server publishes no port |
| RabbitMQ UI | http://localhost:15672 | `RABBITMQ_USER` / `RABBITMQ_PASSWORD` in `.env` |
| PostgreSQL, Valkey, RabbitMQ (AMQP) | 5432, 6379, 5672 | `DB_PORT`, `REDIS_PORT`, `RABBITMQ_PORT` |
| Tempo (OTLP) | 4317 (gRPC), 4318 (HTTP) | |
| Observability | http://localhost:3000/admin/logs · /admin/metrics · /admin/traces | Admin role, in the web client |
| PgAdmin | http://localhost:5433 | Development tool, only with `docker compose --profile admin up` |
| RedisInsight | http://localhost:5540 | Development tool, only with `docker compose --profile admin up` |

## Running tests

```bash
# Python, from the repository root (each service has its own pytest.ini)
pytest -c tests/mas/pytest.ini tests/mas -m "not requires_stack"
pytest -c tests/agent/pytest.ini tests/agent
pytest -c tests/knowledge_store/pytest.ini tests/knowledge_store
# Or all three: ./scripts/test/run-all.sh

# Web client
cd src/services/web-client && npm test

# Load tests (need a running stack)
cd scripts/perf && locust -f load-locust.py
```

Tests that need a running stack are in [scripts/integration-checks/](scripts/integration-checks/README.md). Every CI run posts a per-service coverage table to its Workflow Summary and uploads the HTML reports as artifacts (`coverage-mas`, `coverage-agent`, `coverage-knowledge-store`).

## Documentation

Full documentation lives under [`docs/`](docs/) and is published as a browsable site with MkDocs.

| Topic | Link |
|-------|------|
| Getting started (onboarding, config, troubleshooting) | [docs/getting-started.md](docs/getting-started.md) |
| Architecture (overview, services, data model) | [docs/architecture.md](docs/architecture.md) |
| API reference (MAS, Knowledge Store, WebSocket) | [docs/api-reference.md](docs/api-reference.md) |
| Operations (deployment, hardware profiles, monitoring, secrets) | [docs/operations.md](docs/operations.md) |
| Security and compliance (RBAC, audit, data, telemetry) | [docs/security.md](docs/security.md) |
| How to contribute | [CONTRIBUTING.md](CONTRIBUTING.md) |
| Code style | [docs/contributing.md](docs/contributing.md) |
| Test strategy | [TESTING.md](TESTING.md) |
| Versions and releases | [VERSIONING.md](VERSIONING.md) |
| Benchmarks | [benchmarks/README.md](benchmarks/README.md) |
| Demo (script, cheatsheet) | [docs/demo.md](docs/demo.md) |
| Changelog | [CHANGELOG.md](CHANGELOG.md) |
| Beta test plan | [beta_test_plan.md](beta_test_plan.md) |
| Decision records | [docs/adr/](docs/adr/) |
| EIP deliverables (start here for the jury) | [docs/eip/README.md](docs/eip/README.md) |

To build the site and the API references (pdoc, TypeDoc) into HTML:

```bash
pip install mkdocs mkdocs-material mkdocs-mermaid2-plugin pdoc
cd src/services/web-client && npm install --save-dev typedoc && cd -
./scripts/docs.sh            # or ./scripts/docs.sh --serve for live reload
```

## Contributing

All work starts as a GitHub issue, and contributions need a signed Horus Contributor Agreement. [CONTRIBUTING.md](CONTRIBUTING.md) says how to get one and how to send a change: branches, commits, pull requests and tests.

## License

Horus is **closed-source, proprietary software** (all rights reserved). Having access to this repository or to a Horus build gives no right to use, copy or distribute it: every use requires a signed agreement with the licensors (commercial licence, evaluation licence or contributor agreement).

- Terms: [LICENSE](LICENSE) (Horus Proprietary Software Licence v2, 30/09/2026)
- Why Horus is closed source: [ADR-004](docs/adr/ADR-004-closed-source-licence.md)
- Third-party components keep their own licences: [THIRD_PARTY_NOTICES](THIRD_PARTY_NOTICES) lists them (generated by `scripts/licences/third_party_notices.py`), and the [dependency licence inventory](docs/eip/dependency-licence-inventory.xlsx) reviews them
- Contributions are accepted only under a signed Contributor Agreement ([LICENSE](LICENSE), section 9).

## Authors

- **Loup Marquez** -- loup.m.marquez@gmail.com
- **Matheus Lopez** -- matheus.lopez@epitech.eu
- **Noah Gibelli** -- noah.gibelli@epitech.eu

What each of us built, and the external contributors: [CONTRIBUTORS.md](CONTRIBUTORS.md).
