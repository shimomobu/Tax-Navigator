import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from langchain_ollama import OllamaLLM, OllamaEmbeddings
from langchain_qdrant import QdrantVectorStore
from sentence_transformers import CrossEncoder

OLLAMA_URL   = os.getenv("OLLAMA_URL",   "http://ollama-service.ollama.svc.cluster.local:11434")
QDRANT_URL   = os.getenv("QDRANT_URL",   "http://qdrant-service.mlops.svc.cluster.local:6333")
PHOENIX_URL  = os.getenv("PHOENIX_COLLECTOR_ENDPOINT", "http://phoenix-service.mlops.svc.cluster.local:4317")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gemma4:e4b")
COLLECTION   = os.getenv("COLLECTION",   "tax_navigator")

SOURCE_LABELS = {
    "nta_tax_answer": "国税庁タックスアンサー",
    "nta_qa_cases":   "国税庁質疑応答事例",
    "tribunal_cases": "国税不服審判所裁決事例",
    "nta_tsutatsu":   "国税庁法令解釈通達",
}

# サービスインスタンス（lifespan で初期化）
_services: dict = {}


def get_source_label(source: str) -> str:
    return SOURCE_LABELS.get(source, source)


def get_embeddings() -> OllamaEmbeddings:
    return _services["embeddings"]


def get_llm() -> OllamaLLM:
    return _services["llm"]


def get_cross_encoder() -> CrossEncoder:
    return _services["cross_encoder"]


@asynccontextmanager
async def lifespan(app: FastAPI):
    if os.getenv("TESTING") != "true":
        from phoenix.otel import register
        from openinference.instrumentation.langchain import LangChainInstrumentor
        tracer_provider = register(project_name="tax-navigator", endpoint=PHOENIX_URL)
        LangChainInstrumentor().instrument(tracer_provider=tracer_provider)

        _services["embeddings"]    = OllamaEmbeddings(base_url=OLLAMA_URL, model="nomic-embed-text")
        _services["llm"]           = OllamaLLM(base_url=OLLAMA_URL, model=OLLAMA_MODEL)
        _services["cross_encoder"] = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
    yield
    _services.clear()


app = FastAPI(title="Tax Navigator API", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

if os.getenv("TESTING") != "true":
    os.makedirs("/app/static", exist_ok=True)
    app.mount("/static", StaticFiles(directory="/app/static"), name="static")

# ──────────────────────────────────────────
# プロンプトテンプレート
# ──────────────────────────────────────────

SYSTEM_PROMPT = """あなたは日本の税務専門家です。個人事業主（青色申告・免税事業者）の税務・経費に関する質問に答えます。

【個人事業主の主要税務ルール（必ず参照すること）】

▼ 必要経費として認められる費用（所得税法37条）
- 業務目的の旅費・交通費（電車・バス・タクシー・ガソリン代等）は認められる
- 取引先への接待・会議費（カフェ代・会食費）は認められる（法人の損金不算入制限は個人事業主には適用なし）
- 取引先への贈答品（歳暮・中元等）は接待交際費として認められる
- 業務用資産の保険料（動産総合保険等）は認められる
- 業務に直接関連する書籍・研修費は認められる
- 青色事業専従者給与：事前届出（青色事業専従者給与に関する届出書）があれば配偶者・家族への給与は認められる（所得税法57条）

▼ 家事関連費の按分（所得税法施行令96条）
- 自宅家賃・電気代・通信費等で業務とプライベートが混在する場合→業務使用割合で按分して認められる（グレーゾーンではなく「認められる」）
- 按分根拠（面積比・時間比・通話明細等）の記録が必要

▼ 少額減価償却（所得税）
- 取得価額10万円未満：全額消耗品費として認められる（所得税法施行令138条）
- 取得価額30万円未満（青色申告者のみ）：租税特別措置法56条の特例で一括経費算入認められる
- 取得価額30万円以上：法定耐用年数での減価償却

▼ 家事費として認められない費用（所得税法45条）
- 個人の食事代（一人でのランチ等）は認められない
- 一般的なビジネススーツ・私服（日常着用可能なもの）は認められない
- 個人の健康診断・医療費は認められない

▼ グレーゾーンとなるケース
- 業務関連性が曖昧で状況により判断が分かれる場合のみ「グレーゾーン」とする
- 自宅から別の事務所への通勤費（自宅＝事業所でない場合）
- 現在の業務と直接関係しない新スキル習得の研修費
- 按分の根拠・割合が不明確な場合

以下のルールを厳守してください：
- 回答は必ず下記の【出力フォーマット】に従ってください
- 根拠は参照文書または上記の税務ルールを引用し、条文番号を明記してください
- 仕訳は青色申告・複式簿記・免税事業者（インボイスなし）の前提で作成してください
- 消費税区分は参考として表示してください（仕入税額控除の計算は不要）
- 金額は税込で記載してください

【出力フォーマット】
## 判断
次の3択のうち**1つだけ**を、文言をそのままコピーして記載すること。それ以外の表現は使用しないこと：
- 経費として認められる
- 経費として認められない
- グレーゾーン（要確認）

判断基準：上記の税務ルールまたは参照文書に根拠があれば断定すること。本当に状況依存・不明確な場合のみ「グレーゾーン（要確認）」を選ぶ。

## 根拠
（参照文書からの引用・条文番号等）

## 注意事項
（留意点・証拠書類・按分方法等。税理士への確認が必要な場合はここに記載）

## 仕訳
| 借方科目 | 借方金額 | 貸方科目 | 貸方金額 | 摘要 | 消費税区分 |
|---|---|---|---|---|---|
| 〇〇費 | 金額 | 現金/預金 | 金額 | 内容 | 課税仕入10% |

（仕訳が不要・不明な場合は「仕訳なし」と記載）
"""

def build_prompt(context: str, question: str) -> str:
    return f"""{SYSTEM_PROMPT}

---
【参照文書】
{context}

---
【質問】
{question}
"""


# ──────────────────────────────────────────
# スキーマ
# ──────────────────────────────────────────

class AskRequest(BaseModel):
    question: str
    k: int = 15
    top_n: int = 4


class AskResponse(BaseModel):
    answer: str
    sources: list[dict]
    reranked_chunks: int


# ──────────────────────────────────────────
# エンドポイント
# ──────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def index():
    return FileResponse("/app/static/index.html")


@app.get("/health")
def health():
    return {"status": "ok", "model": OLLAMA_MODEL, "collection": COLLECTION}


@app.post("/ask", response_model=AskResponse)
def ask(
    req: AskRequest,
    embeddings: OllamaEmbeddings = Depends(get_embeddings),
    llm: OllamaLLM = Depends(get_llm),
    cross_encoder: CrossEncoder = Depends(get_cross_encoder),
):
    try:
        vectorstore = QdrantVectorStore.from_existing_collection(
            embedding=embeddings,
            url=QDRANT_URL,
            collection_name=COLLECTION,
        )
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=f"ナレッジベースに接続できません（コレクション: {COLLECTION}）: {e}",
        )

    # クエリ拡張: 税務ドメインの文脈を付加してembedding精度を向上
    expanded_query = f"個人事業主 必要経費 所得税 青色申告 経費 {req.question}"
    retriever  = vectorstore.as_retriever(search_kwargs={"k": req.k})
    candidates = retriever.invoke(expanded_query)

    if not candidates:
        raise HTTPException(status_code=404, detail="関連する文書が見つかりませんでした。")

    # クロスエンコーダーでリランキング
    pairs  = [[req.question, doc.page_content] for doc in candidates]
    scores = cross_encoder.predict(pairs)
    ranked = sorted(zip(scores, candidates), key=lambda x: x[0], reverse=True)
    top_docs = [doc for _, doc in ranked[: req.top_n]]

    # コンテキスト構築（出典情報付き）
    context_parts = []
    for i, doc in enumerate(top_docs, 1):
        meta         = doc.metadata
        source       = meta.get("source", "")
        title        = meta.get("title", "")
        url          = meta.get("url", "")
        source_label = get_source_label(source)

        header = f"[文書{i}] {source_label}「{title}」"
        if url:
            header += f"（{url}）"
        context_parts.append(f"{header}\n{doc.page_content}")

    context = "\n\n".join(context_parts)
    prompt  = build_prompt(context, req.question)
    answer  = llm.invoke(prompt)

    sources = [
        {
            "title":    doc.metadata.get("title", ""),
            "source":   doc.metadata.get("source", ""),
            "url":      doc.metadata.get("url", ""),
            "category": doc.metadata.get("category", ""),
        }
        for doc in top_docs
    ]

    return AskResponse(
        answer=answer,
        sources=sources,
        reranked_chunks=len(top_docs),
    )
