import asyncio
import base64
import json
import os
import re
import urllib.request
from datetime import datetime
from urllib.parse import urlparse, quote_plus
from playwright.async_api import async_playwright

ZYTE_API_KEY = os.environ.get("ZYTE_API_KEY", "").strip()

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
    ("ES", "Trade Inn"): [
        "https://www.tradeinn.com/swiminn/es/trajes-y-complementos-trajes/11400/s?q=zone3",
        "https://www.tradeinn.com/swiminn/es/s?q=zone3+versa"
    ],
    ("ES", "Deporvillage"): [
        "https://www.deporvillage.com/natacion-zone3",
        "https://www.deporvillage.com/catalogsearch/result/?q=zone3+neopreno",
        "https://www.deporvillage.com/catalogsearch/result/?q=zone3+ascend",
        "https://www.deporvillage.com/catalogsearch/result/?q=zone3+glide",
        "https://www.deporvillage.com/catalogsearch/result/?q=zone3+sin+mangas",
        "https://www.deporvillage.com/catalogsearch/result/?q=zone3+sleeveless",
        "https://www.deporvillage.com/catalogsearch/result/?q=zone3+versa",
        "https://www.deporvillage.com/catalogsearch/result/?q=5056305752330",
        "https://www.deporvillage.com/catalogsearch/result/?q=5056305752385"
    ],
    ("ES", "Bike 24"): [
        "https://www.bike24.es/marcas/zone3",
        "https://www.bike24.es/marcas/zone3?page=2",
        "https://www.bike24.es/buscar?searchTerm=zone3+wetsuit",
        "https://www.bike24.es/buscar?searchTerm=zone3+active+flex",
        "https://www.bike24.es/buscar?searchTerm=zone3+versa",
        "https://www.bike24.es/buscar?searchTerm=5056305745455",
        "https://www.bike24.es/buscar?searchTerm=5056305746940"
    ],
    ("ES", "Sportano"): [
        "https://sportano.com/en/zone3",
        "https://sportano.com/en/zone3?p=2",
        "https://sportano.com/en/search?q=zone3+wetsuit",
        "https://sportano.com/en/search?q=zone3+vanquish",
        "https://sportano.com/en/search?q=zone3+aspire",
        "https://sportano.com/en/search?q=zone3+vision",
        "https://sportano.com/en/search?q=zone3+active+flex",
        "https://sportano.com/en/search?q=zone3+glide",
        "https://sportano.com/en/search?q=zone3+ascend",
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
        "https://www.alltricks.es/s?k=zone3+ascend",
        "https://www.alltricks.es/s?k=zone3+glide"
    ],
    ("UK", "Trade Inn"): [
        "https://www.tradeinn.com/swiminn/en/suits-and-complements-suits/11400/s?q=zone3",
        "https://www.tradeinn.com/swiminn/en/s?q=zone3+versa"
    ],
    ("UK", "Deporvillage"): [
        "https://www.deporvillage.co.uk/swimming-triathlon%3Azone3%3Aneoprene_wetsuits",
        "https://www.deporvillage.co.uk/catalogsearch/result/?q=zone3+wetsuit",
        "https://www.deporvillage.co.uk/catalogsearch/result/?q=zone3+ascend",
        "https://www.deporvillage.co.uk/catalogsearch/result/?q=zone3+glide",
        "https://www.deporvillage.co.uk/catalogsearch/result/?q=zone3+sleeveless",
        "https://www.deporvillage.co.uk/catalogsearch/result/?q=zone3+versa",
        "https://www.deporvillage.co.uk/catalogsearch/result/?q=5056305752330",
        "https://www.deporvillage.co.uk/catalogsearch/result/?q=5056305752385"
    ],
    ("UK", "Sportshoes"): [
        "https://www.sportsshoes.com/products/?q=zone3%20wetsuit",
        "https://www.sportsshoes.com/products/?q=zone3%20aspire",
        "https://www.sportsshoes.com/products/?q=zone3%20ascend",
        "https://www.sportsshoes.com/products/?q=zone3%20glide",
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
        "https://www.sigmasports.com/search?query=zone3+ascend",
        "https://www.sigmasports.com/search?query=zone3+glide"
    ],
    ("UK", "Wetsuit Outlet"): [
        "https://www.wetsuitoutlet.co.uk/zone3-m-123.html?currency=GBP",
        "https://www.wetsuitoutlet.co.uk/advanced_search_result.php?keywords=zone3+vanquish&currency=GBP",
        "https://www.wetsuitoutlet.co.uk/advanced_search_result.php?keywords=zone3+aspire&currency=GBP",
        "https://www.wetsuitoutlet.co.uk/advanced_search_result.php?keywords=zone3+versa&currency=GBP"
    ]
}

# Candidate direct URLs & sequential ID probes for Bike 24 and Deporvillage missing SKUs
DIRECT_CANDIDATE_PROBES = {
    ("ES", "Bike 24", "WS25WACTF101"): [
        "https://www.bike24.es/productos/1004855",
        "https://www.bike24.es/productos/1004859",
        "https://www.bike24.es/productos/1004860",
        "https://www.bike24.es/productos/905638",
        "https://www.bike24.es/productos/905639",
        "https://www.bike24.es/productos/905640",
        "https://www.bike24.es/productos/905643",
        "https://www.bike24.es/productos/905644"
    ],
    ("ES", "Deporvillage", "WS26MGLISL101"): [
        "https://www.deporvillage.com/traje-neopreno-zone3-ascend-sin-mangas",
        "https://www.deporvillage.com/traje-de-neopreno-zone3-ascend-sin-mangas",
        "https://www.deporvillage.com/traje-neopreno-zone3-glide-sin-mangas",
        "https://www.deporvillage.com/traje-de-neopreno-zone3-glide-sin-mangas",
        "https://www.deporvillage.com/traje-neopreno-zone3-ascend-sleeveless"
    ],
    ("ES", "Deporvillage", "WS26WGLISL101"): [
        "https://www.deporvillage.com/traje-neopreno-zone3-ascend-sin-mangas-mujer",
        "https://www.deporvillage.com/traje-de-neopreno-zone3-ascend-sin-mangas-mujer",
        "https://www.deporvillage.com/traje-neopreno-zone3-glide-sin-mangas-mujer",
        "https://www.deporvillage.com/traje-de-neopreno-zone3-glide-sin-mangas-mujer",
        "https://www.deporvillage.com/traje-neopreno-zone3-ascend-sleeveless-mujer"
    ],
    ("UK", "Deporvillage", "WS26MGLISL101"): [
        "https://www.deporvillage.co.uk/zone3-ascend-sleeveless-wetsuit-black-grey",
        "https://www.deporvillage.co.uk/zone3-glide-sleeveless-wetsuit-black-grey",
        "https://www.deporvillage.co.uk/zone3-ascend-sleeveless-wetsuit"
    ],
    ("UK", "Deporvillage", "WS26WGLISL101"): [
        "https://www.deporvillage.co.uk/zone3-ascend-sleeveless-wetsuit-black-grey-women",
        "https://www.deporvillage.co.uk/zone3-glide-sleeveless-wetsuit-black-grey-women",
        "https://www.deporvillage.co.uk/zone3-ascend-sleeveless-wetsuit-women"
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

    if "ADV" in code and any(plus_tok in combined for plus_tok in ["advance+", "advance plus", "advance-plus", "advence+", "advence plus"]):
        return False, "Versió Advance+ / Advance Plus exclosa (el model monitoritzat és l'Advance estàndard)"

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

def fetch_zyte_raw_sync(url, country):
    """Calls Zyte API with geolocation (ES or GB) using only Python stdlib and returns raw browserHtml + product dict."""
    if not ZYTE_API_KEY:
        return None
    try:
        geo = "GB" if country == "UK" else "ES"
        payload = json.dumps({
            "url": url,
            "browserHtml": True,
            "product": True,
            "productOptions": {"extractFrom": "browserHtml"},
            "geolocation": geo
        }).encode("utf-8")

        auth = base64.b64encode(f"{ZYTE_API_KEY}:".encode("utf-8")).decode("utf-8")
        req = urllib.request.Request(
            "https://api.zyte.com/v1/extract",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Authorization": f"Basic {auth}"
            },
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=28) as resp:
            if resp.status != 200:
                return None
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None

def parse_html_fast_stdlib(html_str, base_url, zprod=None):
    """Instant (<5ms) pure-Python stdlib parser for Zyte HTML. Never blocks on external scripts."""
    if not html_str:
        info = {"title": "", "h1": "", "ldNodes": [], "metaCurr": "", "metaPrice": "", "domPrices": [], "bodyText": "", "links": []}
    else:
        m_title = re.search(r"<title[^>]*>(.*?)</title>", html_str, flags=re.I | re.S)
        title = re.sub(r"\s+", " ", m_title.group(1)).strip() if m_title else ""

        h1_matches = re.findall(r"<h1[^>]*>(.*?)</h1>", html_str, flags=re.I | re.S)
        h1_list = [re.sub(r"<[^>]+>", " ", h).strip() for h in h1_matches]
        h1 = re.sub(r"\s+", " ", " | ".join(filter(None, h1_list))).strip()

        ld_nodes = re.findall(r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html_str, flags=re.I | re.S)

        meta_curr = ""
        m_mc = re.search(r'<meta[^>]+(?:property|name|itemprop)=["\'](?:product:price:currency|og:price:currency|priceCurrency)["\'][^>]+content=["\']([^"\']+)["\']', html_str, flags=re.I)
        if not m_mc:
            m_mc = re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name|itemprop)=["\'](?:product:price:currency|og:price:currency|priceCurrency)["\']', html_str, flags=re.I)
        if m_mc:
            meta_curr = m_mc.group(1).strip()

        meta_price = ""
        m_mp = re.search(r'<meta[^>]+(?:property|name|itemprop)=["\'](?:product:price:amount|og:price:amount|price)["\'][^>]+content=["\']([^"\']+)["\']', html_str, flags=re.I)
        if not m_mp:
            m_mp = re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name|itemprop)=["\'](?:product:price:amount|og:price:amount|price)["\']', html_str, flags=re.I)
        if m_mp:
            meta_price = m_mp.group(1).strip()

        dom_prices = []
        for m_p in re.finditer(r'id=["\']js-precio["\'][^>]*>([^<]+)<', html_str, flags=re.I):
            dom_prices.append({"selector": "#js-precio", "text": m_p.group(1).strip(), "attrCurr": ""})

        links = []
        parsed_base = urlparse(base_url)
        base_origin = f"{parsed_base.scheme}://{parsed_base.netloc}" if parsed_base.scheme else ""
        for m_a in re.finditer(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', html_str, flags=re.I | re.S):
            href = m_a.group(1).strip()
            if href.startswith("/") and base_origin:
                href = base_origin + href
            if href.startswith("http"):
                txt = re.sub(r"<[^>]+>", " ", m_a.group(2))
                txt = re.sub(r"\s+", " ", txt).strip()
                links.append({"href": href, "text": txt})

        clean_html = re.sub(r"<(script|style|noscript)[^>]*>.*?</\1>", " ", html_str, flags=re.I | re.S)
        body_text = re.sub(r"<[^>]+>", " ", clean_html)
        body_text = re.sub(r"\s+", " ", body_text).strip()[:4500]

        info = {
            "title": title,
            "h1": h1,
            "ldNodes": ld_nodes,
            "metaCurr": meta_curr,
            "metaPrice": meta_price,
            "domPrices": dom_prices,
            "bodyText": body_text,
            "links": links
        }

    if isinstance(zprod, dict) and zprod.get("name"):
        if not info["h1"]:
            info["h1"] = str(zprod.get("name", "")).strip()
        if not info["title"]:
            info["title"] = str(zprod.get("name", "")).strip()
    info["zyteProduct"] = zprod or {}
    return info

async def fetch_via_zyte(page, url, country):
    zdata = await asyncio.to_thread(fetch_zyte_raw_sync, url, country)
    if not zdata:
        return None
    html_str = zdata.get("browserHtml") or ""
    zprod = zdata.get("product") or {}
    return parse_html_fast_stdlib(html_str, url, zprod)

async def discover_missing_pdps(page_es, page_uk, tracking, today_str):
    """Deep Auto-Discovery engine: direct candidate probes + operator catalog/search + Zyte fallback + DuckDuckGo HTML."""
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

        # 0. Direct candidate probes for priority missing SKUs (Bike 24 & Deporvillage)
        for row in list(rows):
            probe_urls = DIRECT_CANDIDATE_PROBES.get((country, operator, row["code"]), [])
            for p_url in probe_urls:
                try:
                    resp = await page.goto(p_url, wait_until="domcontentloaded", timeout=18000)
                    page_title_h1 = ""
                    if resp and resp.status == 200:
                        await page.wait_for_timeout(1200)
                        page_title_h1 = await page.evaluate("() => (document.title || '') + ' | ' + Array.from(document.querySelectorAll('h1')).map(e => e.innerText).join(' ')")
                    elif ZYTE_API_KEY and resp and resp.status in (403, 429, 503):
                        zinfo = await fetch_via_zyte(page, p_url, country)
                        if zinfo:
                            page_title_h1 = f"{zinfo.get('title', '')} | {zinfo.get('h1', '')}"
                    if page_title_h1:
                        id_ok, _ = validate_product_identity(page_title_h1, p_url, row["code"], row["model"])
                        if id_ok:
                            row["url"] = p_url
                            row["status"] = "PENDING_URL"
                            row["evidence"] = f"Auto-Discovery Probe ({today_str}): Fitxa PDP verificada a {operator} ({country})"
                            discovered_total += 1
                            rows.remove(row)
                            break
                except Exception:
                    continue

        if not rows:
            continue

        # 1. Scan operator catalog & targeted model/EAN search URLs (with Zyte fallback if blocked)
        for c_url in cat_urls:
            try:
                resp = await page.goto(c_url, wait_until="domcontentloaded", timeout=25000)
                if resp and resp.status == 200:
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
                elif ZYTE_API_KEY and (not resp or resp.status in (403, 429, 503)):
                    zinfo = await fetch_via_zyte(page, c_url, country)
                    if zinfo and zinfo.get("links"):
                        collected_links.extend(zinfo["links"])
            except Exception:
                if ZYTE_API_KEY:
                    zinfo = await fetch_via_zyte(page, c_url, country)
                    if zinfo and zinfo.get("links"):
                        collected_links.extend(zinfo["links"])

        # Match collected links against remaining missing rows
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

            # 2. Fallback: DuckDuckGo HTML search (`site:<operator_domain> zone3 <model> <code/EAN>`)
            if not found_url and expected_dom and code != "WS25WSRV101":
                ean = MODEL_EANS.get(code, "")
                for q_str in [f"site:{expected_dom} zone3 {model_name}", f"site:{expected_dom} {code} OR {ean}"]:
                    if found_url:
                        break
                    try:
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
                    row["status"] = "UNMAPPED"
                    row["evidence"] = f"Cerca automàtica a {operator} ({today_str}): cap fitxa PDP localitzada (no confirma absència comercial)"

    return discovered_total

def evaluate_page_info_candidates(page_info, row, source_prefix=""):
    url = row.get("url", "").strip()
    country = row["country"]
    expected_curr = row["currency"]
    sig = EXPECTED_MARKET_SIGNALS[country]
    expected_sym = sig["symbol"]
    forbidden_sym = sig["forbidden_symbol"]
    pvp = float(row["pvp"])
    code = row["code"]
    model_name = row["model"]

    body_low = (page_info.get("bodyText") or "").lower()
    if any(c in body_low for c in ["verify you are human", "cf-chl-bypass", "access denied", "captcha"]):
        return None, False, "BLOCKED_CAPTCHA", "Bloqueig anti-bot / Captcha detectat"

    title_h1 = f"{page_info.get('title', '')} | {page_info.get('h1', '')}".strip()
    id_ok, id_msg = validate_product_identity(title_h1, url, code, model_name)
    if not id_ok:
        return None, False, "IDENTITY_MISMATCH", id_msg

    ean = MODEL_EANS.get(code, "")
    has_exact_sku = (code.lower() in f"{title_h1} {url} {body_low}".lower()) or (ean and ean in body_low)
    min_allowed_ratio = 0.25 if has_exact_sku else 0.42

    candidates = []
    instock_variant_prices = []
    oos_variant_prices = []
    detected_oos = False
    detected_instock = False
    currency_mismatch = False

    # 0. Zyte Automatic Product Extraction (if provided by Zyte fallback)
    zprod = page_info.get("zyteProduct") or {}
    if isinstance(zprod, dict) and zprod.get("price"):
        z_curr = str(zprod.get("currency") or zprod.get("currencyRaw") or "").upper().strip()
        if z_curr in ("€", "EUR"):
            z_curr = "EUR"
        elif z_curr in ("£", "GBP"):
            z_curr = "GBP"
        if z_curr and z_curr != expected_curr:
            currency_mismatch = True
        else:
            z_val = normalize_price(zprod.get("price"))
            z_avail = str(zprod.get("availability") or "").lower()
            is_z_oos = False
            if "instock" in z_avail:
                detected_instock = True
            elif "outofstock" in z_avail or "discontinued" in z_avail:
                detected_oos = True
                is_z_oos = True
            if z_val:
                candidates.append((
                    1,
                    is_z_oos,
                    z_val,
                    f"{source_prefix}Zyte Product API [{z_curr or expected_curr} | Mercat {country}] ({z_val:.2f} {expected_sym}) · '{(zprod.get('name') or page_info.get('h1', ''))[:40]}'"
                ))

    # 1. Structured JSON-LD Product / ProductGroup / hasVariant offers
    for raw_ld in page_info.get("ldNodes", []):
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
                    variant_size = str(item.get("size", "") or item.get("color", "")).strip()
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
                        off_size = str(off.get("sku", "") or off.get("name", "") or variant_size).strip()
                        is_off_oos = False
                        if "instock" in avail:
                            detected_instock = True
                        elif "outofstock" in avail or "discontinued" in avail:
                            detected_oos = True
                            is_off_oos = True
                        for p_key in ["price", "lowPrice", "highPrice"]:
                            if p_key in off:
                                val = normalize_price(off[p_key])
                                if val and (pvp * min_allowed_ratio) <= val <= (pvp * 1.20):
                                    if not is_off_oos and p_key in ("price", "lowPrice"):
                                        instock_variant_prices.append((val, off_size))
                                    elif is_off_oos:
                                        oos_variant_prices.append((val, off_size))
                                    candidates.append((
                                        1,
                                        is_off_oos,
                                        val,
                                        f"{source_prefix}JSON-LD {p_key} [{effective_curr} | Mercat {country}] ({val:.2f} {expected_sym}) · Producte: '{(prod_name or page_info.get('h1', ''))[:40]}'"
                                    ))
        except Exception:
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
                False,
                val,
                f"{source_prefix}Meta OG [{m_curr or expected_curr} | Mercat {country}] ({val:.2f} {expected_sym}) · H1: '{page_info.get('h1', '')[:40]}'"
            ))

    # 3. Main Product DOM elements (excluding all carousels/related blocks)
    u_low = url.lower()
    has_local_domain_currency = (
        (country == "ES" and any(d in u_low for d in [".es/", ".nl/", "country=es", "currency=eur", "deporvillage.com/", "sportano.com/"])) or
        (country == "UK" and any(d in u_low for d in [".co.uk/", "country=uk", "currency=gbp", "sigmasports.com/", "sportsshoes.com/"]))
    )
    for dp in page_info.get("domPrices", []):
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
                    False,
                    val,
                    f"{source_prefix}DOM Principal {dp['selector']} [{expected_curr} | Mercat {country}] ({val:.2f} {expected_sym}) · H1: '{page_info.get('h1', '')[:38]}'"
                ))

    body_has_oos_text = any(w in body_low for w in ["agotado", "out of stock", "fuera de stock", "sold out", "no disponible", "currently unavailable"])
    if body_has_oos_text and not detected_instock:
        detected_oos = True

    valid_candidates = [(prio, is_oos_cand, p, ev) for (prio, is_oos_cand, p, ev) in candidates if (pvp * min_allowed_ratio) <= p <= (pvp * 1.20)]

    # If there are in-stock candidates, filter out any candidate that is explicitly marked out-of-stock
    instock_candidates = [c for c in valid_candidates if not c[1]]
    if instock_candidates:
        valid_candidates = instock_candidates

    if not valid_candidates:
        if currency_mismatch:
            return None, False, "CURRENCY_MISMATCH", f"Moneda de la pàgina no coincideix amb {expected_curr} ({country})"
        if detected_oos:
            return None, True, "OUT_OF_STOCK", f"Producte esgotat a la fitxa ({(page_info.get('h1') or page_info.get('title') or '')[:35]})"
        return None, False, "NO_VALID_PRICE", f"Cap preu principal ({expected_curr}) validat a la fitxa"

    # Sort by priority (1=JSON-LD/Zyte, 2=Meta, 3=DOM) then lowest price
    valid_candidates.sort(key=lambda x: (x[0], x[2]))
    _, best_cand_oos, best_price, best_evidence = valid_candidates[0]

    # Subtle note in tooltip if multiple in-stock sizes have different prices
    unique_instock_prices = sorted(list(set(round(p, 2) for (p, _) in instock_variant_prices)))
    if len(unique_instock_prices) > 1:
        min_p = unique_instock_prices[0]
        max_p = unique_instock_prices[-1]
        min_sizes = [sz for (p, sz) in instock_variant_prices if round(p, 2) == min_p and sz]
        sz_note = f" ({min_sizes[0][:18]})" if min_sizes else ""
        best_evidence += f" · [Nota talles: preu mínim en talla específica{sz_note}; altres talles en estoc fins a {max_p:.2f} {expected_sym}]"

    final_oos = True if (best_cand_oos or (detected_oos and not detected_instock)) else False
    return round(best_price, 2), final_oos, "VERIFIED", best_evidence

async def extract_verified_pdp_price(page, row, force_zyte_only=False):
    url = row.get("url", "").strip()
    country = row["country"]

    if is_generic_category_url(url):
        return None, False, "PENDING_PDP", "En quarantena: URL de categoria genèrica (cal fitxa individual PDP)"

    mkt_ok, mkt_msg = validate_market_url(url, country)
    if not mkt_ok:
        return None, False, "MARKET_MISMATCH", mkt_msg

    # If domain already tripped the Playwright circuit breaker and ZYTE_API_KEY is configured, go straight to Zyte
    if force_zyte_only and ZYTE_API_KEY:
        z_info = await fetch_via_zyte(page, url, country)
        if z_info:
            return evaluate_page_info_candidates(z_info, row, source_prefix="[Zyte] ")
        return None, False, "BLOCKED_HTTP", "Accés bloquejat i sense resposta de Zyte API"

    status_code = "ERROR"
    evidence_str = ""

    try:
        if country == "UK":
            await page.set_extra_http_headers({"Accept-Language": "en-GB,en;q=0.9"})
        else:
            await page.set_extra_http_headers({"Accept-Language": "es-ES,es;q=0.9"})

        resp = await page.goto(url, wait_until="domcontentloaded", timeout=18000)
        if not resp:
            status_code, evidence_str = "HTTP_ERROR", "Timeout sense resposta HTTP"
        elif resp.status in (403, 429, 503):
            status_code, evidence_str = "BLOCKED_HTTP", f"Accés bloquejat per l'operador (HTTP {resp.status})"
        elif resp.status >= 400:
            status_code, evidence_str = "HTTP_ERROR", f"Error HTTP {resp.status}"
        else:
            await page.wait_for_timeout(1400)
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

            price_val, is_oos, status_code, evidence_str = evaluate_page_info_candidates(page_info, row, source_prefix="")
            if status_code == "VERIFIED" or status_code == "OUT_OF_STOCK":
                return price_val, is_oos, status_code, evidence_str

    except Exception as e:
        status_code, evidence_str = "ERROR", f"Error de lectura: {str(e)[:60]}"

    # Hybrid Zyte Fallback: if Playwright hit anti-bot (403/429/503/Captcha) or empty JS render and ZYTE_API_KEY is available
    if ZYTE_API_KEY and status_code in ("BLOCKED_HTTP", "BLOCKED_CAPTCHA", "HTTP_ERROR", "NO_VALID_PRICE", "ERROR"):
        z_info = await fetch_via_zyte(page, url, country)
        if z_info:
            z_price, z_oos, z_status, z_ev = evaluate_page_info_candidates(z_info, row, source_prefix="[Zyte] ")
            if z_status in ("VERIFIED", "OUT_OF_STOCK"):
                return z_price, z_oos, z_status, z_ev

    return None, False, status_code, evidence_str

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
    CIRCUIT_BREAKER_LIMIT = 2

    print(f"Starting Zone3 Audit Scraper v9 ({now_iso}) | Zyte Hybrid Fallback: {'ENABLED' if ZYTE_API_KEY else 'NOT_SET (using Playwright Stealth)'}")

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

        # PHASE 1: Deep Auto-Discovery of missing PDP URLs (Probes + Catalog/EAN Search + Zyte + DuckDuckGo)
        discovered_count = await discover_missing_pdps(page_es, page_uk, tracking, today_str)

        updated_count = 0
        zyte_rescued_count = 0
        quarantined_count = 0
        circuit_skipped = 0

        # PHASE 2: Price Verification on all mapped PDPs
        for row in tracking:
            row["is_from"] = False
            url = row.get("url", "").strip()
            if not url:
                if row.get("status") not in ("NOT_LISTED", "UNMAPPED"):
                    row["status"] = "UNMAPPED"
                row["freshness"] = "NONE"
                if not row.get("evidence"):
                    row["evidence"] = "Cerca automàtica: cap fitxa PDP localitzada al catàleg de l'operador"
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
            playwright_blocked_for_dom = domain_blocks.get(dom, 0) >= CIRCUIT_BREAKER_LIMIT

            if playwright_blocked_for_dom and not ZYTE_API_KEY:
                circuit_skipped += 1
                row["freshness"] = "HISTORICAL_PDP" if (row.get("status") == "VERIFIED" and row.get("last_read") != today_str) else row.get("freshness", "NONE")
                row["evidence"] = f"Aturada preventiva (Circuit Breaker) a {dom} per bloqueig HTTP/Captcha · Configura ZYTE_API_KEY per rescatar-lo · Lectura del {row.get('last_read') or 'històric'}"
                continue

            page = page_uk if row["country"] == "UK" else page_es
            min_price, is_oos, status_code, evidence_str = await extract_verified_pdp_price(
                page, row, force_zyte_only=playwright_blocked_for_dom
            )

            if status_code in ("BLOCKED_HTTP", "BLOCKED_CAPTCHA"):
                domain_blocks[dom] = domain_blocks.get(dom, 0) + 1

            if status_code == "VERIFIED" and min_price is not None and min_price > 0:
                if "[Zyte]" in evidence_str:
                    zyte_rescued_count += 1
                prev_price = row.get("price")
                prev_date = row.get("last_read", "")

                # Daily Lowest Price Rule (AM/PM consolidation):
                # If we already read a LOWER price earlier today for this model/operator/country, keep the lower price of today
                effective_price = min_price
                effective_oos = bool(is_oos)
                effective_evidence = evidence_str

                existing_same_day = next(
                    (h for h in history if str(h.get("timestamp", ""))[:10] == today_str and h.get("country") == row["country"] and h.get("operator") == row["operator"] and h.get("code") == row["code"] and h.get("audit_status", "VALID") == "VALID"),
                    None
                )

                if existing_same_day and existing_same_day.get("price") is not None and float(existing_same_day["price"]) > 0:
                    old_day_price = float(existing_same_day["price"])
                    if min_price < old_day_price:
                        existing_same_day["intraday_higher_price"] = old_day_price
                        existing_same_day["audit_note"] = f"Preu mínim diari actualitzat a {run_slot} ({min_price:.2f} vs lectura prèvia d'avui {old_day_price:.2f})"
                        existing_same_day["price"] = min_price
                        existing_same_day["disc_imp"] = round(row["pvp"] - min_price, 2)
                        existing_same_day["disc_pct"] = round((existing_same_day["disc_imp"] / row["pvp"]) * 100, 1)
                        existing_same_day["out_of_stock"] = bool(is_oos)
                        existing_same_day["is_from"] = False
                        existing_same_day["evidence"] = evidence_str
                        existing_same_day["run_slot"] = run_slot
                        existing_same_day["timestamp_iso"] = now_iso
                    elif min_price > old_day_price:
                        effective_price = old_day_price
                        effective_oos = bool(existing_same_day.get("out_of_stock", False))
                        existing_same_day["intraday_higher_price"] = min_price
                        existing_same_day["audit_note"] = f"Mantingut preu mínim diari ({old_day_price:.2f}); lectura posterior a {run_slot}: {min_price:.2f}"
                        effective_evidence = f"{existing_same_day.get('evidence', evidence_str)} · [Mínim diari mantingut davant {min_price:.2f} a {run_slot}]"
                    else:
                        existing_same_day["timestamp_iso"] = now_iso
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
                        "price": effective_price,
                        "disc_imp": round(row["pvp"] - effective_price, 2),
                        "disc_pct": round(((row["pvp"] - effective_price) / row["pvp"]) * 100, 1),
                        "out_of_stock": effective_oos,
                        "is_from": False,
                        "url": url,
                        "audit_status": "VALID",
                        "evidence": effective_evidence
                    }
                    if prev_price is not None and prev_price != effective_price and prev_date != today_str:
                        new_entry["previous_price"] = prev_price
                        new_entry["previous_date"] = prev_date
                    history.append(new_entry)

                row["price"] = effective_price
                row["disc_imp"] = round(row["pvp"] - effective_price, 2)
                row["disc_pct"] = round((row["disc_imp"] / row["pvp"]) * 100, 1)
                row["status"] = "VERIFIED"
                row["freshness"] = "LIVE_TODAY"
                row["last_read"] = today_str
                row["out_of_stock"] = effective_oos
                row["is_from"] = False
                row["evidence"] = effective_evidence
                updated_count += 1
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

    print(f"Scan finished ({now_iso}). Auto-discovered PDPs: {discovered_count} | Live today: {updated_count} (Zyte rescued: {zyte_rescued_count}) | Quarantined: {quarantined_count} | Circuit-breaker skipped: {circuit_skipped} | Total history: {len(history)}")

if __name__ == "__main__":
    asyncio.run(main())
