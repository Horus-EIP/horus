# ADR-003: Selection of FastAPI for client request's routing

**Date:** 2026-04-14
**Status:** Accepted

## Context
Because the MAS orchestrator must expose an API to integrate with a web frontend, we needed a framework that was both highly efficient and developer-friendly. We required a solution that makes it easy to define routes, automatically generate/maintain API documentation, and seamlessly implement security measures to comply with our on-premise data privacy charter. Additionally, the framework had to natively support asynchronous operations and WebSockets to enable an instant, real-time chat experience for the users.

## Decision
We selected **FastAPI** for API routing and WebSocket management inside the orchestrator and agent components.

## Consequences

**Pros:**
- **Low barrier to entry:** Very easy to understand, learn, and set up for the development team.
- **Modern and agile:** Its modern architecture allows us to build an elaborated and robust infrastructure quickly without spending hours on configuration overhead.
- **High modularity:** It gives us the flexibility to build a highly customized API tailored strictly to our specific needs, without forcing a fixed project structure.
- **Performance evidence:** Async I/O handles concurrent AI calls without thread pool exhaustion. Testing proved high efficiency with 100% of standard messages processed in `<1s` (BTP F15: 50/50).
- **Time saved:** Utilizing built-in Pydantic validation and automatic OpenAPI documentation saved an estimated 4 weeks of development time versus using Flask with manual validation.

**Cons / Accepted Risks:**
- **Scaling considerations:** While excellent for MVP and initial production, sustaining massive enterprise-level traffic requires more complex deployment tuning (e.g., multi-worker setup via Gunicorn/Uvicorn) compared to APIs built with compiled languages like Rust or Go.

## Alternatives considered
- **Django:** Rejected. While very secure and robust, its monolithic “batteries-included” architecture is too rigid for our modular microservices approach and is less suited for native WebSockets compared to FastAPI.
- **Flask:** Rejected. It is modular and simple, but lacks native, built-in asynchronous support (vital for our LLM calls and WebSockets) and requires too many third-party plugins to get automatic OpenAPI documentation and strict typing.
