"""
裁決事例・税務文書のsentiment分類スクリプト

各JSONLレコードのcontentをLLMで分析し、以下のメタデータを付与する:
  sentiment: positive / negative / neutral
  result:    認容 / 棄却 / 一部認容 / 不明

使い方:
  python3 classify_sentiment.py --input data/tribunal_cases.jsonl --output data/tribunal_cases_classified.jsonl
  python3 classify_sentiment.py --input data/nta_taxanswer.jsonl --output data/nta_taxanswer_classified.jsonl
"""

import argparse
import json
import time
from pathlib import Path

import httpx

OLLAMA_URL = "http://localhost:11434"
MODEL = "gemma4:e4b"
INTERVAL = 0.5  # 秒

CLASSIFY_PROMPT = """以下の税務文書を分析して、JSON形式のみで回答してください。

【分類基準】
- sentiment:
  - positive: 納税者の主張が認められた、経費が認められた、控除が認められた等
  - negative: 納税者の主張が棄却された、経費が認められなかった、更正処分が維持された等
  - neutral: 手続き的な内容、一般的な解説、認否が混在する等

- result（裁決事例の場合）:
  - 認容: 納税者の請求が認められた
  - 棄却: 納税者の請求が棄却された
  - 一部認容: 一部のみ認められた
  - 不明: 裁決事例でない、または判断不明

【文書】
{content}

【回答形式】JSONのみ。説明不要。
{{"sentiment": "positive|negative|neutral", "result": "認容|棄却|一部認容|不明"}}"""


def classify(client: httpx.Client, content: str) -> dict:
    prompt = CLASSIFY_PROMPT.format(content=content[:1000])  # 長すぎる場合は先頭1000文字で判断
    try:
        r = client.post(
            f"{OLLAMA_URL}/api/generate",
            json={
                "model": MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0},
            },
            timeout=60,
        )
        text = r.json()["response"].strip()
        # JSON部分だけ抽出
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(text[start:end])
    except Exception as e:
        print(f"  [WARN] 分類エラー: {e}")
    return {"sentiment": "neutral", "result": "不明"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--resume", action="store_true", help="出力ファイルが存在する場合は続きから再開")
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)

    # resume: 処理済みURLを収集
    done_urls = set()
    if args.resume and output_path.exists():
        with open(output_path, encoding="utf-8") as f:
            for line in f:
                try:
                    done_urls.add(json.loads(line)["url"])
                except Exception:
                    pass
        print(f"再開: 処理済み {len(done_urls)} 件をスキップ")

    records = []
    with open(input_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except Exception:
                    pass

    print(f"入力: {len(records)} 件")
    print(f"処理対象: {len(records) - len(done_urls)} 件")

    mode = "a" if args.resume else "w"
    processed = 0
    skipped = 0

    with httpx.Client() as client, open(output_path, mode, encoding="utf-8") as out:
        for i, record in enumerate(records, 1):
            if record.get("url") in done_urls:
                skipped += 1
                continue

            result = classify(client, record.get("content", ""))
            record["sentiment"] = result.get("sentiment", "neutral")
            record["result"] = result.get("result", "不明")

            out.write(json.dumps(record, ensure_ascii=False) + "\n")
            out.flush()
            processed += 1

            if processed % 50 == 0:
                print(f"  {i}/{len(records)} 件完了 (処理:{processed} スキップ:{skipped})")

            time.sleep(INTERVAL)

    print(f"完了: 処理 {processed} 件 / スキップ {skipped} 件 -> {output_path}")


if __name__ == "__main__":
    main()
