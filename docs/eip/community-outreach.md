# Community Outreach & Expert Recruitment - Horus

## Strategy & Objectives
Horus is a closed-source, local multi-agent B2B application. Our current technical bottlenecks revolve around the vLLM/Docker stack: massive download sizes (25GB), long installation times (46+ min), and high CPU latency (40s inference causing WebSocket drops). 
Our goal is to gather architectural advice on CPU-only optimization and recruit voluntary, vetted contributors for small, scoped technical tasks (1–4 hours) under NDA.

---

## Target Platforms & Draft Posts

### 1. Reddit: r/LocalLLaMA

* **Name + link:** Reddit - r/LocalLLaMA (https://www.reddit.com/r/LocalLLaMA/comments/1wvwmb5/comment/pdfj0gg/?screen_view_count=2)
* **Type:** Subreddit / Online Community
* **Audience:** The largest community of developers, researchers, and enthusiasts focused on running LLMs locally, quantization, and hardware performance.
* **Posting rules:** Strict rules regarding spam and self-promotion. Technical discussions and genuine architecture questions are highly welcomed, but accounts with 0 karma may face automated blocks.
* *Date checked:* Oct 2, 2026


* **Why it fits Horus:** The absolute best place to find engineers who understand CPU-only inference, memory limits, and quantization bottlenecks.
* **Draft post:**
> **Title:** How do you keep a local multi-agent app usable on CPU-only / low-RAM machines?
> Hi everyone,
> We're three final-year students at Epitech building Horus, a multi-agent assistant that runs entirely locally and offline. Our current challenge is hardware: keeping it usable on machines without a powerful GPU, without long setup times, excessive RAM/VRAM use or crashes.
> Where we are today, from our last beta test:
> * One tester needed over 2 hours to install. The Python dependencies alone take 21–46 min, and the download is about 25 GB.
> * On CPU only, routing a question can take around 40 s, long enough for our WebSocket connection to drop.
> 
> 
> *(We currently use vLLM / Docker with our core models tested on modest hardware).*
> We'd love advice from anyone experienced with:
> * CPU-only LLM inference and memory-efficient loading
> * Quantization and model choice for low-end hardware
> * GPU/CPU fallback strategies
> * Hardware detection and adaptive configuration
> * Preventing resource exhaustion during setup and execution
> 
> 
> Advice in the comments is very welcome, with no strings attached.
> **Looking for contributors:** We also have a few small, well-scoped tasks or code reviews (about 1–4 hours), for example reviewing our hardware detection and model selection, or benchmarking a quantized model on a 16 GB RAM laptop.
> To be transparent: Horus is closed source and will be licensed to companies. Contributing is voluntary and unpaid. Before seeing any code, contributors sign a short confidentiality and contributor agreement, and the code they contribute becomes part of Horus. In return we offer thorough code reviews, full credit in the project and a professional reference on request.
> We're not sharing code or private links publicly. If this interests you, comment below or DM me with your experience in local inference, CPU optimisation or offline apps.


* **Key Community Feedback & Advice Received:**
  * **Community Stance on Closed Source/Unpaid Help:** Feedback highlighted that outsourcing core engineering challenges for a closed-source, unpaid project can face strong skepticism in open-source communities. *Action taken:* Clarified student status and transparency, pivoting the thread strictly toward technical architecture advice and acknowledging hardware gaps (like expanding beyond NVIDIA GPU detection to iGPUs and NPUs).
  * **Non-Generative Routing Optimization:** The 40s routing latency comes from using a generative model for routing. Instead, use a lightweight approach (e.g., small embedding model with nearest-neighbor lookup, or keyword/regex pass) to drop routing to milliseconds.
  * **Agent Segmentation & Context Isolation:** Running agentic work on low-end hardware is possible (e.g., 4B models like Qwen-based variants doing web searches or sub-tasks), *provided* tasks are strictly segmented and isolated with a limited cognitive surface, small context bloat, and tight delegation trees.
  * **Installer vs. Runtime Separation & Lazy Loading:** Treat the installer and runtime as separate resource budgets. Detect CPU features, RAM, VRAM, and disk *before* pulling anything; avoid a 25 GB upfront dependency by implementing lazy, resumable model downloads and a small default model.
  * **Python Stack & Binary Compilation:** The 21–46 min installation time is largely driven by PyTorch/CUDA wheels. On CPU paths, switch to lightweight binaries (like `llama.cpp` / `llama-cpp-python` CPU wheels) or compile Python code into standalone binaries using tools like **Nuitka**.
  * **WebSocket Resilience & Job Queuing:** Long CPU generations/load times cause WebSocket drops. Treat long calls as asynchronous jobs (return a job ID immediately), stream tokens, and send regular heartbeat/progress frames.
  * **Fixed Tiering Profiles:** Rather than trying to auto-tune everything dynamically, detect system capabilities at first run (RAM, AVX2/AVX-512) and select from 2–3 pre-tested fixed configuration profiles.

* **Multi-Agent Handoffs & Communication Patterns:**
  * Instead of passing heavy text summaries up the chain, low-level agents can use **handoff documents** detailing their references/actions and pass file paths up, or use a shared **message board** that other agents read (ideal for deep-search pipelines needing grounding sources).
  * **Failure Handling:** For minor failures (e.g., opening too many pages exceeding context), no explicit retries are needed; parent agents can interpret failures or reroute dynamically. Generic errors (like out-of-context) transmit clean error messages upward.
  * **Specialized Model Tiers & Tool Usage:**
    * Small models load fast and bring distinct strengths. For luxury/high VRAM setups, use larger workers (e.g., 35B/Qwen 27B IQ3_S as a brain) combined with fast 4B models for search. For tight hardware, models like **Sharp Spark (4B)** excel at actions/exploration, **Neo Horse** for analytics/summaries, and **Agents A1** for orchestration.
    * For simple extraction/summarization tasks requiring maximum speed, consider ultra-light alternatives like *Minicpm 2b*, *Lfm 2.6b*, or *Ling Tiny*.
    * **Tool Constraints:** Small models can reliably call tools *if* the tool set is strictly limited (avoid giving them 20+ tools at once).
    
---
### 2. Reddit: r/selfhosted

* **Name + link:** Reddit - r/selfhosted (https://www.reddit.com/r/selfhosted/comments/1wvtzba/running_local_multiagent_llms_on_modest_hardware/)
* **Type:** Subreddit / Online Community
* **Audience:** Developers, home lab enthusiasts, and self-hosters dealing with local deployment and infrastructure limits.
* **Posting rules:** Strict compliance with spam/self-promotion rules. Technical architecture and open discussions are welcome.
* *Date checked:* Oct 2, 2026


* **Why it fits Horus:** Perfect for gathering feedback on resource exhaustion, offline setup constraints, and low-end hardware management.
* **Revised Post Copy (live edit pending):**
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

* **Key Community Feedback & Advice Received:**
  * **Treat Agents as Logical Actors:** Do not treat agents as separate model processes; instead, use a single inference service with a bounded queue and admission control based on resident model memory plus the KV-cache budget.
  * **Shared Resource Architecture:** Run a single inference process (like `llama-server`) where all agents queue requests, avoiding multiple models running in separate processes.
  * **CPU Stack & GGUF Strategy:** For CPU-only paths, transition to GGUF format via `llama.cpp` using a 4–5 bit quantization (e.g., Q4_K_M for a 3B–4B model) and keep Transformers as a compatibility fallback.
  * **Hardware & Thread Optimization:** Pin threads to physical cores, set context sizes as low as the task allows, and apply system resource controls (like a `systemd` `MemoryMax` or cgroup limit) on the inference process to prevent host crashes.
  * **Benchmarking Plan:** Benchmark the 4–5 bit GGUF against current models on real prompts (recording first-token latency, tokens/s, peak RSS, and quality regressions) to derive the concurrency ceiling.

---

### 3. Reddit: r/locallm

* **Name + link:** Reddit - r/locallm (https://www.reddit.com/r/LocalLLM/comments/1wvxzaj/how_do_you_keep_a_local_multiagent_app_usable_on/)
* **Type:** Subreddit / Online Community
* **Audience:** Developers and enthusiasts dedicated to running large language models locally on personal and modest hardware.
* **Posting rules:** Follow general community guidelines against pure spam; technical discussions about local performance are well received.
* *Date checked:* Oct 2, 2026


* **Why it fits Horus:** Highly focused on local execution constraints, making it an ideal place to discuss CPU inference bottlenecks and memory footprints.
* **Revised Post Copy (live edit pending):**
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

* **Expert Insights from Offline App Developers (e.g., NoNetPlay feedback):** 
  * Saving users from a broken first download is more critical than having a faster model; resumable range requests and multiple regional mirrors prevent users from abandoning the app right at the start.
  * Keep routing off the heavy path: a small classifier or embedding lookup in front drastically reduces initial blocking time.

#### Feedback from Reddit (r/LocalLLm)

    The 25 GB Problem & App/Weights Separation:

        Feedback from developers of offline apps (e.g., NoNetPlay) highlighted that the massive initial download size is the real conversion killer, far worse than a 40s routing delay.

        Solution: Decouple the app binary from the model weights. Ship a tiny bootstrap installer (~35 MB) and pull models afterward via a custom downloader.

    Downloader & CDN Best Practices:

        Implement multiple regional mirrors (CDN performance varies heavily by country).

        Always use resumable downloads (partial files + HTTP range requests) with final hash verification. First-download failure is where most users quit; a retry that resumes rather than restarting is invaluable.

    Python Dependency Hell (21–46 min setup):

        Indicates code compilation or heavy package resolution happening on the user's machine (a lottery). Fix by pinning wheels or shipping a prebuilt runtime.

    Hardware Gating vs. Tiering Strategy:

        Either enforce a hard gate on chip generation (rejecting unsupported hardware cleanly rather than delivering a broken 3-minute first token) or perform a fixed-tier detection once at install (RAM + core count) and store the choice locally.

    Transport Layer & WebSocket Resilience:

        40s routing on CPU is an expected hardware cost; the transport layer should not drop connections. Stream tokens as they come, or send regular heartbeat frames every few seconds.

    Routing & Context Optimization:

        Keep routing off the heavy generative model path by placing a small classifier, embedding lookup, or regex pass in front.

        Ensure agents act as logical actors sharing a single resident model process with a bounded queue and strict context caps, rather than spinning up separate heavy model instances.

---

### 4. Reddit: r/localaistack

* **Name + link:** Reddit - r/localaistack (https://www.reddit.com/r/LocalAIStack/comments/1wvxyjt/how_do_you_keep_a_local_multiagent_app_usable_on/)
* **Type:** Subreddit / Online Community
* **Audience:** Engineers and hobbyists focusing on building and stacking local AI components, architectures, and deployment pipelines.
* **Posting rules:** Standard etiquette regarding technical sharing and openness.
* *Date checked:* Oct 2, 2026


* **Why it fits Horus:** Directly aligns with stack optimization (Docker, runtimes, pipelines) for local AI environments.
* **Revised Post Copy (live edit pending):**
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

Name + link: GitHub Discussions - llama.cpp (https://github.com/ggml-org/llama.cpp/discussions/29859)

Type: Repository Q&A / Discussion Forum

Audience: Core contributors and power users specialized in C/C++ local execution, performance tuning, and CPU-bound LLM optimization.

Posting rules: Keep discussions technical, focused on the project's ecosystem or general local CPU/quantization performance. Avoid pure spam.

Date checked: Oct 2, 2026

Why it fits Horus: The absolute reference hub for developers tackling low-resource and CPU-only inference bottlenecks.

Revised Post Copy (live edit pending):

> **CPU-only llama-server configuration for a 4B RAG assistant**
>
> We're three final-year Epitech students building Horus, a proprietary local multi-agent assistant. We have moved our CPU path to llama.cpp and are tuning a shared llama-server rather than running a separate model process per agent.
>
> Our current CPU evaluation uses Qwen3-4B-Instruct-2507 Q4_K_M. The 100-question benchmark reached 93 correct answers with an 18.2-second median on a Ryzen AI 9 HX 370 (12 cores), 64 GB RAM, with 31 GiB available to Docker. This is not a 16 GB reference-machine result. The GPU run used Qwen3-4B-Instruct-2507 AWQ with vLLM on an RTX 4070 Laptop GPU (8 GB).
>
> For llama-server on CPU, which settings have had the biggest impact on RAG quality and first-token latency? We would especially value practical advice on context size, `--threads`, KV-cache type, `mmap`, and metrics to collect (peak RSS, tokens/s, citation accuracy).
>
> Horus is closed source and intended for commercial licensing; the benchmark kit is open source. This is a technical question, not a request for endorsement. Any contribution is voluntary and unpaid, under a short agreement, with review, credit and a reference offered.

* **KV-Cache Quantization (`q8_0` vs `f16`):**
  * `q8_0` K/V quantization is not completely lossless, especially in heavy RAG workloads where passages occupy most of the context.
  * **Testing Strategy:** Don't rely on perplexity alone. Compare `q8_0` against `f16` on actual RAG workloads (same retrieved chunks, prompts, and max context). Specifically check factual accuracy, citations, and degradation when relevant passages are located far back in the context.
  * **Recommendation for 16 GB targets:** Try `q8_0` first for memory savings. If measurable regression occurs, test K and V caches separately before falling back to full `f16`.
* **Hardware-Aware Selection & Execution:**
  * Detect RAM/VRAM first and dynamically select models + quantization tiers instead of relying on a static configuration.
  * Keep context sizes conservative, as KV-cache consumption scales heavily on CPU-only systems.
  * Use adaptive GPU offloading (offload what fits in VRAM, gracefully fall back to CPU for the rest).
  * Keep the runtime simple: a single shared model instance, limited concurrency, appropriate context limits, and using `mmap` to manage physical memory loading.

---

### 6. Dev.to Community

Name + link: Dev.to (https://dev.to/nogigi83/how-do-you-keep-a-local-multi-agent-app-usable-on-cpu-only-low-ram-machines-4gok)

Type: Developer Community & Blogging Platform

Audience: Software engineers across all disciplines, highly active in backend, DevOps, and practical software architecture challenges.

Posting rules: Encourage knowledge sharing and architectural discussions; transparency regarding side projects and collaboration.

Date checked: Oct 2, 2026

Why it fits Horus: Excellent platform to frame resource optimization as a core engineering challenge and attract developers who love solving deep performance bottlenecks.

Revised Post Copy (live edit pending):

> **What we learned packaging a local LLM app for CPU-only machines**
>
> We're three final-year Epitech students building Horus, a proprietary assistant that runs locally. In an earlier beta, one install took over two hours and the first download was about 25 GB. That made us rethink how app binaries, Python dependencies and model weights should be installed and updated.
>
> Our current CPU benchmark runs Qwen3-4B-Instruct-2507 Q4_K_M through llama.cpp. It scored 93/100 with an 18.2-second median on a Ryzen AI 9 HX 370 laptop with 64 GB RAM (31 GiB available to Docker). We have not yet run on the 16 GB reference machine.
>
> For offline desktop software, what has worked for you: separating models from the application, resumable downloads, prebuilt CPU wheels, or a small bootstrap installer? What would you measure first to make the first-run experience reliable?
>
> Horus is closed source and intended for commercial licensing; our benchmark kit is open source. We welcome practical packaging advice, not endorsements. Contributions are voluntary and unpaid, with a short agreement, review, credit and a reference.

### 7. Discord: Hugging Face (#help-and-feedback & #jobs-and-collaboration)

Name + link: Discord - Hugging Face (https://discord.gg/huggingface)

Type: Discord Server

Audience: Massive global community of ML engineers, researchers, and developers discussing models, deployment, and MLOps.

Posting rules: Technical architectural questions go to #help-and-feedback; collaboration/recruitment posts go to #jobs-and-collaboration using proper tags. Avoid spam.

Date checked: Oct 2, 2026

Why it fits Horus: Perfect for engaging directly with machine learning engineers who face hardware constraints and local deployment challenges every day.

Draft Post Copy (publication status not verified):

> **Question for Hugging Face: choosing quantization and hardware tiers for local inference**
>
> We're three final-year students at Epitech building Horus, a proprietary local multi-agent assistant. Our current CPU evaluation uses Qwen3-4B-Instruct-2507 Q4_K_M with llama.cpp; the GPU evaluation uses the AWQ model with vLLM on an RTX 4070 Laptop GPU (8 GB).
>
> These measurements are from a Ryzen AI 9 HX 370 laptop with 64 GB host RAM and 31 GiB assigned to Docker. We have not measured on a 16 GB reference machine, so we are looking for practical guidance before claiming that tier works.
>
> If you deploy local models across mixed hardware, how do you choose between quantization, a smaller model, and a hard minimum-memory requirement? Which benchmark dimensions best predict a stable user experience: peak RSS, time to first token, total latency, or quality on the target workload?
>
> Horus is closed source and intended for commercial licensing; the benchmark kit is open source. This is an architecture question; any contribution would be voluntary and unpaid under a short agreement, with review, credit and a reference.

#### Feedback 

External Providers / Alternatives: Mention of exploring external inference providers (e.g., featherless.ai) if local constraints become too tight.

Model Recommendations for Low-End Hardware:

    Suggestions to look into specialized architectures for constrained environments (e.g., darkc0de/K2-Horizon-MoVA-36B-A4B-heretic).

    Ultra-lightweight alternatives like specific GGUF quants (e.g., mradermacher/gemma-4-E4B-it-ultra-uncensored-heretic-i1-GGUF at Q5_K_M).

Quantization Sweet Spot: For GGUF/CPU, Q4_K_M is acceptable, but Q5_K_M is preferred. All other quants are generally considered a waste of disk space and performance.
### 8. Reddit: r/selfhostedai
* **Name + link:** Reddit - r/selfhostedai (https://www.reddit.com/r/SelfHostedAI/comments/1ww04wd/how_do_you_keep_a_local_multiagent_app_usable_on/)
* **Type:** Subreddit / Online Community
* **Audience:** Self-hosters and sysadmins specifically running and deploying AI models, local LLMs, and open-source infrastructure on home servers.
* **Posting rules:** Standard tech community guidelines; great reception for infrastructure-heavy and resource-optimization questions.
  * *Date checked:* Oct 2, 2026
* **Why it fits Horus:** Directly targets self-hosters running local AI stacks, making it ideal for gathering insights on resource limits, Docker setups, and container performance on modest hardware.
* **Revised Post Copy (live edit pending):**
  > **How do you keep one local model process within a home server's memory budget?**
  >
  > We're three final-year Epitech students building Horus, a proprietary local multi-agent assistant. We are moving CPU inference to one shared llama-server so several agents can queue requests without loading separate model copies.
  >
  > Our CPU benchmark uses Qwen3-4B-Instruct-2507 Q4_K_M and currently runs on a Ryzen AI 9 HX 370 laptop with 64 GB host RAM (31 GiB available to Docker). We have not tested the 16 GB reference machine yet.
  >
  > For a self-hosted AI service, what is a safe way to budget resident model memory, KV cache and concurrent requests? Do you enforce a hard cgroup/container limit, and what signals tell you the service is approaching an OOM or swapping?
  >
  > Horus is closed source and intended for commercial licensing; its benchmark kit is open source. We are asking for operational advice, not endorsements. Contributions are voluntary and unpaid, with a short agreement, review, credit and a reference.

### 9. Reddit: r/homelab
* **Name + link:** Reddit - r/homelab (https://www.reddit.com/r/homelab/comments/1ww0xpm/how_do_you_keep_a_local_multiagent_app_usable_on/)
* **Type:** Subreddit / Online Community
* **Audience:** Hardware enthusiasts, systems administrators, and self-hosters managing physical servers, recycled enterprise hardware, and resource-constrained home labs.
* **Posting rules:** Strict rules against low-effort posts, but deep infrastructure and resource-management discussions are highly valued.
  * *Date checked:* Oct 2, 2026
* **Why it fits Horus:** Excellent for capturing physical constraints (CPU throttling, RAM pressure, disk I/O bottlenecks) on modest or older hardware setups.
* **Revised Post Copy (live edit pending):**
  > **What should I measure before running a 4B model on older homelab hardware?**
  >
  > We're three final-year students at Epitech building Horus, a proprietary multi-agent assistant that runs locally. We want to make CPU inference stable on home servers and older machines, not just fast on a development workstation.
  >
  > Our current CPU setup is Qwen3-4B-Instruct-2507 Q4_K_M via llama.cpp, benchmarked on a Ryzen AI 9 HX 370 laptop (12 cores, 64 GB RAM; 31 GiB available to Docker). We have not run the benchmark on a 16 GB reference machine.
  >
  > For your homelab, what has mattered most when hosting a quantized model: sustained memory bandwidth, thermal throttling, disk/mmap behaviour, or limiting context and concurrency? What minimum monitoring would you want before calling a setup stable?
  >
  > Horus is closed source and intended for commercial licensing; the benchmark kit is open source. We welcome technical feedback, not endorsements. Contributions are voluntary and unpaid, with a short agreement, review, credit and a reference.

### 10. Reddit: r/LangChain
* **Name + link:** Reddit - r/LangChain (https://www.reddit.com/r/LangChain/comments/1ww0ypn/how_do_you_keep_a_local_multiagent_app_usable_on/)
* **Type:** Subreddit / Online Community
* **Audience:** Developers building LLM applications, multi-agent frameworks, RAG pipelines, and orchestration workflows.
* **Posting rules:** Focus on technical application patterns, framework design, and agent loops.
  * *Date checked:* Oct 2, 2026
* **Why it fits Horus:** Directly targets multi-agent loop optimization, delegation strategies, context bloat management, and orchestration overhead under strict resource bounds.
* **Revised Post Copy (live edit pending):**
  > **How should a local agent graph share one CPU-bound model server?**
  >
  > We're three final-year Epitech students building Horus, a proprietary local multi-agent assistant. Our current CPU path uses one llama-server with Qwen3-4B-Instruct-2507 Q4_K_M; the benchmark on a Ryzen AI 9 HX 370 laptop (64 GB RAM, 31 GiB available to Docker) reached an 18.2-second median across 100 questions. We have not measured on a 16 GB reference machine yet.
  >
  > For agent frameworks, how do you bound work when several nodes depend on the same slow inference endpoint? We are interested in queueing/backpressure, keeping context small across handoffs, and avoiding duplicate model calls for routing or tool selection.
  >
  > Horus is closed source and intended for commercial licensing; the benchmark kit is open source. We welcome architecture feedback, not endorsements. Contributions are voluntary and unpaid, with a short agreement, review, credit and a reference.
