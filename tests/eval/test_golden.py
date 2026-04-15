"""
RAGOps ゴールデンデータセット pytest 統合

常に実行: データセット構造の検証
ライブ評価: TAX_NAVIGATOR_URL 環境変数が設定されている場合のみ実行

実行方法:
  # 構造検証のみ（CI デフォルト）
  pytest tests/eval/test_golden.py

  # ライブ評価（実行中の API が必要）
  TAX_NAVIGATOR_URL=http://localhost:8000 pytest tests/eval/test_golden.py -v
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from tests.eval.evaluate import (
    EvalResult,
    check_keyword_coverage,
    extract_judgment,
    load_dataset,
    run_evaluation,
)

DATASET_PATH = Path(__file__).parent.parent / "data" / "golden_dataset.json"
API_URL = os.environ.get("TAX_NAVIGATOR_URL", "")

# ─── データセット構造の検証（常に実行） ───────────────────────────────────────

class TestGoldenDatasetStructure:
    """ゴールデンデータセット JSON が正しい形式であることを検証する"""

    def test_dataset_exists(self):
        assert DATASET_PATH.exists(), f"データセットが見つかりません: {DATASET_PATH}"

    def test_dataset_is_valid_json(self):
        with open(DATASET_PATH, encoding="utf-8") as f:
            data = json.load(f)
        assert isinstance(data, list)

    def test_dataset_has_minimum_cases(self):
        cases = load_dataset(DATASET_PATH)
        assert len(cases) >= 10, "最低10件のテストケースが必要です"

    def test_all_cases_have_required_fields(self):
        cases = load_dataset(DATASET_PATH)
        for case in cases:
            assert case.id, f"id が空: {case}"
            assert case.category, f"category が空: {case.id}"
            assert case.question, f"question が空: {case.id}"
            assert case.expected_judgment, f"expected_judgment が空: {case.id}"
            assert isinstance(case.expected_basis_keywords, list), (
                f"expected_basis_keywords がリストでない: {case.id}"
            )

    def test_expected_judgment_values_are_valid(self):
        valid_values = {"認められる", "認められない", "グレーゾーン"}
        cases = load_dataset(DATASET_PATH)
        for case in cases:
            assert case.expected_judgment in valid_values, (
                f"{case.id}: expected_judgment の値が不正: {case.expected_judgment!r}"
            )

    def test_case_ids_are_unique(self):
        cases = load_dataset(DATASET_PATH)
        ids = [c.id for c in cases]
        assert len(ids) == len(set(ids)), "重複した ID があります"

    def test_keywords_are_nonempty_strings(self):
        cases = load_dataset(DATASET_PATH)
        for case in cases:
            for kw in case.expected_basis_keywords:
                assert isinstance(kw, str) and kw.strip(), (
                    f"{case.id}: 空のキーワードがあります"
                )

    def test_category_distribution(self):
        """主要カテゴリが複数存在することを確認する"""
        cases = load_dataset(DATASET_PATH)
        categories = {c.category for c in cases}
        assert len(categories) >= 3, f"カテゴリが少なすぎます: {categories}"

    def test_judgment_distribution(self):
        """3種類の判断がすべて存在することを確認する"""
        cases = load_dataset(DATASET_PATH)
        judgments = {c.expected_judgment for c in cases}
        assert "認められる" in judgments
        assert "認められない" in judgments
        assert "グレーゾーン" in judgments


# ─── ユニット: extract_judgment ───────────────────────────────────────────────

class TestExtractJudgment:
    def test_ok_pattern(self):
        assert extract_judgment("経費として認められる費用です") == "認められる"

    def test_ng_pattern(self):
        assert extract_judgment("経費として認められない支出です") == "認められない"

    def test_gray_pattern(self):
        assert extract_judgment("グレーゾーン（要確認）の支出です") == "グレーゾーン"

    def test_ng_takes_priority_over_ok(self):
        # 「認められない」は「認められる」を含むため優先順位が重要
        assert extract_judgment("認められない") == "認められない"

    def test_unknown_returns_fumu(self):
        assert extract_judgment("不明な回答です") == "不明"


# ─── ユニット: check_keyword_coverage ────────────────────────────────────────

class TestCheckKeywordCoverage:
    def test_full_coverage(self):
        hits, cov = check_keyword_coverage("旅費と交通費と必要経費について", ["旅費", "交通費", "必要経費"])
        assert hits == ["旅費", "交通費", "必要経費"]
        assert cov == pytest.approx(1.0)

    def test_partial_coverage(self):
        hits, cov = check_keyword_coverage("旅費について", ["旅費", "交通費"])
        assert hits == ["旅費"]
        assert cov == pytest.approx(0.5)

    def test_no_coverage(self):
        hits, cov = check_keyword_coverage("関係ない文章", ["旅費", "交通費"])
        assert hits == []
        assert cov == pytest.approx(0.0)

    def test_empty_keywords(self):
        hits, cov = check_keyword_coverage("何かの文章", [])
        assert hits == []
        assert cov == pytest.approx(1.0)


# ─── ライブ評価（TAX_NAVIGATOR_URL 設定時のみ） ───────────────────────────────

@pytest.mark.skipif(
    not API_URL,
    reason="TAX_NAVIGATOR_URL が未設定のためスキップ（ライブ評価には設定が必要）",
)
class TestLiveEvaluation:
    """実行中の API に対してゴールデンデータセットを評価する"""

    @pytest.fixture(scope="class")
    def eval_results(self) -> list[EvalResult]:
        return run_evaluation(
            dataset_path=DATASET_PATH,
            api_url=API_URL,
            use_ragas=False,
        )

    def test_no_api_errors(self, eval_results):
        errors = [r for r in eval_results if r.error]
        error_ids = [r.case.id for r in errors]
        assert not errors, f"API エラーが発生したケース: {error_ids}"

    def test_judgment_accuracy_above_threshold(self, eval_results):
        valid = [r for r in eval_results if not r.error]
        matches = sum(1 for r in valid if r.judgment_match)
        acc = matches / len(valid) if valid else 0.0
        assert acc >= 0.70, (
            f"判断精度 {acc:.1%} が閾値 70% を下回っています "
            f"({matches}/{len(valid)} 件一致)"
        )

    def test_average_keyword_coverage_above_threshold(self, eval_results):
        valid = [r for r in eval_results if not r.error]
        avg_cov = sum(r.keyword_coverage for r in valid) / len(valid) if valid else 0.0
        assert avg_cov >= 0.50, (
            f"平均キーワードカバレッジ {avg_cov:.1%} が閾値 50% を下回っています"
        )

    def test_all_responses_have_content(self, eval_results):
        for r in eval_results:
            if not r.error:
                assert r.actual_answer.strip(), (
                    f"{r.case.id}: 回答が空です"
                )

    def test_latency_within_acceptable_range(self, eval_results):
        """平均レイテンシが30秒以内であることを確認する"""
        valid = [r for r in eval_results if not r.error]
        avg_latency = sum(r.latency_ms for r in valid) / len(valid) if valid else 0.0
        assert avg_latency <= 30_000, (
            f"平均レイテンシ {avg_latency:.0f}ms が 30,000ms を超えています"
        )

    def test_sources_returned_for_valid_questions(self, eval_results):
        """有効な質問には出典が返されることを確認する"""
        for r in eval_results:
            if not r.error:
                assert len(r.sources) > 0, (
                    f"{r.case.id}: 出典が0件です"
                )

    def test_ok_cases_are_recognized(self, eval_results):
        """「認められる」ケースが正しく判定されることを確認する"""
        ok_cases = [r for r in eval_results if r.case.expected_judgment == "認められる" and not r.error]
        if not ok_cases:
            pytest.skip("認められるケースがありません")
        matches = sum(1 for r in ok_cases if r.judgment_match)
        acc = matches / len(ok_cases)
        assert acc >= 0.60, (
            f"「認められる」の判断精度 {acc:.1%} が低すぎます ({matches}/{len(ok_cases)})"
        )

    def test_ng_cases_are_recognized(self, eval_results):
        """「認められない」ケースが正しく判定されることを確認する"""
        ng_cases = [r for r in eval_results if r.case.expected_judgment == "認められない" and not r.error]
        if not ng_cases:
            pytest.skip("認められないケースがありません")
        matches = sum(1 for r in ng_cases if r.judgment_match)
        acc = matches / len(ng_cases)
        assert acc >= 0.60, (
            f"「認められない」の判断精度 {acc:.1%} が低すぎます ({matches}/{len(ng_cases)})"
        )
