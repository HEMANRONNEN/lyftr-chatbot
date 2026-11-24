import litellm
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture
def make_client(tmp_path):
    def _make(simulation=True, keys=("k1", "k2")):
        settings = Settings(
            api_keys=list(keys),
            model="gemini/gemini-2.0-flash",
            database_url=f"sqlite:///{tmp_path}/test.db",
            allowed_origins=["http://localhost:3000"],
            enable_failure_simulation=simulation,
            mock_response="The capital of France is Paris.",
        )
        return TestClient(create_app(settings))

    return _make


@pytest.fixture
def client(make_client):
    return make_client()


@pytest.fixture
def real_completion():
    return litellm.completion
