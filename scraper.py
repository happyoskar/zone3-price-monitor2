import asyncio
import json
import re
from datetime import datetime
from playwright.async_api import async_playwright

GENERIC_URL_PATTERNS = [
    "/brands/zone-3",
    "/wetsuits/zone3/",
    "/natacion-zone3",
    "swimming-triathlon",
    "zone3%3awomen",
    "/store/zone-3/",
    "/marcas/zone3"
]

MODEL_KEYWORDS = {
    "WS22MVAN101": ["vanquish"],
    "WS22WVAN101": ["vanquish"],
    "WS25MASP101": ["aspire"],
    "WS25WASP101": ["aspire"],
    "WS24MVIS101": ["vision"],
    "WS24WVIS101": ["vision"],
    "WS21MADV101": ["advance", "advence"],
    "WS21WADV101": ["advance", "advence"],
    "WS21MAGI116": ["agile"],
    "WS21WAGI114": ["agile"],
    "WS26MGLISL101": ["ascend", "glide"],
    "WS26WGLISL101": ["ascend", "glide"],
    "WS25MACTF101": ["active-flex", "active flex", "activeflex"],
    "WS25WACTF101": ["active-flex", "active flex", "activeflex"],
    "WS25MSRV101": ["versa"],
    "WS25WSRV101": ["versa"]
}

FEMALE_TOKENS = ["women", "woman", "mujer", "dames", "femme", "womens", "ladies", "chica"]
MALE_TOKENS = ["men", "man", "hombre", "heren", "homme", "mens"]

def is_generic_category_url(u):
    if not u or not isinstance(u, str):
        return True
    u_low = u.lower().strip()
    if u_low.endswith("/zone3") or u_low.endswith("/zone3/"):
        return True
    return any(p in u_low for p in GENERIC_URL_PATTERNS)

def normalize_price(val_str):
    try:
        s = re.sub(r"[^\d.,]", "", str(val_str).strip())
        if not s:
            return None
        if "," in s and "." in s:
            if s.rfind(",") > s.rfind("."):
                s = s.replace(".", "").replace(",", ".")
            else:
                s = s.replace(",", "")
        elif "," in s:
            s = s.replace(",", ".")
        return float(s)
    except:
        return None

def validate_product_identity(title_h1_text, url, code, model_name):
    combined = f"{title_h1_text} {url}".lower()
    keywords = MODEL_KEYWORDS.get(code, [])
    if keywords and not any(k in combined for k in keywords):
        return False, f"El títol ({title_h1_text[:45]}) no conté el model ({'/'.join(keywords)})"

    is_womens_model = "W" in code[4:6] or "women" in model_name.lower()
    has_female_word = any(re.search(r"\b" + w + r"\b", combined) for w in FEMALE_TOKENS)
    if is_womens_model and not has_female_word:
        return False, f"S'esperava model de dona però la fitxa no indica Women/Mujer ({title_h1_text[:40]})"
    if not is_womens_model and has_female_word:
        return False, f"S'esperava model d'home però la fitxa indica Women/Mujer ({title_h1_text[:40]})"

    return True, "Identitat validada"

async def extract_verified_pdp_price(page, row):
    url = row.get("url", "").strip()
    country = row["country"]
    expected_curr = row["currency"]
    pvp = float(row["pvp"])
    code = row["code"]
    model_name = row["model"]

    if is_generic_category_url(url):
        return None, False, "PENDING_PDP", "En quarantena: URL de categoria genèrica (cal fitxa individual PDP)"

    try:
        if country == "UK":
            await page.set_extra_http_headers({"Accept-Language": "en-GB,en;q=0.9"})
        else:
            await page.set_extra_http_headers({"Accept-Language": "es-ES,es;q=0.9"})

        resp = await page.goto(url, wait_until="domcontentloaded", timeout=35000)
        if not resp or resp.status >= 400:
            return None, False, "HTTP_ERROR", f"HTTP {resp.status if resp else 'Timeout'}"

        await page.wait_for_timeout(3500)

        page_info = await page.evaluate("""() => {
            const title = document.title || "";
            const h1 = Array.from(document.querySelectorAll("h1")).map(e => e.innerText.trim()).join(" | ");
            const ldNodes = Array.from(document.querySelectorAll('script[type="application/ld+json"]')).map(s => s.innerText);
            const metaCurr = (document.querySelector('meta[property="product:price:currency"], meta[property="og:price:currency"], [itemprop="priceCurrency"]') || {}).content || "";
            const metaPrice = (document.querySelector('meta[property="product:price:amount"], meta[property="og:price:amount"], meta[itemprop="price"]') || {}).content || "";

            const selectors = [
                '[itemprop="price"]', '.product-price', '.price-sales', '#js-precio',
                '.pdp-price', '.product-page-price', '.price--main', '.current-price',
                '[data-testid="price"]', '.product-price__price', '.final-price',
                '.price-box__price', '.product-card__price', '.c-price'
            ];
            const domPrices = [];
            selectors.forEach(sel => {
                document.querySelectorAll(sel).forEach(el => {
                    // Ignore crossed-out old RRP prices
                    if (el.closest('del, s, .old-price, .price-old, .rrp, .strike')) return;
                    const txt = (el.innerText || el.getAttribute("content") || "").trim();
                    if (txt) domPrices.push({ selector: sel, text: txt });
                });
            });

            const bodyText = (document.body ? document.body.innerText : "").slice(0, 5000);
            return { title, h1, ldNodes, metaCurr, metaPrice, domPrices, bodyText };
        }""")

        title_h1 = f"{page_info['title']} | {page_info['h1']}".strip()
        id_ok, id_msg = validate_product_identity(title_h1, url, code, model_name)
        if not id_ok:
            return None, False, "IDENTITY_MISMATCH", id_msg

        candidates = []
        detected_oos = False
        currency_mismatch = False

        # 1. Parse structured JSON-LD Product offers first (highest reliability)
        for raw_ld in page_info["ldNodes"]:
            try:
                data = json.loads(raw_ld)
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if isinstance(item, dict) and "@graph" in item and isinstance(item["@graph"], list):
                        items.extend(item["@graph"])
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    t = str(item.get("@type", "")).lower()
                    if "product" in t:
                        offers = item.get("offers", [])
                        if isinstance(offers, dict):
                            offers = [offers]
                        elif not isinstance(offers, list):
                            offers = []
                        for off in offers:
                            if not isinstance(off, dict):
                                continue
                            curr = str(off.get("priceCurrency", "")).upper().strip()
                            if curr and curr != expected_curr:
                                currency_mismatch = True
                                continue
                            avail = str(off.get("availability", "")).lower()
                            if "outofstock" in avail or "discontinued" in avail:
                                detected_oos = True
                            for p_key in ["lowPrice", "price"]:
                                if p_key in off:
                                    val = normalize_price(off[p_key])
                                    if val:
                                        candidates.append((val, f"JSON-LD {p_key} ({curr or expected_curr} {val:.2f}) · '{page_info['h1'][:35] or page_info['title'][:35]}'"))
            except:
                pass

        # 2. Check OpenGraph / Microdata price if currency matches
        m_curr = str(page_info.get("metaCurr", "")).upper().strip()
        if m_curr and m_curr != expected_curr:
            currency_mismatch = True
        elif page_info.get("metaPrice"):
            val = normalize_price(page_info["metaPrice"])
            if val:
                candidates.append((val, f"Meta OG/Microdata ({expected_curr} {val:.2f}) · '{page_info['h1'][:35] or page_info['title'][:35]}'"))

        # 3. Check main product DOM price elements (verifying currency symbol if present)
        wrong_sym = "£" if expected_curr == "EUR" else "€"
        for dp in page_info["domPrices"]:
            txt = dp["text"]
            if wrong_sym in txt:
                continue
            for m in re.finditer(r"([\d]{2,3}(?:[.,]\d{1,2})?)", txt):
                val = normalize_price(m.group(1))
                if val:
                    candidates.append((val, f"DOM {dp['selector']} ({expected_curr} {val:.2f}) · '{page_info['h1'][:35] or page_info['title'][:35]}'"))

        # STRICT PRICE FLOOR: A real Zone3 wetsuit never costs less than 45% of its official RRP (prevents accessories or Agile prices from contaminating Vanquish-X/Aspire)
        valid_candidates = [(p, ev) for (p, ev) in candidates if (pvp * 0.45) <= p <= (pvp * 1.20)]

        if not valid_candidates:
            if currency_mismatch:
                return None, False, "CURRENCY_MISMATCH", f"Moneda de la pàgina no coincideix amb {expected_curr}"
            body_low = page_info["bodyText"].lower()
            if detected_oos or any(w in body_low for w in ["agotado", "out of stock", "fuera de stock", "sold out", "no disponible"]):
                return None, True, "OUT_OF_STOCK", f"Producte sense estoc a la fitxa ({page_info['h1'][:35] or page_info['title'][:35]})"
            return None, False, "NO_VALID_PRICE", f"Cap preu entre 45%-120% PVP ({pvp*0.45:.0f}-{pvp*1.2:.0f} {expected_curr})"

        valid_candidates.sort(key=lambda x: x[0])
        best_price, best_evidence = valid_candidates[0]
        return round(best_price, 2), detected_oos, "VERIFIED", best_evidence

    except Exception as e:
        return None, False, "ERROR", f"Error de lectura: {str(e)[:60]}"

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
        quarantined_count = 0
        for row in tracking:
            url = row.get("url", "").strip()
            if not url:
                row["status"] = "UNMAPPED"
                row["evidence"] = "Sense URL assignada"
                continue

            if is_generic_category_url(url):
                row["status"] = "PENDING_PDP"
                row["price"] = None
                row["disc_imp"] = None
                row["disc_pct"] = None
                row["evidence"] = "En quarantena: URL de categoria genèrica (cal URL de fitxa individual PDP)"
                quarantined_count += 1
                continue

            page = page_uk if row["country"] == "UK" else page_es
            min_price, is_oos, status_code, evidence_str = await extract_verified_pdp_price(page, row)

            if status_code == "VERIFIED" and min_price is not None and min_price > 0:
                row["price"] = min_price
                row["disc_imp"] = round(row["pvp"] - min_price, 2)
                row["disc_pct"] = round((row["disc_imp"] / row["pvp"]) * 100, 1)
                row["status"] = "VERIFIED"
                row["last_read"] = today_str
                row["out_of_stock"] = bool(is_oos)
                row["is_from"] = False
                row["evidence"] = evidence_str
                updated_count += 1

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
                    "out_of_stock": bool(is_oos),
                    "is_from": False,
                    "url": url,
                    "evidence": evidence_str
                })
            else:
                # Keep previous verified price if it exists (marked via last_read date as older reading), but log today's check status in evidence
                if status_code == "OUT_OF_STOCK":
                    row["out_of_stock"] = True
                if row.get("price") is not None and row.get("status") == "VERIFIED":
                    row["evidence"] = f"Última lectura vàlida ({row.get('last_read', '')}) · Avui ({today_str}): {evidence_str}"
                else:
                    row["status"] = "PENDING_URL"
                    row["evidence"] = f"Revisat ({today_str}): {evidence_str}"

        await browser.close()

    history.sort(key=lambda x: (str(x.get("timestamp", "")), x.get("country", ""), x.get("operator", ""), x.get("code", "")))

    with open("data/tracking.json", "w", encoding="utf-8") as f:
        json.dump(tracking, f, indent=2, ensure_ascii=False)
    with open("data/history.json", "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2, ensure_ascii=False)

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

    with open("index.html", "r", encoding="utf-8") as f:
        html_doc = f.read()

    html_doc = re.sub(r"(?:const|let) DATA_ROWS = \[.*?\];", lambda _: "let DATA_ROWS = " + json.dumps(tracking, ensure_ascii=False) + ";", html_doc, flags=re.S)
    html_doc = re.sub(r"(?:const|let) HISTORY_COMPACT = \[.*?\];", lambda _: "let HISTORY_COMPACT = " + json.dumps(history_compact, ensure_ascii=False) + ";", html_doc, flags=re.S)
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html_doc)

    print(f"Scan finished at {now_str}. Verified PDP prices updated today: {updated_count}. Quarantined category URLs: {quarantined_count}. Total clean history records: {len(history_compact)}")

if __name__ == "__main__":
    asyncio.run(main())
