"""
RAGOps ゴールデンデータセット評価スクリプト

評価レイヤー:
  L4 判断精度 (Judgment Accuracy)   - 「認められる/認められない/グレーゾーン」の一致率
  L1 キーワードカバレッジ            - 期待キーワードが回答に含まれる割合
  L2 忠実性 (Faithfulness)          - Ragas: 回答が検索文書に忠実か (要 --ragas)
  L3 回答関連性 (Answer Relevancy)  - Ragas: 回答が質問に関連するか (要 --ragas)

使用例:
  python -m tests.eval.evaluate --url http://localhost:8000
  python -m tests.eval.evaluate --url http://localhost:8000 --ragas
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import requests

# ─── データ構造 ──────────────────────────────────────────────────────────────

@dataclass
class GoldenCase:
    id: str
    category: str
    question: str
    expected_judgment: str          # 認められる | 認められない | グレーゾーン
    expected_basis_keywords: list[str]
    notes: str = ""


@dataclass
class EvalResult:
    case: GoldenCase
    actual_answer: str = ""
    actual_judgment: str = ""
    sources: list[dict] = field(default_factory=list)
    reranked_chunks: int = 0
    judgment_match: bool = False
    keyword_hits: list[str] = field(default_factory=list)
    keyword_coverage: float = 0.0
    ragas_faithfulness: Optional[float] = None
    ragas_relevancy: Optional[float] = None
    error: Optional[str] = None
    latency_ms: float = 0.0


# ─── データ読み込み ───────────────────────────────────────────────────────────

def load_dataset(path: str | Path) -> list[GoldenCase]:
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    return [GoldenCase(**item) for item in raw]


# ─── 判断抽出 ─────────────────────────────────────────────────────────────────

JUDGMENT_PATTERNS = {
    "認められる": [
        "経費として認められる",
        "必要経費として認められ",
        "経費に算入できます",
        "経費計上が可能",
        "認められます",
        "認められる",
    ],
    "認められない": [
        "経費として認められない",
        "必要経費に算入できません",
        "経費に算入できません",
        "経費計上はできません",
        "認められません",
        "認められない",
    ],
    "グレーゾーン": [
        "グレーゾーン",
        "グレー",
        "要確認",
        "税理士への確認を推奨",
        "税理士にご確認",
        "判断が異なります",
        "状況によって異なります",
        "一概には判断できません",
    ],
}


def extract_judgment(answer: str) -> str:
    """回答テキストから判断カテゴリを抽出する"""
    # 「認められない」を先にチェック（「認められる」を部分一致で誤検出しないため）
    for pattern in JUDGMENT_PATTERNS["認められない"]:
        if pattern in answer:
            return "認められない"
    for pattern in JUDGMENT_PATTERNS["グレーゾーン"]:
        if pattern in answer:
            return "グレーゾーン"
    for pattern in JUDGMENT_PATTERNS["認められる"]:
        if pattern in answer:
            return "認められる"
    return "不明"


# ─── キーワードカバレッジ ─────────────────────────────────────────────────────

def check_keyword_coverage(answer: str, keywords: list[str]) -> tuple[list[str], float]:
    """期待キーワードが回答に含まれるかを確認する"""
    if not keywords:
        return [], 1.0
    hits = [kw for kw in keywords if kw in answer]
    coverage = len(hits) / len(keywords)
    return hits, coverage


# ─── API 呼び出し ─────────────────────────────────────────────────────────────

def call_ask(url: str, question: str, timeout: int = 300) -> tuple[dict, float]:
    """
    /ask エンドポイントを呼び出す。
    (response_dict, latency_ms) を返す。
    """
    endpoint = url.rstrip("/") + "/ask"
    start = time.perf_counter()
    resp = requests.post(
        endpoint,
        json={"question": question},
        timeout=timeout,
    )
    latency_ms = (time.perf_counter() - start) * 1000
    resp.raise_for_status()
    return resp.json(), latency_ms


# ─── Ragas 評価 ───────────────────────────────────────────────────────────────

def run_ragas(
    results: list[EvalResult],
    ollama_url: str = "http://localhost:11434",
    ollama_model: str = "gemma4:e4b",
) -> None:
    """
    Ragas で L2(忠実性) / L3(回答関連性) を計算し、results を in-place 更新する。
    ragas / datasets がインストールされていない場合はスキップ。
    """
    try:
        from datasets import Dataset
        from ragas import evaluate
        from ragas.llms import LangchainLLMWrapper
        from ragas.metrics import answer_relevancy, faithfulness
        from langchain_community.llms import Ollama
    except ImportError:
        print("[WARN] ragas/datasets/langchain が未インストールのため Ragas 評価をスキップします")
        return

    # 評価可能なケースのみ抽出（エラーなし・回答あり）
    valid = [r for r in results if not r.error and r.actual_answer]
    if not valid:
        return

    llm = LangchainLLMWrapper(Ollama(base_url=ollama_url, model=ollama_model))

    data = {
        "question": [r.case.question for r in valid],
        "answer": [r.actual_answer for r in valid],
        "contexts": [
            [s.get("title", "") + " " + s.get("url", "") for s in r.sources]
            for r in valid
        ],
        "ground_truth": [r.case.notes for r in valid],
    }

    dataset = Dataset.from_dict(data)

    try:
        scores = evaluate(
            dataset,
            metrics=[faithfulness, answer_relevancy],
            llm=llm,
            raise_exceptions=False,
        )
        df = scores.to_pandas()
        for i, result in enumerate(valid):
            result.ragas_faithfulness = float(df.iloc[i].get("faithfulness", float("nan")))
            result.ragas_relevancy = float(df.iloc[i].get("answer_relevancy", float("nan")))
    except Exception as exc:
        print(f"[WARN] Ragas 評価中にエラーが発生しました: {exc}")


# ─── レポート出力 ─────────────────────────────────────────────────────────────

def _bar(ratio: float, width: int = 20) -> str:
    filled = int(ratio * width)
    return "█" * filled + "░" * (width - filled)


def print_report(results: list[EvalResult]) -> None:
    total = len(results)
    errors = [r for r in results if r.error]
    valid = [r for r in results if not r.error]

    judgment_matches = sum(1 for r in valid if r.judgment_match)
    judgment_acc = judgment_matches / len(valid) if valid else 0.0

    avg_kw = sum(r.keyword_coverage for r in valid) / len(valid) if valid else 0.0
    avg_latency = sum(r.latency_ms for r in valid) / len(valid) if valid else 0.0

    ragas_valid = [r for r in valid if r.ragas_faithfulness is not None]
    avg_faith = (
        sum(r.ragas_faithfulness for r in ragas_valid) / len(ragas_valid)
        if ragas_valid else None
    )
    avg_relev = (
        sum(r.ragas_relevancy for r in ragas_valid) / len(ragas_valid)
        if ragas_valid else None
    )

    print()
    print("=" * 64)
    print("  TAX NAVIGATOR RAGOps 評価レポート")
    print("=" * 64)
    print(f"  テストケース数  : {total}")
    print(f"  エラー数        : {len(errors)}")
    print(f"  有効評価数      : {len(valid)}")
    print()
    print(f"  L4 判断精度     : {judgment_acc:.1%}  {_bar(judgment_acc)}")
    print(f"                    ({judgment_matches}/{len(valid)} 件一致)")
    print()
    print(f"  L1 KWカバレッジ : {avg_kw:.1%}  {_bar(avg_kw)}")
    print()
    if avg_faith is not None:
        print(f"  L2 忠実性       : {avg_faith:.3f}  {_bar(avg_faith)}")
    if avg_relev is not None:
        print(f"  L3 回答関連性   : {avg_relev:.3f}  {_bar(avg_relev)}")
    if avg_faith is not None:
        print()

    print(f"  平均レイテンシ  : {avg_latency:.0f} ms")
    print()
    print("-" * 64)
    print(f"  {'ID':<8} {'期待':<12} {'実際':<12} {'判断':^4} {'KW':^6}  質問")
    print("-" * 64)
    for r in results:
        if r.error:
            print(f"  {r.case.id:<8} {'':12} {'ERROR':<12} {'':^4} {'':^6}  {r.case.question[:30]}")
            continue
        match_mark = "✓" if r.judgment_match else "✗"
        kw_str = f"{r.keyword_coverage:.0%}"
        print(
            f"  {r.case.id:<8} {r.case.expected_judgment:<12} {r.actual_judgment:<12}"
            f" {match_mark:^4} {kw_str:^6}  {r.case.question[:30]}"
        )
    print("=" * 64)
    print()

    # 閾値チェック
    threshold = 0.70
    if judgment_acc < threshold:
        print(f"  [FAIL] 判断精度 {judgment_acc:.1%} < 閾値 {threshold:.0%}")
    else:
        print(f"  [PASS] 判断精度 {judgment_acc:.1%} >= 閾値 {threshold:.0%}")
    print()


def save_report(results: list[EvalResult], output_path: str | Path) -> None:
    """評価結果を JSON で保存する"""
    data = []
    for r in results:
        data.append({
            "id": r.case.id,
            "category": r.case.category,
            "question": r.case.question,
            "expected_judgment": r.case.expected_judgment,
            "actual_judgment": r.actual_judgment,
            "judgment_match": r.judgment_match,
            "keyword_coverage": r.keyword_coverage,
            "keyword_hits": r.keyword_hits,
            "reranked_chunks": r.reranked_chunks,
            "latency_ms": r.latency_ms,
            "ragas_faithfulness": r.ragas_faithfulness,
            "ragas_relevancy": r.ragas_relevancy,
            "error": r.error,
        })
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"  レポートを保存しました: {output_path}")


# ─── メイン評価ロジック ───────────────────────────────────────────────────────

def run_evaluation(
    dataset_path: str | Path,
    api_url: str,
    use_ragas: bool = False,
    ollama_url: str = "http://localhost:11434",
    ollama_model: str = "gemma4:e4b",
) -> list[EvalResult]:
    cases = load_dataset(dataset_path)
    results: list[EvalResult] = []

    print(f"\n評価開始: {len(cases)} ケース → {api_url}")
    print("-" * 48)

    for i, case in enumerate(cases, 1):
        print(f"  [{i:02d}/{len(cases):02d}] {case.id} {case.question[:35]}...", end=" ", flush=True)
        result = EvalResult(case=case)

        try:
            resp, latency = call_ask(api_url, case.question)
            result.actual_answer = resp.get("answer", "")
            result.sources = resp.get("sources", [])
            result.reranked_chunks = resp.get("reranked_chunks", 0)
            result.latency_ms = latency

            result.actual_judgment = extract_judgment(result.actual_answer)
            result.judgment_match = result.actual_judgment == case.expected_judgment

            result.keyword_hits, result.keyword_coverage = check_keyword_coverage(
                result.actual_answer, case.expected_basis_keywords
            )

            status = "✓" if result.judgment_match else "✗"
            print(f"{status} ({latency:.0f}ms)")

        except Exception as exc:
            result.error = str(exc)
            print(f"ERROR: {exc}")

        results.append(result)

    if use_ragas:
        print("\nRagas 評価を実行中...")
        run_ragas(results, ollama_url=ollama_url, ollama_model=ollama_model)

    return results


# ─── CLI ─────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Tax Navigator RAGOps ゴールデンデータセット評価"
    )
    parser.add_argument(
        "--url",
        default=os.environ.get("TAX_NAVIGATOR_URL", "http://localhost:8000"),
        help="API ベース URL (デフォルト: TAX_NAVIGATOR_URL 環境変数 or http://localhost:8000)",
    )
    parser.add_argument(
        "--dataset",
        default=str(Path(__file__).parent.parent / "data" / "golden_dataset.json"),
        help="ゴールデンデータセット JSON パス",
    )
    parser.add_argument(
        "--ragas",
        action="store_true",
        help="Ragas による L2/L3 評価を実行する",
    )
    parser.add_argument(
        "--ollama-url",
        default="http://localhost:11434",
        help="Ollama API URL (Ragas 評価用)",
    )
    parser.add_argument(
        "--ollama-model",
        default="gemma4:e4b",
        help="Ollama モデル名 (Ragas 評価用)",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="レポート JSON 出力パス (省略時は保存しない)",
    )
    args = parser.parse_args()

    results = run_evaluation(
        dataset_path=args.dataset,
        api_url=args.url,
        use_ragas=args.ragas,
        ollama_url=args.ollama_url,
        ollama_model=args.ollama_model,
    )

    print_report(results)

    if args.output:
        save_report(results, args.output)

    # 判断精度が閾値未満なら exit 1
    valid = [r for r in results if not r.error]
    if valid:
        acc = sum(1 for r in valid if r.judgment_match) / len(valid)
        if acc < 0.70:
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
