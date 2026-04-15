import os

os.environ["TESTING"] = "true"

import pytest
from unittest.mock import MagicMock
from fastapi.testclient import TestClient

from app.main import app, get_embeddings, get_llm, get_cross_encoder


@pytest.fixture
def mock_embeddings():
    return MagicMock()


@pytest.fixture
def mock_llm():
    m = MagicMock()
    m.invoke.return_value = "## 判断\n経費として認められる\n\n## 根拠\nテスト根拠\n\n## 仕訳\n仕訳なし"
    return m


@pytest.fixture
def mock_cross_encoder():
    m = MagicMock()
    m.predict.side_effect = lambda pairs: [0.9 - i * 0.1 for i in range(len(pairs))]
    return m


@pytest.fixture
def client(mock_embeddings, mock_llm, mock_cross_encoder):
    app.dependency_overrides[get_embeddings] = lambda: mock_embeddings
    app.dependency_overrides[get_llm] = lambda: mock_llm
    app.dependency_overrides[get_cross_encoder] = lambda: mock_cross_encoder

    with TestClient(app) as c:
        yield c

    app.dependency_overrides.clear()
