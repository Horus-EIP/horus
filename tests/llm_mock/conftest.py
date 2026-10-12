import pytest
from clients import Running

from llm_mock.settings import Settings


@pytest.fixture
def mock_server():
    started = []

    def start(**settings):
        running = Running(Settings(**{"latency_ms": 0, **settings}))
        started.append(running)
        return running

    yield start
    for running in started:
        running.stop()


@pytest.fixture
def server(mock_server):
    return mock_server()
