"""
Tests for Pydantic schemas
"""

import pytest
from pydantic import ValidationError

from schemas.schemas import (
    PASSWORD_POLICY,
    ConversationCreation,
    CreateUserRequest,
    RegistrationForm,
    TaskForm,
    TaskResultForm,
    Token,
    UserPasswordModification,
)


class TestRegistrationForm:
    """Test the RegistrationForm schema."""

    def test_registration_form_valid_data(self):
        """Test RegistrationForm with valid data."""
        data = {
            "name": "TestAgent",
            "skills": ["python", "data_analysis", "ml"],
            "description": "A test agent for data processing",
        }

        form = RegistrationForm(**data)

        assert form.name == "TestAgent"
        assert form.skills == ["python", "data_analysis", "ml"]
        assert form.description == "A test agent for data processing"

    def test_registration_form_empty_skills(self):
        """Test RegistrationForm with empty skills list."""
        data = {"name": "TestAgent", "skills": [], "description": "A test agent"}

        form = RegistrationForm(**data)

        assert form.skills == []

    def test_registration_form_missing_name(self):
        """Test RegistrationForm validation fails without name."""
        data = {"skills": ["python"], "description": "A test agent"}

        with pytest.raises(ValidationError) as exc_info:
            RegistrationForm(**data)

        errors = exc_info.value.errors()
        assert any(error["loc"] == ("name",) for error in errors)
        assert any(error["type"] == "missing" for error in errors)

    def test_registration_form_missing_skills(self):
        """Test RegistrationForm validation fails without skills."""
        data = {"name": "TestAgent", "description": "A test agent"}

        with pytest.raises(ValidationError) as exc_info:
            RegistrationForm(**data)

        errors = exc_info.value.errors()
        assert any(error["loc"] == ("skills",) for error in errors)

    def test_registration_form_missing_description(self):
        """Test RegistrationForm validation fails without description."""
        data = {"name": "TestAgent", "skills": ["python"]}

        with pytest.raises(ValidationError) as exc_info:
            RegistrationForm(**data)

        errors = exc_info.value.errors()
        assert any(error["loc"] == ("description",) for error in errors)

    def test_registration_form_invalid_skills_type(self):
        """Test RegistrationForm validation fails with invalid skills type."""
        data = {
            "name": "TestAgent",
            "skills": "not_a_list",
            "description": "A test agent",
        }

        with pytest.raises(ValidationError) as exc_info:
            RegistrationForm(**data)

        errors = exc_info.value.errors()
        assert any(error["loc"] == ("skills",) for error in errors)

    def test_registration_form_dict_export(self):
        """Test RegistrationForm can be exported to dict."""
        data = {
            "name": "TestAgent",
            "skills": ["python", "ml"],
            "description": "A test agent",
        }

        form = RegistrationForm(**data)
        result_dict = form.model_dump()

        # Add default type field to expected data
        expected = data.copy()
        expected["type"] = None

        assert result_dict == expected

    def test_registration_form_json_export(self):
        """Test RegistrationForm can be exported to JSON."""
        data = {
            "name": "TestAgent",
            "skills": ["python"],
            "description": "A test agent",
        }

        form = RegistrationForm(**data)
        json_str = form.model_dump_json()

        assert '"name":"TestAgent"' in json_str
        assert '"skills":["python"]' in json_str


class TestTaskForm:
    """Test the TaskForm schema."""

    def test_task_form_valid_data(self):
        """Test TaskForm with valid data."""
        data = {
            "demand": "Process this data",
            "conversation_id": 123,
            "skills_required": ["data_processing", "python"],
        }

        form = TaskForm(**data)

        assert form.demand == "Process this data"
        assert form.conversation_id == 123
        assert form.skills_required == ["data_processing", "python"]

    def test_task_form_empty_skills_required(self):
        """Test TaskForm with empty skills_required list."""
        data = {
            "demand": "Simple task",
            "conversation_id": 123,
            "skills_required": [],
        }

        form = TaskForm(**data)

        assert form.skills_required == []

    def test_task_form_missing_demand(self):
        """Test TaskForm validation fails without demand."""
        data = {"conversation_id": "conv_123", "skills_required": ["python"]}

        with pytest.raises(ValidationError) as exc_info:
            TaskForm(**data)

        errors = exc_info.value.errors()
        assert any(error["loc"] == ("demand",) for error in errors)

    def test_task_form_accepts_missing_conversation_id(self):
        """conversation_id is Optional[int] = None — should NOT raise."""
        data = {"demand": "Process this data", "skills_required": ["python"]}
        form = TaskForm(**data)
        assert form.conversation_id is None

    def test_task_form_missing_skills_required(self):
        """Test TaskForm validation fails without skills_required."""
        data = {"demand": "Process this data", "conversation_id": "conv_123"}

        with pytest.raises(ValidationError) as exc_info:
            TaskForm(**data)

        errors = exc_info.value.errors()
        assert any(error["loc"] == ("skills_required",) for error in errors)

    def test_task_form_invalid_skills_required_type(self):
        """Test TaskForm validation fails with invalid skills_required type."""
        data = {
            "demand": "Process this data",
            "conversation_id": "conv_123",
            "skills_required": "not_a_list",
        }

        with pytest.raises(ValidationError) as exc_info:
            TaskForm(**data)

        errors = exc_info.value.errors()
        assert any(error["loc"] == ("skills_required",) for error in errors)


class TestTaskResultForm:
    """Test the TaskResultForm schema."""

    def test_task_result_form_valid_data(self):
        """Test TaskResultForm with valid data."""
        data = {
            "task_id": "task_001",
            "result": "Task completed successfully",
            "conversation_id": "conv_123",
            "agent_id": "agent_456",
        }

        form = TaskResultForm(**data)

        assert form.task_id == "task_001"
        assert form.result == "Task completed successfully"
        assert form.conversation_id == "conv_123"
        assert form.agent_id == "agent_456"

    def test_task_result_form_missing_task_id(self):
        """Test TaskResultForm validation fails without task_id."""
        data = {
            "result": "Task completed",
            "conversation_id": "conv_123",
            "agent_id": "agent_456",
        }

        with pytest.raises(ValidationError) as exc_info:
            TaskResultForm(**data)

        errors = exc_info.value.errors()
        assert any(error["loc"] == ("task_id",) for error in errors)

    def test_task_result_form_missing_result(self):
        """Test TaskResultForm validation fails without result."""
        data = {
            "task_id": "task_001",
            "conversation_id": "conv_123",
            "agent_id": "agent_456",
        }

        with pytest.raises(ValidationError) as exc_info:
            TaskResultForm(**data)

        errors = exc_info.value.errors()
        assert any(error["loc"] == ("result",) for error in errors)

    def test_task_result_form_accepts_missing_conversation_id(self):
        """conversation_id is Optional[str] = None — should NOT raise."""
        data = {
            "task_id": "task_001",
            "result": "Task completed",
            "agent_id": "agent_456",
        }
        form = TaskResultForm(**data)
        assert form.conversation_id is None
        return
        # (kept for diff continuity — the rest of the original block is dead)
        with pytest.raises(ValidationError) as exc_info:
            TaskResultForm(**data)

        errors = exc_info.value.errors()
        assert any(error["loc"] == ("conversation_id",) for error in errors)

    def test_task_result_form_missing_agent_id(self):
        """Test TaskResultForm validation fails without agent_id."""
        data = {
            "task_id": "task_001",
            "result": "Task completed",
            "conversation_id": "conv_123",
        }

        with pytest.raises(ValidationError) as exc_info:
            TaskResultForm(**data)

        errors = exc_info.value.errors()
        assert any(error["loc"] == ("agent_id",) for error in errors)


class TestCreateUserRequest:
    """Test the CreateUserRequest schema."""

    def test_create_user_request_valid_data(self):
        """Test CreateUserRequest with valid data."""
        data = {"username": "testuser", "password": "Secure#Pass123"}

        request = CreateUserRequest(**data)

        assert request.username == "testuser"
        assert request.password == "Secure#Pass123"

    def test_create_user_request_missing_username(self):
        """Test CreateUserRequest validation fails without username."""
        data = {"password": "Secure#Pass123"}

        with pytest.raises(ValidationError) as exc_info:
            CreateUserRequest(**data)

        errors = exc_info.value.errors()
        assert any(error["loc"] == ("username",) for error in errors)

    def test_create_user_request_missing_password(self):
        """Test CreateUserRequest validation fails without password."""
        data = {"username": "testuser"}

        with pytest.raises(ValidationError) as exc_info:
            CreateUserRequest(**data)

        errors = exc_info.value.errors()
        assert any(error["loc"] == ("password",) for error in errors)

    def test_create_user_request_empty_username(self):
        """Test CreateUserRequest with empty username."""
        data = {"username": "", "password": "Secure#Pass123"}

        # Empty string should still be valid (business logic can validate this)
        request = CreateUserRequest(**data)
        assert request.username == ""

    def test_create_user_request_empty_password(self):
        """Test CreateUserRequest rejects an empty password."""
        data = {"username": "testuser", "password": ""}

        with pytest.raises(ValidationError) as exc_info:
            CreateUserRequest(**data)
        assert any(error["loc"] == ("password",) for error in exc_info.value.errors())

    def test_create_user_request_rejects_weak_passwords(self):
        for weak in ("Short1!", "alllowercase1!", "ALLUPPERCASE1!", "NoDigitsHere!", "NoSpecial123x"):
            with pytest.raises(ValidationError) as exc_info:
                CreateUserRequest(username="testuser", password=weak)
            assert any(error["loc"] == ("password",) for error in exc_info.value.errors())

    def test_create_user_request_policy_message_is_readable(self):
        with pytest.raises(ValidationError) as exc_info:
            CreateUserRequest(username="testuser", password="short")
        assert exc_info.value.errors()[0]["msg"] == PASSWORD_POLICY


class TestUserPasswordModificationPolicy:
    def test_new_password_must_meet_the_policy(self):
        with pytest.raises(ValidationError):
            UserPasswordModification(old_password="x", new_password="weak")

    def test_old_password_is_not_policed(self):
        m = UserPasswordModification(old_password="x", new_password="New#Secure2026")
        assert m.old_password == "x"


class TestToken:
    """Test the Token schema."""

    def test_token_valid_data(self):
        """Test Token with valid data."""
        data = {
            "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.test",
            "token_type": "bearer",
        }

        token = Token(**data)

        assert token.access_token == "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.test"
        assert token.token_type == "bearer"

    def test_token_missing_access_token(self):
        """Test Token validation fails without access_token."""
        data = {"token_type": "bearer"}

        with pytest.raises(ValidationError) as exc_info:
            Token(**data)

        errors = exc_info.value.errors()
        assert any(error["loc"] == ("access_token",) for error in errors)

    def test_token_missing_token_type(self):
        """Test Token validation fails without token_type."""
        data = {"access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.test"}

        with pytest.raises(ValidationError) as exc_info:
            Token(**data)

        errors = exc_info.value.errors()
        assert any(error["loc"] == ("token_type",) for error in errors)

    def test_token_different_token_types(self):
        """Test Token with different token types."""
        token_types = ["bearer", "Bearer", "JWT", "Basic"]

        for token_type in token_types:
            data = {"access_token": "test_token", "token_type": token_type}

            token = Token(**data)
            assert token.token_type == token_type


class TestConversationCreation:
    """Test the ConversationCreation schema."""

    def test_conversation_creation_valid_data(self):
        """Test ConversationCreation with valid data."""
        data = {"name": "My New Conversation"}

        conversation = ConversationCreation(**data)

        assert conversation.name == "My New Conversation"

    def test_conversation_creation_missing_name(self):
        """Test ConversationCreation validation fails without name."""
        data = {}

        with pytest.raises(ValidationError) as exc_info:
            ConversationCreation(**data)

        errors = exc_info.value.errors()
        assert any(error["loc"] == ("name",) for error in errors)

    def test_conversation_creation_empty_name(self):
        """Test ConversationCreation with empty name."""
        data = {"name": ""}

        # Empty string should still be valid
        conversation = ConversationCreation(**data)
        assert conversation.name == ""

    def test_conversation_creation_long_name(self):
        """Test ConversationCreation with long name."""
        long_name = "A" * 1000  # Very long name
        data = {"name": long_name}

        conversation = ConversationCreation(**data)
        assert conversation.name == long_name

    def test_conversation_creation_special_characters(self):
        """Test ConversationCreation with special characters in name."""
        special_name = "Conversation #1 - Test & Demo (2024)"
        data = {"name": special_name}

        conversation = ConversationCreation(**data)
        assert conversation.name == special_name


class TestSchemaInheritance:
    """Test that all schemas inherit from BaseModel correctly."""

    def test_all_schemas_inherit_from_basemodel(self):
        """Test that all schemas inherit from Pydantic BaseModel."""
        from pydantic import BaseModel

        schemas = [
            RegistrationForm,
            TaskForm,
            TaskResultForm,
            CreateUserRequest,
            Token,
            ConversationCreation,
        ]

        for schema in schemas:
            assert issubclass(schema, BaseModel)

    def test_schemas_have_model_methods(self):
        """Test that schemas have Pydantic model methods."""
        # Test with a simple schema
        data = {"name": "Test"}
        conversation = ConversationCreation(**data)

        # Verify common Pydantic methods exist
        assert hasattr(conversation, "model_dump")
        assert hasattr(conversation, "model_dump_json")
        assert hasattr(conversation, "model_validate")
        assert hasattr(ConversationCreation, "model_fields")


class TestSchemaJSONSerialization:
    """Test JSON serialization and deserialization of schemas."""

    def test_registration_form_json_roundtrip(self):
        """Test RegistrationForm JSON serialization roundtrip."""
        original_data = {
            "name": "TestAgent",
            "skills": ["python", "ml"],
            "description": "A test agent",
        }

        # Create form and serialize to JSON
        form = RegistrationForm(**original_data)
        json_str = form.model_dump_json()

        # Deserialize back from JSON
        import json

        parsed_data = json.loads(json_str)
        new_form = RegistrationForm(**parsed_data)

        # Verify data integrity
        assert new_form.name == original_data["name"]
        assert new_form.skills == original_data["skills"]
        assert new_form.description == original_data["description"]

    def test_task_result_form_complex_json(self):
        """Test TaskResultForm with complex data."""
        complex_data = {
            "task_id": "task_001",
            "result": "Complex task completed",
            "conversation_id": "conv_123",
            "agent_id": "agent_456",
        }

        form = TaskResultForm(**complex_data)

        # Verify data is preserved
        assert form.task_id == "task_001"
        assert form.result == "Complex task completed"
        assert form.conversation_id == "conv_123"
        assert form.agent_id == "agent_456"


class TestSchemaValidationEdgeCases:
    """Test edge cases in schema validation."""

    def test_schema_with_none_values(self):
        """Test schemas behavior with None values where not allowed."""
        # None values should cause validation errors for required fields

        with pytest.raises(ValidationError):
            RegistrationForm(name=None, skills=[], description="test")

        with pytest.raises(ValidationError):
            TaskForm(demand=None, conversation_id="123", skills_required=[])

        with pytest.raises(ValidationError):
            Token(access_token=None, token_type="bearer")

    def test_schema_with_extra_fields(self):
        """Test schemas behavior with extra fields."""
        # By default, Pydantic should ignore extra fields
        data = {
            "name": "TestAgent",
            "skills": ["python"],
            "description": "test",
            "extra_field": "should_be_ignored",
        }

        form = RegistrationForm(**data)

        # Extra field should be ignored
        assert not hasattr(form, "extra_field")
        assert form.name == "TestAgent"

    def test_schema_field_types_coercion(self):
        """Test type coercion in schemas."""
        # Test that Pydantic v2 is strict with types

        # Integer conversation_id should cause validation error in Pydantic v2
        # But we changed the schema to accept int, so we test with something invalid, like a dict
        data = {
            "demand": "test",
            "conversation_id": {"id": 123},  # dict instead of int
            "skills_required": ["python"],
        }

        with pytest.raises(ValidationError) as exc_info:
            TaskForm(**data)

        # Also test with string that is not a valid int
        data_str = {
            "demand": "test",
            "conversation_id": "invalid_int",
            "skills_required": ["python"],
        }
        with pytest.raises(ValidationError):
            TaskForm(**data_str)
        errors = exc_info.value.errors()
        assert any(error["loc"] == ("conversation_id",) for error in errors)
        assert any(error["type"] == "int_type" for error in errors)
