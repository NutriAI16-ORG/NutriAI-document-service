import os
import uuid
import pytest
from datetime import datetime
from unittest.mock import patch, MagicMock

# Override env vars BEFORE importing any app modules.
os.environ["DATABASE_URL"] = "sqlite:///./test.db"
os.environ["AZURE_STORAGE_CONNECTION_STRING"] = "DefaultEndpointsProtocol=https;AccountName=test;AccountKey=dGVzdA==;EndpointSuffix=core.windows.net"
os.environ["AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT"] = "https://test.cognitiveservices.azure.com/"
os.environ["AZURE_DOCUMENT_INTELLIGENCE_KEY"] = "test-key"
os.environ["AZURE_OPENAI_ENDPOINT"] = "https://test.openai.azure.com/"
os.environ["AZURE_OPENAI_KEY"] = "test-key"
os.environ["AZURE_OPENAI_DEPLOYMENT_NAME"] = "gpt-4"

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import Document

TEST_DATABASE_URL = "sqlite:///./test.db"
engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()

app.dependency_overrides[get_db] = override_get_db

@pytest.fixture(autouse=True)
def setup_database():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)

@pytest.fixture
def client():
    return TestClient(app)

@pytest.fixture
def db_session():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()

@pytest.fixture
def test_user():
    class MockUser:
        id = uuid.uuid4()
    return MockUser()

@pytest.fixture
def authenticated_client(client, test_user):
    client.headers["X-User-ID"] = str(test_user.id)
    return client
