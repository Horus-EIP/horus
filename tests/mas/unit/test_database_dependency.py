import importlib
from unittest.mock import Mock

import pytest

# Import the database module under the package name used in the project
database_module = importlib.import_module("db.database")


def test_get_db_closes_on_success(monkeypatch):
    """Ensure that the dependency yields the session and closes it on normal completion."""
    mock_session = Mock()
    mock_session.close = Mock()

    # Replace SessionLocal with a callable that returns our mock session
    monkeypatch.setattr(database_module, "SessionLocal", lambda: mock_session)

    gen = database_module.get_db()
    session = next(gen)
    assert session is mock_session

    # Advance the generator to completion which should run the finally block
    with pytest.raises(StopIteration):
        next(gen)

    mock_session.close.assert_called_once()


def test_get_db_rolls_back_and_closes_on_exception(monkeypatch):
    """Simulate an exception inside the dependency consumer: rollback then close should be called."""
    mock_session = Mock()
    mock_session.close = Mock()
    mock_session.rollback = Mock()

    monkeypatch.setattr(database_module, "SessionLocal", lambda: mock_session)

    gen = database_module.get_db()
    session = next(gen)
    assert session is mock_session

    # Throw an exception into the generator to simulate an error during usage.
    with pytest.raises(ValueError):
        gen.throw(ValueError("boom"))

    mock_session.rollback.assert_called_once()
    mock_session.close.assert_called_once()
