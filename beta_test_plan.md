---
title:          Beta Test Plan
subtitle:       Horus Multi-Agent Orchestration System
author:         Horus Team
module:         G-EIP-700
version:        1.1
---

## **1. Project Context**

Horus AI is a self-hosted multi-agent orchestration system designed to enable secure, private, and scalable AI deployments. The platform empowers businesses to build autonomous, real-time, and modular AI workflows without relying on external cloud services.

The system operates through several interconnected components:
- **MAS (Multi-Agent System Orchestrator)**: A FastAPI-based service responsible for agent registry, conversation management, task orchestration, and user authentication
- **Agent Service**: Handles the RAG (Retrieval-Augmented Generation) pipeline, consuming tasks via RabbitMQ and providing intelligent responses grounded in uploaded documents
- **Knowledge Store**: A document management system powered by ChromaDB that allows users to upload, organize, and query documents for context-aware AI responses
- **Web Client**: A Next.js-based dashboard providing chat interface, conversation management, knowledge store UI, admin functionalities, and real-time analytics

The platform uses PostgreSQL for data persistence, Redis for caching, RabbitMQ for message queuing, and integrates comprehensive observability through Prometheus, Grafana, and Jaeger.

---

## **2. User Roles**

The following roles will be involved in beta testing.

| **Role Name** | **Description** |
|---------------|-----------------|
| Admin | An administrator with full system access who can manage users, configure system settings, register/delete agents, assign roles, view analytics, and access all resources |
| Manager | An operational manager who can create and approve tasks, execute agents, view analytics, delete agents, view task queue, and manage team operations without user administration privileges |
| User | A standard application user who can create conversations, send messages, create tasks, execute agents, delete their own conversations, and interact with the knowledge store |

---

## **3. Feature Table**

All of the listed features will be demonstrated during the beta presentation.

| **Feature ID** | **User Role** | **Feature Name** | **Short Description** |
|----------------|---------------|------------------|----------------------|
| F1 | Everyone | User Registration | A new user can create an account with username and password |
| F2 | Everyone | User Login | A user can log in to the system using their credentials and receive a JWT token |
| F3 | Admin | Create New User | An admin can create new user accounts via the admin panel with username, password, and role assignment |
| F4 | Admin | Delete User | An admin can delete existing user accounts from the system |
| F5 | Admin | Assign User Role | An admin can assign or change a user's role (admin, manager, user) via the admin panel |
| F6 | Admin | View All Users | An admin can view a list of all registered users and their roles |
| F7 | Everyone | Create Conversation | A user can create a new conversation with a custom name |
| F8 | Everyone | List Conversations | A user can view all their existing conversations via the Conversations page |
| F9 | Owner/Admin/Manager | Delete Conversation | A user can delete their own conversation; admins and managers can delete any conversation |
| F10 | Everyone | Send Message | A user can send a text message within a conversation |
| F11 | Everyone | Receive AI Response | The system returns an AI-generated response to user queries in real-time via WebSocket |
| F12 | Everyone | View Message History | A user can view the complete message history of a conversation |
| F13 | Everyone | Upload Document | A user can upload a document to the knowledge store for RAG processing |
| F14 | Everyone | List Documents | A user can view all uploaded documents in the knowledge store |
| F15 | Everyone | Delete Document | A user can delete a document from the knowledge store |
| F16 | Everyone | Query Documents | A user can query the knowledge store to retrieve relevant document excerpts |
| F17 | Admin | Register Agent | An admin can register a new agent with specific skills via the admin panel with API key generation |
| F18 | Everyone | View Registered Agents | Users can view all registered agents with their status and capabilities on the dashboard |
| F19 | Admin/Manager | Delete Agent | An admin or manager can unregister an agent from the system via the dashboard or admin panel |
| F20 | Everyone | Create Task | A user can create a new task specifying the demand and required skills |
| F21 | Manager/Admin | View Task Queue | A manager can view task queue statistics (pending, running, completed, failed, cancelled, timeout) via the Tasks page |
| F22 | Admin | Cancel Task | An admin can cancel a pending or running task via the API |
| F23 | Everyone | Receive Task Result | A user receives the task result notification upon completion via WebSocket |
| F24 | Everyone | Access Dashboard | A user can access the main dashboard with real-time system analytics graph |
| F25 | Everyone | View Analytics | Users can view real-time system analytics including active agents, running tasks, and pending tasks via a live graph on the dashboard |

---

## **4. Success Criteria**

| **Feature ID** | **Key Success Criteria** | **Indicator/Metric** | **Result** |
|----------------|-------------------------|----------------------|------------|
| F1 | A new user can successfully register with unique username and valid password | 15 registration attempts, all successful with unique usernames | Pending |
| F2 | A registered user can log in and receive a valid JWT token without errors | 30 login attempts, 0 failures related to the application | Pending |
| F3 | Admin can create users via modal form with username, password, and role selection | 10 user creations via UI, all visible in admin panel with correct roles | Pending |
| F4 | Deleted users can no longer access the system | 5 deletions, all users properly removed and blocked | Pending |
| F5 | Role changes are immediately reflected in user permissions via modal dialog | 10 role changes, all permissions updated correctly | Pending |
| F6 | Admin can view complete and accurate user list with search and filter by role | User list displays correctly with search and role filter | Pending |
| F7 | Creating a conversation adds it to the user's conversation list | 20 conversations created, all visible immediately | Pending |
| F8 | User can see all their conversations on the Conversations page with search | 15 conversation lists loaded, all correctly displayed | Pending |
| F9 | Owner/Admin/Manager can delete conversation via delete button with confirmation modal | 10 deletions by owner, 5 by admin, 0 residual data | Pending |
| F10 | Sent messages appear in the conversation within 1 second | 50 messages sent, average latency < 1s | Pending |
| F11 | AI responses are received via WebSocket within 10 seconds for simple queries | 30 queries, 95% responses under 10s | Pending |
| F12 | Complete message history loads correctly with proper ordering | 20 conversation loads, all messages in correct order | Pending |
| F13 | Document is uploaded and processed for RAG indexing successfully | 20 documents uploaded (PDF, TXT, DOCX), 0 failures | Pending |
| F14 | All uploaded documents appear in the knowledge store list with metadata | Document list reflects all uploads with title, size, date | Pending |
| F15 | Deleted documents are removed from search results | 10 deletions, 0 phantom documents in queries | Pending |
| F16 | Query returns relevant document excerpts with semantic matching | 25 queries, relevance score > 70% for known documents | Pending |
| F17 | Admin can register agents via form with name, skills, description; receives API key | 5 agent registrations with API key displayed | Pending |
| F18 | Agent list on dashboard shows status, skills, last heartbeat with auto-refresh | Agent status updates within 10s of heartbeat change | Pending |
| F19 | Admin/Manager can delete agents via delete button with confirmation modal | 3 agent deletions from dashboard, no tasks routed after | Pending |
| F20 | Created tasks are assigned to appropriate agents based on skills | 15 tasks created, 90% correctly routed | Pending |
| F21 | Task queue page displays all stats (pending, running, completed, failed, cancelled, timeout) with progress bar | Stats match backend API across 20 checks | Pending |
| F22 | Cancel task API endpoint properly cancels pending/running tasks | 5 cancellations via API, all stopped within 5 seconds | Pending |
| F23 | Task results are delivered to users via WebSocket notification | 20 task completions, all notifications received | Pending |
| F24 | Dashboard loads with real-time analytics graph and stats cards | 25 dashboard loads, graph renders correctly, < 3s load time | Pending |
| F25 | Real-time analytics graph shows active agents, running tasks, pending tasks over time | Graph updates every 10s with accurate data for 30 data points | Pending |
