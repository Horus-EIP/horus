# 🧠 Horus Project

Welcome to Horus AI – a self-hosted multi-agent orchestration system that enables secure, private, and scalable AI deployments.

## 🌟 Project Goal

Empower businesses to build autonomous, real-time, and modular AI workflows without relying on external cloud services.

## 📁 Repository Structure

- `src/infra`: Docker Compose orchestration and infrastructure
- `src/services/mas`: FastAPI orchestrator (agent registry, conversations, chat, tasks)
- `src/services/agent`: FastAPI agent (RAG pipeline, RabbitMQ consumer, heartbeats)
- `src/services/knowledge-store`: FastAPI + Chroma (upload/list/delete/query documents)
- `src/services/web-client`: Next.js dashboard (chat, dashboard, knowledge store UI)
- `docs/`: Markdown documentation
- `.github/`: GitHub Actions and CI/CD

## 🚀 Getting Started

```bash
cd src/infra
docker compose up --build
```

## 👥 Contribution

All work must start as an issue. Follow commit conventions and submit pull requests with 2 reviews.

### 📚 Contribution Resources

- [🧾 Git Commit Convention](docs/commit_convention.md)
- [📌 Issue and Task Management Guide](docs/issues.md)
- [🔁 Contribution Workflow Rules](docs/workflow.md)
- [🤝 Contributing Guide](CONTRIBUTING.md)
