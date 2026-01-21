# MAS - Multi-Agent System

A sophisticated Multi-Agent System (MAS) built with FastAPI, featuring intelligent agent orchestration, real-time communication, and advanced LLM integration for task distribution and execution.

## 🏗️ Architecture Overview

The MAS is designed as a distributed system where multiple AI agents can be registered, managed, and orchestrated to handle various tasks. The system provides:

- **Agent Registry & Management**: Dynamic agent registration and lifecycle management
- **Task Orchestration**: Intelligent task distribution based on agent capabilities
- **Real-time Communication**: WebSocket-based chat interface for real-time interactions
- **User Management**: Authentication, authorization, and role-based access control
- **Conversation Management**: Persistent conversation history and context management
- **LLM Integration**: Local language model for intelligent task routing and processing

## 🚀 Key Features

### Agent Management
- Dynamic agent registration with skill-based categorization
- Health monitoring and status tracking via heartbeat system
- Automatic agent selection based on task requirements
- RabbitMQ-based message queuing for reliable task distribution

### Authentication & Authorization
- JWT-based authentication system
- Role-based access control (User/Admin)
- Secure password hashing with bcrypt
- Token blacklisting for secure logout

### Real-time Communication
- WebSocket support for live chat functionality
- Conversation persistence across sessions
- Multi-client support for collaborative environments
- Real-time task result streaming

### Task Processing
- Intelligent task analysis and agent selection
- Multi-step task execution with future action planning
- Context-aware conversation handling
- Comprehensive error handling and logging

### Data Management
- PostgreSQL database for persistent storage
- Redis for caching and session management
- Database migrations and initialization scripts
- Comprehensive data models for all entities

## 📁 Project Structure

```
src/services/mas/
├── agents/                     # Agent management system
│   ├── controller.py          # Agent lifecycle and heartbeat monitoring
│   ├── registry_tool_functions.py  # Core agent registry operations
│   └── routes.py              # Agent management API endpoints
├── auth/                      # Authentication system
│   ├── auth_tool_functions.py # Authentication utilities and JWT handling
│   └── routes.py              # Authentication API endpoints
├── chat/                      # Real-time communication
│   ├── chat_tool_functions.py # WebSocket management and messaging
│   └── routes.py              # Chat WebSocket endpoints
├── conversations/             # Conversation management
│   ├── conversation_tool_functions.py  # Conversation operations
│   └── routes.py              # Conversation API endpoints
├── core/                      # Core system components
│   ├── app.py                 # FastAPI application factory
│   ├── config.py              # Configuration management
│   ├── hybrid_logging.py      # Advanced logging system
│   ├── llm_setup.py           # Local LLM configuration
│   ├── logger.py              # Logging utilities
│   ├── middleware.py          # Custom middleware
│   └── rabbitmq_tool.py       # RabbitMQ connection management
├── db/                        # Database layer
│   ├── database.py            # Database connection and session management
│   ├── dependency.py          # Database dependency injection
│   ├── init_setup.py          # Database initialization
│   ├── models.py              # SQLAlchemy ORM models
│   └── redis.py               # Redis connection management
├── schemas/                   # Pydantic schemas
│   └── schemas.py             # API request/response models
├── tasks/                     # Task management system
│   ├── task_tool_functions.py # Task processing and agent selection
│   └── routes.py              # Task API endpoints
├── users/                     # User management
│   └── routes.py              # User administration endpoints
├── client_tests/              # Test clients and examples
├── tests/                     # Unit and integration tests
├── models/                    # Local LLM models storage
├── main.py                    # Application entry point
├── docker-compose.yml         # Docker orchestration
├── Dockerfile                 # Container definition
└── requirements.txt           # Python dependencies
```

## 🛠️ Technology Stack

### Backend Framework
- **FastAPI**: Modern, fast web framework for building APIs
- **Uvicorn**: ASGI server for high-performance async applications
- **Pydantic**: Data validation using Python type annotations

### Database & Storage
- **PostgreSQL**: Primary database for persistent data storage
- **Redis**: In-memory data store for caching and sessions
- **SQLAlchemy**: Python SQL toolkit and ORM

### Message Queue
- **RabbitMQ**: Message broker for reliable inter-agent communication
- **Pika**: Python client for RabbitMQ

### AI & Machine Learning
- **Transformers**: Hugging Face transformers library
- **PyTorch**: Deep learning framework
- **BitsAndBytes**: 4-bit quantization for efficient model loading
- **Accelerate**: Distributed training and inference

### Authentication & Security
- **JWT (JSON Web Tokens)**: Stateless authentication
- **Passlib**: Password hashing utilities
- **bcrypt**: Secure password hashing

### Communication
- **WebSockets**: Real-time bidirectional communication
- **HTTPX**: Modern HTTP client for testing

### Development & Testing
- **pytest**: Testing framework
- **pytest-asyncio**: Async testing support
- **pytest-cov**: Test coverage reporting

## 🐳 Docker Setup

The application is fully containerized with Docker Compose for easy deployment:

```yaml
services:
  - web: FastAPI application server
  - rabbitmq: Message broker
  - postgres: Primary database
  - redis: Cache and session store
  - pgadmin: Database administration interface
```

### Quick Start with Docker

1. **Clone and navigate to the project:**
   ```bash
   cd /path/to/project
   ```

2. **Set up environment variables:**
   ```bash
   cp .env.example .env
   # Edit .env with your configuration
   ```

3. **Start all services:**
   ```bash
   docker-compose up -d
   ```

4. **Access the application:**
   - API Documentation: http://localhost:8000/docs
   - PGAdmin: http://localhost:5050
   - RabbitMQ Management: http://localhost:15672

## ⚙️ Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `POSTGRES_USER` | PostgreSQL username | admin |
| `POSTGRES_PASSWORD` | PostgreSQL password | secret |
| `POSTGRES_DB` | Database name | orchestrator_db |
| `DB_PORT` | Database port | 5432 |
| `SUPER_USER_USERNAME` | Initial admin username | admin |
| `SUPER_USER_PASSWORD` | Initial admin password | secret |
| `JWT_SECRET_KEY` | JWT signing secret | your_secret_key |
| `JWT_ALGORITHM` | JWT algorithm | HS256 |
| `REDIS_PORT` | Redis port | 6379 |
| `REDIS_PASSWORD` | Redis password | secret |

### Local LLM Configuration

The system supports local LLM deployment with automatic model detection and 4-bit quantization for efficient inference. Models are stored in the `models/` directory.

## 📚 API Documentation

### Authentication Endpoints
- `POST /auth/register` - Register a new user account
- `POST /auth/token` - Authenticate and get access token
- `POST /auth/logout` - Logout and blacklist token

### Agent Management
- `POST /agents/register` - Register a new agent
- `DELETE /agents/unregister/{agent_id}` - Remove an agent
- `GET /agents/details/{id}` - Get agent details
- `GET /agents/details/` - List all agents
- `POST /agents/heartbeat/{agent_id}` - Agent heartbeat signal

### Conversation Management
- `POST /conversations/create-conversation/` - Create new conversation
- `GET /conversations/get_history/{chat_id}` - Get conversation history
- `DELETE /conversations/delete-conversation/{chat_id}` - Delete conversation
- `GET /conversations/get-conversations/` - List user conversations

### Task Management
- `POST /tasks/new_task/` - Create and dispatch new task
- `POST /tasks/task-result/` - Submit task result from agent

### User Management (Admin Only)
- `POST /users/make-admin/{user_id}` - Grant admin rights
- `POST /users/remove-admin-grant/{user_id}` - Revoke admin rights

### Real-time Communication
- `WS /chat/{conversation_id}/` - WebSocket endpoint for real-time chat

## 🧪 Testing

The project includes comprehensive testing suite:

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=. --cov-report=html

# Run specific test categories
pytest tests/test_auth.py
pytest tests/test_agents.py
```

### Test Clients

The `client_tests/` directory contains example clients demonstrating system usage:

- `client.py` - Basic HTTP API testing
- `client_multiple_agents.py` - Multi-agent orchestration example
- `client_test_user_rights.py` - User permission testing
- `client_single_agent_rooting.py` - Single agent task routing

## 🔧 Development

### Local Development Setup

1. **Create virtual environment:**
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Set up databases:**
   ```bash
   # Start PostgreSQL and Redis (via Docker or locally)
   docker-compose up -d postgres redis
   ```

4. **Run the application:**
   ```bash
   uvicorn main:app --reload --host 0.0.0.0 --port 8000
   ```

### Code Quality

The project follows modern Python development practices:

- **Type hints** throughout the codebase
- **Async/await** for I/O operations
- **Pydantic models** for data validation
- **Comprehensive error handling**
- **Structured logging** with rich formatting
- **Security best practices**

## 🔍 Monitoring & Logging

The system includes advanced logging capabilities:

- **Structured logging** with JSON formatting
- **Color-coded console output** for development
- **File rotation** and compression
- **Error tracking** with stack traces
- **Performance monitoring**
- **Request/response logging**

Log levels and outputs are configurable through environment variables and the logging configuration system.

## 🚀 Deployment

### Production Deployment

1. **Configure environment variables** for production
2. **Set up SSL/TLS** certificates
3. **Configure reverse proxy** (nginx recommended)
4. **Set up monitoring** and log aggregation
5. **Configure backup strategies** for PostgreSQL

### Scaling Considerations

- **Horizontal scaling**: Multiple FastAPI instances behind load balancer
- **Database scaling**: Read replicas and connection pooling
- **Message queue**: RabbitMQ clustering
- **Caching**: Redis clustering for high availability

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

### Development Guidelines

- Follow PEP 8 style guide
- Add type hints to all functions
- Write comprehensive tests for new features
- Update documentation for API changes
- Use conventional commit messages

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- FastAPI team for the excellent web framework
- Hugging Face for the transformers library
- The open-source community for various dependencies

---

For more detailed information about specific components, please refer to the inline documentation within each module.