"""
国税不服審判所 公表裁決事例 スクレイパー

サイト構造:
  https://www.kfs.go.jp/service/JP/index.html  - 集号一覧（No.43〜）
  https://www.kfs.go.jp/service/JP/idx/N.html  - 各集号のインデックス
  https://www.kfs.go.jp/service/JP/N/XXX.html  - 個別裁決事例

出力: data/tribunal_cases.jsonl
※ サイトは Shift-JIS エンコーディング
"""

import json
import time
import re
import os
from datetime import date
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

BASE_URL    = "https://www.kfs.go.jp"
JP_INDEX    = "https://www.kfs.go.jp/service/JP/index.html"
TODAY       = str(date.today())
INTERVAL    = 2.0
OUTPUT_DIR  = os.path.join(os.path.dirname(__file__), "data")
ENCODING    = "shift_jis"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; TaxNavigator/1.0; research use)"
}


def fetch(client: httpx.Client, url: str) -> BeautifulSoup | None:
    try:
        r = client.get(url, timeout=30)
        r.raise_for_status()
        text = r.content.decode(ENCODING, errors="replace")
        return BeautifulSoup(text, "lxml")
    except Exception as e:
        print(f"  [SKIP] {url} -> {e}")
        return None


def clean_text(el) -> str:
    if el is None:
        return ""
    return re.sub(r"\s+", " ", el.get_text(separator=" ")).strip()


def scrape_tribunal():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    out_path = os.path.join(OUTPUT_DIR, "tribunal_cases.jsonl")
    count = 0
    seen_urls = set()

    with httpx.Client(headers=HEADERS, follow_redirects=True) as client, \
         open(out_path, "w", encoding="utf-8") as f:

        print("=== 国税不服審判所 裁決事例 ===")

        # 集号インデックス一覧を取得
        top = fetch(client, JP_INDEX)
        time.sleep(INTERVAL)
        if top is None:
            print("インデックスページ取得失敗")
            return

        # idx/N.html 形式のリンクを収集
        vol_links = []
        for a in top.select("a[href]"):
            href = a["href"]
            if re.search(r"idx/\d+\.html", href):
                full = urljoin(JP_INDEX, href)
                vol_links.append((clean_text(a), full))

        print(f"集号数: {len(vol_links)} 冊")

        # 各集号から個別事例リンクを収集
        article_links: list[tuple[str, str]] = []

        for vol_title, vol_url in vol_links:
            vol_soup = fetch(client, vol_url)
            time.sleep(INTERVAL)
            if vol_soup is None:
                continue

            # 個別事例は ../N/NN/index.html 形式（集号インデックスからの相対パス）
            for a in vol_soup.select("a[href]"):
                href = a["href"]
                link_text = clean_text(a)
                # 「裁決事例」テキストのリンク、または /service/JP/数字/数字/ パターン
                if link_text == "裁決事例" or re.search(r"/JP/\d+/\d+/", href):
                    full = urljoin(vol_url, href)
                    if full not in seen_urls and "/service/JP/" in full:
                        seen_urls.add(full)
                        article_links.append((vol_title, full))

        print(f"個別事例候補: {len(article_links)} 件")

        # 個別事例をスクレイプ
        for vol_title, url in article_links:
            soup = fetch(client, url)
            time.sleep(INTERVAL)
            if soup is None:
                continue

            title_el = soup.select_one("h1, h2, h3, .case-title")
            title = clean_text(title_el) or vol_title

            # 本文エリアを取得
            body = soup.select_one(
                "#contents, .contents, article, .main, #main"
            )
            if body is None:
                body = soup.select_one("body")

            content = clean_text(body)
            if len(content) < 100:
                continue

            record = {
                "source":     "tribunal_cases",
                "url":        url,
                "title":      title,
                "category":   vol_title,
                "content":    content,
                "scraped_at": TODAY,
            }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            count += 1
            if count % 10 == 0:
                print(f"  {count} 件完了...")

    print(f"裁決事例 完了: {count} 件 -> {out_path}")


if __name__ == "__main__":
    scrape_tribunal()
