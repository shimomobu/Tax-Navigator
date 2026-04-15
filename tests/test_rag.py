"""
純粋関数（build_prompt, get_source_label）のユニットテスト
"""
import pytest
from app.main import build_prompt, get_source_label, SYSTEM_PROMPT


class TestGetSourceLabel:
    def test_nta_tax_answer(self):
        assert get_source_label("nta_tax_answer") == "国税庁タックスアンサー"

    def test_nta_qa_cases(self):
        assert get_source_label("nta_qa_cases") == "国税庁質疑応答事例"

    def test_tribunal_cases(self):
        assert get_source_label("tribunal_cases") == "国税不服審判所裁決事例"

    def test_nta_tsutatsu(self):
        assert get_source_label("nta_tsutatsu") == "国税庁法令解釈通達"

    def test_unknown_source_returns_original(self):
        assert get_source_label("unknown_source") == "unknown_source"

    def test_empty_string(self):
        assert get_source_label("") == ""


class TestBuildPrompt:
    def test_contains_system_prompt(self):
        result = build_prompt("コンテキスト", "質問")
        assert SYSTEM_PROMPT in result

    def test_contains_question(self):
        question = "この経費は認められますか？"
        result = build_prompt("コンテキスト", question)
        assert question in result

    def test_contains_context(self):
        context = "【文書1】テスト文書\n内容テスト"
        result = build_prompt(context, "質問")
        assert context in result

    def test_contains_reference_section_header(self):
        result = build_prompt("コンテキスト", "質問")
        assert "【参照文書】" in result

    def test_contains_question_section_header(self):
        result = build_prompt("コンテキスト", "質問")
        assert "【質問】" in result
