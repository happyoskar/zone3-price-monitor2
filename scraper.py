import asyncio
import json
import re
from datetime import datetime
from urllib.parse import urlparse
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

EXPECTED_MARKET_SIGNALS = {
    "ES": {"currency": "EUR", "symbol": "€", "forbidden_symbol": "£", "bad_domains": [".co.uk"]},
    "UK": {"currency": "GBP", "symbol": "£", "forbidden_symbol": "€", "bad_domains": [".es", ".nl"]}
}

def is_generic_category_url(u):
    if not u or not isinstance(u, str):
        return True
    u_low = u.lower().strip()
    if u_low.endswith("/zone3") or u_low.endswith("/zone3/"):
        return True
    return any(p in u_low for p in GENERIC_URL_PATTERNS)

def get_domain(u):
    try:
        return urlparse(u).netloc.lower()
    except:
        return ""

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

def validate_product_identity(text_to_check, url, code, model_name):
    combined = f"{text_to_check} {url}".lower()
    keywords = MODEL_KEYWORDS.get(code, [])
    if keywords and not any(k in combined for k in keywords):
        return False, f"El producte ('{text_to_check[:45]}') no conté el model ({'/'.join(keywords)})"

    is_womens_model = "W" in code[4:6] or "women" in model_name.lower()
    has_female_word = any(re.search(r"\b" + w + r"\b", combined) for w in FEMALE_TOKENS)
    if is_womens_model and not has_female_word:
        return False, f"Model de dona però la fitxa no indica Women/Mujer ('{text_to_check[:40]}')"
    if not is_womens_model and has_female_word:
        return False, f"Model d'home però la fitxa indica Women/Mujer ('{text_to_check[:40]}')"

    return True, "Identitat de producte i gènere validada"

def validate_market_url(url, country):
    u_low = url.lower()
    sig = EXPECTED_MARKET_SIGNALS[country]
    for bd in sig["bad_domains"]:
        if bd in u_low:
            return False, f"Domini {bd} incompatible amb el mercat {country}"
    if "tradeinn.com" in u_low:
        if country == "UK" and "country=es" in u_low:
            return False, "URL TradeInn amb paràmetre country=es en mercat UK"
        if country == "ES" and "country=uk" in u_low:
            return False, "URL TradeInn amb paràmetre country=uk en mercat ES"
    return True, f"Mercat {country} validat a la URL"

async def extract_verified_pdp_price(page, row):
    url = row.get("url", "").strip()
    country = row["country"]
    expected_curr = row["currency"]
    sig = EXPECTED_MARKET_SIGNALS[country]
    expected_sym = sig["symbol"]
    forbidden_sym = sig["forbidden_symbol"]
    pvp = float(row["pvp"])
    code = row["code"]
    model_name = row["model"]

    if is_generic_category_url(url):
        return None, False, "PENDING_PDP", "En quarantena: URL de categoria genèrica (cal fitxa individual PDP)"

    mkt_ok, mkt_msg = validate_market_url(url, country)
    if not mkt_ok:
        return None, False, "MARKET_MISMATCH", mkt_msg

    try:
        if country == "UK":
            await page.set_extra_http_headers({"Accept-Language": "en-GB,en;q=0.9"})
        else:
            await page.set_extra_http_headers({"Accept-Language": "es-ES,es;q=0.9"})

        resp = await page.goto(url, wait_until="domcontentloaded", timeout=35000)
        if not resp:
            return None, False, "HTTP_ERROR", "Timeout sense resposta HTTP"
        if resp.status in (403, 429, 503):
            return None, False, "BLOCKED_HTTP", f"Accés bloquejat per l'operador (HTTP {resp.status})"
        if resp.status >= 400:
            return None, False, "HTTP_ERROR", f"Error HTTP {resp.status}"

        await page.wait_for_timeout(3000)

        page_info = await page.evaluate("""() => {
            const title = document.title || "";
            const h1 = Array.from(document.querySelectorAll("h1")).map(e => e.innerText.trim()).join(" | ");
            const ldNodes = Array.from(document.querySelectorAll('script[type="application/ld+json"]')).map(s => s.innerText);
            const metaCurr = (document.querySelector('meta[property="product:price:currency"], meta[property="og:price:currency"], [itemprop="priceCurrency"]') || {}).content || "";
            const metaPrice = (document.querySelector('meta[property="product:price:amount"], meta[property="og:price:amount"], meta[itemprop="price"]') || {}).content || "";

            // Exclude any related / carousel / recommendation / footer / sidebar containers so cross-sell prices are NEVER read
            const forbiddenContainers = [
                '.related', '.recommendations', '.cross-sell', '.upsell', '.similar-products',
                '.product-carousel', '.also-bought', '.alternatives', 'aside', 'footer', 'nav',
                '[data-testid*="recommend"]', '[class*="recommend"]', '[class*="related"]',
                '[class*="carousel"]', '[class*="slider"]', '[class*="cross"]', '[id*="related"]'
            ].join(', ');

            const selectors = [
                '[itemprop="price"]', '.product-price', '.price-sales', '#js-precio',
                '.pdp-price', '.product-page-price', '.price--main', '.current-price',
                '[data-testid="price"]', '.product-price__price', '.final-price',
                '.price-box__price'
            ];
            const domPrices = [];
            selectors.forEach(sel => {
                document.querySelectorAll(sel).forEach(el => {
                    if (el.closest('del, s, .old-price, .price-old, .rrp, .strike')) return;
                    if (el.closest(forbiddenContainers)) return;
                    const txt = (el.innerText || el.getAttribute("content") || "").trim();
                    const attrCurr = (el.getAttribute("data-currency") || el.getAttribute("currency") || "").trim();
                    if (txt) domPrices.push({ selector: sel, text: txt, attrCurr });
                });
            });

            const bodyText = (document.body ? document.body.innerText : "").slice(0, 4000);
            return { title, h1, ldNodes, metaCurr, metaPrice, domPrices, bodyText };
        }""")

        body_low = page_info["bodyText"].lower()
        if any(c in body_low for c in ["verify you are human", "cf-chl-bypass", "access denied", "captcha"]):
            return None, False, "BLOCKED_CAPTCHA", "Bloqueig anti-bot / Captcha detectat"

        title_h1 = f"{page_info['title']} | {page_info['h1']}".strip()
        id_ok, id_msg = validate_product_identity(title_h1, url, code, model_name)
        if not id_ok:
            return None, False, "IDENTITY_MISMATCH", id_msg

        candidates = []
        detected_oos = False
        currency_mismatch = False

        # 1. Structured JSON-LD Product offers (linked specifically to THIS product's name/SKU and explicit priceCurrency)
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
                        prod_name = str(item.get("name", "")).strip()
                        prod_sku = str(item.get("sku", "") or item.get("mpn", "")).strip()
                        # Verify this JSON-LD Product node actually belongs to our target model (not a related item)
                        if prod_name:
                            ld_ok, _ = validate_product_identity(f"{prod_name} {prod_sku}", url, code, model_name)
                            if not ld_ok:
                                continue
                        offers = item.get("offers", [])
                        if isinstance(offers, dict):
                            offers = [offers]
                        elif not isinstance(offers, list):
                            offers = []
                        for off in offers:
                            if not isinstance(off, dict):
                                continue
                            curr = str(off.get("priceCurrency", "")).upper().strip()
                            if not curr:
                                continue
                            if curr != expected_curr:
                                currency_mismatch = True
                                continue
                            avail = str(off.get("availability", "")).lower()
                            if "outofstock" in avail or "discontinued" in avail:
                                detected_oos = True
                            for p_key in ["price", "lowPrice"]:
                                if p_key in off:
                                    val = normalize_price(off[p_key])
                                    if val:
                                        candidates.append((
                                            1, # Priority 1: JSON-LD with explicit currency & product match
                                            val,
                                            f"JSON-LD {p_key} [Moneda explícita {curr} | Mercat {country}] ({val:.2f} {expected_sym}) · Producte: '{(prod_name or page_info['h1'])[:40]}'"
                                        ))
            except:
                pass

        # 2. OpenGraph / Microdata with explicit meta currency
        m_curr = str(page_info.get("metaCurr", "")).upper().strip()
        if m_curr:
            if m_curr != expected_curr:
                currency_mismatch = True
            elif page_info.get("metaPrice"):
                val = normalize_price(page_info["metaPrice"])
                if val:
                    candidates.append((
                        2,
                        val,
                        f"Meta OG [Moneda explícita {m_curr} | Mercat {country}] ({val:.2f} {expected_sym}) · H1: '{page_info['h1'][:40]}'"
                    ))

        # 3. Main Product DOM elements (requiring explicit currency symbol or metaCurr == expected_curr, excluding all carousels/related blocks)
        for dp in page_info["domPrices"]:
            txt = dp["text"]
            if forbidden_sym in txt:
                currency_mismatch = True
                continue
            has_explicit_curr = (expected_sym in txt) or (expected_curr in txt.upper()) or (m_curr == expected_curr) or (dp.get("attrCurr", "").upper() == expected_curr)
            if not has_explicit_curr:
                continue
            for m in re.finditer(r"([\d]{2,3}(?:[.,]\d{1,2})?)", txt):
                val = normalize_price(m.group(1))
                if val:
                    candidates.append((
                        3,
                        val,
                        f"DOM Principal {dp['selector']} [Moneda explícita {expected_curr} | Mercat {country}] ({val:.2f} {expected_sym}) · H1: '{page_info['h1'][:38]}'"
                    ))

        # Filter by strict price floor (45% to 120% of official RRP)
        valid_candidates = [(prio, p, ev) for (prio, p, ev) in candidates if (pvp * 0.45) <= p <= (pvp * 1.20)]

        if not valid_candidates:
            if currency_mismatch:
                return None, False, "CURRENCY_MISMATCH", f"Moneda de la pàgina no coincideix amb {expected_curr} ({country})"
            if detected_oos or any(w in body_low for w in ["agotado", "out of stock", "fuera de stock", "sold out", "no disponible"]):
                return None, True, "OUT_OF_STOCK", f"Producte sense estoc a la fitxa ({page_info['h1'][:35] or page_info['title'][:35]})"
            return None, False, "NO_VALID_PRICE", f"Cap preu principal amb moneda explícita {expected_curr} entre 45%-120% PVP"

        # Sort by source priority first (JSON-LD > Meta > Main DOM), then price
        valid_candidates.sort(key=lambda x: (x[0], x[1]))
        _, best_price, best_evidence = valid_candidates[0]
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
    slot_suffix = "AM" if now_dt.hour < 14 else "PM"
    run_slot = f"{today_str}-{slot_suffix}"
    now_iso = now_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    # Persistent Circuit Breaker per domain: stops hitting an operator if 2 consecutive block/captcha responses occur
    domain_blocks = {}
    CIRCUIT_BREAKER_LIMIT = 2

    async with async_playwright() as p:
        # Clean headless browser launch without stealth/automation-hiding flags
        browser = await p.chromium.launch(headless=True)
        context_es = await browser.new_context(locale="es-ES", timezone_id="Europe/Madrid")
        context_uk = await browser.new_context(locale="en-GB", timezone_id="Europe/London")

        page_es = await context_es.new_page()
        page_uk = await context_uk.new_page()

        updated_count = 0
        quarantined_count = 0
        circuit_skipped = 0

        for row in tracking:
            url = row.get("url", "").strip()
            if not url:
                row["status"] = "UNMAPPED"
                row["freshness"] = "NONE"
                row["evidence"] = "Sense URL assignada"
                continue

            if is_generic_category_url(url):
                row["status"] = "PENDING_PDP"
                row["freshness"] = "NONE"
                row["price"] = None
                row["disc_imp"] = None
                row["disc_pct"] = None
                row["evidence"] = "En quarantena: URL de categoria genèrica (cal URL de fitxa individual PDP)"
                quarantined_count += 1
                continue

            dom = get_domain(url)
            if domain_blocks.get(dom, 0) >= CIRCUIT_BREAKER_LIMIT:
                circuit_skipped += 1
                row["freshness"] = "HISTORICAL_PDP" if (row.get("status") == "VERIFIED" and row.get("last_read") != today_str) else row.get("freshness", "NONE")
                row["evidence"] = f"Aturada preventiva (Circuit Breaker) a {dom} per bloqueig HTTP/Captcha · Es conserva lectura del {row.get('last_read') or 'històric'}"
                continue

            page = page_uk if row["country"] == "UK" else page_es
            min_price, is_oos, status_code, evidence_str = await extract_verified_pdp_price(page, row)

            if status_code in ("BLOCKED_HTTP", "BLOCKED_CAPTCHA"):
                domain_blocks[dom] = domain_blocks.get(dom, 0) + 1

            if status_code == "VERIFIED" and min_price is not None and min_price > 0:
                prev_price = row.get("price")
                prev_date = row.get("last_read", "")
                row["price"] = min_price
                row["disc_imp"] = round(row["pvp"] - min_price, 2)
                row["disc_pct"] = round((row["disc_imp"] / row["pvp"]) * 100, 1)
                row["status"] = "VERIFIED"
                row["freshness"] = "LIVE_TODAY"
                row["last_read"] = today_str
                row["out_of_stock"] = bool(is_oos)
                row["is_from"] = False
                row["evidence"] = evidence_str
                updated_count += 1

                # APPEND-ONLY HISTORY: Never delete older readings; log intra-day AM/PM slot and keep previous_price if changed
                existing_same_slot = next(
                    (h for h in history if h.get("run_slot") == run_slot and h.get("country") == row["country"] and h.get("operator") == row["operator"] and h.get("code") == row["code"] and h.get("audit_status", "VALID") == "VALID"),
                    None
                )
                if existing_same_slot:
                    if existing_same_slot.get("price") != min_price:
                        existing_same_slot["previous_price"] = existing_same_slot.get("price")
                        existing_same_slot["audit_note"] = f"Actualitzat dins del mateix torn {run_slot} ({now_iso})"
                    existing_same_slot["price"] = min_price
                    existing_same_slot["disc_imp"] = row["disc_imp"]
                    existing_same_slot["disc_pct"] = row["disc_pct"]
                    existing_same_slot["out_of_stock"] = bool(is_oos)
                    existing_same_slot["evidence"] = evidence_str
                    existing_same_slot["timestamp_iso"] = now_iso
                else:
                    new_entry = {
                        "timestamp": today_str,
                        "run_slot": run_slot,
                        "timestamp_iso": now_iso,
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
                        "audit_status": "VALID",
                        "evidence": evidence_str
                    }
                    if prev_price is not None and prev_price != min_price:
                        new_entry["previous_price"] = prev_price
                        new_entry["previous_date"] = prev_date
                    history.append(new_entry)
            else:
                if status_code == "OUT_OF_STOCK":
                    row["out_of_stock"] = True
                if row.get("price") is not None and row.get("status") == "VERIFIED":
                    row["freshness"] = "LIVE_TODAY" if row.get("last_read") == today_str else "HISTORICAL_PDP"
                    row["evidence"] = f"Lectura històrica ({row.get('last_read', '')}) · Revisió avui ({run_slot}): {evidence_str}"
                else:
                    row["status"] = "PENDING_URL"
                    row["freshness"] = "NONE"
                    row["evidence"] = f"Revisat ({run_slot}): {evidence_str}"

        await browser.close()

    history.sort(key=lambda x: (str(x.get("timestamp", "")), str(x.get("run_slot", "")), x.get("country", ""), x.get("operator", ""), x.get("code", "")))

    with open("data/tracking.json", "w", encoding="utf-8") as f:
        json.dump(tracking, f, indent=2, ensure_ascii=False)
    with open("data/history.json", "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2, ensure_ascii=False)

    # HISTORY_COMPACT for charts only includes VALID PDP readings (excluding QUARANTINED_CATEGORY_URL)
    valid_history = [h for h in history if h.get("audit_status", "VALID") == "VALID"]
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
        for h in valid_history
    ]

    with open("index.html", "r", encoding="utf-8") as f:
        html_doc = f.read()

    html_doc = re.sub(r"(?:const|let) DATA_ROWS = \[.*?\];", lambda _: "let DATA_ROWS = " + json.dumps(tracking, ensure_ascii=False) + ";", html_doc, flags=re.S)
    html_doc = re.sub(r"(?:const|let) HISTORY_COMPACT = \[.*?\];", lambda _: "let HISTORY_COMPACT = " + json.dumps(history_compact, ensure_ascii=False) + ";", html_doc, flags=re.S)
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html_doc)

    print(f"Scan finished ({now_iso}). Live today: {updated_count} | Quarantined: {quarantined_count} | Circuit-breaker skipped: {circuit_skipped} | Total history (with quarantined trace): {len(history)}")

if __name__ == "__main__":
    asyncio.run(main())
