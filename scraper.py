import asyncio
import json
import re
from datetime import datetime
from playwright.async_api import async_playwright

async def extract_min_price(page, url, country, pvp):
    try:
        if country == "UK":
            await page.set_extra_http_headers({"Accept-Language": "en-GB,en;q=0.9"})
        else:
            await page.set_extra_http_headers({"Accept-Language": "es-ES,es;q=0.9"})

        resp = await page.goto(url, wait_until="domcontentloaded", timeout=35000)
        if not resp or resp.status >= 400:
            return None

        await page.wait_for_timeout(3500)
        html = await page.content()

        candidates = []

        # 1. JSON-LD lowPrice / price
        for m in re.finditer(r'"(?:lowPrice|price)"\s*:\s*["\']?([\d]+(?:[.,]\d{1,2})?)["\']?', html, re.I):
            val = normalize_price(m.group(1))
            if val:
                candidates.append(val)

        # 2. OpenGraph / Microdata price
        for m in re.finditer(r'(?:product:price:amount|og:price:amount|itemprop=["\']price["\'])[^>]*content=["\']([\d.,]+)["\']', html, re.I):
            val = normalize_price(m.group(1))
            if val:
                candidates.append(val)

        # 3. Visible DOM price elements evaluated directly in browser JS
        dom_prices = await page.evaluate('''() => {
            const selectors = [
                '[itemprop="price"]', '.product-price', '.price-sales', '#js-precio',
                '.pdp-price', '.product-page-price', '.price--main', '.current-price',
                '[data-testid="price"]', '.product-price__price', '.final-price'
            ];
            const found = [];
            selectors.forEach(sel => {
                document.querySelectorAll(sel).forEach(el => {
                    const txt = el.innerText || el.getAttribute('content') || '';
                    found.push(txt);
                });
            });
            return found;
        }''')

        for txt in dom_prices:
            for m in re.finditer(r'([\d]{2,3}(?:[.,]\d{1,2})?)', txt):
                val = normalize_price(m.group(1))
                if val:
                    candidates.append(val)

        # Filter valid wetsuit prices (between 25% and 120% of official RRP, never inventing anything)
        valid = [p for p in candidates if (pvp * 0.25) <= p <= (pvp * 1.20)]
        if not valid:
            return None
        return round(min(valid), 2)
    except Exception as e:
        print(f"Error reading {url}: {e}")
        return None

def normalize_price(val_str):
    try:
        s = re.sub(r'[^\d.,]', '', str(val_str).strip())
        if ',' in s and '.' in s:
            if s.rfind(',') > s.rfind('.'):
                s = s.replace('.', '').replace(',', '.')
            else:
                s = s.replace(',', '')
        elif ',' in s:
            s = s.replace(',', '.')
        return float(s)
    except:
        return None

async def main():
    with open("data/tracking.json", "r", encoding="utf-8") as f:
        tracking = json.load(f)
    with open("data/history.json", "r", encoding="utf-8") as f:
        history = json.load(f)

    now_dt = datetime.utcnow()
    today_str = now_dt.strftime("%Y-%m-%d")
    now_str = now_dt.strftime("%Y-%m-%d %H:%M")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        context_es = await browser.new_context(
            locale="es-ES",
            timezone_id="Europe/Madrid",
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
        context_uk = await browser.new_context(
            locale="en-GB",
            timezone_id="Europe/London",
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )

        page_es = await context_es.new_page()
        page_uk = await context_uk.new_page()

        updated_count = 0
        for row in tracking:
            url = row.get("url", "").strip()
            if not url:
                continue
            page = page_uk if row["country"] == "UK" else page_es
            min_price = await extract_min_price(page, url, row["country"], row["pvp"])

            # STRICT RULE: Only update if a real verified price was extracted from the page
            if min_price is not None and min_price > 0:
                row["price"] = min_price
                row["disc_imp"] = round(row["pvp"] - min_price, 2)
                row["disc_pct"] = round((row["disc_imp"] / row["pvp"]) * 100, 1)
                row["status"] = "VERIFIED"
                row["last_read"] = today_str
                row["out_of_stock"] = False
                row["is_from"] = False
                updated_count += 1

                # Update or append today's reading in history
                history = [
                    h for h in history
                    if not (str(h.get("timestamp", ""))[:10] == today_str and h.get("country") == row["country"] and h.get("operator") == row["operator"] and h.get("code") == row["code"])
                ]
                history.append({
                    "timestamp": today_str,
                    "country": row["country"],
                    "currency": row["currency"],
                    "operator": row["operator"],
                    "code": row["code"],
                    "model": row["model"],
                    "pvp": row["pvp"],
                    "price": min_price,
                    "disc_imp": row["disc_imp"],
                    "disc_pct": row["disc_pct"],
                    "out_of_stock": False,
                    "is_from": False,
                    "url": url
                })

        await browser.close()

    # Sort history chronologically
    history.sort(key=lambda x: (str(x.get("timestamp", "")), x.get("country", ""), x.get("operator", ""), x.get("code", "")))

    with open("data/tracking.json", "w", encoding="utf-8") as f:
        json.dump(tracking, f, indent=2, ensure_ascii=False)
    with open("data/history.json", "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2, ensure_ascii=False)

    # Build compact history array for index.html: [date, country, operator, code, price, disc_pct, out_of_stock_int, is_from_int]
    history_compact = [
        [
            str(h.get("timestamp", ""))[:10],
            h["country"],
            h["operator"],
            h["code"],
            float(h["price"]),
            float(h["disc_pct"]),
            1 if h.get("out_of_stock") else 0,
            1 if h.get("is_from") else 0
        ]
        for h in history
    ]

    # Inject updated DATA_ROWS and HISTORY_COMPACT into index.html for GitHub Pages
    with open("index.html", "r", encoding="utf-8") as f:
        html_doc = f.read()

    html_doc = re.sub(
        r"const DATA_ROWS = \[.*?\];",
        "const DATA_ROWS = " + json.dumps(tracking, ensure_ascii=False) + ";",
        html_doc,
        flags=re.S
    )
    html_doc = re.sub(
        r"const HISTORY_COMPACT = \[.*?\];",
        "const HISTORY_COMPACT = " + json.dumps(history_compact, ensure_ascii=False) + ";",
        html_doc,
        flags=re.S
    )
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html_doc)

    print(f"Scan finished at {now_str}. Real verified prices updated: {updated_count}. Total history records: {len(history_compact)}")

if __name__ == "__main__":
    asyncio.run(main())
