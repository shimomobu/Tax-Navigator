"""
国税庁 法令解釈通達 スクレイパー

対象: 所得税・消費税・国税通則法関連の通達
出力: data/nta_tsutatsu.jsonl
"""

import json
import time
import re
import os
from datetime import date
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

BASE_URL = "https://www.nta.go.jp"
TSUTATSU_TOP = "https://www.nta.go.jp/law/tsutatsu/menu.htm"
TODAY = str(date.today())
INTERVAL = 1.5
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "data")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; TaxNavigator/1.0; research use)"
}

# 個人事業主に関連性の高い通達カテゴリのキーワード
RELEVANT_KEYWORDS = [
    "所得税", "消費税", "国税通則", "青色申告", "必要経費",
    "事業所得", "雑所得", "家事関連費", "減価償却",
]


def fetch(client: httpx.Client, url: str) -> BeautifulSoup | None:
    try:
        r = client.get(url, timeout=20)
        r.raise_for_status()
        r.encoding = r.charset_encoding or "utf-8"
        return BeautifulSoup(r.text, "lxml")
    except Exception as e:
        print(f"  [SKIP] {url} -> {e}")
        return None


def clean_text(el) -> str:
    if el is None:
        return ""
    return re.sub(r"\s+", " ", el.get_text(separator=" ")).strip()


def is_relevant(text: str) -> bool:
    return any(kw in text for kw in RELEVANT_KEYWORDS)


def scrape_tsutatsu():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    out_path = os.path.join(OUTPUT_DIR, "nta_tsutatsu.jsonl")
    count = 0
    seen_urls = set()

    with httpx.Client(headers=HEADERS, follow_redirects=True) as client, \
         open(out_path, "w", encoding="utf-8") as f:

        print("=== 法令解釈通達 ===")
        top = fetch(client, TSUTATSU_TOP)
        if top is None:
            print("トップページ取得失敗")
            return
        time.sleep(INTERVAL)

        # トップページのカテゴリリンクを収集
        cat_links: list[tuple[str, str]] = []
        seen_cat = set()

        for a in top.select("a[href]"):
            href = a["href"]
            link_text = clean_text(a)
            if "/tsutatsu/" in href and href.endswith((".htm", ".html")):
                full = urljoin(BASE_URL, href)
                if full not in seen_cat:
                    seen_cat.add(full)
                    cat_links.append((link_text, full))

        print(f"通達カテゴリ候補: {len(cat_links)} 件")

        # 関連性の高いカテゴリを優先しつつ全件処理
        article_links: list[tuple[str, str]] = []
        seen_articles = set()

        for cat_name, cat_url in cat_links:
            relevant = is_relevant(cat_name)
            cat_soup = fetch(client, cat_url)
            time.sleep(INTERVAL)
            if cat_soup is None:
                continue

            for a in cat_soup.select("a[href]"):
                href = a["href"]
                link_text = clean_text(a)
                if "/tsutatsu/" in href and href.endswith((".htm", ".html")):
                    full = urljoin(BASE_URL, href)
                    if full not in seen_articles and full != cat_url:
                        seen_articles.add(full)
                        # 関連キーワードがあるものを優先リストに
                        priority = relevant or is_relevant(link_text)
                        article_links.append((cat_name, full, priority))

        # 関連性高いものを先に処理
        article_links.sort(key=lambda x: (not x[2], x[0]))
        print(f"通達個別ページ候補: {len(article_links)} 件")

        for cat_name, url, _ in article_links:
            soup = fetch(client, url)
            time.sleep(INTERVAL)
            if soup is None:
                continue

            title_el = soup.select_one("h1, h2, .mainTitle")
            title = clean_text(title_el) or cat_name

            body = soup.select_one(
                "#main-content, .main-content, article, .contentsInner, .content"
            )
            if body is None:
                body = soup.select_one("body")

            content = clean_text(body)
            if len(content) < 100:
                continue

            record = {
                "source": "nta_tsutatsu",
                "url": url,
                "title": title,
                "category": cat_name,
                "content": content,
                "scraped_at": TODAY,
            }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            count += 1
            if count % 10 == 0:
                print(f"  {count} 件完了...")

    print(f"法令解釈通達 完了: {count} 件 -> {out_path}")


if __name__ == "__main__":
    scrape_tsutatsu()
