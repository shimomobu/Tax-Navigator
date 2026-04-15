"""
スクレイピング済みJSONLファイルをQdrantに投入するスクリプト。

使い方:
  # Qdrantにポートフォワード（K8S外から実行する場合）
  microk8s kubectl port-forward -n mlops svc/qdrant-service 6333:6333 &

  # 仮想環境を作って実行
  python3 -m venv .venv
  source .venv/bin/activate
  pip install -r requirements.txt
  python ingest.py

環境変数:
  QDRANT_URL    : Qdrantエンドポイント（デフォルト: http://localhost:6333）
  OLLAMA_URL    : OllamaエンドポイントURL（デフォルト: http://localhost:11434）
  COLLECTION    : Qdrantコレクション名（デフォルト: tax_navigator）
  DATA_DIR      : JSONLファイルのディレクトリ（デフォルト: ./data）
"""

import json
import os
import sys
from pathlib import Path

from langchain_ollama import OllamaEmbeddings
from langchain_qdrant import QdrantVectorStore
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain.schema import Document
from tqdm import tqdm

QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
COLLECTION = os.getenv("COLLECTION", "tax_navigator")
DATA_DIR = Path(os.getenv("DATA_DIR", Path(__file__).parent / "data"))

# 法律文書向けにチャンクを大きめに設定
CHUNK_SIZE = 500
CHUNK_OVERLAP = 50
BATCH_SIZE = 50  # Qdrantへの一括投入サイズ

JSONL_FILES = [
    "nta_taxanswer.jsonl",
    "nta_shitsugi.jsonl",
    "tribunal_cases.jsonl",
    "nta_tsutatsu.jsonl",
]


def load_jsonl(path: Path) -> list[dict]:
    records = []
    if not path.exists():
        print(f"  [SKIP] ファイルが存在しません: {path}")
        return records
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError as e:
                    print(f"  [WARN] JSON解析エラー: {e}")
    return records


def records_to_documents(records: list[dict]) -> list[Document]:
    docs = []
    for r in records:
        content = r.get("content", "").strip()
        if not content:
            continue
        metadata = {
            "source": r.get("source", ""),
            "url": r.get("url", ""),
            "title": r.get("title", ""),
            "category": r.get("category", ""),
            "scraped_at": r.get("scraped_at", ""),
        }
        docs.append(Document(page_content=content, metadata=metadata))
    return docs


def main():
    print(f"Qdrant URL  : {QDRANT_URL}")
    print(f"Ollama URL  : {OLLAMA_URL}")
    print(f"Collection  : {COLLECTION}")
    print(f"Data Dir    : {DATA_DIR}")
    print()

    embeddings = OllamaEmbeddings(base_url=OLLAMA_URL, model="nomic-embed-text:latest")
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", "。", "、", " ", ""],
    )

    total_chunks = 0

    for filename in JSONL_FILES:
        path = DATA_DIR / filename
        print(f"--- {filename} ---")
        records = load_jsonl(path)
        if not records:
            continue

        print(f"  レコード数: {len(records)}")
        docs = records_to_documents(records)
        chunks = splitter.split_documents(docs)
        print(f"  チャンク数: {len(chunks)}")

        # バッチ投入
        for i in tqdm(range(0, len(chunks), BATCH_SIZE), desc=f"  投入中"):
            batch = chunks[i: i + BATCH_SIZE]
            try:
                QdrantVectorStore.from_documents(
                    batch,
                    embeddings,
                    url=QDRANT_URL,
                    collection_name=COLLECTION,
                )
            except Exception as e:
                print(f"\n  [ERROR] バッチ {i}〜{i+BATCH_SIZE}: {e}")
                sys.exit(1)

        total_chunks += len(chunks)
        print(f"  完了")

    print(f"\n===========================")
    print(f"投入完了: 合計 {total_chunks} チャンク -> コレクション '{COLLECTION}'")


if __name__ == "__main__":
    main()
