"""
Pydantic Data Models and Schemas

This module defines the Pydantic models used for API request/response validation
and serialization throughout the MAS application. These schemas ensure data
integrity and provide automatic API documentation.

Key Features:
- Automatic request/response validation
- JSON serialization/deserialization
- Type safety and IDE support
- Automatic OpenAPI/Swagger documentation generation
- Data transformation and validation rules

Schema Categories:
- Agent Management: Models for agent registration and configuration
- Task Management: Models for task creation, execution, and results
- User Management: Models for user authentication and registration
- Authentication: Models for JWT tokens and login credentials
- Conversation Management: Models for chat and conversation operations

All models inherit from Pydantic BaseModel, providing:
- Automatic validation of incoming data
- Type conversion when possible
- Clear error messages for validation failures
- JSON Schema generation for API documentation
"""

from typing import Optional

from pydantic import BaseModel

from auth.permissions import Role
from db.models import AgentTypes


class RegistrationForm(BaseModel):
    """
    Schema for agent registration requests.

    Used when registering new agents in the multi-agent system.
    Each agent must have a unique name and specify their capabilities.

    Attributes:
        name (str): Unique identifier/name for the agent
        skills (list[str]): List of capabilities/skills the agent possesses
        description (str): Human-readable description of the agent's purpose

    Example:
        {
            "name": "Summarizer Agent",
            "skills": ["nlp", "text_summarization", "content_analysis"],
            "description": "Specialized agent for text summarization and content analysis"
        }
    """

    name: str
    skills: list[str]
    description: str
    type: Optional[AgentTypes] = None


class TaskForm(BaseModel):
    """
    Schema for task creation and assignment requests.

    Used when creating new tasks to be assigned to appropriate agents.
    The system uses the skills_required to match with suitable agents.

    Attributes:
        demand (str): The task description or user request
        conversation_id (int): UUID of the conversation this task belongs to
        skills_required (list[str]): Skills needed to complete this task

    Example:
        {
            "demand": "Summarize this document and extract key points",
            "conversation_id": 123,
            "skills_required": ["nlp", "summarization"]
        }
    """

    demand: str
    conversation_id: int
    skills_required: list[str]


class TaskResultForm(BaseModel):
    """
    Schema for task result submission from agents.

    Used when agents submit completed task results back to the system.
    Includes conversation context and potential follow-up actions.

    Attributes:
        result (str): The completed task result/response
        conversation_id (str): UUID of the conversation this result belongs to
        agent_id (str): UUID of the agent that completed the task
        history (list): Conversation history for context
        future_actions (list): Planned follow-up actions/tasks

    Example:
        {
            "result": "Document summary: Key points include...",
            "conversation_id": "123e4567-e89b-12d3-a456-426614174000",
            "agent_id": "987fcdeb-51a2-43d1-b456-426614174000",
            "history": [{"role": "user", "message": "Please summarize this"}],
            "future_actions": []
        }
    """

    result: str
    conversation_id: str
    agent_id: str
    task_id: str


class CreateUserRequest(BaseModel):
    """
    Schema for user registration requests.

    Used when creating new user accounts in the system.
    Passwords are automatically hashed before storage.

    Attributes:
        username (str): Unique username for the account
        password (str): Plain text password (will be hashed automatically)

    Security Notes:
        - Username must be unique across the system
        - Password will be hashed using bcrypt before database storage
        - Original password is never stored in plaintext

    Example:
        {
            "username": "newuser123",
            "password": "secure_password_here"
        }
    """

    username: str
    password: str


class Token(BaseModel):
    """
    Schema for JWT authentication token responses.

    Returned after successful authentication to provide access credentials.
    Used for all subsequent authenticated API requests.

    Attributes:
        access_token (str): JWT token string for authentication
        token_type (str): Type of token, always "bearer" for JWT

    Usage:
        Include in Authorization header as: "Bearer {access_token}"

    Example:
        {
            "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
            "token_type": "bearer"
        }
    """

    access_token: str
    token_type: str


class ConversationCreation(BaseModel):
    """
    Schema for conversation creation requests.

    Used when creating new chat conversations in the system.
    Each conversation requires a name for identification.

    Attributes:
        name (str): Human-readable name/title for the conversation

    Example:
        {
            "name": "Technical Support Chat"
        }
    """

    name: str


class UserPasswordModification(BaseModel):
    old_password: str
    new_password: str


class UpdateRole(BaseModel):
    user_id: str
    new_role: Role


class SubTask(BaseModel):
    id: str
    agent_type: str
    description: str
    depends_on: list[str] = []
    status: str


class CollaborativeTask(BaseModel):
    sub_tasks: list[SubTask]
