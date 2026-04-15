// @ts-check
const { test, expect } = require('@playwright/test');

// ─── モックデータ ───────────────────────────────────────────────────────────

const MOCK_ANSWER_OK = `## 判断
経費として認められる

## 根拠
所得税法第37条（必要経費）に基づき、業務に直接関連する費用は必要経費として認められます。

## 注意事項
業務使用であることの記録（領収書・出張報告書等）を適切に保管してください。

## 仕訳
| 借方科目 | 借方金額 | 貸方科目 | 貸方金額 | 摘要 | 消費税区分 |
|---|---|---|---|---|---|
| 旅費交通費 | 1,000 | 現金 | 1,000 | 電車代（業務用） | 課税仕入10% |`;

const MOCK_ANSWER_NG = `## 判断
経費として認められない

## 根拠
プライベートな支出は必要経費に該当しません。`;

const MOCK_ANSWER_GRAY = `## 判断
グレーゾーン（要確認）

## 根拠
業務関連性の割合により判断が異なります。税理士への確認を推奨します。`;

const MOCK_SOURCES = [
  {
    title: 'タックスアンサーNo.2210 やさしい必要経費の知識',
    source: 'nta_tax_answer',
    url: 'https://www.nta.go.jp/taxes/shiraberu/taxanswer/shotoku/2210.htm',
    category: '所得税',
  },
  {
    title: '自宅兼事務所の経費',
    source: 'nta_qa_cases',
    url: 'https://www.nta.go.jp/law/shitsugi/shotoku/04/01.htm',
    category: '所得税',
  },
];

function mockAsk(page, answer, sources = MOCK_SOURCES) {
  return page.route('/ask', route =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ answer, sources, reranked_chunks: sources.length }),
    })
  );
}

// ─── テスト ─────────────────────────────────────────────────────────────────

test.describe('ページ読み込み', () => {
  test('タイトルと入力フォームが表示される', async ({ page }) => {
    await page.goto('/');
    await expect(page).toHaveTitle('Tax Navigator');
    await expect(page.locator('h1')).toContainText('TAX NAVIGATOR');
    await expect(page.locator('#question')).toBeVisible();
    await expect(page.locator('#ask-btn')).toBeVisible();
    await expect(page.locator('#clear-btn')).toBeVisible();
  });

  test('初期状態で result-area は空', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('#result-area')).toBeEmpty();
  });
});

test.describe('質問送信', () => {
  test('回答カードと出典カードが表示される', async ({ page }) => {
    await mockAsk(page, MOCK_ANSWER_OK);
    await page.goto('/');

    await page.fill('#question', '交通費は経費になりますか？');
    await page.click('#ask-btn');

    await expect(page.locator('.answer-card')).toBeVisible();
    await expect(page.locator('.sources-card')).toBeVisible();
  });

  test('回答カードに参照件数が表示される', async ({ page }) => {
    await mockAsk(page, MOCK_ANSWER_OK);
    await page.goto('/');

    await page.fill('#question', '交通費は経費になりますか？');
    await page.click('#ask-btn');

    await expect(page.locator('.answer-card-header')).toContainText('件の文書を参照');
  });

  test('回答に ## 見出しがレンダリングされる', async ({ page }) => {
    await mockAsk(page, MOCK_ANSWER_OK);
    await page.goto('/');

    await page.fill('#question', '交通費は経費になりますか？');
    await page.click('#ask-btn');

    const h2s = page.locator('.answer-body h2');
    await expect(h2s.first()).toBeVisible();
    await expect(h2s.first()).toContainText('判断');
  });

  test('回答に仕訳テーブルがレンダリングされる', async ({ page }) => {
    await mockAsk(page, MOCK_ANSWER_OK);
    await page.goto('/');

    await page.fill('#question', '仕訳を教えてください');
    await page.click('#ask-btn');

    await expect(page.locator('.answer-body table')).toBeVisible();
    await expect(page.locator('.answer-body th').first()).toContainText('借方科目');
  });
});

test.describe('判断バッジの色分け', () => {
  test('「経費として認められる」は緑色バッジ', async ({ page }) => {
    await mockAsk(page, MOCK_ANSWER_OK);
    await page.goto('/');
    await page.fill('#question', '交通費は？');
    await page.click('#ask-btn');

    await expect(page.locator('.badge-ok')).toBeVisible();
    await expect(page.locator('.badge-ok')).toContainText('経費として認められる');
  });

  test('「経費として認められない」は赤色バッジ', async ({ page }) => {
    await mockAsk(page, MOCK_ANSWER_NG);
    await page.goto('/');
    await page.fill('#question', '私用の支出は？');
    await page.click('#ask-btn');

    await expect(page.locator('.badge-ng')).toBeVisible();
    await expect(page.locator('.badge-ng')).toContainText('経費として認められない');
  });

  test('「グレーゾーン」はオレンジバッジ', async ({ page }) => {
    await mockAsk(page, MOCK_ANSWER_GRAY);
    await page.goto('/');
    await page.fill('#question', '按分の場合は？');
    await page.click('#ask-btn');

    await expect(page.locator('.badge-gray')).toBeVisible();
    await expect(page.locator('.badge-gray')).toContainText('グレーゾーン');
  });
});

test.describe('出典カード', () => {
  test('出典件数がサマリーに表示される', async ({ page }) => {
    await mockAsk(page, MOCK_ANSWER_OK);
    await page.goto('/');
    await page.fill('#question', '質問');
    await page.click('#ask-btn');

    await expect(page.locator('.sources-card summary')).toContainText('参照出典 (2 件)');
  });

  test('出典を開くと出典アイテムが表示される', async ({ page }) => {
    await mockAsk(page, MOCK_ANSWER_OK);
    await page.goto('/');
    await page.fill('#question', '質問');
    await page.click('#ask-btn');

    await page.locator('.sources-card summary').click();
    await expect(page.locator('.source-item').first()).toBeVisible();
    await expect(page.locator('.source-badge').first()).toContainText('国税庁タックスアンサー');
  });
});

test.describe('クリアボタン', () => {
  test('クリアボタンで入力と結果が消える', async ({ page }) => {
    await mockAsk(page, MOCK_ANSWER_OK);
    await page.goto('/');

    await page.fill('#question', '交通費は？');
    await page.click('#ask-btn');
    await expect(page.locator('.answer-card')).toBeVisible();

    await page.click('#clear-btn');
    await expect(page.locator('#question')).toHaveValue('');
    await expect(page.locator('#result-area')).toBeEmpty();
  });
});

test.describe('キーボードショートカット', () => {
  test('Ctrl+Enter で質問が送信される', async ({ page }) => {
    await mockAsk(page, MOCK_ANSWER_OK);
    await page.goto('/');

    await page.fill('#question', 'Ctrl+Enterテスト');
    await page.locator('#question').press('Control+Enter');

    await expect(page.locator('.answer-card')).toBeVisible();
  });
});

test.describe('入力バリデーション', () => {
  test('空の質問では /ask リクエストが発生しない', async ({ page }) => {
    const requests = [];
    await page.route('/ask', route => {
      requests.push(route);
      route.fulfill({ status: 200, contentType: 'application/json', body: '{}' });
    });

    await page.goto('/');
    await page.click('#ask-btn');

    await page.waitForTimeout(300);
    expect(requests).toHaveLength(0);
  });
});

test.describe('エラーハンドリング', () => {
  test('API エラー時にエラーカードが表示される', async ({ page }) => {
    await page.route('/ask', route =>
      route.fulfill({
        status: 503,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'ナレッジベースに接続できません' }),
      })
    );

    await page.goto('/');
    await page.fill('#question', '質問');
    await page.click('#ask-btn');

    await expect(page.locator('.error-card')).toBeVisible();
    await expect(page.locator('.error-card')).toContainText('エラー');
  });
});
