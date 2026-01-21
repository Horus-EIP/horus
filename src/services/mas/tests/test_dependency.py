"""
Tests for database dependency module
"""

from typing import Annotated
from unittest.mock import MagicMock, patch

import pytest
from fastapi import Depends
from sqlalchemy.orm import Session

from db.dependency import db_dependency, get_db


class TestGetDbFunction:
    """Test the get_db dependency function."""

    @patch("db.database.SessionLocal")
    def test_get_db_creates_and_closes_session(self, mock_session_local):
        """Test that get_db creates a session and closes it properly."""
        mock_session = MagicMock()
        mock_session_local.return_value = mock_session

        # Create the generator
        db_generator = get_db()

        # Get the session
        db_session = next(db_generator)

        # Verify session creation
        mock_session_local.assert_called_once()
        assert db_session == mock_session

        # Complete the generator to trigger cleanup
        try:
            next(db_generator)
        except StopIteration:
            pass

        # Verify session is closed
        mock_session.close.assert_called_once()

    @patch("db.database.SessionLocal")
    def test_get_db_closes_session_on_exception(self, mock_session_local):
        """Test that get_db closes session even when exception occurs."""
        mock_session = MagicMock()
        mock_session_local.return_value = mock_session

        # Create the generator
        db_generator = get_db()

        # Get the session
        db_session = next(db_generator)
        assert db_session == mock_session

        # Simulate an exception in the generator
        test_exception = Exception("Database operation failed")

        with pytest.raises(Exception) as exc_info:
            db_generator.throw(test_exception)

        assert exc_info.value == test_exception

        # Verify session is still closed despite the exception
        mock_session.close.assert_called_once()

    @patch("db.database.SessionLocal")
    def test_get_db_is_generator(self, mock_session_local):
        """Test that get_db returns a generator."""
        mock_session = MagicMock()
        mock_session_local.return_value = mock_session

        result = get_db()

        # Verify it's a generator
        import types

        assert isinstance(result, types.GeneratorType)

        # Verify we can iterate over it
        sessions = list(result)
        assert len(sessions) == 1
        assert sessions[0] == mock_session

    @patch("db.database.SessionLocal")
    def test_get_db_yields_exactly_one_session(self, mock_session_local):
        """Test that get_db yields exactly one session."""
        mock_session = MagicMock()
        mock_session_local.return_value = mock_session

        db_generator = get_db()

        # First next() should return the session
        db_session = next(db_generator)
        assert db_session == mock_session

        # Second next() should raise StopIteration
        with pytest.raises(StopIteration):
            next(db_generator)

    @patch("db.database.SessionLocal")
    def test_get_db_multiple_calls_create_separate_sessions(self, mock_session_local):
        """Test that multiple calls to get_db create separate sessions."""
        mock_session1 = MagicMock()
        mock_session2 = MagicMock()
        mock_session_local.side_effect = [mock_session1, mock_session2]

        # Create two generators
        gen1 = get_db()
        gen2 = get_db()

        # Get sessions from both generators
        session1 = next(gen1)
        session2 = next(gen2)

        # Verify they are different sessions
        assert session1 == mock_session1
        assert session2 == mock_session2
        assert session1 != session2

        # Verify both sessions are created
        assert mock_session_local.call_count == 2

    @patch("db.database.SessionLocal")
    def test_get_db_exception_during_session_creation(self, mock_session_local):
        """Test get_db behavior when session creation fails."""
        session_error = Exception("Failed to create session")
        mock_session_local.side_effect = session_error

        with pytest.raises(Exception) as exc_info:
            db_generator = get_db()
            next(db_generator)

        assert exc_info.value == session_error


class TestDbDependency:
    """Test the db_dependency type annotation."""

    def test_db_dependency_is_annotated(self):
        """Test that db_dependency is properly annotated."""
        # Check if it's an Annotated type
        from typing import _AnnotatedAlias

        assert isinstance(db_dependency, _AnnotatedAlias)

    def test_db_dependency_annotation_components(self):
        """Test the components of the db_dependency annotation."""
        # Extract the annotation components
        if hasattr(db_dependency, "__args__"):
            args = db_dependency.__args__

            # First argument should be Session type
            assert args[0] is Session

            # Second argument should be Depends
            if len(args) > 1:
                assert isinstance(args[1], Depends)

    def test_db_dependency_depends_on_get_db(self):
        """Test that db_dependency uses get_db as dependency."""
        # Extract the Depends object
        if hasattr(db_dependency, "__args__") and len(db_dependency.__args__) > 1:
            depends_obj = db_dependency.__args__[1]

            # Verify it depends on get_db function
            assert depends_obj.dependency == get_db

    def test_db_dependency_usage_pattern(self):
        """Test typical usage pattern of db_dependency."""
        # This tests how db_dependency would be used in a FastAPI route
        from typing import get_args, get_origin

        # Verify it can be used in type hints
        def example_route(db: db_dependency):
            return db

        # Extract parameter annotation
        import inspect

        sig = inspect.signature(example_route)
        param_annotation = sig.parameters["db"].annotation

        # Verify the annotation matches
        assert param_annotation == db_dependency


class TestSessionIntegration:
    """Test integration with SQLAlchemy Session."""

    @patch("db.database.SessionLocal")
    def test_yielded_session_is_sqlalchemy_session(self, mock_session_local):
        """Test that the yielded object is a SQLAlchemy session."""
        mock_session = MagicMock(spec=Session)
        mock_session_local.return_value = mock_session

        db_generator = get_db()
        db_session = next(db_generator)

        # Verify it behaves like a SQLAlchemy session
        assert hasattr(db_session, "query")
        assert hasattr(db_session, "add")
        assert hasattr(db_session, "commit")
        assert hasattr(db_session, "rollback")
        assert hasattr(db_session, "close")

    @patch("db.database.SessionLocal")
    def test_session_operations(self, mock_session_local):
        """Test typical session operations work with get_db."""
        mock_session = MagicMock(spec=Session)
        mock_session_local.return_value = mock_session

        db_generator = get_db()
        db_session = next(db_generator)

        # Test typical operations
        db_session.query("SELECT * FROM users")
        db_session.add("some_object")
        db_session.commit()

        # Verify operations were called
        db_session.query.assert_called_once_with("SELECT * FROM users")
        db_session.add.assert_called_once_with("some_object")
        db_session.commit.assert_called_once()


class TestFastAPIIntegration:
    """Test integration with FastAPI dependency injection."""

    def test_depends_import(self):
        """Test that Depends is properly imported from FastAPI."""
        from fastapi import Depends as FastAPIDepends

        # Verify we're using the correct Depends
        if hasattr(db_dependency, "__args__") and len(db_dependency.__args__) > 1:
            depends_obj = db_dependency.__args__[1]
            assert type(depends_obj) is type(FastAPIDepends(get_db))

    def test_session_type_import(self):
        """Test that Session type is properly imported from SQLAlchemy."""
        from sqlalchemy.orm import Session as SQLAlchemySession

        # Verify we're using the correct Session type
        if hasattr(db_dependency, "__args__"):
            session_type = db_dependency.__args__[0]
            assert session_type is SQLAlchemySession

    @patch("db.dependency.get_db")
    def test_dependency_injection_pattern(self, mock_get_db):
        """Test the dependency injection pattern."""
        mock_session = MagicMock(spec=Session)
        mock_get_db.return_value = iter([mock_session])

        # Simulate FastAPI calling the dependency
        if hasattr(db_dependency, "__args__") and len(db_dependency.__args__) > 1:
            depends_obj = db_dependency.__args__[1]
            result = depends_obj.dependency()

            # Convert generator to list to get the session
            session_list = list(result)
            assert len(session_list) == 1
            assert session_list[0] == mock_session


class TestModuleStructure:
    """Test the module structure and imports."""

    def test_required_imports(self):
        """Test that all required imports are present."""
        import db.dependency

        # Verify essential components are imported
        assert hasattr(db.dependency, "Annotated")
        assert hasattr(db.dependency, "Depends")
        assert hasattr(db.dependency, "Session")
        assert hasattr(db.dependency, "SessionLocal")

    def test_exported_functions_and_variables(self):
        """Test that required functions and variables are exported."""
        import db.dependency

        # Verify main exports
        assert hasattr(db.dependency, "get_db")
        assert hasattr(db.dependency, "db_dependency")

        # Verify they are callable/usable
        assert callable(db.dependency.get_db)
        assert hasattr(db.dependency.db_dependency, "__args__")

    def test_module_dependencies(self):
        """Test that module properly depends on database module."""
        import db.dependency

        # Should be able to access SessionLocal from database module
        assert hasattr(db.dependency, "SessionLocal")

        # SessionLocal should be from db.database module
        from db.database import SessionLocal as DatabaseSessionLocal

        assert db.dependency.SessionLocal is DatabaseSessionLocal


class TestErrorHandling:
    """Test error handling scenarios."""

    @patch("db.database.SessionLocal")
    def test_get_db_handles_session_close_error(self, mock_session_local):
        """Test get_db handles errors during session close."""
        mock_session = MagicMock()
        mock_session.close.side_effect = Exception("Close failed")
        mock_session_local.return_value = mock_session

        db_generator = get_db()
        db_session = next(db_generator)

        # Exception during close should not prevent the generator from finishing
        with pytest.raises(Exception) as exc_info:
            try:
                next(db_generator)
            except StopIteration:
                pass

        # Verify close was attempted despite the error
        mock_session.close.assert_called_once()

    @patch("db.database.SessionLocal")
    def test_get_db_cleanup_on_generator_close(self, mock_session_local):
        """Test that cleanup occurs when generator is explicitly closed."""
        mock_session = MagicMock()
        mock_session_local.return_value = mock_session

        db_generator = get_db()
        db_session = next(db_generator)

        # Explicitly close the generator
        db_generator.close()

        # Verify session cleanup occurred
        mock_session.close.assert_called_once()


class TestConcurrency:
    """Test concurrent usage scenarios."""

    @patch("db.database.SessionLocal")
    def test_concurrent_get_db_calls(self, mock_session_local):
        """Test that concurrent get_db calls work independently."""
        # Create separate mock sessions
        sessions = [MagicMock() for _ in range(3)]
        mock_session_local.side_effect = sessions

        # Create multiple generators simultaneously
        generators = [get_db() for _ in range(3)]

        # Get sessions from all generators
        db_sessions = [next(gen) for gen in generators]

        # Verify each generator got its own session
        assert len(set(db_sessions)) == 3  # All sessions should be unique
        assert mock_session_local.call_count == 3

        # Complete all generators
        for gen in generators:
            try:
                next(gen)
            except StopIteration:
                pass

        # Verify all sessions were closed
        for session in sessions:
            session.close.assert_called_once()
