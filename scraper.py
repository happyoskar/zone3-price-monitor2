import asyncio
import json
import re
from datetime import datetime
from urllib.parse import urlparse, quote_plus
from playwright.async_api import async_playwright

STEALTH_INIT_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
window.chrome = { runtime: {} };
Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
Object.defineProperty(navigator, 'languages', { get: () => ['es-ES', 'es', 'en-GB', 'en'] });
"""

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"

GENERIC_URL_PATTERNS = [
    "/brands/zone-3",
    "/wetsuits/zone3/",
    "/natacion-zone3",
    "swimming-triathlon",
    "zone3%3awomen",
    "/store/zone-3/",
    "/marcas/zone3"
]

OPERATOR_CATALOG_URLS = {
    ("ES", "Trade Inn"): ["https://www.tradeinn.com/swiminn/es/trajes-y-complementos-trajes/11400/s?q=zone3"],
    ("ES", "Deporvillage"): ["https://www.deporvillage.com/natacion-zone3", "https://www.deporvillage.com/catalogsearch/result/?q=zone3+neopreno"],
    ("ES", "Bike 24"): ["https://www.bike24.es/marcas/zone3", "https://www.bike24.es/buscar?searchTerm=zone3+wetsuit"],
    ("ES", "Sportano"): [
        "https://sportano.com/en/zone3",
        "https://sportano.com/en/zone3?p=2",
        "https://sportano.com/en/search?q=zone3+wetsuit",
        "https://sportano.com/en/search?q=zone3+vanquish",
        "https://sportano.com/en/search?q=zone3+aspire",
        "https://sportano.com/en/search?q=zone3+vision",
        "https://sportano.com/en/search?q=zone3+active+flex",
        "https://sportano.com/en/search?q=zone3+glide",
        "https://sportano.com/en/search?q=zone3+versa"
    ],
    ("ES", "Wetsuit Outlet"): [
        "https://www.wetsuitoutlet.es/zone3-m-123.html?currency=EUR",
        "https://www.wetsuitoutlet.es/advanced_search_result.php?keywords=zone3+vanquish&currency=EUR",
        "https://www.wetsuitoutlet.es/advanced_search_result.php?keywords=zone3+aspire&currency=EUR",
        "https://www.wetsuitoutlet.es/advanced_search_result.php?keywords=zone3+versa&currency=EUR"
    ],
    ("ES", "Triathlon24"): [
        "https://www.triathlon24.nl/wetsuits/zone3/",
        "https://www.triathlon24.nl/search/zone3+vanquish/",
        "https://www.triathlon24.nl/search/zone3+ascend/",
        "https://www.triathlon24.nl/search/zone3+glide/",
        "https://www.triathlon24.nl/search/zone3+versa/"
    ],
    ("ES", "Alltricks"): [
        "https://www.alltricks.es/C-46286-combinaisons-_-maillots-de-bain/N-147403-marque~zone3",
        "https://www.alltricks.es/s?k=zone3+neopreno",
        "https://www.alltricks.es/s?k=zone3+vanquish",
        "https://www.alltricks.es/s?k=zone3+aspire",
        "https://www.alltricks.es/s?k=zone3+vision",
        "https://www.alltricks.es/s?k=zone3+active+flex",
        "https://www.alltricks.es/s?k=zone3+ascend"
    ],
    ("UK", "Trade Inn"): ["https://www.tradeinn.com/swiminn/en/suits-and-complements-suits/11400/s?q=zone3"],
    ("UK", "Deporvillage"): [
        "https://www.deporvillage.co.uk/swimming-triathlon%3Azone3%3Aneoprene_wetsuits",
        "https://www.deporvillage.co.uk/catalogsearch/result/?q=zone3+wetsuit"
    ],
    ("UK", "Sportshoes"): [
        "https://www.sportsshoes.com/products/?q=zone3%20wetsuit",
        "https://www.sportsshoes.com/products/?q=zone3%20aspire",
        "https://www.sportsshoes.com/products/?q=zone3%20ascend",
        "https://www.sportsshoes.com/products/?q=zone3%20versa"
    ],
    ("UK", "My Triathlon"): ["https://mytriathlon.co.uk/brands/Zone-3.html"],
    ("UK", "Sigma"): [
        "https://www.sigmasports.com/brand/zone3/wetsuits",
        "https://www.sigmasports.com/brand/zone3",
        "https://www.sigmasports.com/search?query=zone3+wetsuit",
        "https://www.sigmasports.com/search?query=zone3+vision",
        "https://www.sigmasports.com/search?query=zone3+agile",
        "https://www.sigmasports.com/search?query=zone3+active+flex",
        "https://www.sigmasports.com/search?query=zone3+ascend"
    ],
    ("UK", "Wetsuit Outlet"): [
        "https://www.wetsuitoutlet.co.uk/zone3-m-123.html?currency=GBP",
        "https://www.wetsuitoutlet.co.uk/advanced_search_result.php?keywords=zone3+vanquish&currency=GBP",
        "https://www.wetsuitoutlet.co.uk/advanced_search_result.php?keywords=zone3+aspire&currency=GBP",
        "https://www.wetsuitoutlet.co.uk/advanced_search_result.php?keywords=zone3+versa&currency=GBP"
    ]
}

OPERATOR_DOMAIN_FILTER = {
    ("ES", "Trade Inn"): "tradeinn.com",
    ("ES", "Deporvillage"): "deporvillage.com",
    ("ES", "Bike 24"): "bike24.es",
    ("ES", "Sportano"): "sportano.com",
    ("ES", "Wetsuit Outlet"): "wetsuitoutlet.es",
    ("ES", "Triathlon24"): "triathlon24.nl",
    ("ES", "Alltricks"): "alltricks.es",
    ("UK", "Trade Inn"): "tradeinn.com",
    ("UK", "Deporvillage"): "deporvillage.co.uk",
    ("UK", "Sportshoes"): "sportsshoes.com",
    ("UK", "My Triathlon"): "mytriathlon.co.uk",
    ("UK", "Sigma"): "sigmasports.com",
    ("UK", "Wetsuit Outlet"): "wetsuitoutlet.co.uk"
}

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

MODEL_EANS = {
    "WS22MVAN101": "5056305724818",
    "WS22WVAN101": "5056305724894",
    "WS25MASP101": "5056305745202",
    "WS25WASP101": "5056305745295",
    "WS24MVIS101": "5056305737726",
    "WS24WVIS101": "5056305739447",
    "WS21MADV101": "5056305711115",
    "WS21WADV101": "5056305710835",
    "WS21MAGI116": "5056305711139",
    "WS21WAGI114": "5056305711221",
    "WS26MGLISL101": "5056305752330",
    "WS26WGLISL101": "5056305752385",
    "WS25MACTF101": "5056305745370",
    "WS25WACTF101": "5056305745455",
    "WS25MSRV101": "5056305745585",
    "WS25WSRV101": "5056305746940"
}

FEMALE_TOKENS = ["women", "woman", "mujer", "dames", "femme", "womens", "ladies", "chica"]

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
    if any(p in u_low for p in GENERIC_URL_PATTERNS):
        return True
    if any(x in u_low for x in ["/search", "catalogsearch", "searchterm=", "?q=", "/s?k=", "advanced_search_result"]):
        return True
    return False

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

    if "GLISL" in code:
        if not any(w in combined for w in ["sleeveless", "sin mangas", "mouwloos", "sans manches", "glisl", "ascend"]):
            return False, "El model és Sleeveless (sense mànigues) però la fitxa és de màniga llarga"
    else:
        if any(w in combined for w in ["sleeveless", "sin mangas", "mouwloos", "sans manches"]):
            return False, "El model és de màniga llarga però la fitxa és Sleeveless"

    if any(bad in combined for bad in ["goggles", "gafas", "gloves", "guantes", "socks", "calcetines", "buoy", "boya", "cap", "gorro", "trisuit", "kneeskin", "jammer"]):
        return False, "Accessori exclòs (no és un neoprè)"

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

async def discover_missing_pdps(page_es, page_uk, tracking, today_str):
    """Deep Auto-Discovery engine: scans operator Zone3 catalogs, model search endpoints, and DuckDuckGo HTML fallback."""
    missing_by_op = {}
    for row in tracking:
        st = row.get("status", "")
        if st in ("UNMAPPED", "NOT_LISTED", "PENDING_PDP") or not row.get("url"):
            missing_by_op.setdefault((row["country"], row["operator"]), []).append(row)

    discovered_total = 0
    for (country, operator), rows in missing_by_op.items():
        cat_urls = OPERATOR_CATALOG_URLS.get((country, operator), [])
        expected_dom = OPERATOR_DOMAIN_FILTER.get((country, operator), "")
        page = page_uk if country == "UK" else page_es
        collected_links = []

        # 1. Scan operator catalog & targeted model search URLs
        for c_url in cat_urls:
            try:
                resp = await page.goto(c_url, wait_until="domcontentloaded", timeout=25000)
                if not resp or resp.status >= 400:
                    continue
                await page.wait_for_timeout(1800)
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight / 2)")
                await page.wait_for_timeout(700)
                links = await page.evaluate("""() => {
                    return Array.from(document.querySelectorAll('a[href]')).map(a => ({
                        href: a.href,
                        text: (a.innerText || a.getAttribute('title') || a.getAttribute('aria-label') || '').trim()
                    })).filter(x => x.href && x.href.startsWith('http'));
                }""")
                collected_links.extend(links)
            except Exception:
                continue

        # Match collected links against missing rows
        for row in rows:
            code = row["code"]
            model_name = row["model"]
            found_url = None
            for link in collected_links:
                href = link["href"].split("#")[0]
                if expected_dom and expected_dom not in href.lower():
                    continue
                if is_generic_category_url(href):
                    continue
                mkt_ok, _ = validate_market_url(href, country)
                if not mkt_ok:
                    continue
                id_ok, _ = validate_product_identity(link["text"], href, code, model_name)
                if id_ok:
                    if "tradeinn.com" in href.lower() and "country=" not in href.lower():
                        sep = "&" if "?" in href else "?"
                        href = f"{href}{sep}country={'uk' if country == 'UK' else 'es'}"
                    found_url = href
                    break

            # 2. Fallback: DuckDuckGo HTML search (`site:<operator_domain> zone3 <model>`) if still not found
            if not found_url and expected_dom and code != "WS25WSRV101":
                try:
                    q_str = f"site:{expected_dom} zone3 {model_name} {code}"
                    ddg_url = f"https://html.duckduckgo.com/html/?q={quote_plus(q_str)}"
                    resp = await page.goto(ddg_url, wait_until="domcontentloaded", timeout=18000)
                    if resp and resp.status == 200:
                        await page.wait_for_timeout(1000)
                        ddg_links = await page.evaluate("""() => {
                            return Array.from(document.querySelectorAll('a.result__a')).map(a => ({
                                href: a.href,
                                text: (a.innerText || '').trim()
                            }));
                        }""")
                        for dlink in ddg_links:
                            href = dlink["href"].split("#")[0]
                            if expected_dom not in href.lower() or is_generic_category_url(href):
                                continue
                            mkt_ok, _ = validate_market_url(href, country)
                            if not mkt_ok:
                                continue
                            id_ok, _ = validate_product_identity(dlink["text"], href, code, model_name)
                            if id_ok:
                                found_url = href
                                break
                except Exception:
                    pass

            if found_url:
                row["url"] = found_url
                row["status"] = "PENDING_URL"
                row["evidence"] = f"Auto-Discovery ({today_str}): Fitxa PDP localitzada per a {operator} ({country})"
                discovered_total += 1
            else:
                if row.get("status") in ("UNMAPPED", "NOT_LISTED"):
                    row["status"] = "NOT_LISTED"
                    row["evidence"] = f"Verificat al catàleg i cercador de {operator} ({today_str}): model no comercialitzat actualment"

    return discovered_total

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

        await page.wait_for_timeout(2800)

        page_info = await page.evaluate("""() => {
            const title = document.title || "";
            const h1 = Array.from(document.querySelectorAll("h1")).map(e => e.innerText.trim()).join(" | ");
            const ldNodes = Array.from(document.querySelectorAll('script[type="application/ld+json"]')).map(s => s.innerText);
            const metaCurr = (document.querySelector('meta[property="product:price:currency"], meta[property="og:price:currency"], [itemprop="priceCurrency"]') || {}).content || "";
            const metaPrice = (document.querySelector('meta[property="product:price:amount"], meta[property="og:price:amount"], meta[itemprop="price"]') || {}).content || "";

            const forbiddenContainers = [
                '.related', '.recommendations', '.cross-sell', '.upsell', '.similar-products',
                '.product-carousel', '.also-bought', '.alternatives', 'aside', 'footer', 'nav',
                '[data-testid*="recommend"]', '[class*="recommend"]', '[class*="related"]',
                '[class*="carousel"]', '[class*="slider"]', '[class*="cross"]', '[id*="related"]'
            ].join(', ');

            const selectors = [
                '[itemprop="price"]', '#js-precio', '[data-testid="price"]', '[data-testid="product-price"]',
                '.product-detail-price', '.price__value', '.pdp-price', '.product-page-price',
                '.price--main', '.price--withoutTax', '#productPrice', '.product-price__price',
                '.final-price', '.price-box__price', '.product-price', '.price-sales', '.current-price'
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

            const bodyText = (document.body ? document.body.innerText : "").slice(0, 4500);
            return { title, h1, ldNodes, metaCurr, metaPrice, domPrices, bodyText };
        }""")

        body_low = page_info["bodyText"].lower()
        if any(c in body_low for c in ["verify you are human", "cf-chl-bypass", "access denied", "captcha"]):
            return None, False, "BLOCKED_CAPTCHA", "Bloqueig anti-bot / Captcha detectat"

        title_h1 = f"{page_info['title']} | {page_info['h1']}".strip()
        id_ok, id_msg = validate_product_identity(title_h1, url, code, model_name)
        if not id_ok:
            return None, False, "IDENTITY_MISMATCH", id_msg

        # Check if exact SKU or EAN is present in the page or URL (allows deeper clearance discounts >= 25% PVP)
        ean = MODEL_EANS.get(code, "")
        has_exact_sku = (code.lower() in f"{title_h1} {url} {body_low}".lower()) or (ean and ean in body_low)
        min_allowed_ratio = 0.25 if has_exact_sku else 0.42

        candidates = []
        detected_oos = False
        currency_mismatch = False

        # 1. Structured JSON-LD Product / ProductGroup / hasVariant offers
        for raw_ld in page_info["ldNodes"]:
            try:
                data = json.loads(raw_ld)
                items = data if isinstance(data, list) else [data]
                for item in list(items):
                    if isinstance(item, dict):
                        if "@graph" in item and isinstance(item["@graph"], list):
                            items.extend(item["@graph"])
                        if "hasVariant" in item and isinstance(item["hasVariant"], list):
                            items.extend(item["hasVariant"])
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    t = str(item.get("@type", "")).lower()
                    if "product" in t:
                        prod_name = str(item.get("name", "")).strip()
                        prod_sku = str(item.get("sku", "") or item.get("mpn", "") or item.get("gtin13", "")).strip()
                        if prod_name:
                            ld_ok, _ = validate_product_identity(f"{prod_name} {prod_sku}", url, code, model_name)
                            if not ld_ok:
                                continue
                        offers = item.get("offers", [])
                        if isinstance(offers, dict):
                            if "offers" in offers and isinstance(offers["offers"], list):
                                offers = [offers] + offers["offers"]
                            else:
                                offers = [offers]
                        elif not isinstance(offers, list):
                            offers = []
                        for off in offers:
                            if not isinstance(off, dict):
                                continue
                            curr = str(off.get("priceCurrency", "") or page_info.get("metaCurr", "")).upper().strip()
                            if curr and curr != expected_curr:
                                currency_mismatch = True
                                continue
                            effective_curr = curr or expected_curr
                            avail = str(off.get("availability", "")).lower()
                            if "outofstock" in avail or "discontinued" in avail:
                                detected_oos = True
                            for p_key in ["price", "lowPrice", "highPrice"]:
                                if p_key in off:
                                    val = normalize_price(off[p_key])
                                    if val:
                                        candidates.append((
                                            1,
                                            val,
                                            f"JSON-LD {p_key} [{effective_curr} | Mercat {country}] ({val:.2f} {expected_sym}) · Producte: '{(prod_name or page_info['h1'])[:40]}'"
                                        ))
            except:
                pass

        # 2. OpenGraph / Microdata
        m_curr = str(page_info.get("metaCurr", "")).upper().strip()
        if m_curr and m_curr != expected_curr:
            currency_mismatch = True
        elif page_info.get("metaPrice"):
            val = normalize_price(page_info["metaPrice"])
            if val:
                candidates.append((
                    2,
                    val,
                    f"Meta OG [{m_curr or expected_curr} | Mercat {country}] ({val:.2f} {expected_sym}) · H1: '{page_info['h1'][:40]}'"
                ))

        # 3. Main Product DOM elements (excluding all carousels/related blocks)
        u_low = url.lower()
        has_local_domain_currency = (
            (country == "ES" and any(d in u_low for d in [".es/", ".nl/", "country=es", "currency=eur", "deporvillage.com/", "sportano.com/"])) or
            (country == "UK" and any(d in u_low for d in [".co.uk/", "country=uk", "currency=gbp", "sigmasports.com/", "sportsshoes.com/"]))
        )
        for dp in page_info["domPrices"]:
            txt = dp["text"]
            if forbidden_sym in txt:
                currency_mismatch = True
                continue
            has_explicit_curr = (
                (expected_sym in txt) or
                (expected_curr in txt.upper()) or
                (m_curr == expected_curr) or
                (dp.get("attrCurr", "").upper() == expected_curr) or
                has_local_domain_currency
            )
            if not has_explicit_curr:
                continue
            for m in re.finditer(r"([\d]{2,3}(?:[.,]\d{1,2})?)", txt):
                val = normalize_price(m.group(1))
                if val:
                    candidates.append((
                        3,
                        val,
                        f"DOM Principal {dp['selector']} [{expected_curr} | Mercat {country}] ({val:.2f} {expected_sym}) · H1: '{page_info['h1'][:38]}'"
                    ))

        valid_candidates = [(prio, p, ev) for (prio, p, ev) in candidates if (pvp * min_allowed_ratio) <= p <= (pvp * 1.20)]

        if not valid_candidates:
            if currency_mismatch:
                return None, False, "CURRENCY_MISMATCH", f"Moneda de la pàgina no coincideix amb {expected_curr} ({country})"
            if detected_oos or any(w in body_low for w in ["agotado", "out of stock", "fuera de stock", "sold out", "no disponible", "currently unavailable"]):
                return None, True, "OUT_OF_STOCK", f"Producte esgotat a la fitxa ({page_info['h1'][:35] or page_info['title'][:35]})"
            return None, False, "NO_VALID_PRICE", f"Cap preu principal ({expected_curr}) validat a la fitxa"

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

    domain_blocks = {}
    CIRCUIT_BREAKER_LIMIT = 4

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"]
        )
        context_es = await browser.new_context(
            locale="es-ES",
            timezone_id="Europe/Madrid",
            user_agent=USER_AGENT,
            viewport={"width": 1366, "height": 768}
        )
        context_uk = await browser.new_context(
            locale="en-GB",
            timezone_id="Europe/London",
            user_agent=USER_AGENT,
            viewport={"width": 1366, "height": 768}
        )
        await context_es.add_init_script(STEALTH_INIT_SCRIPT)
        await context_uk.add_init_script(STEALTH_INIT_SCRIPT)

        page_es = await context_es.new_page()
        page_uk = await context_uk.new_page()

        # PHASE 1: Deep Auto-Discovery of missing PDP URLs (Catalog + Search + DuckDuckGo HTML fallback)
        discovered_count = await discover_missing_pdps(page_es, page_uk, tracking, today_str)

        updated_count = 0
        quarantined_count = 0
        circuit_skipped = 0

        # PHASE 2: Price Verification on all mapped PDPs
        for row in tracking:
            row["is_from"] = False
            url = row.get("url", "").strip()
            if not url:
                row["status"] = "NOT_LISTED"
                row["freshness"] = "NONE"
                if not row.get("evidence"):
                    row["evidence"] = "Model no llistat al catàleg actual de l'operador"
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
                    existing_same_slot["is_from"] = False
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

    valid_history = [h for h in history if h.get("audit_status", "VALID") == "VALID"]
    history_compact = [
        [
            str(h.get("timestamp", ""))[:10],
            h["country"],
            h["operator"],
            h["code"],
            float(h["price"]),
            round(float(h["disc_pct"]), 1),
            1 if h.get("out_of_stock") else 0,
            0
        ]
        for h in valid_history
    ]

    with open("index.html", "r", encoding="utf-8") as f:
        html_doc = f.read()

    html_doc = re.sub(r"(?:const|let) DATA_ROWS = \[.*?\];", lambda _: "let DATA_ROWS = " + json.dumps(tracking, ensure_ascii=False) + ";", html_doc, flags=re.S)
    html_doc = re.sub(r"(?:const|let) HISTORY_COMPACT = \[.*?\];", lambda _: "let HISTORY_COMPACT = " + json.dumps(history_compact, ensure_ascii=False) + ";", html_doc, flags=re.S)
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html_doc)

    print(f"Scan finished ({now_iso}). Auto-discovered PDPs: {discovered_count} | Live today: {updated_count} | Quarantined: {quarantined_count} | Circuit-breaker skipped: {circuit_skipped} | Total history: {len(history)}")

if __name__ == "__main__":
    asyncio.run(main())
