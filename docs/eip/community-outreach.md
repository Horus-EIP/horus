# Community Outreach & Expert Recruitment - Horus

## Strategy & Objectives
Horus is a closed-source, local multi-agent B2B application. Our current technical bottlenecks revolve around the vLLM/Docker stack: massive download sizes (25GB), long installation times (46+ min), and high CPU latency (40s inference causing WebSocket drops).

Our goal is to gather architectural advice on CPU-only optimization and recruit voluntary, vetted contributors for small, scoped technical tasks (1–4 hours) under NDA.

---

## Target Platforms & Draft Posts

### 1. Reddit: r/LocalLLaMA

- **Name + link:** Reddit - r/LocalLLaMA (https://www.reddit.com/r/LocalLLaMA/comments/1wvwmb5/comment/pdfj0gg/?screen_view_count=2)
- **Type:** Subreddit / Online Community
- **Audience:** The largest community of developers, researchers, and enthusiasts focused on running LLMs locally, quantization, and hardware performance.
- **Posting rules:** Strict rules regarding spam and self-promotion. Technical discussions and genuine architecture questions are highly welcomed, but accounts with 0 karma may face automated blocks.
  - *Date checked:* Oct 2, 2026
- **Why it fits Horus:** The absolute best place to find engineers who understand CPU-only inference, memory limits, and quantization bottlenecks.
- **Published Post (Oct 2, 2026):**
  > **Title:** How do you keep a local multi-agent app usable on CPU-only / low-RAM machines?
  >
  > Hi everyone,
  >
  > We're three final-year students at Epitech building Horus, a multi-agent assistant that runs entirely locally and offline. Our current challenge is hardware: keeping it usable on machines without a powerful GPU, without long setup times, excessive RAM/VRAM use or crashes.
  >
  > Where we are today, from our last beta test:
  > * One tester needed over 2 hours to install. The Python dependencies alone take 21–46 min, and the download is about 25 GB.
  > * On CPU only, routing a question can take around 40 s, long enough for our WebSocket connection to drop.
  >
  > *(We currently use vLLM / Docker with our core models tested on modest hardware).*
  >
  > We'd love advice from anyone experienced with:
  > * CPU-only LLM inference and memory-efficient loading
  > * Quantization and model choice for low-end hardware
  > * GPU/CPU fallback strategies
  > * Hardware detection and adaptive configuration
  > * Preventing resource exhaustion during setup and execution
  >
  > Advice in the comments is very welcome, with no strings attached.
  >
  > **Looking for contributors:** We also have a few small, well-scoped tasks or code reviews (about 1–4 hours), for example reviewing our hardware detection and model selection, or benchmarking a quantized model on a 16 GB RAM laptop.
  >
  > To be transparent: Horus is closed source and will be licensed to companies. Contributing is voluntary and unpaid. Before seeing any code, contributors sign a short confidentiality and contributor agreement, and the code they contribute becomes part of Horus. In return we offer thorough code reviews, full credit in the project and a professional reference on request.
  >
  > We're not sharing code or private links publicly. If this interests you, comment below or DM me with your experience in local inference, CPU optimisation or offline apps.

- **Key Community Feedback & Advice Received:**
  - **Community Stance on Closed Source/Unpaid Help:** Feedback highlighted that outsourcing core engineering challenges for a closed-source, unpaid project can face strong skepticism in open-source communities. *Action taken:* Clarified student status and transparency, pivoting the thread strictly toward technical architecture advice and acknowledging hardware gaps (like expanding beyond NVIDIA GPU detection to iGPUs and NPUs).
  - **Non-Generative Routing Optimization:** The 40s routing latency comes from using a generative model for routing. Instead, use a lightweight approach (e.g., small embedding model with nearest-neighbor lookup, or keyword/regex pass) to drop routing to milliseconds.
  - **Agent Segmentation & Context Isolation:** Running agentic work on low-end hardware is possible (e.g., 4B models like Qwen-based variants doing web searches or sub-tasks), *provided* tasks are strictly segmented and isolated with a limited cognitive surface, small context bloat, and tight delegation trees.
  - **Installer vs. Runtime Separation & Lazy Loading:** Treat the installer and runtime as separate resource budgets. Detect CPU features, RAM, VRAM, and disk *before* pulling anything; avoid a 25 GB upfront dependency by implementing lazy, resumable model downloads and a small default model.
  - **Python Stack & Binary Compilation:** The 21–46 min installation time is largely driven by PyTorch/CUDA wheels. On CPU paths, switch to lightweight binaries (like `llama.cpp` / `llama-cpp-python` CPU wheels) or compile Python code into standalone binaries using tools like **Nuitka**.
  - **WebSocket Resilience & Job Queuing:** Long CPU generations/load times cause WebSocket drops. Treat long calls as asynchronous jobs (return a job ID immediately), stream tokens, and send regular heartbeat/progress frames.
  - **Fixed Tiering Profiles:** Rather than trying to auto-tune everything dynamically, detect system capabilities at first run (RAM, AVX2/AVX-512) and select from 2–3 pre-tested fixed configuration profiles.
  - **Multi-Agent Handoffs & Communication Patterns:**
    - Instead of passing heavy text summaries up the chain, low-level agents can use **handoff documents** detailing their references/actions and pass file paths up, or use a shared **message board** that other agents read (ideal for deep-search pipelines needing grounding sources).
  - **Failure Handling:** For minor failures (e.g., opening too many pages exceeding context), no explicit retries are needed; parent agents can interpret failures or reroute dynamically. Generic errors (like out-of-context) transmit clean error messages upward.
  - **Specialized Model Tiers & Tool Usage:**
    - Small models load fast and bring distinct strengths. For luxury/high VRAM setups, use larger workers (e.g., 35B/Qwen 27B IQ3_S as a brain) combined with fast 4B models for search. For tight hardware, models like **Sharp Spark (4B)** excel at actions/exploration, **Neo Horse** for analytics/summaries, and **Agents A1** for orchestration.
    - For simple extraction/summarization tasks requiring maximum speed, consider ultra-light alternatives like *Minicpm 2b*, *Lfm 2.6b*, or *Ling Tiny*.
  - **Tool Constraints:** Small models can reliably call tools *if* the tool set is strictly limited (avoid giving them 20+ tools at once).

---

### 2. Reddit: r/selfhosted

- **Name + link:** Reddit - r/selfhosted (https://www.reddit.com/r/selfhosted/comments/1wvtzba/running_local_multiagent_llms_on_modest_hardware/)
- **Type:** Subreddit / Online Community
- **Audience:** Developers, home lab enthusiasts, and self-hosters dealing with local deployment and infrastructure limits.
- **Posting rules:** Strict compliance with spam/self-promotion rules. Technical architecture and open discussions are welcome.
  - *Date checked:* Oct 2, 2026
- **Why it fits Horus:** Perfect for gathering feedback on resource exhaustion, offline setup constraints, and low-end hardware management.

- **Original Published Post (Oct 2, 2026):**
  > **Running local multi-agent LLMs on modest hardware (CPU-only): How do you prevent resource exhaustion?**
  >
  > Hi everyone,
  > We're three final-year students at Epitech building Horus, a multi-agent assistant that runs entirely locally and offline. Our current challenge is hardware: keeping it usable on machines without a powerful GPU, without long setup times, excessive RAM/VRAM use or crashes.
  >
  > Where we are today, from our last beta test:
  > * One tester needed over 2 hours to install. The Python dependencies alone take 21–46 min, and the download is about 25 GB.
  > * On CPU only, routing a question can take around 40 s, long enough for our WebSocket connection to drop.
  >
  > [Models we use + the smallest machine we've tested on]
  >
  > We'd love advice from anyone experienced with:
  > * CPU-only LLM inference and memory-efficient loading
  > * Quantization and model choice for low-end hardware
  > * GPU/CPU fallback strategies
  > * Hardware detection and adaptive configuration
  > * Preventing resource exhaustion during setup and execution
  >
  > Advice in the comments is very welcome, with no strings attached.
  >
  > **Looking for contributors:** We also have a few small, well-scoped tasks or code reviews (about 1–4 hours), for example reviewing our hardware detection and model selection, or benchmarking a quantized model on a 16 GB RAM laptop.
  >
  > To be transparent: Horus is closed source and will be licensed to companies. Contributing is voluntary and unpaid. Before seeing any code, contributors sign a short confidentiality and contributor agreement, and the code they contribute becomes part of Horus. In return we offer thorough code reviews, full credit in the project and a professional reference on request.
  >
  > We're not sharing code or private links publicly. If this interests you, comment below or DM me with your experience in local inference, CPU optimisation or offline apps.

- **Revised Post Copy (live edit pending):**
  > **Running a local LLM stack in a home lab: how do you control memory and concurrency?**
  >
  > Hi everyone,
  >
  > We're three final-year students at Epitech building Horus, a proprietary multi-agent assistant that runs locally. An earlier beta install took over two hours; we're now separating install-time costs from runtime and trying to keep the inference service within a predictable memory budget.
  >
  > Our latest CPU benchmark used Qwen3-4B-Instruct-2507 Q4_K_M through llama.cpp on a development laptop with a Ryzen AI 9 HX 370 (12 cores), 64 GB RAM and 31 GiB available to Docker. We have not run this benchmark on a 16 GB reference machine yet.
  >
  > For a self-hosted deployment, would you use one shared inference server with a bounded request queue, or isolate each agent in its own process? Which memory and concurrency limits have worked reliably for you?
  >
  > We're particularly interested in peak RSS, context/KV-cache limits and host-level safeguards such as cgroups. Advice is welcome; we are not asking anyone to endorse the product.
  >
  > Horus is closed source and intended for commercial licensing; its benchmark kit is open source. Any contribution is voluntary and unpaid, under a short agreement, with review, credit and a reference offered.

- **Key Community Feedback & Advice Received:**
  - **Treat Agents as Logical Actors:** Do not treat agents as separate model processes; instead, use a single inference service with a bounded queue and admission control based on resident model memory plus the KV-cache budget.
  - **Shared Resource Architecture:** Run a single inference process (like `llama-server`) where all agents queue requests, avoiding multiple models running in separate processes.
  - **CPU Stack & GGUF Strategy:** For CPU-only paths, transition to GGUF format via `llama.cpp` using a 4–5 bit quantization (e.g., Q4_K_M for a 3B–4B model) and keep Transformers as a compatibility fallback.
  - **Hardware & Thread Optimization:** Pin threads to physical cores, set context sizes as low as the task allows, and apply system resource controls (like a `systemd` `MemoryMax` or cgroup limit) on the inference process to prevent host crashes.
  - **Benchmarking Plan:** Benchmark the 4–5 bit GGUF against current models on real prompts (recording first-token latency, tokens/s, peak RSS, and quality regressions) to derive the concurrency ceiling.

---

### 3. Reddit: r/locallm

- **Name + link:** Reddit - r/locallm (https://www.reddit.com/r/LocalLLM/comments/1wvxzaj/how_do_you_keep_a_local_multiagent_app_usable_on/)
- **Type:** Subreddit / Online Community
- **Audience:** Developers and enthusiasts dedicated to running large language models locally on personal and modest hardware.
- **Posting rules:** Follow general community guidelines against pure spam; technical discussions about local performance are well received.
  - *Date checked:* Oct 2, 2026
- **Why it fits Horus:** Highly focused on local execution constraints, making it an ideal place to discuss CPU inference bottlenecks and memory footprints.

- **Original Published Post (Oct 2, 2026):**
  > **How do you keep a local multi-agent app usable on CPU-only / low-RAM machines?**
  >
  > Hi everyone,
  > We're three final-year students at Epitech building Horus, a multi-agent assistant that runs entirely locally and offline. Our current challenge is hardware: keeping it usable on machines without a powerful GPU, without long setup times, excessive RAM/VRAM use or crashes.
  > Where we are today, from our last beta test:
  > * One tester needed over 2 hours to install. The Python dependencies alone take 21–46 min, and the download is about 25 GB.
  > * On CPU only, routing a question can take around 40 s, long enough for our WebSocket connection to drop.
  >
  > [Models we use + the smallest machine we've tested on]
  > We'd love advice from anyone experienced with:
  > * CPU-only LLM inference and memory-efficient loading
  > * Quantization and model choice for low-end hardware
  > * GPU/CPU fallback strategies
  > * Hardware detection and adaptive configuration
  > * Preventing resource exhaustion during setup and execution
  >
  > Advice in the comments is very welcome, with no strings attached.
  > **Looking for contributors:** we also have a few small, well-scoped tasks or code reviews (about 1–4 hours), for example [reviewing our hardware detection and model selection, or benchmarking a quantized model on a 16 GB RAM laptop].
  > To be transparent: Horus is closed source and will be licensed to companies. Contributing is voluntary and unpaid. Before seeing any code, contributors sign a short confidentiality and contributor agreement, and the code they contribute becomes part of Horus. In return we offer thorough code reviews, full credit in the project and a professional reference on request.
  > We're not sharing code or private links publicly. If this interests you, comment below or DM me with your experience in local inference, CPU optimisation or offline apps.

- **Revised Post Copy (live edit pending):**
  > **Which CPU quantization would you trust for a 4B model with RAG?**
  >
  > Hi,
  >
  > We're three Epitech students working on Horus, a proprietary local multi-agent assistant. We are comparing CPU-friendly model configurations and want to understand which quality and memory measurements matter most in real retrieval-augmented tasks.
  >
  > Our current CPU evaluation uses Qwen3-4B-Instruct-2507 in Q4_K_M through llama.cpp. It was measured on a Ryzen AI 9 HX 370 laptop with 64 GB RAM (31 GiB available to Docker); the 16 GB reference machine has not been tested yet. The same model's GPU evaluation uses AWQ with vLLM on an RTX 4070 Laptop GPU (8 GB).
  >
  > For a 16 GB target, would you start with Q4_K_M or a higher quant and reduce context/KV-cache instead? Which RAG-specific checks do you use beyond perplexity—citation accuracy, retrieval placement, or long-context degradation?
  >
  > Horus is closed source and intended for commercial licensing; the benchmark kit is open source. We are looking for technical feedback, not endorsements. Contributions are voluntary and unpaid, with a short agreement, review, credit and a reference.

- **Key Community Feedback & Advice Received:**
  - **Expert Insights from Offline App Developers:**
    - Saving users from a broken first download is more critical than having a faster model; resumable range requests and multiple regional mirrors prevent users from abandoning the app right at the start.
    - Keep routing off the heavy path: a small classifier or embedding lookup in front drastically reduces initial blocking time.
  - **The 25 GB Problem & App/Weights Separation:**
    - Feedback from developers of offline apps highlighted that the massive initial download size is the real conversion killer.
    - *Solution:* Decouple the app binary from the model weights. Ship a tiny bootstrap installer (~35 MB) and pull models afterward via a custom downloader.
  - **Downloader & CDN Best Practices:**
    - Implement multiple regional mirrors (CDN performance varies heavily by country).
    - Always use resumable downloads (partial files + HTTP range requests) with final hash verification.
  - **Python Dependency Hell (21–46 min setup):**
    - Indicates code compilation or heavy package resolution happening on the user's machine. Fix by pinning wheels or shipping a prebuilt runtime.
  - **Hardware Gating vs. Tiering Strategy:**
    - Either enforce a hard gate on chip generation or perform a fixed-tier detection once at install (RAM + core count) and store the choice locally.
  - **Transport Layer & WebSocket Resilience:**
    - 40s routing on CPU is an expected hardware cost; the transport layer should not drop connections. Stream tokens as they come, or send regular heartbeat frames every few seconds.
  - **Routing & Context Optimization:**
    - Ensure agents act as logical actors sharing a single resident model process with a bounded queue and strict context caps, rather than spinning up separate heavy model instances.

---

### 4. Reddit: r/localaistack

- **Name + link:** Reddit - r/localaistack (https://www.reddit.com/r/LocalAIStack/comments/1wvxyjt/how_do_you_keep_a_local_multiagent_app_usable_on/)
- **Type:** Subreddit / Online Community
- **Audience:** Engineers and hobbyists focusing on building and stacking local AI components, architectures, and deployment pipelines.
- **Posting rules:** Standard etiquette regarding technical sharing and openness.
  - *Date checked:* Oct 2, 2026
- **Why it fits Horus:** Directly aligns with stack optimization (Docker, runtimes, pipelines) for local AI environments.

- **Original Published Post (Oct 2, 2026):**
  > **How do you keep a local multi-agent app usable on CPU-only / low-RAM machines?**
  >
  > Hi everyone,
  > We're three final-year students at Epitech building Horus, a multi-agent assistant that runs entirely locally and offline. Our current challenge is hardware: keeping it usable on machines without a powerful GPU, without long setup times, excessive RAM/VRAM use or crashes.
  > Where we are today, from our last beta test:
  > * One tester needed over 2 hours to install. The Python dependencies alone take 21–46 min, and the download is about 25 GB.
  > * On CPU only, routing a question can take around 40 s, long enough for our WebSocket connection to drop.
  >
  > [Models we use + the smallest machine we've tested on]
  > We'd love advice from anyone experienced with:
  > * CPU-only LLM inference and memory-efficient loading
  > * Quantization and model choice for low-end hardware
  > * GPU/CPU fallback strategies
  > * Hardware detection and adaptive configuration
  > * Preventing resource exhaustion during setup and execution
  >
  > Advice in the comments is very welcome, with no strings attached.
  > **Looking for contributors:** we also have a few small, well-scoped tasks or code reviews (about 1–4 hours), for example [reviewing our hardware detection and model selection, or benchmarking a quantized model on a 16 GB RAM laptop].
  > To be transparent: Horus is closed source and will be licensed to companies. Contributing is voluntary and unpaid. Before seeing any code, contributors sign a short confidentiality and contributor agreement, and the code they contribute becomes part of Horus. In return we offer thorough code reviews, full credit in the project and a professional reference on request.
  > We're not sharing code or private links publicly. If this interests you, comment below or DM me with your experience in local inference, CPU optimisation or offline apps.

- **Revised Post Copy (live edit pending):**
  > **How would you package a local AI stack without a huge first download?**
  >
  > Hi everyone,
  >
  > We're three final-year students at Epitech building Horus, a proprietary assistant that runs locally. An earlier beta install took over two hours, and its initial download was about 25 GB. We're looking at how to make the app, model weights and runtime easier to install and update independently.
  >
  > Our current CPU benchmark uses Qwen3-4B-Instruct-2507 Q4_K_M with llama.cpp on a Ryzen AI 9 HX 370 laptop (64 GB RAM; 31 GiB available to Docker). We have not measured on the 16 GB reference machine. The GPU run uses Qwen3-4B-Instruct-2507 AWQ with vLLM on an RTX 4070 Laptop GPU (8 GB).
  >
  > For a Docker-based offline application, what has worked best for resumable model downloads, smaller CPU dependency sets and keeping app upgrades separate from model updates? We would especially value lessons from projects that ship to machines with limited disk and memory.
  >
  > Horus is closed source and intended for commercial licensing; our benchmark kit is open source. We are sharing the engineering problem transparently and welcome advice, not endorsements. Contributions are voluntary and unpaid, with a short agreement, review, credit and a reference.

---

### 5. GitHub Discussions: llama.cpp

- **Name + link:** GitHub Discussions - llama.cpp (https://github.com/ggml-org/llama.cpp/discussions/29859)
- **Type:** Repository Q&A / Discussion Forum
- **Audience:** Core contributors and power users specialized in C/C++ local execution, performance tuning, and CPU-bound LLM optimization.
- **Posting rules:** Keep discussions technical, focused on the project's ecosystem or general local CPU/quantization performance. Avoid pure spam.
  - *Date checked:* Oct 2, 2026
- **Why it fits Horus:** The absolute reference hub for developers tackling low-resource and CPU-only inference bottlenecks.

- **Original Published Post (Oct 2, 2026):**
  > **How do you keep a local multi-agent app usable on CPU-only / low-RAM machines?**
  >
  > Hi everyone,
  > We're three final-year students at Epitech building Horus, a multi-agent assistant that runs entirely locally and offline. Our current challenge is hardware: keeping it usable on machines without a powerful GPU, without long setup times, excessive RAM/VRAM use or crashes.
  > Where we are today, from our last beta test:
  > * One tester needed over 2 hours to install. The Python dependencies alone take 21–46 min, and the download is about 25 GB.
  > * On CPU only, routing a question can take around 40 s, long enough for our WebSocket connection to drop.
  >
  > [Models we use + the smallest machine we've tested on]
  > We'd love advice from anyone experienced with:
  > * CPU-only LLM inference and memory-efficient loading
  > * Quantization and model choice for low-end hardware
  > * GPU/CPU fallback strategies
  > * Hardware detection and adaptive configuration
  > * Preventing resource exhaustion during setup and execution
  >
  > Advice in the comments is very welcome, with no strings attached.
  > **Looking for contributors:** we also have a few small, well-scoped tasks or code reviews (about 1–4 hours), for example [reviewing our hardware detection and model selection, or benchmarking a quantized model on a 16 GB RAM laptop].
  > To be transparent: Horus is closed source and will be licensed to companies. Contributing is voluntary and unpaid. Before seeing any code, contributors sign a short confidentiality and contributor agreement, and the code they contribute becomes part of Horus. In return we offer thorough code reviews, full credit in the project and a professional reference on request.
  > We're not sharing code or private links publicly. If this interests you, comment below or DM me with your experience in local inference, CPU optimisation or offline apps.

- **Revised Post Copy (live edit pending):**
  > **CPU-only llama-server configuration for a 4B RAG assistant**
  >
  > We're three final-year Epitech students building Horus, a proprietary local multi-agent assistant. We have moved our CPU path to llama.cpp and are tuning a shared llama-server rather than running a separate model process per agent.
  >
  > Our current CPU evaluation uses Qwen3-4B-Instruct-2507 Q4_K_M. The 100-question benchmark reached 93 correct answers with an 18.2-second median on a Ryzen AI 9 HX 370 (12 cores), 64 GB RAM, with 31 GiB available to Docker. This is not a 16 GB reference-machine result. The GPU run used Qwen3-4B-Instruct-2507 AWQ with vLLM on an RTX 4070 Laptop GPU (8 GB).
  >
  > For llama-server on CPU, which settings have had the biggest impact on RAG quality and first-token latency? We would especially value practical advice on context size, `--threads`, KV-cache type, `mmap`, and metrics to collect (peak RSS, tokens/s, citation accuracy).
  >
  > Horus is closed source and intended for commercial licensing; the benchmark kit is open source. This is a technical question, not a request for endorsement. Any contribution is voluntary and unpaid, under a short agreement, with review, credit and a reference offered.

- **Key Community Feedback & Advice Received:**
  - **KV-Cache Quantization (`q8_0` vs `f16`):**
    - `q8_0` K/V quantization is not completely lossless, especially in heavy RAG workloads where passages occupy most of the context.
  - **Testing Strategy:** Don't rely on perplexity alone. Compare `q8_0` against `f16` on actual RAG workloads (same retrieved chunks, prompts, and max context).
  - **Recommendation for 16 GB targets:** Try `q8_0` first for memory savings. If measurable regression occurs, test K and V caches separately before falling back to full `f16`.
  - **Hardware-Aware Selection & Execution:**
    - Detect RAM/VRAM first and dynamically select models + quantization tiers instead of relying on a static configuration.
    - Keep context sizes conservative, as KV-cache consumption scales heavily on CPU-only systems.
    - Keep the runtime simple: a single shared model instance, limited concurrency, appropriate context limits, and using `mmap` to manage physical memory loading.

---

### 6. Dev.to Community

- **Name + link:** Dev.to (https://dev.to/nogigi83/how-do-you-keep-a-local-multi-agent-app-usable-on-cpu-only-low-ram-machines-4gok)
- **Type:** Developer Community & Blogging Platform
- **Audience:** Software engineers across all disciplines, highly active in backend, DevOps, and practical software architecture challenges.
- **Posting rules:** Encourage knowledge sharing and architectural discussions; transparency regarding side projects and collaboration.
  - *Date checked:* Oct 2, 2026
- **Why it fits Horus:** Excellent platform to frame resource optimization as a core engineering challenge and attract developers who love solving deep performance bottlenecks.

- **Original Published Post (Oct 2, 2026):**
  > **How do you keep a local multi-agent app usable on CPU-only / low-RAM machines?**
  >
  > Hi everyone,
  > We're three final-year students at Epitech building Horus, a multi-agent assistant that runs entirely locally and offline. Our current challenge is hardware: keeping it usable on machines without a powerful GPU, without long setup times, excessive RAM/VRAM use or crashes.
  > Where we are today, from our last beta test:
  > * One tester needed over 2 hours to install. The Python dependencies alone take 21–46 min, and the download is about 25 GB.
  > * On CPU only, routing a question can take around 40 s, long enough for our WebSocket connection to drop.
  >
  > [Models we use + the smallest machine we've tested on]
  > We'd love advice from anyone experienced with:
  > * CPU-only LLM inference and memory-efficient loading
  > * Quantization and model choice for low-end hardware
  > * GPU/CPU fallback strategies
  > * Hardware detection and adaptive configuration
  > * Preventing resource exhaustion during setup and execution
  >
  > Advice in the comments is very welcome, with no strings attached.
  > **Looking for contributors:** we also have a few small, well-scoped tasks or code reviews (about 1–4 hours), for example [reviewing our hardware detection and model selection, or benchmarking a quantized model on a 16 GB RAM laptop].
  > To be transparent: Horus is closed source and will be licensed to companies. Contributing is voluntary and unpaid. Before seeing any code, contributors sign a short confidentiality and contributor agreement, and the code they contribute becomes part of Horus. In return we offer thorough code reviews, full credit in the project and a professional reference on request.
  > We're not sharing code or private links publicly. If this interests you, comment below or DM me with your experience in local inference, CPU optimisation or offline apps.

- **Revised Post Copy (live edit pending):**
  > **What we learned packaging a local LLM app for CPU-only machines**
  >
  > We're three final-year Epitech students building Horus, a proprietary assistant that runs locally. In an earlier beta, one install took over two hours and the first download was about 25 GB. That made us rethink how app binaries, Python dependencies and model weights should be installed and updated.
  >
  > Our current CPU benchmark runs Qwen3-4B-Instruct-2507 Q4_K_M through llama.cpp. It scored 93/100 with an 18.2-second median on a Ryzen AI 9 HX 370 laptop with 64 GB RAM (31 GiB available to Docker). We have not yet run on the 16 GB reference machine.
  >
  > For offline desktop software, what has worked for you: separating models from the application, resumable downloads, prebuilt CPU wheels, or a small bootstrap installer? What would you measure first to make the first-run experience reliable?
  >
  > Horus is closed source and intended for commercial licensing; our benchmark kit is open source. We welcome practical packaging advice, not endorsements. Contributions are voluntary and unpaid, with a short agreement, review, credit and a reference.

---

### 7. Discord: Hugging Face (#help-and-feedback & #jobs-and-collaboration)

- **Name + link:** Discord - Hugging Face (https://discord.gg/huggingface)
- **Type:** Discord Server
- **Audience:** Massive global community of ML engineers, researchers, and developers discussing models, deployment, and MLOps.
- **Posting rules:** Technical architectural questions go to #help-and-feedback; collaboration/recruitment posts go to #jobs-and-collaboration using proper tags. Avoid spam.
  - *Date checked:* Oct 2, 2026
- **Why it fits Horus:** Perfect for engaging directly with machine learning engineers who face hardware constraints and local deployment challenges every day.

- **Original Published Post (Oct 2, 2026):**
  > **How do you keep a local multi-agent app usable on CPU-only / low-RAM machines?**
  >
  > Hi everyone,
  > We're three final-year students at Epitech building Horus, a multi-agent assistant that runs entirely locally and offline. Our current challenge is hardware: keeping it usable on machines without a powerful GPU, without long setup times, excessive RAM/VRAM use or crashes.
  > Where we are today, from our last beta test:
  > * One tester needed over 2 hours to install. The Python dependencies alone take 21–46 min, and the download is about 25 GB.
  > * On CPU only, routing a question can take around 40 s, long enough for our WebSocket connection to drop.
  >
  > [Models we use + the smallest machine we've tested on]
  > We'd love advice from anyone experienced with:
  > * CPU-only LLM inference and memory-efficient loading
  > * Quantization and model choice for low-end hardware
  > * GPU/CPU fallback strategies
  > * Hardware detection and adaptive configuration
  > * Preventing resource exhaustion during setup and execution
  >
  > Advice in the comments is very welcome, with no strings attached.
  > **Looking for contributors:** we also have a few small, well-scoped tasks or code reviews (about 1–4 hours), for example [reviewing our hardware detection and model selection, or benchmarking a quantized model on a 16 GB RAM laptop].
  > To be transparent: Horus is closed source and will be licensed to companies. Contributing is voluntary and unpaid. Before seeing any code, contributors sign a short confidentiality and contributor agreement, and the code they contribute becomes part of Horus. In return we offer thorough code reviews, full credit in the project and a professional reference on request.
  > We're not sharing code or private links publicly. If this interests you, comment below or DM me with your experience in local inference, CPU optimisation or offline apps.

- **Draft Post Copy (publication status not verified):**
  > **Question for Hugging Face: choosing quantization and hardware tiers for local inference**
  >
  > We're three final-year students at Epitech building Horus, a proprietary local multi-agent assistant. Our current CPU evaluation uses Qwen3-4B-Instruct-2507 Q4_K_M with llama.cpp; the GPU evaluation uses the AWQ model with vLLM on an RTX 4070 Laptop GPU (8 GB).
  >
  > These measurements are from a Ryzen AI 9 HX 370 laptop with 64 GB host RAM and 31 GiB assigned to Docker. We have not measured on a 16 GB reference machine, so we are looking for practical guidance before claiming that tier works.
  >
  > If you deploy local models across mixed hardware, how do you choose between quantization, a smaller model, and a hard minimum-memory requirement? Which benchmark dimensions best predict a stable user experience: peak RSS, time to first token, total latency, or quality on the target workload?
  >
  > Horus is closed source and intended for commercial licensing; the benchmark kit is open source. This is an architecture question; any contribution would be voluntary and unpaid under a short agreement, with review, credit and a reference.

- **Key Community Feedback & Advice Received:**
  - **External Providers / Alternatives:** Mention of exploring external inference providers (e.g., featherless.ai) if local constraints become too tight.
  - **Model Recommendations for Low-End Hardware:**
    - Suggestions to look into specialized architectures for constrained environments.
    - Ultra-lightweight alternatives like specific GGUF quants (e.g., mradermacher/gemma-4-E4B-it-ultra-uncensored-heretic-i1-GGUF at Q5_K_M).
  - **Quantization Sweet Spot:** For GGUF/CPU, `Q4_K_M` is acceptable, but `Q5_K_M` is preferred. All other quants are generally considered a waste of disk space and performance.

---

### 8. Reddit: r/selfhostedai

- **Name + link:** Reddit - r/selfhostedai (https://www.reddit.com/r/SelfHostedAI/comments/1ww04wd/how_do_you_keep_a_local_multiagent_app_usable_on/)
- **Type:** Subreddit / Online Community
- **Audience:** Self-hosters and sysadmins specifically running and deploying AI models, local LLMs, and open-source infrastructure on home servers.
- **Posting rules:** Standard tech community guidelines; great reception for infrastructure-heavy and resource-optimization questions.
  - *Date checked:* Oct 2, 2026
- **Why it fits Horus:** Directly targets self-hosters running local AI stacks, making it ideal for gathering insights on resource limits, Docker setups, and container performance on modest hardware.

- **Original Published Post (Oct 2, 2026):**
  > **Running local multi-agent LLMs on modest hardware (CPU-only): How do you prevent resource exhaustion?**
  >
  > Hi everyone,
  > We're three final-year students at Epitech building Horus, a multi-agent assistant that runs entirely locally and offline. Our current challenge is hardware: keeping it usable on machines without a powerful GPU, without long setup times, excessive RAM/VRAM use or crashes.
  >
  > Where we are today, from our last beta test:
  > * One tester needed over 2 hours to install. The Python dependencies alone take 21–46 min, and the download is about 25 GB.
  > * On CPU only, routing a question can take around 40 s, long enough for our WebSocket connection to drop.
  >
  > [Models we use + the smallest machine we've tested on]
  >
  > We'd love advice from anyone experienced with:
  > * CPU-only LLM inference and memory-efficient loading
  > * Quantization and model choice for low-end hardware
  > * GPU/CPU fallback strategies
  > * Hardware detection and adaptive configuration
  > * Preventing resource exhaustion during setup and execution
  >
  > Advice in the comments is very welcome, with no strings attached.
  >
  > **Looking for contributors:** we also have a few small, well-scoped tasks or code reviews (about 1–4 hours), for example [reviewing our hardware detection and model selection, or benchmarking a quantized model on a 16 GB RAM laptop].
  >
  > To be transparent: Horus is closed source and will be licensed to companies. Contributing is voluntary and unpaid. Before seeing any code, contributors sign a short confidentiality and contributor agreement, and the code they contribute becomes part of Horus. In return we offer thorough code reviews, full credit in the project and a professional reference on request.
  >
  > We're not sharing code or private links publicly. If this interests you, comment below or DM me with your experience in local inference, CPU optimisation or offline apps.

- **Revised Post Copy (live edit pending):**
  > **How do you keep one local model process within a home server's memory budget?**
  >
  > We're three final-year Epitech students building Horus, a proprietary local multi-agent assistant. We are moving CPU inference to one shared llama-server so several agents can queue requests without loading separate model copies.
  >
  > Our CPU benchmark uses Qwen3-4B-Instruct-2507 Q4_K_M and currently runs on a Ryzen AI 9 HX 370 laptop with 64 GB host RAM (31 GiB available to Docker). We have not tested the 16 GB reference machine yet.
  >
  > For a self-hosted AI service, what is a safe way to budget resident model memory, KV cache and concurrent requests? Do you enforce a hard cgroup/container limit, and what signals tell you the service is approaching an OOM or swapping?
  >
  > Horus is closed source and intended for commercial licensing; its benchmark kit is open source. We are asking for operational advice, not endorsements. Contributions are voluntary and unpaid, with a short agreement, review, credit and a reference.

---

### 9. Reddit: r/homelab

- **Name + link:** Reddit - r/homelab (https://www.reddit.com/r/homelab/comments/1ww0xpm/how_do_you_keep_a_local_multiagent_app_usable_on/)
- **Type:** Subreddit / Online Community
- **Audience:** Hardware enthusiasts, systems administrators, and self-hosters managing physical servers, recycled enterprise hardware, and resource-constrained home labs.
- **Posting rules:** Strict rules against low-effort posts, but deep infrastructure and resource-management discussions are highly valued.
  - *Date checked:* Oct 2, 2026
- **Why it fits Horus:** Excellent for capturing physical constraints (CPU throttling, RAM pressure, disk I/O bottlenecks) on modest or older hardware setups.

- **Original Published Post (Oct 2, 2026):**
  > **Running local multi-agent LLMs on modest hardware (CPU-only): How do you prevent resource exhaustion?**
  >
  > Hi everyone,
  > We're three final-year students at Epitech building Horus, a multi-agent assistant that runs entirely locally and offline. Our current challenge is hardware: keeping it usable on machines without a powerful GPU, without long setup times, excessive RAM/VRAM use or crashes.
  >
  > Where we are today, from our last beta test:
  > * One tester needed over 2 hours to install. The Python dependencies alone take 21–46 min, and the download is about 25 GB.
  > * On CPU only, routing a question can take around 40 s, long enough for our WebSocket connection to drop.
  >
  > [Models we use + the smallest machine we've tested on]
  >
  > We'd love advice from anyone experienced with:
  > - CPU-only LLM inference and memory-efficient loading
  > - Quantization and model choice for low-end hardware
  > - GPU/CPU fallback strategies
  > - Hardware detection and adaptive configuration
  > - Preventing resource exhaustion during setup and execution
  >
  > Advice in the comments is very welcome, with no strings attached.
  >
  > **Looking for contributors:** we also have a few small, well-scoped tasks or code reviews (about 1–4 hours), for example [reviewing our hardware detection and model selection, or benchmarking a quantized model on a 16 GB RAM laptop].
  >
  > To be transparent: Horus is closed source and will be licensed to companies. Contributing is voluntary and unpaid. Before seeing any code, contributors sign a short confidentiality and contributor agreement, and the code they contribute becomes part of Horus. In return we offer thorough code reviews, full credit in the project and a professional reference on request.
  >
  > We're not sharing code or private links publicly. If this interests you, comment below or DM me with your experience in local inference, CPU optimisation or offline apps.

- **Revised Post Copy (live edit pending):**
  > **What should I measure before running a 4B model on older homelab hardware?**
  >
  > We're three final-year students at Epitech building Horus, a proprietary multi-agent assistant that runs locally. We want to make CPU inference stable on home servers and older machines, not just fast on a development workstation.
  >
  > Our current CPU setup is Qwen3-4B-Instruct-2507 Q4_K_M via llama.cpp, benchmarked on a Ryzen AI 9 HX 370 laptop (12 cores, 64 GB RAM; 31 GiB available to Docker). We have not run the benchmark on a 16 GB reference machine.
  >
  > For your homelab, what has mattered most when hosting a quantized model: sustained memory bandwidth, thermal throttling, disk/mmap behaviour, or limiting context and concurrency? What minimum monitoring would you want before calling a setup stable?
  >
  > Horus is closed source and intended for commercial licensing; the benchmark kit is open source. We welcome technical feedback, not endorsements. Contributions are voluntary and unpaid, with a short agreement, review, credit and a reference.

---

### 10. Reddit: r/LangChain

- **Name + link:** Reddit - r/LangChain (https://www.reddit.com/r/LangChain/comments/1ww0ypn/how_do_you_keep_a_local_multiagent_app_usable_on/)
- **Type:** Subreddit / Online Community
- **Audience:** Developers building LLM applications, multi-agent frameworks, RAG pipelines, and orchestration workflows.
- **Posting rules:** Focus on technical application patterns, framework design, and agent loops.
  - *Date checked:* Oct 2, 2026
- **Why it fits Horus:** Directly targets multi-agent loop optimization, delegation strategies, context bloat management, and orchestration overhead under strict resource bounds.

- **Original Published Post (Oct 2, 2026):**
  > How do you keep a local multi-agent app usable on CPU-only / low-RAM machines?
  >
  > Hi everyone,
  >
  > We're three final-year students at Epitech building Horus, a multi-agent assistant that runs entirely locally and offline. Our current challenge is hardware: keeping it usable on machines without a powerful GPU, without long setup times, excessive RAM/VRAM use or crashes.
  >
  > Where we are today, from our last beta test:
  > * One tester needed over 2 hours to install. The Python dependencies alone take 21–46 min, and the download is about 25 GB.
  > * On CPU only, routing a question can take around 40 s, long enough for our WebSocket connection to drop.
  >
  > [Models we use + the smallest machine we've tested on]
  >
  > We'd love advice from anyone experienced with:
  > - CPU-only LLM inference and memory-efficient loading
  > - Quantization and model choice for low-end hardware
  > - GPU/CPU fallback strategies
  > - Hardware detection and adaptive configuration
  > - Preventing resource exhaustion during setup and execution
  >
  > Advice in the comments is very welcome, with no strings attached.
  >
  > **Looking for contributors:** we also have a few small, well-scoped tasks or code reviews (about 1–4 hours), for example [reviewing our hardware detection and model selection, or benchmarking a quantized model on a 16 GB RAM laptop].
  >
  > To be transparent: Horus is closed source and will be licensed to companies. Contributing is voluntary and unpaid. Before seeing any code, contributors sign a short confidentiality and contributor agreement, and the code they contribute becomes part of Horus. In return we offer thorough code reviews, full credit in the project and a professional reference on request.
  >
  > We're not sharing code or private links publicly. If this interests you, comment below or DM me with your experience in local inference, CPU optimisation or offline apps.

- **Revised Post Copy (live edit pending):**
  > **How should a local agent graph share one CPU-bound model server?**
  >
  > We're three final-year Epitech students building Horus, a proprietary local multi-agent assistant. Our current CPU path uses one llama-server with Qwen3-4B-Instruct-2507 Q4_K_M; the benchmark on a Ryzen AI 9 HX 370 laptop (64 GB RAM, 31 GiB available to Docker) reached an 18.2-second median across 100 questions. We have not measured on a 16 GB reference machine yet.
  >
  > For agent frameworks, how do you bound work when several nodes depend on the same slow inference endpoint? We are interested in queueing/backpressure, keeping context small across handoffs, and avoiding duplicate model calls for routing or tool selection.
  >
  > Horus is closed source and intended for commercial licensing; the benchmark kit is open source. We welcome architecture feedback, not endorsements. Contributions are voluntary and unpaid, with a short agreement, review, credit and a reference.

---

### 11. Reddit: r/Backend

- **Name + link:** Reddit - r/Backend (https://www.reddit.com/r/Backend/comments/1x6j10e/pattern_for_handling_long_cpublocking_tasks/)
- **Type:** Subreddit / Online Community
- **Audience:** Backend engineers, API architects, and systems developers.
- **Posting rules:** Technical focus on server-side architecture, asynchronous queues, and persistent connections.
- *Date checked:* Oct 15, 2026
- **Why it fits Horus:** Perfect for discussing the decoupling of CPU-heavy inference tasks (40s latency) from persistent WebSocket client connections.
- **Published Post Content:**
  > **Title:** Pattern for handling long CPU-blocking tasks behind persistent WebSocket connections
  >
  > Hello backend devs,
  >
  > In an offline backend architecture, client apps communicate via WebSockets while tasks are processed by a local background engine. On CPU-only systems, synchronous processing steps can create 30+ second gaps before streaming begins, causing connection timeouts.
  >
  > We are refactoring the transport layer to immediately return an async job ID, queue work in a bounded worker pool, and emit regular heartbeat/ping frames over the WebSocket during execution gaps.
  >
  > How do you typically decouple persistent transport layers from blocking compute steps to prevent transport dropouts in local desktop backends?
  >
  > *Context:* Architectural feedback query on async job queuing and WebSocket state management.
- **Status:** Published & Active

- **Key Community Feedback & Advice Received (r/Backend):**
  - **Event Loop Non-Blocking Imperative:** CPU-bound tasks must run in dedicated background processes/workers rather than blocking the main asyncio thread, otherwise heartbeats and pings will freeze regardless.
  - **Job Persistence vs WebSocket Lifecycles:** Decouple job execution from connection state so that background inference survives client drops and clients can reconnect using a `job_id`.
  - **Bounded Work Queues:** Implement hard capacity limits on the job queue to prevent memory and CPU overload from stacked client requests.
  - **Job Persistence Beyond Socket Drops:** Store execution results under the `job_id` so background tasks survive client disconnections. Clients can re-attach using `{"resume": job_id}` instead of re-running CPU passes.
  - **Native Ping/Pong Usage:** Use native WebSocket ping/pong frames to keep connections alive efficiently without over-engineering custom protocol frames.

---

### 12. Reddit: r/mlops

- **Name + link:** Reddit - r/mlops (https://www.reddit.com/r/mlops/comments/1x6ixlq/managing_memory_footprints_for_local_cpubound/)
- **Type:** Subreddit / Online Community
- **Audience:** MLOps engineers, AI infrastructure specialists, and deployment engineers.
- **Posting rules:** Focuses on production ML pipelines, local model execution, and hardware resource constraints. AI disclosure provided in comments as required.
- *Date checked:* Oct 15, 2026
- **Why it fits Horus:** Ideal for gathering feedback on model quantization choices (Q4_K_M vs Q5_K_M) and CPU-bound fallback strategies.
- **Published Post Content:**
  > **Title:** Managing memory footprints for local CPU-bound model execution daemons
  >
  > Hi MLOps community,
  >
  > We are working on optimizing an offline local inference engine running on client machines without discrete GPUs.
  >
  > To fit within 16 GB RAM client constraints, we are evaluating GGUF quantization tiers (Q4_K_M vs Q5_K_M) paired with dynamic KV-cache caps and a single resident daemon model architecture.
  >
  > When benchmarking local CPU inference engines under strict RAM constraints, what metrics (peak RSS, first-token latency, memory bandwidth pressure) do you prioritize to establish the stability ceiling?
  >
  > *Context:* Engineering inquiry into local CPU model execution and quantization trade-offs.
- **Status:** Published & Active (AI disclosure submitted)

- **Key Community Feedback & Advice Received (r/mlops):**
  - **Peak RSS is the Critical Metric:** Peak Resident Set Size (RSS) must be the primary metric monitored to establish stability limits; if Peak RSS breaches memory caps, OOM kills render latency metrics irrelevant.
  - **Latency vs Stability:** First-token latency measures UX, whereas Peak RSS measures system survival under memory caps.
  - **Memory Bandwidth Bottlenecks:** Memory bandwidth saturation explains unexpected CPU performance dips, though tracking it requires dedicated profiling tooling.
  - **Benchmark Priorities:** Focus benchmarking efforts on **Peak RAM usage** and **First Token Latency** (UX metric), paired with long-run stability testing to verify that memory allocation remains stable and leak-free across extended multi-agent reasoning loops.
  - **Benchmarking Priority Stack:** Prioritize **Peak RAM usage** (hard stability ceiling) and **First Token Latency** (UX metric), backed by long-run stability testing to verify zero memory accumulation across multi-agent loops.

---

### 13. Reddit: r/docker

- **Name + link:** Reddit - r/docker (https://www.reddit.com/r/docker/comments/1x6iwv7/setting_strict_cgroup_memorymax_bounds_on_local/)
- **Type:** Subreddit / Online Community
- **Audience:** Infrastructure, containerization, and DevOps specialists.
- **Posting rules:** Technical discussions on container isolation, resource caps, and daemon configuration.
- *Date checked:* Oct 15, 2026
- **Why it fits Horus:** Addresses process boundaries and memory caps (`cgroups v2`, `--memory-swap`, `MemoryMax`) to avoid host freezes on client devices.
- **Published Post Content:**
  > **Title:** Setting strict cgroup / MemoryMax bounds on local background container daemons
  >
  > Hi everyone,
  >
  > We are testing a local background service running on client laptops. During peak context processing, memory spikes can risk pushing the host OS into swap death.
  >
  > We are configuring container resource limits (`--memory`, `--memory-swap`, `cgroups v2`) to isolate the local execution daemon from the rest of the host system.
  >
  > For those deploying background containers on desktop client endpoints: what memory overhead buffer do you leave for the host OS to prevent hard freezes when a container hits its hard limit?
  >
  > *Context:* Architectural query regarding container limits on client endpoints.
- **Status:** Published & Active
- **Key Community Feedback & Advice Received (r/docker):**
  - **Zero Container Swap (`memory.swap.max 0`):** Set `--memory-swap` equal to `--memory` in cgroups v2. This ensures internal container OOM rather than host-wide swap death, keeping the user's OS responsive.
  - **Soft Cap Throttling (`memory.high`):** Set `memory.high` at 80–90% of `memory.max` to trigger kernel memory reclamation before hitting hard OOM limits, smoothing out context spikes.
  - **The 70% Physical RAM Rule:** Cap total container allocations to <= 70% of physical RAM (e.g., max 11 GB capped on a 16 GB laptop), leaving ~30% for host OS, display drivers, and user applications.
  - **Data-Driven Sizing & Telemetry:** Read `memory.peak` to determine the actual high watermark under load, and monitor `memory.events` (`oom_kill` counter) to detect silent crashes.
  - **CPU Throttling (`cpu.max`):** Enforce CPU quotas to prevent multithreaded inference from freezing the desktop UI.

---

### 14. Reddit: r/Python

- **Name + link:** Reddit - r/Python (https://www.reddit.com/r/Python/comments/1x6iq32/bypassing_heavy_pytorch_wheels_for_desktop_python/)
- **Type:** Subreddit / Online Community
- **Audience:** Python developers, library authors, and packaging maintainers.
- **Posting rules:** Technical topics regarding Python runtimes, C-extensions, packaging, and execution speed.
- *Date checked:* Oct 15, 2026
- **Why it fits Horus:** Tackles the 21–46 minute PyTorch/CUDA setup bottleneck and options for lightweight binary runtimes (e.g., `llama-cpp-python`, Nuitka).
- **Published Post Content:**
  > **Title:** Bypassing heavy PyTorch wheels for desktop Python application distribution
  >
  > Hi Python devs,
  >
  > We are three final-year students at Epitech working on Horus, a local offline multi-agent backend written in Python. Our biggest distribution hurdle is dependency management on end-user machines.
  >
  > Bottlenecks observed in our last user test:
  > * Dependency installation takes 21–46 minutes on user machines due to PyTorch/CUDA wheel resolution, reaching a 25 GB footprint.
  > * CPU-bound inference takes ~40 seconds during routing, causing persistent WebSocket connections to drop.
  >
  > We are looking for Python packaging and runtime advice on:
  > * Replacing PyTorch with prebuilt C++ bindings (`llama-cpp-python` or native C binaries) for the CPU execution path.
  > * Compiling CPython orchestrator code into standalone executables via Nuitka.
  > * Pinning wheels and pre-bundling runtimes to eliminate on-device compilation.
  > * Implementing async heartbeats to keep WebSockets alive during blocking compute tasks.
  >
  > **Looking for code reviews:** We have 1–4 hour scoped tasks for Python packaging and hardware detection reviews.
  >
  > *Disclosure:* Horus is closed source and licensed commercially. Our benchmark suite is open source (`Horus-EIP/horus-bench-kit`). Contributions are unpaid/voluntary under an NDA agreement, returning thorough code reviews, project credit, and professional references.
- **Status:** Published & Active

- **Key Community Feedback & Advice Received (r/Python):**
  - **Replace PyTorch with ONNX Runtime:** To avoid pulling massive PyTorch/CUDA binaries, export non-generative models or embedding/routing classifiers to ONNX format and execute them via `onnxruntime` (CPU).
  - **Fast Package Resolution with `uv`:** Replace `pip` with `uv` for dependency resolution during setup, or ship pre-built runtime containers/executables so end-users perform zero local package compilation.
  - **`llama.cpp` + Docker Stack Validation:** Standardizing on a pre-packaged Docker container executing `llama.cpp` directly is recommended as the cleanest distribution path, isolating the Python orchestrator from C++ binary execution and avoiding client system contamination.
  - **Astral Optimized Wheels (`wheels.astral.sh`):** Leverage pre-built, ultra-fast Python wheels from the Astral ecosystem (`uv`) to bypass PyTorch/CUDA compilation stages and minimize installation time on end-user machines.
  - **llama-cpp-python Adoption:** Recommended for shipping lightweight cross-platform CPU binaries without multi-GB PyTorch wheels. Allocate engineering effort for the runtime adapter layer.
  - **Packaging Tooling:** Start with PyInstaller for distribution builds; Nuitka introduces high friction when bundling C-extension bindings like `llama-cpp-python`.
  - **CI Prebuilt Wheels:** Build and pin platform-specific wheels in CI to avoid native C++ compilation on user hardware.

---

### 15. GitHub Discussions: FastAPI

- **Name + link:** GitHub Discussions - FastAPI (https://github.com/fastapi/fastapi/discussions/16502)
- **Type:** Public Discussion Board
- **Audience:** Asynchronous Python engineers, ASGI specialists, and API developers.
- **Posting rules:** Focused on async event loop mechanics, WebSockets, and queueing patterns.
- *Date checked:* Oct 15, 2026
- **Why it fits Horus:** Direct focus on ASGI/FastAPI WebSocket connection state, heartbeat frames, and async worker queue management under long synchronous CPU blocks.
- **Published Post Content:**
  > **Title:** Maintaining healthy WebSocket connections during 30s+ synchronous CPU inference blocks
  >
  > Hi everyone,
  >
  > In our offline assistant project, a FastAPI backend communicates with a local frontend over WebSockets. On machines without GPUs, agent reasoning steps can take up to 40 seconds before the first token is generated. This idle gap causes WebSocket connections to drop or time out.
  >
  > We are restructuring the transport logic: returning an immediate job acknowledgment, running inference in a bounded background queue, and pushing progress/heartbeat frames every few seconds prior to token streaming.
  >
  > What async patterns or middleware do you recommend in FastAPI to ensure background CPU-bound tasks never starve the main asyncio event loop or disconnect WebSockets?
  >
  > *Note on context:* Horus is a commercial, closed-source project (student final-year project), but our testing tools are open source (`Horus-EIP/horus-bench-kit`). Voluntary, unpaid code reviews on our async WebSocket queue are welcomed under NDA with full credit and references provided.
- **Status:** Published & Active

- **Key Community Feedback & Advice Received (FastAPI Discussions):**
  - **WebSocket Handler Non-Blocking Pattern (`asyncio.create_task`):**
    Awaiting the worker or streaming job directly inside `while True: receive_json()` prevents the server from reading incoming WebSocket frames during the 40s pass. Wrap the stream/worker call in `asyncio.create_task()` so the loop immediately returns to reading messages. This enables client-side cancellation (`{"type": "cancel"}`), multiple prompts, and instant disconnect detection.
  - **Worker Cancellation Caveat:** Cancelling an `asyncio.Task` only stops the ASGI/WebSocket forwarding, not the underlying process in `ProcessPoolExecutor`. Real cancellation requires workers to check a shared `multiprocessing.Event` between reasoning steps or executing passes in manageable process bounds.
  - **`BrokenProcessPool` Recovery:** Catch `concurrent.futures.process.BrokenProcessPool` explicitly. If an inference worker is OOM-killed while loading a model, the backend must catch the exception, notify the client (`{"type": "error", "code": "INFERENCE_CRASHED"}`), and re-instantiate the pool.
  - **Explicit CPU PyTorch Wheels & `uv`:** Eliminate multi-gigabyte CUDA bloat (`nvidia-*` wheels) on CPU installs using `pip install torch --index-url https://download.pytorch.org/whl/cpu`. Combining explicit CPU index resolution with `uv` reduces install times from 45 minutes down to a few seconds.
  - **Provide a Minimal Reproducible Example (MRE):** Abstract questions often trigger automated or vague responses. Providing a runnable MRE using dummy CPU loops (`time.sleep` / heavy CPU functions) yields direct, code-level architectural fixes from maintainers.
  - **Root Cause Identified (Event Loop Starvation):** WebSocket dropouts are caused by the `asyncio` event loop freezing during 30s+ CPU calls. Uvicorn runs on a single thread and cannot process incoming I/O frames or respond to keepalive pings (20s defaults) when blocked.
  - **The GIL makes `to_thread` a lie for CPU work:** Standard thread pools or `asyncio.to_thread` do not solve the problem because the Python Global Interpreter Lock (GIL) will still stall the event loop. You *must* offload to a separate OS process.
  - **ProcessPoolExecutor Pattern:** Keep the API pure-async by routing all heavy CPU passes through a `ProcessPoolExecutor` (e.g., `max_workers=os.cpu_count() - 1` to leave one core for the ASGI loop).
  - **Dedicated Routing Pool:** Run light classification/routing in an isolated `ProcessPoolExecutor(max_workers=1)` so short tasks never queue behind heavy 40s generations.
  - **Backpressure & Bounded Queues:** Moving inference off the event loop fixes WebSockets but introduces queue bloat if requests accumulate. Benchmark memory per worker, keep worker counts small, and put a bounded queue in front of the pool. If the queue is full, explicitly return a `busy` response instead of accepting infinite jobs.
  - **Connection Warming & UI Progress:** Keep the connection warm with server heartbeat pings every ~15s. Add an app-level progress channel (e.g., an `asyncio.Queue` fed by worker callbacks) to push reasoning progress to the UI instead of a silent loading spinner.
  - **Comprehensive Metrics:** Do not only optimize inference time. Measure queue wait time, peak RAM per worker, and WebSocket responsiveness together to avoid hiding the next bottleneck.
  - **Future Scaling & Packaging Integration:** Quarantining the heavy synchronous engine behind a process pool fixes both runtime drops and setup pain. It allows packaging the engine as a pinned wheel (`hatch build`), turning a 45-min install into a few seconds. It also provides the exact architectural seam needed to easily swap the local pool for a distributed queue (Celery, arq, dramatiq) if the project scales beyond a single box.
  - **Resumable Protocol Implementation:**
    ```python
    # Core async state pattern for CPU-bound tasks in FastAPI
    import asyncio
    from concurrent.futures import ProcessPoolExecutor

    pool = ProcessPoolExecutor(max_workers=os.cpu_count() - 1)

    # Inside the websocket handler:
    fut = loop.run_in_executor(pool, route_request, payload)
    jobs[job_id] = fut

    # TTL cleanup: remove from registry after 5 minutes
    fut.add_done_callback(lambda f, j=job_id: loop.call_later(300, jobs.pop, j, None))
    ```