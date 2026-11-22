import os
import tempfile

# Configure the app before it is imported anywhere.
_TMP = tempfile.mkdtemp(prefix="nova-test-")
os.environ["NOVA_ENV"] = "test"
os.environ["NOVA_SECRET_KEY"] = "test-secret-key-not-for-production-use"
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP}/test.db"
os.environ["NOVA_WORKSPACE_DIR"] = f"{_TMP}/workspace"
os.environ["NOVA_WORKER_ENABLED"] = "true"
os.environ["NOVA_WORKER_CONCURRENCY"] = "2"
os.environ["NOVA_AI_PROVIDER"] = ""
os.environ["GEMINI_API_KEY"] = ""
os.environ["OPENAI_API_KEY"] = ""
os.environ["ANTHROPIC_API_KEY"] = ""
os.environ["WHATSAPP_APP_SECRET"] = "test-app-secret"
os.environ["WHATSAPP_ALLOWED_NUMBERS"] = "+919999999999"
os.environ["WHATSAPP_TOKEN"] = "test-whatsapp-token"
os.environ["WHATSAPP_PHONE_NUMBER_ID"] = "1234567890"
os.environ["NOVA_CORS_ORIGINS"] = "http://localhost:3000"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(scope="session")
def auth(client):
    response = client.post(
        "/api/auth/register",
        json={"email": "owner@example.com", "password": "a-very-long-password", "name": "Owner"},
    )
    assert response.status_code == 200, response.text
    data = response.json()
    return {"token": data["token"], "user": data["user"]}


@pytest.fixture(scope="session")
def headers(auth):
    return {"Authorization": f"Bearer {auth['token']}"}
