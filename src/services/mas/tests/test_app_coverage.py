import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from core.app import create_app_environment


class TestAppCoverage:

    def test_create_app(self):
        app = create_app_environment()
        assert app.title == "MAS - Multi-Agent System"
        # Check if routers are included (indirectly by checking routes)
        # We can check if the routes list is populated
        assert len(app.routes) > 0

    @patch("core.app.init_db")
    @patch("core.app.check_agent_heartbeat")
    @patch("core.app.rabbitmq_instance")
    def test_lifespan_success(
        self, mock_rabbitmq, mock_heartbeat, mock_init_db
    ):
        # Mock async heartbeat
        async def fake_heartbeat():
            try:
                while True:
                    await asyncio.sleep(0.1)
            except asyncio.CancelledError:
                pass

        mock_heartbeat.side_effect = fake_heartbeat

        app = create_app_environment()
        with TestClient(app) as client:
            # Note: Base.metadata.create_all is no longer called from app.py
            # It's handled by init_db() and Alembic migrations
            mock_init_db.assert_called_once()
            mock_rabbitmq.connect.assert_called_once()

        mock_rabbitmq.close.assert_called_once()

    @patch("core.app.init_db")
    def test_lifespan_db_failure(self, mock_init_db):
        mock_init_db.side_effect = Exception("DB Error")
        app = create_app_environment()
        # TestClient context manager triggers startup
        with pytest.raises(Exception, match="DB Error"):
            with TestClient(app) as client:
                pass

    @patch("core.app.init_db")
    @patch("core.app.db.models.Base.metadata.create_all")
    @patch("core.app.check_agent_heartbeat")
    @patch("core.app.rabbitmq_instance")
    def test_lifespan_rabbitmq_failure(
        self, mock_rabbitmq, mock_heartbeat, mock_create_all, mock_init_db
    ):
        mock_rabbitmq.connect.side_effect = Exception("RabbitMQ Error")
        app = create_app_environment()
        with pytest.raises(Exception, match="RabbitMQ Error"):
            with TestClient(app) as client:
                pass
