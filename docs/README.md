# Horus AI Documentation

## Getting Started

- [Developer Onboarding](getting-started/onboarding.md)
- [Configuration Reference](getting-started/configuration.md)
- [Troubleshooting](getting-started/troubleshooting.md)

## Architecture

- [Architecture Overview](architecture/overview.md)
- [Data Model](architecture/data-model.md)

## API Reference

- [MAS API](api/mas-api.md)
- [Knowledge Store API](api/knowledge-store-api.md)
- [WebSocket API](api/websocket-api.md)

## Operations

- [Deployment](operations/deployment.md)
- [Monitoring and Observability](operations/monitoring.md)
- [Secrets Management](operations/secrets-management.md)
- [Environment Matrix](operations/environment-matrix.md)

## Contributing

- [Workflow](contributing/workflow.md)
- [Commit Convention](contributing/commit-convention.md)
- [Testing Policy](contributing/testing-policy.md)
- [Known Issues](contributing/issues.md)

## Security

- [RBAC (Role-Based Access Control)](security/rbac.md)
- [Security Audit](security/security-audit.md)

## Compliance

- [Architecture Fiche](compliance/architecture_fiche.md)
- [Data Protection](compliance/data_protection.md)
- [Telemetry](compliance/telemetry.md)

## Archive

Sprint plans and older documents are preserved under the `docs/archive/` directory (not included in the MkDocs navigation above).

---

## Generating Documentation

Run `scripts/generate_docs.sh` from the repo root to build browsable HTML
documentation from all sources (Python docstrings, TypeScript TSDoc, and
Markdown docs). See the script header for prerequisites.
