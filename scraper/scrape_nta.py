"""
国税庁 タックスアンサー・質疑応答事例 スクレイパー

出力: data/nta_taxanswer.jsonl / data/nta_shitsugi.jsonl
"""

import json
import time
import re
import os
from datetime import date
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

BASE_URL = "https://www.nta.go.jp"
TODAY = str(date.today())
INTERVAL = 1.5  # 秒（robots.txt 尊重）
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "data")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; TaxNavigator/1.0; research use)"
}


def fetch(client: httpx.Client, url: str) -> BeautifulSoup | None:
    try:
        r = client.get(url, timeout=20)
        r.raise_for_status()
        r.encoding = r.charset_encoding or "utf-8"
        return BeautifulSoup(r.text, "lxml")
    except Exception as e:
        print(f"  [SKIP] {url} -> {e}")
        return None


def clean_text(soup_element) -> str:
    if soup_element is None:
        return ""
    return re.sub(r"\s+", " ", soup_element.get_text(separator=" ")).strip()


# ──────────────────────────────────────────
# タックスアンサー
# ──────────────────────────────────────────

TAXANSWER_TOP = "https://www.nta.go.jp/taxes/shiraberu/taxanswer/index2.htm"


def scrape_taxanswer():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    out_path = os.path.join(OUTPUT_DIR, "nta_taxanswer.jsonl")
    seen_urls = set()
    count = 0

    with httpx.Client(headers=HEADERS, follow_redirects=True) as client, \
         open(out_path, "w", encoding="utf-8") as f:

        print("=== タックスアンサー ===")
        top = fetch(client, TAXANSWER_TOP)
        if top is None:
            print("トップページ取得失敗")
            return

        time.sleep(INTERVAL)

        # カテゴリリンクを収集
        category_links = []
        for a in top.select("a[href]"):
            href = a["href"]
            if "/taxanswer/" in href and href.endswith(".htm"):
                full = urljoin(BASE_URL, href)
                if full not in seen_urls:
                    seen_urls.add(full)
                    category_links.append((clean_text(a), full))

        print(f"カテゴリ候補: {len(category_links)} 件")

        # 各カテゴリページを取得→個別ページのリンクを収集
        article_links = []
        seen_articles = set()

        for cat_title, cat_url in category_links:
            cat_soup = fetch(client, cat_url)
            time.sleep(INTERVAL)
            if cat_soup is None:
                continue

            for a in cat_soup.select("a[href]"):
                href = a["href"]
                if "/taxanswer/" in href and href.endswith(".htm"):
                    full = urljoin(BASE_URL, href)
                    if full not in seen_articles and full != cat_url:
                        seen_articles.add(full)
                        article_links.append((cat_title, full))

        print(f"個別ページ候補: {len(article_links)} 件")

        # 個別ページをスクレイプ
        for cat_title, url in article_links:
            soup = fetch(client, url)
            time.sleep(INTERVAL)
            if soup is None:
                continue

            title_el = soup.select_one("h1, h2, .mainTitle")
            title = clean_text(title_el) or cat_title

            # 本文エリアを取得（サイドバー・ナビを除く）
            body = soup.select_one("#main-content, .main-content, article, .contentsInner")
            if body is None:
                body = soup.select_one("body")

            content = clean_text(body)
            if len(content) < 100:
                continue

            record = {
                "source": "nta_tax_answer",
                "url": url,
                "title": title,
                "category": cat_title,
                "content": content,
                "scraped_at": TODAY,
            }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            count += 1
            if count % 20 == 0:
                print(f"  {count} 件完了...")

    print(f"タックスアンサー 完了: {count} 件 -> {out_path}")


# ──────────────────────────────────────────
# 質疑応答事例
# ──────────────────────────────────────────

SHITSUGI_TOP = "https://www.nta.go.jp/law/shitsugi/01.htm"


def scrape_shitsugi():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    out_path = os.path.join(OUTPUT_DIR, "nta_shitsugi.jsonl")
    count = 0

    with httpx.Client(headers=HEADERS, follow_redirects=True) as client, \
         open(out_path, "w", encoding="utf-8") as f:

        print("=== 質疑応答事例 ===")
        top = fetch(client, SHITSUGI_TOP)
        if top is None:
            print("トップページ取得失敗")
            return
        time.sleep(INTERVAL)

        # 大カテゴリリンク（所得税、法人税、消費税など）
        seen_cat = set()
        cat_links = []
        for a in top.select("a[href]"):
            href = a["href"]
            if "/shitsugi/" in href and href.endswith(".htm"):
                full = urljoin("https://www.nta.go.jp/law/shitsugi/", href)
                full = urljoin(BASE_URL, urlparse(full).path)
                if full not in seen_cat:
                    seen_cat.add(full)
                    cat_links.append((clean_text(a), full))

        print(f"大カテゴリ: {len(cat_links)} 件")

        seen_articles = set()
        article_links = []

        for cat_name, cat_url in cat_links:
            cat_soup = fetch(client, cat_url)
            time.sleep(INTERVAL)
            if cat_soup is None:
                continue

            for a in cat_soup.select("a[href]"):
                href = a["href"]
                if "/shitsugi/" in href and href.endswith(".htm"):
                    full = urljoin(cat_url, href)
                    if full not in seen_articles and full != cat_url:
                        seen_articles.add(full)
                        article_links.append((cat_name, full))

            # サブカテゴリも一段掘る
            for sub_a in cat_soup.select("a[href]"):
                sub_href = sub_a["href"]
                if "/shitsugi/" in sub_href and sub_href.endswith(".htm"):
                    sub_full = urljoin(cat_url, sub_href)
                    if sub_full in seen_cat:
                        continue
                    seen_cat.add(sub_full)
                    sub_soup = fetch(client, sub_full)
                    time.sleep(INTERVAL)
                    if sub_soup is None:
                        continue
                    for a2 in sub_soup.select("a[href]"):
                        h2 = a2["href"]
                        if "/shitsugi/" in h2 and h2.endswith(".htm"):
                            full2 = urljoin(sub_full, h2)
                            if full2 not in seen_articles and full2 != sub_full:
                                seen_articles.add(full2)
                                article_links.append((cat_name, full2))

        print(f"個別事例候補: {len(article_links)} 件")

        for cat_name, url in article_links:
            soup = fetch(client, url)
            time.sleep(INTERVAL)
            if soup is None:
                continue

            title_el = soup.select_one("h1, h2, .mainTitle, .question")
            title = clean_text(title_el) or url

            body = soup.select_one("#main-content, .main-content, article, .contentsInner")
            if body is None:
                body = soup.select_one("body")

            content = clean_text(body)
            if len(content) < 100:
                continue

            record = {
                "source": "nta_qa_cases",
                "url": url,
                "title": title,
                "category": cat_name,
                "content": content,
                "scraped_at": TODAY,
            }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            count += 1
            if count % 20 == 0:
                print(f"  {count} 件完了...")

    print(f"質疑応答事例 完了: {count} 件 -> {out_path}")


if __name__ == "__main__":
    scrape_taxanswer()
    scrape_shitsugi()
