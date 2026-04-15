"""
FastAPI エンドポイントの統合テスト
"""
import pytest
from unittest.mock import MagicMock, patch
from langchain.schema import Document


def _make_docs(n=7):
    return [
        Document(
            page_content=f"テスト文書{i}の内容。経費に関する説明。",
            metadata={
                "source": "nta_tax_answer",
                "title": f"タックスアンサーNo.{i}",
                "url": f"https://www.nta.go.jp/taxes/{i}",
                "category": "所得税",
            },
        )
        for i in range(n)
    ]


class TestHealthEndpoint:
    def test_health_returns_200(self, client):
        response = client.get("/health")
        assert response.status_code == 200

    def test_health_returns_status_ok(self, client):
        response = client.get("/health")
        assert response.json()["status"] == "ok"

    def test_health_contains_model_info(self, client):
        response = client.get("/health")
        data = response.json()
        assert "model" in data
        assert "collection" in data


class TestAskEndpoint:
    def test_ask_returns_200(self, client):
        docs = _make_docs(7)
        mock_vs = MagicMock()
        mock_vs.as_retriever.return_value.invoke.return_value = docs

        with patch("app.main.QdrantVectorStore.from_existing_collection", return_value=mock_vs):
            response = client.post("/ask", json={"question": "交通費は経費になりますか？"})

        assert response.status_code == 200

    def test_ask_returns_answer_and_sources(self, client):
        docs = _make_docs(7)
        mock_vs = MagicMock()
        mock_vs.as_retriever.return_value.invoke.return_value = docs

        with patch("app.main.QdrantVectorStore.from_existing_collection", return_value=mock_vs):
            response = client.post("/ask", json={"question": "交通費は経費になりますか？"})

        data = response.json()
        assert "answer" in data
        assert "sources" in data
        assert isinstance(data["sources"], list)

    def test_ask_default_top_n_is_4(self, client):
        docs = _make_docs(7)
        mock_vs = MagicMock()
        mock_vs.as_retriever.return_value.invoke.return_value = docs

        with patch("app.main.QdrantVectorStore.from_existing_collection", return_value=mock_vs):
            response = client.post("/ask", json={"question": "質問"})

        data = response.json()
        assert data["reranked_chunks"] == 4
        assert len(data["sources"]) == 4

    def test_ask_respects_top_n(self, client):
        docs = _make_docs(7)
        mock_vs = MagicMock()
        mock_vs.as_retriever.return_value.invoke.return_value = docs

        with patch("app.main.QdrantVectorStore.from_existing_collection", return_value=mock_vs):
            response = client.post("/ask", json={"question": "質問", "top_n": 2})

        data = response.json()
        assert data["reranked_chunks"] == 2
        assert len(data["sources"]) == 2

    def test_ask_qdrant_unavailable_returns_503(self, client):
        with patch(
            "app.main.QdrantVectorStore.from_existing_collection",
            side_effect=Exception("接続失敗"),
        ):
            response = client.post("/ask", json={"question": "質問"})

        assert response.status_code == 503

    def test_ask_no_documents_returns_404(self, client):
        mock_vs = MagicMock()
        mock_vs.as_retriever.return_value.invoke.return_value = []

        with patch("app.main.QdrantVectorStore.from_existing_collection", return_value=mock_vs):
            response = client.post("/ask", json={"question": "質問"})

        assert response.status_code == 404

    def test_ask_question_required(self, client):
        response = client.post("/ask", json={})
        assert response.status_code == 422

    def test_ask_sources_contain_expected_fields(self, client):
        docs = _make_docs(7)
        mock_vs = MagicMock()
        mock_vs.as_retriever.return_value.invoke.return_value = docs

        with patch("app.main.QdrantVectorStore.from_existing_collection", return_value=mock_vs):
            response = client.post("/ask", json={"question": "質問"})

        sources = response.json()["sources"]
        assert len(sources) > 0
        for src in sources:
            assert "title" in src
            assert "source" in src
            assert "url" in src
            assert "category" in src
