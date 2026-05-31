# Demo Scripts

Scripts for running and demonstrating the Horus Multi-Agent System.

## Quick Start

```bash
# Make the script executable
chmod +x run_demo.sh

# Start the demo
./run_demo.sh

# Reset demo (clears all data)
./run_demo.sh --reset

# Stop demo
./run_demo.sh --stop
```

## Scripts

### `run_demo.sh`

Main demo runner script that:
1. Starts all Docker services
2. Waits for services to be healthy
3. Seeds demo data
4. Displays access URLs

### `seed_demo_data.py`

Python script that seeds the system with sample data:
- Demo documents in Knowledge Store
- Sample conversations
- Verifies agent connectivity

```bash
# Run standalone
python seed_demo_data.py --url http://localhost:8000 --ks-url http://localhost:8080
```

## Demo Data

The seeder creates the following sample data:

### Documents
| Document | Content |
|----------|---------|
| Q1 Financial Report | Revenue, metrics, regional performance |
| Product Roadmap 2025 | Q1-Q4 planned features |
| Customer FAQ | Common questions and answers |
| Sales Performance | Sales data and pipeline analysis |

### Conversations
- Financial Analysis Demo
- Product Research Demo
- Customer Support Demo

## Demo Queries

Try these queries in the Web Client:

1. **Financial Questions:**
   - "What was our Q1 revenue?"
   - "What is our customer acquisition cost?"
   - "How is each region performing?"

2. **Product Questions:**
   - "What's on the product roadmap for Q2?"
   - "When will mobile apps be available?"

3. **Sales Questions:**
   - "Which sales team is performing best?"
   - "What is our average deal size?"

## Access URLs

After starting the demo:

| Service | URL |
|---------|-----|
| Web Client | http://localhost:3000 |
| MAS API | http://localhost:8000 |
| API Docs | http://localhost:8000/docs |
| Knowledge Store | http://localhost:8080 |
| Grafana | http://localhost:3301 (admin/admin) |
| Prometheus | http://localhost:9090 |

## Troubleshooting

### Services won't start
```bash
# Check Docker is running
docker ps

# Check service logs
cd src/infra
docker compose logs mas
docker compose logs agent
```

### Seeding fails
```bash
# Check MAS is accessible
curl http://localhost:8000/docs

# Check Knowledge Store is accessible
curl http://localhost:8080/health
```

### No agents available
The agent service may take longer to start. Wait a minute and check:
```bash
curl http://localhost:8000/agents/ -H "Authorization: Bearer <token>"
```
