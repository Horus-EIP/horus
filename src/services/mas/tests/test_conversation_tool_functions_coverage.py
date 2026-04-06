from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.exc import SQLAlchemyError

from conversations.conversation_tool_functions import (add_messages,
                                                       get_all_conversations,
                                                       get_conversations,
                                                       get_full_history,
                                                       get_history)
from db.models import Conversations, Messages


class TestConversationToolFunctionsCoverage:

    @pytest.fixture
    def mock_db(self):
        return MagicMock()

    # --- get_history ---

    def test_get_history_standalone_db_creation(self):
        """Test get_history creates its own session if db is None."""
        with patch(
            "conversations.conversation_tool_functions.SessionLocal"
        ) as MockSession:
            mock_session = MockSession.return_value
            # Setup mock query chain
            mock_session.query.return_value.filter.return_value.first.return_value = (
                None
            )

            get_history(1, db=None)

            MockSession.assert_called_once()
            mock_session.close.assert_called_once()

    def test_get_history_sqlalchemy_error(self, mock_db):
        """Test get_history handles SQLAlchemyError gracefully."""
        mock_db.query.side_effect = SQLAlchemyError("DB Error")

        result = get_history(1, db=mock_db)

        assert result == []

    def test_get_history_generic_exception(self, mock_db):
        """Test get_history handles generic Exception gracefully."""
        mock_db.query.side_effect = Exception("Generic Error")

        result = get_history(1, db=mock_db)

        assert result == []

    # --- get_full_history ---

    def test_get_full_history_standalone(self):
        """Test get_full_history creates session if None."""
        with patch(
            "conversations.conversation_tool_functions.get_history"
        ) as mock_get_history:
            with patch(
                "conversations.conversation_tool_functions.SessionLocal"
            ) as MockSession:
                get_full_history(1, db=None)

                MockSession.assert_called_once()
                mock_get_history.assert_called_once()

    # --- get_conversations ---

    def test_get_conversations_standalone_db_creation(self):
        """Test get_conversations creates its own session if db is None."""
        with patch(
            "conversations.conversation_tool_functions.SessionLocal"
        ) as MockSession:
            mock_session = MockSession.return_value
            mock_session.query.return_value.filter.return_value.order_by.return_value.all.return_value = (
                []
            )

            get_conversations("user", db=None)

            MockSession.assert_called_once()
            mock_session.close.assert_called_once()

    def test_get_conversations_sqlalchemy_error(self, mock_db):
        """Test get_conversations handles SQLAlchemyError gracefully."""
        mock_db.query.side_effect = SQLAlchemyError("DB Error")

        result = get_conversations("user", db=mock_db)

        assert result == []

    def test_get_conversations_generic_exception(self, mock_db):
        """Test get_conversations handles generic Exception gracefully."""
        mock_db.query.side_effect = Exception("Generic Error")

        result = get_conversations("user", db=mock_db)

        assert result == []

    # --- add_messages ---

    def test_add_messages_standalone_db_creation(self):
        """Test add_messages creates its own session if db is None."""
        with patch(
            "conversations.conversation_tool_functions.SessionLocal"
        ) as MockSession:
            mock_session = MockSession.return_value
            # Mock conversation check
            mock_session.query.return_value.filter.return_value.first.return_value = (
                MagicMock()
            )

            add_messages("user", "msg", 1, db=None)

            MockSession.assert_called_once()
            mock_session.close.assert_called_once()

    def test_add_messages_conversation_not_found(self, mock_db):
        """Test add_messages returns None if conversation doesn't exist."""
        mock_db.query.return_value.filter.return_value.first.return_value = None

        result = add_messages("user", "msg", 1, db=mock_db)

        assert result is None

    def test_add_messages_sqlalchemy_error_rollback(self, mock_db):
        """Test add_messages handles SQLAlchemyError and rolls back."""
        # Mock conversation exists
        mock_db.query.return_value.filter.return_value.first.return_value = MagicMock()

        # Mock savepoint
        mock_savepoint = MagicMock()
        mock_db.begin_nested.return_value = mock_savepoint

        # Raise error on add
        mock_db.add.side_effect = SQLAlchemyError("DB Error")

        result = add_messages("user", "msg", 1, db=mock_db)

        assert result is None
        mock_savepoint.rollback.assert_called()
        mock_db.rollback.assert_called()

    def test_add_messages_generic_exception_rollback(self, mock_db):
        """Test add_messages handles generic Exception and rolls back."""
        # Mock conversation exists
        mock_db.query.return_value.filter.return_value.first.return_value = MagicMock()

        # Raise error on begin_nested
        mock_db.begin_nested.side_effect = Exception("Generic Error")

        result = add_messages("user", "msg", 1, db=mock_db)

        assert result is None
        mock_db.rollback.assert_called()

    # --- get_all_conversations ---

    def test_get_all_conversations_success(self, mock_db):
        """Test get_all_conversations retrieves all conversations."""
        # Use spec=Conversations to ensure the mock behaves like the real class
        mock_conv = MagicMock(spec=Conversations)
        mock_conv.id = 1
        mock_conv.name = "Chat"
        mock_conv.owner_username = "user"
        mock_conv.created_at = MagicMock()
        mock_conv.created_at.isoformat.return_value = "2025-01-01"
        mock_conv.modified_at = MagicMock()
        mock_conv.modified_at.isoformat.return_value = "2025-01-01"

        mock_db.query.return_value.order_by.return_value.all.return_value = [mock_conv]

        result = get_all_conversations(db=mock_db)

        assert len(result) == 1
        assert result[0]["id"] == 1
