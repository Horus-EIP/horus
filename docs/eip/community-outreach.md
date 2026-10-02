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
---
### 2. Reddit: r/selfhosted

* **Name + link:** Reddit - r/selfhosted (https://www.reddit.com/r/selfhosted/comments/1wvtzba/running_local_multiagent_llms_on_modest_hardware/)
* **Type:** Subreddit / Online Community
* **Audience:** Developers, home lab enthusiasts, and self-hosters dealing with local deployment and infrastructure limits.
* **Posting rules:** Strict compliance with spam/self-promotion rules. Technical architecture and open discussions are welcome.
* *Date checked:* Oct 2, 2026


* **Why it fits Horus:** Perfect for gathering feedback on resource exhaustion, offline setup constraints, and low-end hardware management.
* **Published Post Content:**
> Running local multi-agent LLMs on modest hardware (CPU-only): How do you prevent resource exhaustion?
> Hi everyone,
> We're three final-year students at Epitech building Horus, a multi-agent assistant that runs entirely locally and offline. Our current challenge is hardware: keeping it usable on machines without a powerful GPU, without long setup times, excessive RAM/VRAM use or crashes.
> Where we are today, from our last beta test:
> * One tester needed over 2 hours to install. The Python dependencies alone take 21–46 min, and the download is about 25 GB.
> * On CPU only, routing a question can take around 40 s, long enough for our WebSocket connection to drop.
> 
> 
> [Models we use + the smallest machine we've tested on]
> We'd love advice from anyone experienced with:
> * CPU-only LLM inference and memory-efficient loading
> * Quantization and model choice for low-end hardware
> * GPU/CPU fallback strategies
> * Hardware detection and adaptive configuration
> * Preventing resource exhaustion during setup and execution
> 
> 
> Advice in the comments is very welcome, with no strings attached.
> **Looking for contributors:** we also have a few small, well-scoped tasks or code reviews (about 1–4 hours), for example [reviewing our hardware detection and model selection, or benchmarking a quantized model on a 16 GB RAM laptop].
> To be transparent: Horus is closed source and will be licensed to companies. Contributing is voluntary and unpaid. Before seeing any code, contributors sign a short confidentiality and contributor agreement, and the code they contribute becomes part of Horus. In return we offer thorough code reviews, full credit in the project and a professional reference on request.
> We're not sharing code or private links publicly. If this interests you, comment below or DM me with your experience in local inference, CPU optimisation or offline apps.

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
* **Published Post Content:**
> How do you keep a local multi-agent app usable on CPU-only / low-RAM machines?
> Hi everyone,
> We're three final-year students at Epitech building Horus, a multi-agent assistant that runs entirely locally and offline. Our current challenge is hardware: keeping it usable on machines without a powerful GPU, without long setup times, excessive RAM/VRAM use or crashes.
> Where we are today, from our last beta test:
> * One tester needed over 2 hours to install. The Python dependencies alone take 21–46 min, and the download is about 25 GB.
> * On CPU only, routing a question can take around 40 s, long enough for our WebSocket connection to drop.
> 
> 
> [Models we use + the smallest machine we've tested on]
> We'd love advice from anyone experienced with:
> * CPU-only LLM inference and memory-efficient loading
> * Quantization and model choice for low-end hardware
> * GPU/CPU fallback strategies
> * Hardware detection and adaptive configuration
> * Preventing resource exhaustion during setup and execution
> 
> 
> Advice in the comments is very welcome, with no strings attached.
> **Looking for contributors:** we also have a few small, well-scoped tasks or code reviews (about 1–4 hours), for example [reviewing our hardware detection and model selection, or benchmarking a quantized model on a 16 GB RAM laptop].
> To be transparent: Horus is closed source and will be licensed to companies. Contributing is voluntary and unpaid. Before seeing any code, contributors sign a short confidentiality and contributor agreement, and the code they contribute becomes part of Horus. In return we offer thorough code reviews, full credit in the project and a professional reference on request.
> We're not sharing code or private links publicly. If this interests you, comment below or DM me with your experience in local inference, CPU optimisation or offline apps.

---

### 4. Reddit: r/localaistack

* **Name + link:** Reddit - r/localaistack (https://www.reddit.com/r/LocalAIStack/comments/1wvxyjt/how_do_you_keep_a_local_multiagent_app_usable_on/)
* **Type:** Subreddit / Online Community
* **Audience:** Engineers and hobbyists focusing on building and stacking local AI components, architectures, and deployment pipelines.
* **Posting rules:** Standard etiquette regarding technical sharing and openness.
* *Date checked:* Oct 2, 2026


* **Why it fits Horus:** Directly aligns with stack optimization (Docker, runtimes, pipelines) for local AI environments.
* **Published Post Content:**
> How do you keep a local multi-agent app usable on CPU-only / low-RAM machines?
> Hi everyone,
> We're three final-year students at Epitech building Horus, a multi-agent assistant that runs entirely locally and offline. Our current challenge is hardware: keeping it usable on machines without a powerful GPU, without long setup times, excessive RAM/VRAM use or crashes.
> Where we are today, from our last beta test:
> * One tester needed over 2 hours to install. The Python dependencies alone take 21–46 min, and the download is about 25 GB.
> * On CPU only, routing a question can take around 40 s, long enough for our WebSocket connection to drop.
> 
> 
> [Models we use + the smallest machine we've tested on]
> We'd love advice from anyone experienced with:
> * CPU-only LLM inference and memory-efficient loading
> * Quantization and model choice for low-end hardware
> * GPU/CPU fallback strategies
> * Hardware detection and adaptive configuration
> * Preventing resource exhaustion during setup and execution
> 
> 
> Advice in the comments is very welcome, with no strings attached.
> **Looking for contributors:** we also have a few small, well-scoped tasks or code reviews (about 1–4 hours), for example [reviewing our hardware detection and model selection, or benchmarking a quantized model on a 16 GB RAM laptop].
> To be transparent: Horus is closed source and will be licensed to companies. Contributing is voluntary and unpaid. Before seeing any code, contributors sign a short confidentiality and contributor agreement, and the code they contribute becomes part of Horus. In return we offer thorough code reviews, full credit in the project and a professional reference on request.
> We're not sharing code or private links publicly. If this interests you, comment below or DM me with your experience in local inference, CPU optimisation or offline apps.

---

### 5. GitHub Discussions: llama.cpp

Name + link: GitHub Discussions - llama.cpp (https://github.com/ggml-org/llama.cpp/discussions/29859)

Type: Repository Q&A / Discussion Forum

Audience: Core contributors and power users specialized in C/C++ local execution, performance tuning, and CPU-bound LLM optimization.

Posting rules: Keep discussions technical, focused on the project's ecosystem or general local CPU/quantization performance. Avoid pure spam.

Date checked: Oct 2, 2026

Why it fits Horus: The absolute reference hub for developers tackling low-resource and CPU-only inference bottlenecks.

Published Post Content:

        How do you keep a local multi-agent app usable on CPU-only / low-RAM machines?

        Hi everyone,

        We're three final-year students at Epitech building Horus, a multi-agent assistant that runs entirely locally and offline. Our current challenge is hardware: keeping it usable on machines without a powerful GPU, without long setup times, excessive RAM/VRAM use or crashes.

        Where we are today, from our last beta test:

            One tester needed over 2 hours to install. The Python dependencies alone take 21–46 min, and the download is about 25 GB.

            On CPU only, routing a question can take around 40 s, long enough for our WebSocket connection to drop.

        [Models we use + the smallest machine we've tested on]

        We'd love advice from anyone experienced with:

            CPU-only LLM inference and memory-efficient loading

            Quantization and model choice for low-end hardware

            GPU/CPU fallback strategies

            Hardware detection and adaptive configuration

            Preventing resource exhaustion during setup and execution

        Advice in the comments is very welcome, with no strings attached.

        Looking for contributors: we also have a few small, well-scoped tasks or code reviews (about 1–4 hours), for example [reviewing our hardware detection and model selection, or benchmarking a quantized model on a 16 GB RAM laptop].

        To be transparent: Horus is closed source and will be licensed to companies. Contributing is voluntary and unpaid. Before seeing any code, contributors sign a short confidentiality and contributor agreement, and the code they contribute becomes part of Horus. In return we offer thorough code reviews, full credit in the project and a professional reference on request.

        We're not sharing code or private links publicly. If this interests you, comment below or DM me with your experience in local inference, CPU optimisation or offline apps.

---

### 6. Dev.to Community

Name + link: Dev.to (https://dev.to/gersonrjr/ai-can-write-code-but-can-you-understand-it-c9f)

Type: Developer Community & Blogging Platform

Audience: Software engineers across all disciplines, highly active in backend, DevOps, and practical software architecture challenges.

Posting rules: Encourage knowledge sharing and architectural discussions; transparency regarding side projects and collaboration.

Date checked: Oct 2, 2026

Why it fits Horus: Excellent platform to frame resource optimization as a core engineering challenge and attract developers who love solving deep performance bottlenecks.

Published Post Content:

        How do you keep a local multi-agent app usable on CPU-only / low-RAM machines?

        Hi everyone,

        We're three final-year students at Epitech building Horus, a multi-agent assistant that runs entirely locally and offline. Our current challenge is hardware: keeping it usable on machines without a powerful GPU, without long setup times, excessive RAM/VRAM use or crashes.

        Where we are today, from our last beta test:

            One tester needed over 2 hours to install. The Python dependencies alone take 21–46 min, and the download is about 25 GB.

            On CPU only, routing a question can take around 40 s, long enough for our WebSocket connection to drop.

        [Models we use + the smallest machine we've tested on]

        We'd love advice from anyone experienced with:

            CPU-only LLM inference and memory-efficient loading

            Quantization and model choice for low-end hardware

            GPU/CPU fallback strategies

            Hardware detection and adaptive configuration

            Preventing resource exhaustion during setup and execution

        Advice in the comments is very welcome, with no strings attached.

        Looking for contributors: we also have a few small, well-scoped tasks or code reviews (about 1–4 hours), for example [reviewing our hardware detection and model selection, or benchmarking a quantized model on a 16 GB RAM laptop].

        To be transparent: Horus is closed source and will be licensed to companies. Contributing is voluntary and unpaid. Before seeing any code, contributors sign a short confidentiality and contributor agreement, and the code they contribute becomes part of Horus. In return we offer thorough code reviews, full credit in the project and a professional reference on request.

        We're not sharing code or private links publicly. If this interests you, comment below or DM me with your experience in local inference, CPU optimisation or offline apps.

### 7. Discord: Hugging Face (#help-and-feedback & #jobs-and-collaboration)

Name + link: Discord - Hugging Face (https://discord.gg/huggingface)

Type: Discord Server

Audience: Massive global community of ML engineers, researchers, and developers discussing models, deployment, and MLOps.

Posting rules: Technical architectural questions go to #help-and-feedback; collaboration/recruitment posts go to #jobs-and-collaboration using proper tags. Avoid spam.

Date checked: Oct 2, 2026

Why it fits Horus: Perfect for engaging directly with machine learning engineers who face hardware constraints and local deployment challenges every day.

Published Post Content:

        How do you keep a local multi-agent app usable on CPU-only / low-RAM machines?

        Hi everyone,

        We're three final-year students at Epitech building Horus, a multi-agent assistant that runs entirely locally and offline. Our current challenge is hardware: keeping it usable on machines without a powerful GPU, without long setup times, excessive RAM/VRAM use or crashes.

        Where we are today, from our last beta test:

            One tester needed over 2 hours to install. The Python dependencies alone take 21–46 min, and the download is about 25 GB.

            On CPU only, routing a question can take around 40 s, long enough for our WebSocket connection to drop.

        [Models we use + the smallest machine we've tested on]

        We'd love advice from anyone experienced with:

            CPU-only LLM inference and memory-efficient loading

            Quantization and model choice for low-end hardware

            GPU/CPU fallback strategies

            Hardware detection and adaptive configuration

            Preventing resource exhaustion during setup and execution

        Advice in the comments is very welcome, with no strings attached.

        Looking for contributors: we also have a few small, well-scoped tasks or code reviews (about 1–4 hours), for example [reviewing our hardware detection and model selection, or benchmarking a quantized model on a 16 GB RAM laptop].

        To be transparent: Horus is closed source and will be licensed to companies. Contributing is voluntary and unpaid. Before seeing any code, contributors sign a short confidentiality and contributor agreement, and the code they contribute becomes part of Horus. In return we offer thorough code reviews, full credit in the project and a professional reference on request.

        We're not sharing code or private links publicly. If this interests you, comment below or DM me with your experience in local inference, CPU optimisation or offline apps.
