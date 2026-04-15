# Tax Navigator - 仕様書

## 概要

個人事業主（青色申告）向けの税務RAGシステム。領収書・経費の計上可否判断、税法・通達の根拠参照、仕訳の出力を行う自分用Webアプリ。

---

## ユースケース

| # | ユースケース | 詳細 |
|---|---|---|
| UC-1 | 経費判断 | 領収書・支出が事業経費として認められるか判断する |
| UC-2 | 法規参照 | 根拠となる税法・通達・裁決事例を参照する |
| UC-3 | 仕訳出力 | 経費判断結果に基づき、借方・貸方の仕訳を出力する |

---

## 対象ユーザー

- 利用者: 自分（個人事業主）
- 申告種別: 青色申告
- 帳簿方式: 複式簿記
- インボイス登録: なし（免税事業者）
- 消費税: 消費税区分の参考表示は行う（仕入税額控除の記載は不要）

---

## データソース

スクレイピングにより取得し、Qdrantに格納する。

| ソース | URL | 内容 | グレーゾーン対応 |
|---|---|---|---|
| 国税庁 タックスアンサー | https://www.nta.go.jp/taxes/shiraberu/taxanswer/ | 基本的な経費・税務の判断基準 | △ |
| 国税庁 質疑応答事例 | https://www.nta.go.jp/law/shitsugi/ | 実務上のグレーゾーンに対する公式見解 | ◎ |
| 国税不服審判所 裁決事例 | https://www.kfs.go.jp/ | 実際に争われた事案の判断（最も実務的） | ◎ |
| 国税庁 法令解釈通達 | https://www.nta.go.jp/law/tsutatsu/menu.htm | 税務署内部の運用基準・解釈指針 | ○ |

### スクレイピング方針
- 初回: 手動実行で全件取得・Qdrant投入
- 更新: 定期実行は現時点では対象外（必要に応じて手動再実行）
- robots.txt を尊重し、適切なインターバルを設ける（1秒以上）

---

## 出力形式

### 回答フォーマット

```
【判断】経費として認められる / 認められない / グレーゾーン（要判断）

【根拠】
該当条文・通達・裁決事例の引用

【注意事項】
グレーゾーンの場合の留意点

【仕訳】
借方科目        金額    | 貸方科目    金額    | 摘要          | 消費税区分
旅費交通費      1,100   | 現金        1,100   | 〇〇交通費    | 課税仕入（10%）
```

### 仕訳ルール
- 勘定科目: 一般的な個人事業主向け科目体系
- 消費税区分: 課税仕入・非課税仕入・不課税・課税売上等を参考表示
- 金額: 税込金額で記載（免税事業者のため）

---

## システム構成

### アーキテクチャ

```
[ブラウザ]
    │ HTTP
    ▼
[NGINX Ingress] ← MicroK8S
    │
    ▼
[tax-navigator Pod]
    ├── FastAPI (port 8000)
    │       ├── /          : チャットUI (静的HTML)
    │       ├── /ask       : RAG質問応答
    │       └── /health    : ヘルスチェック
    │
    ├── Qdrant (既存 mlops namespace)
    │       └── collection: tax_navigator
    │
    ├── Ollama (既存 ollama namespace)
    │       ├── LLM: gemma4:e4b
    │       └── Embeddings: nomic-embed-text
    │
    └── Phoenix (既存 mlops namespace)
            └── トレーシング・可観測性
```

### 既存K8Sリソースの再利用

| リソース | Namespace | 用途 |
|---|---|---|
| `qdrant-service` | mlops | ベクトルDB（新collectionを追加） |
| `ollama-service` | ollama | LLM推論 + Embeddings |
| `phoenix-service` | mlops | LLMトレーシング |
| `nginx-ingress` | ingress | リバースプロキシ |

---

## 技術スタック

| レイヤー | 採用技術 | バージョン方針 |
|---|---|---|
| バックエンド | FastAPI + Uvicorn | 既存rag-appに揃える |
| RAGフレームワーク | LangChain | 既存rag-appに揃える |
| ベクトルDB接続 | langchain-qdrant | 既存rag-appに揃える |
| LLM接続 | langchain-ollama | 既存rag-appに揃える |
| Embeddings | OllamaEmbeddings (nomic-embed-text) | 既存rag-appに揃える |
| リランキング | CrossEncoder (ms-marco-MiniLM-L-6-v2) | 既存rag-appに揃える |
| スクレイピング | httpx + BeautifulSoup4 | 新規 |
| 可観測性 | arize-phoenix-otel + openinference-instrumentation-langchain | 既存rag-appに揃える |
| フロントエンド | バニラHTML/CSS/JS（単一ファイル） | 新規 |
| コンテナ | Docker | 既存rag-appに揃える |
| デプロイ | MicroK8S | 既存環境 |

---

## RAG設計

### Qdrant Collection

- コレクション名: `tax_navigator`
- Embedding モデル: `nomic-embed-text`（768次元）
- チャンク設定: chunk_size=500, chunk_overlap=50（法律文書向けに既存より大きめ）

### メタデータ構造

各ドキュメントに以下のメタデータを付与する:

```json
{
  "source": "nta_tax_answer | nta_qa_cases | tribunal_cases | nta_tsutatsu",
  "url": "https://...",
  "title": "ドキュメントタイトル",
  "category": "経費 | 所得 | 控除 | ...",
  "scraped_at": "2026-04-13"
}
```

### 検索・回答フロー

```
質問入力
  │
  ▼
Qdrant 類似検索 (k=7)
  │
  ▼
CrossEncoder リランキング (top_n=4)
  │
  ▼
プロンプト構築（文書 + 質問 + 仕訳出力指示）
  │
  ▼
gemma4 推論
  │
  ▼
回答（判断 + 根拠 + 仕訳表）
```

---

## ファイル構成

```
/home/shimode/dev/Tax-Navigator/
├── SPEC.md                  # 本仕様書
├── scraper/
│   ├── scrape_nta.py        # 国税庁タックスアンサー・質疑応答スクレイパー
│   ├── scrape_tribunal.py   # 国税不服審判所スクレイパー
│   ├── scrape_tsutatsu.py   # 法令解釈通達スクレイパー
│   └── ingest.py            # Qdrant投入スクリプト
├── app/
│   ├── main.py              # FastAPI アプリケーション
│   └── static/
│       └── index.html       # チャットUI
├── requirements.txt
├── Dockerfile
└── deployment.yaml          # K8Sマニフェスト
```

---

## K8Sマニフェスト方針

- Namespace: `mlops`（既存に相乗り）
- Image: `localhost:32000/tax-navigator:v1`（既存のcontainer-registryを使用）
- Resources: CPU 500m / Memory 1Gi（GPU不使用、推論はOllamaに委譲）
- 環境変数:
  - `OLLAMA_URL`: `http://ollama-service.ollama.svc.cluster.local:11434`
  - `QDRANT_URL`: `http://qdrant-service.mlops.svc.cluster.local:6333`
  - `OLLAMA_MODEL`: `gemma4:e4b`
  - `PHOENIX_COLLECTOR_ENDPOINT`: `http://phoenix-service.mlops.svc.cluster.local:4317`

---

## 実装ステップ

| Step | 内容 | 優先度 |
|---|---|---|
| 1 | スクレイパー実装・データ取得・Qdrant投入 | 高 |
| 2 | FastAPI バックエンド（/ask エンドポイント） | 高 |
| 3 | チャットUI（フロントエンド） | 高 |
| 4 | Dockerfile + K8Sマニフェスト | 高 |
| 5 | MicroK8Sデプロイ・動作確認 | 高 |

---

## 制約・注意事項

- 本ツールの回答は参考情報であり、最終判断は税理士等の専門家に確認すること
- 国税庁サイトのスクレイピングはrobots.txtを確認し、適切なアクセス間隔を設けること
- データは取得時点の情報であり、法改正に追従するには再スクレイピングが必要
