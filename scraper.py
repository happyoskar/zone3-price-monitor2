import asyncio
import base64
import json
import os
import re
import time
import urllib.request
from datetime import datetime, timezone, timedelta
try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None

def get_madrid_now():
    if ZoneInfo is not None:
        try:
            return datetime.now(ZoneInfo("Europe/Madrid"))
        except Exception:
            pass
    return datetime.now(timezone(timedelta(hours=1)))
from urllib.parse import urlparse, quote_plus, unquote
from playwright.async_api import async_playwright

ZYTE_API_KEY = os.environ.get("ZYTE_API_KEY", "").strip()
START_MONOTONIC = time.monotonic()
PHASE2_START_MONOTONIC = None
PHASE2_BUDGET_SEC = 1080      # 18-minute dedicated budget for 100% automatic Phase 2 Auto-Discovery (freed by Dual-Lane ES || UK)
MAX_TOTAL_RUNTIME_SEC = 2280  # 38-minute global safety cap (leaves 7-min buffer inside 45-min GitHub Actions workflow)

PERMANENT_EXCLUSIONS = {
    "UK-DEP-WS21WADV101": "Exclosa fitxa Advance Plus (model diferent de WS21WADV101 Advance estàndard)",
    "UK-STA-WS25MSRV101": "Exclòs permanentment per configuració d'usuari (liquidació Start Fitness fora d'abast)"
}

DOMAIN_LOCKS = {}
DOMAIN_LAST_HIT = {}
MIN_SAME_DOMAIN_GAP_SEC = 1.3

def get_root_host(url):
    try:
        host = (urlparse(str(url or "")).netloc or "").lower()
        return host[4:] if host.startswith("www.") else (host or "unknown")
    except Exception:
        return "unknown"

async def throttled_domain_guard(url):
    if not url:
        return
    host = get_root_host(url)
    lock = DOMAIN_LOCKS.get(host)
    if lock is None:
        lock = asyncio.Lock()
        DOMAIN_LOCKS[host] = lock
    async with lock:
        now_t = time.monotonic()
        elapsed = now_t - DOMAIN_LAST_HIT.get(host, 0.0)
        if elapsed < MIN_SAME_DOMAIN_GAP_SEC:
            await asyncio.sleep(MIN_SAME_DOMAIN_GAP_SEC - elapsed)
        DOMAIN_LAST_HIT[host] = time.monotonic()

SECONDARY_OPERATORS = {
    ("ES", "365Rider"),
    ("ES", "ProSwimwear"),
    ("UK", "Start Fitness"),
    ("UK", "ProSwimwear"),
}

def is_secondary_operator(country, operator):
    return (country, operator) in SECONDARY_OPERATORS
MAX_CLEAN_NEW_DISC_PCT = 50.0          # Opció C (v12.6): fins al 50.0% automàtic; tot descompte >50.0% va a Safata de Revisió
CLEAN_NEW_MIN_RATIO = 0.50             # 1.0 - 0.50
MIXED_EX_RENTAL_MIN_RATIO = 0.60       # Bloqueig estructural en fitxes amb selector mixt Ex-Rental (p. ex. < £420 a Vanquish-X)
ZYTE_CONCURRENCY_SEM = None
ZYTE_PAGE_CACHE = {}
DISCOVERY_LINKS_CACHE = {}
COMPLETED_DISCOVERY_OPS = set()

USED_ITEM_TOKENS = (
    "ex-rental", "ex rental", "ex-hire", "ex hire", "ex-demo", "ex demo",
    "second-hand", "second hand", "segunda mano", "pre-owned", "pre owned",
    "reacondicionado", "refurbished", "b-stock", "grade b", "used wetsuit",
    "usedcondition", "refurbishedcondition", "damagedcondition"
)

def is_ex_rental_anomaly(country, operator, code, price_val, pvp_val=None):
    if price_val is None:
        return False
    p = float(price_val)
    if country == "UK" and operator == "My Triathlon" and code in ("WS22MVAN101", "WS22WVAN101") and p < 420.0:
        return True
    return False

def is_time_budget_exceeded(margin_sec=0):
    now_m = time.monotonic()
    if (now_m - START_MONOTONIC) >= (MAX_TOTAL_RUNTIME_SEC - margin_sec):
        return True
    if PHASE2_START_MONOTONIC is not None and (now_m - PHASE2_START_MONOTONIC) >= (PHASE2_BUDGET_SEC - margin_sec):
        return True
    return False

STEALTH_INIT_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
window.chrome = { runtime: {} };
Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
Object.defineProperty(navigator, 'languages', { get: () => ['es-ES', 'es', 'en-GB', 'en'] });
"""

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"

GENERIC_URL_PATTERNS = [
    "/brands/zone-3",
    "/brands/zone3",
    "/wetsuits/zone3/",
    "/natacion-zone3",
    "swimming-triathlon",
    "zone3%3awomen",
    "/store/zone-3/",
    "/marcas/zone3",
    "/brand/6-zone3",
    "/collections/zone3",
    "/product-category/",
    "/zone3-wetsuits"
]

OPERATOR_CATALOG_URLS = {
    ("ES", "Trade Inn"): [
        "https://www.tradeinn.com/swiminn/es/trajes-y-complementos-trajes/11400/s?q=zone3",
        "https://www.tradeinn.com/swiminn/es/s?q=zone3+versa",
        "https://www.tradeinn.com/swiminn/es/s?q=WS25WSRV101",
        "https://www.tradeinn.com/swiminn/es/s?q=5056305746940"
    ],
    ("ES", "Deporvillage"): [
        "https://www.deporvillage.com/natacion-zone3",
        "https://www.deporvillage.com/catalogsearch/result/?q=zone3+neopreno",
        "https://www.deporvillage.com/catalogsearch/result/?q=zone3+ascend",
        "https://www.deporvillage.com/catalogsearch/result/?q=zone3+sin+mangas",
        "https://www.deporvillage.com/catalogsearch/result/?q=zone3+sleeveless",
        "https://www.deporvillage.com/catalogsearch/result/?q=zone3+versa",
        "https://www.deporvillage.com/catalogsearch/result/?q=5056305752330",
        "https://www.deporvillage.com/catalogsearch/result/?q=5056305752385",
        "https://www.deporvillage.com/catalogsearch/result/?q=5056305746940"
    ],
    ("ES", "Bike 24"): [
        "https://www.bike24.es/marcas/zone3",
        "https://www.bike24.es/marcas/zone3?page=2",
        "https://www.bike24.es/marcas/zone3?page=3",
        "https://www.bike24.es/buscar?searchTerm=zone3+wetsuit",
        "https://www.bike24.es/buscar?searchTerm=zone3+active+flex",
        "https://www.bike24.es/buscar?searchTerm=zone3+versa",
        "https://www.bike24.es/buscar?searchTerm=WS25WACTF101",
        "https://www.bike24.es/buscar?searchTerm=5056305745455",
        "https://www.bike24.es/buscar?searchTerm=5056305746940"
    ],
    ("ES", "Sportano"): [
        "https://sportano.com/en/zone3",
        "https://sportano.com/en/zone3?p=2",
        "https://sportano.com/en/search?q=zone3+wetsuit"
    ],
    ("ES", "Wetsuit Outlet"): [
        "https://www.wetsuitoutlet.es/es-es/marcas/zone3",
        "https://www.wetsuitoutlet.es/en-es/brands/zone3",
        "https://www.wetsuitoutlet.es/zone3-m-123.html",
        "https://www.wetsuitoutlet.es/es-es/search?q=zone3+wetsuit",
        "https://www.wetsuitoutlet.es/en-es/search?q=zone3+wetsuit",
        "https://www.wetsuitoutlet.es/advanced_search_result.php?keywords=zone3+vanquish",
        "https://www.wetsuitoutlet.es/advanced_search_result.php?keywords=zone3+aspire",
        "https://www.wetsuitoutlet.es/advanced_search_result.php?keywords=zone3+versa"
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
        "https://www.alltricks.es/s?k=zone3+aspire+mujer",
        "https://www.alltricks.es/s?k=zone3+vision",
        "https://www.alltricks.es/s?k=zone3+vision+mujer",
        "https://www.alltricks.es/s?k=zone3+active+flex",
        "https://www.alltricks.es/s?k=zone3+active+flex+hombre",
        "https://www.alltricks.es/s?k=zone3+ascend",
        "https://www.alltricks.es/s?k=zone3+glide",
        "https://www.alltricks.es/s?k=zone3+versa"
    ],
    ("UK", "Trade Inn"): [
        "https://www.tradeinn.com/swiminn/en/suits-and-complements-suits/11400/s?q=zone3",
        "https://www.tradeinn.com/swiminn/en/s?q=zone3+versa",
        "https://www.tradeinn.com/swiminn/en/s?q=WS25WSRV101"
    ],
    ("UK", "Deporvillage"): [
        "https://www.deporvillage.co.uk/swimming-triathlon%3Azone3%3Aneoprene_wetsuits",
        "https://www.deporvillage.co.uk/catalogsearch/result/?q=zone3+wetsuit",
        "https://www.deporvillage.co.uk/catalogsearch/result/?q=zone3+advance+women",
        "https://www.deporvillage.co.uk/catalogsearch/result/?q=zone3+ascend",
        "https://www.deporvillage.co.uk/catalogsearch/result/?q=zone3+sleeveless",
        "https://www.deporvillage.co.uk/catalogsearch/result/?q=zone3+versa",
        "https://www.deporvillage.co.uk/catalogsearch/result/?q=zone3+versa+women",
        "https://www.deporvillage.co.uk/catalogsearch/result/?q=5056305710835",
        "https://www.deporvillage.co.uk/catalogsearch/result/?q=5056305752330",
        "https://www.deporvillage.co.uk/catalogsearch/result/?q=5056305752385",
        "https://www.deporvillage.co.uk/catalogsearch/result/?q=5056305746940"
    ],
    ("UK", "Sportshoes"): [
        "https://www.sportsshoes.com/products/?q=zone3%20wetsuit",
        "https://www.sportsshoes.com/products/?q=zone3%20aspire",
        "https://www.sportsshoes.com/products/?q=zone3%20ascend",
        "https://www.sportsshoes.com/products/?q=zone3%20glide",
        "https://www.sportsshoes.com/products/?q=zone3%20versa"
    ],
    ("UK", "My Triathlon"): [
        "https://mytriathlon.co.uk/brands/Zone-3.html",
        "https://mytriathlon.co.uk/search.php?search_query=zone3+versa"
    ],
    ("UK", "Sigma"): [
        "https://www.sigmasports.com/triathlon/wetsuits",
        "https://www.sigmasports.com/triathlon/wetsuits?p=2",
        "https://www.sigmasports.com/search?q=zone3&sort=price-high-low",
        "https://www.sigmasports.com/brand/zone3"
    ],
    ("UK", "Wetsuit Outlet"): [
        "https://www.wetsuitoutlet.co.uk/brands/zone3",
        "https://www.wetsuitoutlet.co.uk/zone3-m-123.html",
        "https://www.wetsuitoutlet.co.uk/search?q=zone3+wetsuit",
        "https://www.wetsuitoutlet.co.uk/advanced_search_result.php?keywords=zone3+vanquish",
        "https://www.wetsuitoutlet.co.uk/advanced_search_result.php?keywords=zone3+aspire",
        "https://www.wetsuitoutlet.co.uk/advanced_search_result.php?keywords=zone3+versa"
    ],
    ("ES", "365Rider"): [
        "https://www.365rider.com/brand/6-zone3",
        "https://www.365rider.com/brand/6-zone3?page=2",
        "https://www.365rider.com/busqueda?controller=search&s=zone3+neopreno",
        "https://www.365rider.com/busqueda?controller=search&s=zone3"
    ],
    ("ES", "ProSwimwear"): [
        "https://www.proswimwear.es/product-category/brands/zone3/zone3-wetsuits/",
        "https://www.proswimwear.es/product-category/brands/zone3/zone3-wetsuits/page/2/",
        "https://www.proswimwear.es/product-category/brands/zone3/",
        "https://www.proswimwear.es/?s=zone3+neopreno&post_type=product",
        "https://www.proswimwear.es/?s=zone3+wetsuit&post_type=product"
    ],
    ("UK", "Start Fitness"): [
        "https://startfitness.co.uk/collections/zone3",
        "https://startfitness.co.uk/collections/zone3?page=2",
        "https://startfitness.co.uk/search?q=zone3+wetsuit&type=product",
        "https://startfitness.co.uk/search?q=zone3&type=product"
    ],
    ("UK", "ProSwimwear"): [
        "https://www.proswimwear.co.uk/product-category/brands/zone3/zone3-wetsuits/",
        "https://www.proswimwear.co.uk/product-category/brands/zone3/zone3-wetsuits/page/2/",
        "https://www.proswimwear.co.uk/product-category/brands/zone3/",
        "https://www.proswimwear.co.uk/?s=zone3+wetsuit&post_type=product"
    ]
}

# Candidate direct URLs & sequential ID probes for missing SKUs across operators
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
    ("ES", "Deporvillage", "WS22MVAN101"): [
        "https://www.deporvillage.com/traje-neopreno-zone3-vanquish-x",
        "https://www.deporvillage.com/traje-neopreno-zone3-vanquish-x-negro-naranja",
        "https://www.deporvillage.com/traje-de-neopreno-zone3-vanquish-x",
        "https://www.deporvillage.com/traje-neopreno-zone3-vanquish-x-2"
    ],
    ("ES", "Deporvillage", "WS22WVAN101"): [
        "https://www.deporvillage.com/traje-neopreno-zone3-vanquish-x-mujer",
        "https://www.deporvillage.com/traje-neopreno-zone3-vanquish-x-negro-naranja-mujer",
        "https://www.deporvillage.com/traje-de-neopreno-zone3-vanquish-x-mujer",
        "https://www.deporvillage.com/traje-neopreno-zone3-vanquish-x-mujer-2"
    ],
    ("ES", "Deporvillage", "WS26MGLISL101"): [
        "https://www.deporvillage.com/traje-neopreno-zone3-ascend-sin-mangas",
        "https://www.deporvillage.com/traje-de-neopreno-zone3-ascend-sin-mangas",
        "https://www.deporvillage.com/traje-neopreno-zone3-ascend-sleeveless"
    ],
    ("ES", "Deporvillage", "WS26WGLISL101"): [
        "https://www.deporvillage.com/traje-neopreno-zone3-ascend-sin-mangas-mujer",
        "https://www.deporvillage.com/traje-de-neopreno-zone3-ascend-sin-mangas-mujer",
        "https://www.deporvillage.com/traje-neopreno-zone3-ascend-sleeveless-mujer"
    ],
    ("ES", "Deporvillage", "WS25WSRV101"): [
        "https://www.deporvillage.com/traje-neopreno-zone3-versa-swimrun-mujer",
        "https://www.deporvillage.com/traje-de-neopreno-zone3-versa-swimrun-mujer"
    ],
    ("UK", "Deporvillage", "WS21WADV101"): [
        "https://www.deporvillage.co.uk/zone3-advance-wetsuit-black-grey-blue-women",
        "https://www.deporvillage.co.uk/zone3-advance-wetsuit-black-pink-women",
        "https://www.deporvillage.co.uk/zone3-advance-wetsuit-black-turquoise-women",
        "https://www.deporvillage.co.uk/zone3-advance-wetsuit-women"
    ],

    ("UK", "Deporvillage", "WS26MGLISL101"): [
        "https://www.deporvillage.co.uk/zone3-ascend-sleeveless-wetsuit-black-grey",
        "https://www.deporvillage.co.uk/zone3-ascend-sleeveless-wetsuit"
    ],
    ("UK", "Deporvillage", "WS26WGLISL101"): [
        "https://www.deporvillage.co.uk/zone3-ascend-sleeveless-wetsuit-black-grey-women",
        "https://www.deporvillage.co.uk/zone3-ascend-sleeveless-wetsuit-women"
    ],
    ("ES", "Wetsuit Outlet", "WS25WASP101"): [
        "https://www.wetsuitoutlet.es/2026-zone3-mujer-aspire-neopreno-ws25wasp-black-chalk-p-53918.html?currency=EUR",
        "https://www.wetsuitoutlet.es/2026-zone3-mujer-aspire-neopreno-ws25wasp101-black-chalk-p-53918.html?currency=EUR"
    ],
    ("UK", "Wetsuit Outlet", "WS25WASP101"): [
        "https://www.wetsuitoutlet.co.uk/2026-zone3-womens-aspire-wetsuit-ws25wasp-black-chalk-p-53918.html?currency=GBP",
        "https://www.wetsuitoutlet.co.uk/2026-zone3-womens-aspire-wetsuit-ws25wasp101-black-chalk-p-53918.html?currency=GBP"
    ],
    ("ES", "Triathlon24", "WS22MVAN101"): [
        "https://www.triathlon24.nl/zone3-vanquish-x-wetsuit-lange-mouw-heren/",
        "https://www.triathlon24.nl/zone3-vanquish-x-fullsleeve-wetsuit-heren/"
    ],
    ("ES", "Triathlon24", "WS22WVAN101"): [
        "https://www.triathlon24.nl/zone3-vanquish-x-wetsuit-lange-mouw-dames/",
        "https://www.triathlon24.nl/zone3-vanquish-x-fullsleeve-wetsuit-dames/"
    ],
    ("ES", "Triathlon24", "WS26MGLISL101"): [
        "https://www.triathlon24.nl/zone3-ascend-sleeveless-wetsuit-heren/",
        "https://www.triathlon24.nl/zone3-glide-sleeveless-wetsuit-heren/",
        "https://www.triathlon24.nl/zone3-ascend-wetsuit-mouwloos-heren/"
    ],
    ("ES", "Triathlon24", "WS26WGLISL101"): [
        "https://www.triathlon24.nl/zone3-ascend-sleeveless-wetsuit-dames/",
        "https://www.triathlon24.nl/zone3-glide-sleeveless-wetsuit-dames/",
        "https://www.triathlon24.nl/zone3-ascend-wetsuit-mouwloos-dames/"
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
    ("UK", "Wetsuit Outlet"): "wetsuitoutlet.co.uk",
    ("ES", "365Rider"): "365rider.com",
    ("ES", "ProSwimwear"): "proswimwear.es",
    ("UK", "Start Fitness"): "startfitness.co.uk",
    ("UK", "ProSwimwear"): "proswimwear.co.uk"
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
    "WS21MAGI116": ["agile", "ágil", "agil"],
    "WS21WAGI114": ["agile", "ágil", "agil"],
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
    if any(x in u_low for x in ["/search", "catalogsearch", "searchterm=", "?q=", "/s?k=", "advanced_search_result", "controller=search", "jolisearch", "?s=", "&post_type=product"]):
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
    raw_combined = f"{text_to_check} {url}".lower()
    # Normalize underscores, hyphens, slashes, and punctuation to spaces so \b word-boundary regexes work on underscore URLs (e.g. Alltricks _para_mujer_)
    combined = re.sub(r"[_/\-|.,;:()\[\]]+", " ", raw_combined)
    keywords = MODEL_KEYWORDS.get(code, [])
    if keywords and not any(k in raw_combined or k in combined for k in keywords):
        return False, f"El producte ('{text_to_check[:45]}') no conté el model ({'/'.join(keywords)})"

    if "GLISL" in code:
        if not any(w in combined for w in ["sleeveless", "sin mangas", "mouwloos", "sans manches", "glisl", "ascend"]):
            return False, "El model és Sleeveless (sense mànigues) però la fitxa és de màniga llarga"
    else:
        if any(w in combined for w in ["sleeveless", "sin mangas", "mouwloos", "sans manches"]):
            return False, "El model és de màniga llarga però la fitxa és Sleeveless"

    if "ADV" in code and any(plus_tok in raw_combined or plus_tok in combined for plus_tok in ["advance+", "advance plus", "advance-plus", "advence+", "advence plus"]):
        return False, "Versió Advance+ / Advance Plus exclosa (el model monitoritzat és l'Advance estàndard)"

    if any(used_tok in raw_combined or used_tok in combined for used_tok in USED_ITEM_TOKENS):
        return False, "Producte de 2a mà / Ex-Rental exclòs (només producte nou)"

    if "deporvillage." in raw_combined and re.search(r"\bglide\b", combined):
        return False, "Model Glide exclòs a Deporvillage (es monitoritza exclusivament Ascend)"

    if any(re.search(r"\b" + re.escape(bad) + r"\b", combined) for bad in ["goggles", "gafas", "gloves", "guantes", "socks", "calcetines", "buoy", "boya", "cap", "caps", "gorro", "trisuit", "tritraje", "mono", "bañador", "banador", "chaleco", "camiseta", "culotte", "malla", "kneeskin", "jammer", "parka", "jacket", "shorts", "pants", "backpack", "bag", "thermal", "térmico", "termico", "breaststroke", "aspect", "evolution", "kona-target", "swim skin", "swimskin", "robe"]):
        return False, "Accessori, mono o variant diferent (Mono/Bañador/Thermal/Aspect/Evolution) exclosa"

    if re.search(r"\b(?:201[5-9]|2020)\b", combined):
        return False, "Model de temporada antiga (2015-2020) exclòs"

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
    if "365rider.com" in u_low and country == "ES" and "/gb/" in u_low:
        return False, "URL 365Rider amb ruta /gb/ en mercat ES"
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
        with urllib.request.urlopen(req, timeout=45) as resp:
            if resp.status != 200:
                return None
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


NEXTJS_SALE_PRICE_KEYS = (
    "finalprice", "saleprice", "specialprice", "discountedprice",
    "currentprice", "pricewithtax", "sellingprice", "offerprice",
    "netprice", "ourprice", "activeprice", "price", "lowprice"
)
NEXTJS_FORBIDDEN_PRICE_KEYS = (
    "old", "orig", "rrp", "pvp", "msrp", "cross", "strike", "recommend",
    "previous", "was", "listprice", "withouttax", "shipping", "delivery",
    "installment", "quota", "iva", "taxamount", "discount", "saving"
)

def extract_nextjs_hydration_raw(html_str):
    """Extracts __NEXT_DATA__ JSON string and decoded Next.js App Router RSC (__next_f) chunks."""
    if not html_str:
        return "", ""
    next_data_str = ""
    m_nd = re.search(r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>', html_str, flags=re.I | re.S)
    if m_nd:
        next_data_str = m_nd.group(1).strip()

    rsc_chunks = []
    if "__next_f" in html_str:
        for m_rsc in re.finditer(r'self\.__next_f\.push\(\[\s*\d+\s*,\s*"((?:\\.|[^"\\])*)"\s*\]\)', html_str, flags=re.S):
            raw_chunk = m_rsc.group(1)
            try:
                decoded = json.loads(f'"{raw_chunk}"')
            except Exception:
                decoded = (
                    raw_chunk
                    .replace('\\"', '"')
                    .replace('\\/', '/')
                    .replace('\\n', ' ')
                    .replace('\\\\', '\\')
                )
            if any(tok in decoded.lower() for tok in ("price", "pvp", "ws2", "zone3", "vanquish", "aspire", "vision", "advance", "agile", "versa", "ascend", "stock", "instock", "agotado")):
                rsc_chunks.append(decoded)
    rsc_joined = "\n".join(rsc_chunks)[:220000]
    return next_data_str, rsc_joined

def extract_nextjs_candidates_for_row(page_info, row):
    """Safely extracts main-product sale prices & stock from Next.js (__NEXT_DATA__ and __next_f RSC) verifying SKU/slug/model identity."""
    results = []
    code = row["code"]
    model_name = row["model"]
    url = row.get("url", "").strip()
    expected_curr = row["currency"]
    pvp = float(row["pvp"])
    ean = MODEL_EANS.get(code, "")
    parsed_u = urlparse(url)
    url_slug = parsed_u.path.strip("/").split("/")[-1].lower() if parsed_u.path else ""

    next_data_str = page_info.get("nextDataJson") or ""
    rsc_text = page_info.get("nextRscText") or ""

    def _is_forbidden_key(k_low):
        return any(bad in k_low for bad in NEXTJS_FORBIDDEN_PRICE_KEYS)

    def _extract_numeric_price_from_obj(val_obj):
        if isinstance(val_obj, (int, float)) and not isinstance(val_obj, bool):
            return float(val_obj)
        if isinstance(val_obj, str):
            if re.match(r"^\s*[\d]{2,4}(?:[.,]\d{1,2})?\s*(?:€|£|EUR|GBP)?\s*$", val_obj, flags=re.I):
                return normalize_price(val_obj)
            return None
        if isinstance(val_obj, dict):
            for sub_k in ("finalPrice", "salePrice", "specialPrice", "discountedPrice", "currentPrice", "priceWithTax", "value", "amount", "gross", "raw", "price"):
                if sub_k in val_obj and not _is_forbidden_key(sub_k.lower()):
                    sub_v = _extract_numeric_price_from_obj(val_obj[sub_k])
                    if sub_v is not None:
                        return sub_v
        return None

    # 1. Walk structured __NEXT_DATA__ JSON
    if next_data_str:
        try:
            nd_root = json.loads(next_data_str)

            def _walk_nd(node, inherited_ident="", inherited_curr="", in_related=False, depth=0):
                if depth > 22 or in_related:
                    return
                if isinstance(node, list):
                    for elem in node[:80]:
                        _walk_nd(elem, inherited_ident, inherited_curr, in_related, depth + 1)
                    return
                if not isinstance(node, dict):
                    return

                # Skip related / carousel / cross-sell branches
                local_ident_parts = []
                for id_k in ("name", "title", "productName", "sku", "reference", "ref", "mpn", "ean", "gtin", "gtin13", "slug", "url", "urlKey", "canonicalUrl"):
                    v = node.get(id_k)
                    if isinstance(v, str) and v.strip():
                        local_ident_parts.append(v.strip())
                local_ident = " ".join(local_ident_parts)
                eff_ident = f"{inherited_ident} {local_ident}".strip()
                eff_low = eff_ident.lower()

                local_curr = str(node.get("currency") or node.get("currencyCode") or node.get("priceCurrency") or inherited_curr or "").upper().strip()
                if local_curr in ("€", "EUR"):
                    local_curr = "EUR"
                elif local_curr in ("£", "GBP"):
                    local_curr = "GBP"

                # Check stock signals on this object
                is_oos = False
                has_instock = False
                for st_k in ("inStock", "isAvailable", "available", "hasStock"):
                    if st_k in node and isinstance(node[st_k], bool):
                        if node[st_k]:
                            has_instock = True
                        else:
                            is_oos = True
                if "availability" in node and isinstance(node["availability"], str):
                    av_l = node["availability"].lower()
                    if "outofstock" in av_l or "discontinued" in av_l:
                        is_oos = True
                    elif "instock" in av_l:
                        has_instock = True
                if "stock" in node and isinstance(node["stock"], (int, float)) and not isinstance(node["stock"], bool):
                    if node["stock"] <= 0 and not has_instock:
                        is_oos = True
                    elif node["stock"] > 0:
                        has_instock = True

                # Verify this dict belongs to our target product (by exact SKU/EAN/slug or validated product identity)
                has_exact_ref = (
                    code.lower() in eff_low
                    or (ean and ean in eff_low)
                    or (url_slug and len(url_slug) >= 12 and url_slug in eff_low)
                )
                id_valid = has_exact_ref
                if not id_valid and local_ident:
                    kws = MODEL_KEYWORDS.get(code, [])
                    if kws and any(kw in eff_low for kw in kws):
                        ok_id, _ = validate_product_identity(eff_ident, url if has_exact_ref else "", code, model_name)
                        if not ok_id:
                            # Allow gender inheritance from canonical URL only when product name matches model keywords and doesn't contradict gender
                            ok_with_u, _ = validate_product_identity(eff_ident, url, code, model_name)
                            id_valid = ok_with_u
                        else:
                            id_valid = True

                if id_valid and not any(ut in eff_low for ut in USED_ITEM_TOKENS):
                    # Extract best sale price on this node (preferring explicit sale/final keys over generic 'price' if 'price' equals RRP)
                    node_prices = []
                    for k, v in node.items():
                        k_low = k.lower()
                        if _is_forbidden_key(k_low):
                            continue
                        if k_low in NEXTJS_SALE_PRICE_KEYS or k_low in ("prices", "pricing", "priceinfo", "offer", "offers"):
                            p_num = _extract_numeric_price_from_obj(v)
                            if p_num is not None and (pvp * 0.30) <= p_num <= (pvp * 1.20):
                                prio_k = 0 if k_low in ("finalprice", "saleprice", "specialprice", "discountedprice", "currentprice", "pricewithtax", "sellingprice") else 1
                                node_prices.append((prio_k, p_num, k))
                    if node_prices:
                        node_prices.sort(key=lambda x: (1 if (x[1] >= pvp * 0.995 and len(node_prices) > 1) else 0, x[0], x[1]))
                        best_np = node_prices[0]
                        sz_lbl = str(node.get("size") or node.get("sizeName") or node.get("label") or "").strip()
                        results.append({
                            "price": best_np[1],
                            "oos": bool(is_oos and not has_instock),
                            "currency": local_curr,
                            "size": sz_lbl,
                            "source": f"Next.js __NEXT_DATA__ ({best_np[2]})"
                        })

                for k, v in node.items():
                    k_low = k.lower()
                    child_related = any(rk in k_low for rk in ("related", "recommend", "similar", "crosssell", "upsell", "alsobought", "carousel", "alternatives"))
                    _walk_nd(v, eff_ident if (local_ident or has_exact_ref) else inherited_ident, local_curr, child_related, depth + 1)

            _walk_nd(nd_root)
        except Exception:
            pass

    # 2. Parse Next.js App Router RSC stream (self.__next_f.push) anchored around the target SKU / EAN / URL slug
    if rsc_text:
        rsc_low = rsc_text.lower()
        anchors = []
        for token in filter(None, [f"z3-{code.lower()}", code.lower(), ean.lower() if ean else "", url_slug]):
            if len(token) >= 8:
                for m_anc in re.finditer(re.escape(token), rsc_low):
                    anchors.append(m_anc.start())
        # Deduplicate nearby anchor positions into windows around the main product payload
        anchors.sort()
        windows = []
        for pos in anchors:
            w_start = max(0, pos - 900)
            w_end = min(len(rsc_text), pos + 1800)
            # Truncate window before any related/carousel list or another product card's slug/url
            head_slice = rsc_low[w_start:pos]
            for m_prev_slug in re.finditer(r'"(?:slug|urlkey|canonicalurl)"\s*:\s*"([^"]+)"', head_slice):
                s_val = m_prev_slug.group(1)
                if url_slug and url_slug not in s_val and code.lower() not in s_val:
                    w_start = w_start + m_prev_slug.end()
            tail_slice = rsc_low[pos:w_end]
            m_rel = re.search(r'"(?:relatedproducts|recommendedproducts|similarproducts|crosssell|upsell|recommendations|alternatives|products|items)"\s*:', tail_slice)
            if m_rel:
                w_end = pos + m_rel.start()
            for m_next_slug in re.finditer(r'"(?:slug|urlkey|canonicalurl)"\s*:\s*"([^"]+)"', rsc_low[pos:w_end]):
                s_val = m_next_slug.group(1)
                if url_slug and url_slug not in s_val and code.lower() not in s_val and m_next_slug.start() > 40:
                    w_end = pos + m_next_slug.start()
                    break
            if windows and w_start <= windows[-1][1]:
                windows[-1] = (windows[-1][0], max(windows[-1][1], w_end))
            else:
                windows.append((w_start, w_end))

        rsc_price_patterns = [
            (0, r'"(finalPrice|salePrice|specialPrice|discountedPrice|currentPrice|priceWithTax|sellingPrice)"\s*:\s*(?:\{\s*"(?:value|amount|raw|gross)"\s*:\s*)?"?([\d]{2,4}(?:\.\d{1,2})?)"?'),
            (1, r'"(price|lowPrice)"\s*:\s*(?:\{\s*"(?:value|amount|raw|gross)"\s*:\s*)?"?([\d]{2,4}(?:\.\d{1,2})?)"?')
        ]
        for (w_s, w_e) in windows:
            win_txt = rsc_text[w_s:w_e]
            win_low = win_txt.lower()
            if any(ut in win_low for ut in USED_ITEM_TOKENS):
                continue
            win_curr = ""
            m_wc = re.search(r'"(?:priceCurrency|currency|currencyCode)"\s*:\s*"(EUR|GBP|€|£)"', win_txt, flags=re.I)
            if m_wc:
                c_raw = m_wc.group(1).upper()
                win_curr = "EUR" if c_raw in ("EUR", "€") else "GBP"

            win_has_instock = bool(re.search(r'"(?:inStock|isAvailable|available)"\s*:\s*true|schema\.org/InStock|"stock"\s*:\s*[1-9]', win_txt, flags=re.I))
            win_has_oos = bool(re.search(r'"(?:inStock|isAvailable|available)"\s*:\s*false|schema\.org/OutOfStock', win_txt, flags=re.I))
            win_oos = bool(win_has_oos and not win_has_instock)

            found_in_win = []
            for prio_p, pat in rsc_price_patterns:
                for mp in re.finditer(pat, win_txt, flags=re.I):
                    # Ensure not inside an unclosed oldPrice/rrp wrapper object like `"oldPrice":{"price":859}`
                    ctx_before = win_txt[max(0, mp.start() - 45):mp.start()].lower()
                    if "}" not in ctx_before and re.search(r'"[^"]*(?:old|orig|rrp|pvp|msrp|cross|strike|recommend|previous|was|withouttax|shipping)[^"]*"\s*:\s*\{\s*$', ctx_before):
                        continue
                    p_val = normalize_price(mp.group(2))
                    if p_val is not None and (pvp * 0.30) <= p_val <= (pvp * 1.20):
                        found_in_win.append((prio_p, p_val, mp.group(1)))
            if found_in_win:
                found_in_win.sort(key=lambda x: (1 if (x[1] >= pvp * 0.995 and len(found_in_win) > 1) else 0, x[0], x[1]))
                for _, pv, pk in found_in_win[:3]:
                    results.append({
                        "price": pv,
                        "oos": win_oos,
                        "currency": win_curr,
                        "size": "",
                        "source": f"Next.js RSC __next_f ({pk})"
                    })

    return results

def parse_html_fast_stdlib(html_str, base_url, zprod=None):
    """Instant (<5ms) pure-Python stdlib parser for Zyte HTML with full Next.js (__NEXT_DATA__ / __next_f) & bottom JSON-LD support."""
    if not html_str:
        info = {"title": "", "h1": "", "ldNodes": [], "ldPrimaryCount": 0, "nextDataJson": "", "nextRscText": "", "metaCurr": "", "metaPrice": "", "domPrices": [], "bodyText": "", "links": [], "hasExRentalOption": False}
    else:
        m_title = re.search(r"<title[^>]*>(.*?)</title>", html_str, flags=re.I | re.S)
        title = re.sub(r"\s+", " ", m_title.group(1)).strip() if m_title else ""

        m_head = re.search(r"<head[^>]*>(.*?)</head>", html_str, flags=re.I | re.S)
        head_html = m_head.group(1) if m_head else html_str[:12000]

        h1_matches = re.findall(r"<h1[^>]*>(.*?)</h1>", html_str, flags=re.I | re.S)
        h1_list = [re.sub(r"<[^>]+>", " ", h).strip() for h in h1_matches]
        h1 = re.sub(r"\s+", " ", " | ".join(filter(None, h1_list))).strip()
        # Fallback H1 from main product image alt if SPA delayed H1 tag in static snapshot
        if not h1:
            m_alt_h1 = re.search(r'<img[^>]+alt=["\']([^"\']*zone3[^"\']*?)\s*-\s*#1["\']', html_str, flags=re.I)
            if m_alt_h1:
                h1 = m_alt_h1.group(1).strip()

        # Truncate DOM HTML BEFORE bottom Related/Carousel sections for DOM microdata only,
        # while keeping ALL JSON-LD scripts across the entire document (Next.js injects JSON-LD at the bottom of <body>!)
        m_h1_raw = re.search(r"<h1[^>]*>", html_str, flags=re.I)
        h1_raw_idx = m_h1_raw.start() if m_h1_raw else 0
        m_raw_cut = re.search(
            r'(?:id=["\'](?:tab-related|tab-similar|related-products)["\']|data-list-name=["\'][^"\']*(?:Related|Viewed|Similar)[^"\']*["\']|class=["\'][^"\']*(?:productCarousel|related-products|similar-products|cross-sell|upsell|products-accessories|featured-products)[^"\']*["\']|>\s*(?:Related Products|Customers Also Viewed|You May Also Need|You may also like|Completa tu compra|More Like This|Similar Products|Productos relacionados|También te puede interesar)\s*<)',
            html_str[h1_raw_idx:],
            flags=re.I
        )
        truncated_raw_html = html_str[:h1_raw_idx + m_raw_cut.start()] if m_raw_cut else html_str

        ld_primary = re.findall(r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', truncated_raw_html, flags=re.I | re.S)
        ld_tail = re.findall(r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html_str[len(truncated_raw_html):], flags=re.I | re.S) if len(truncated_raw_html) < len(html_str) else []
        ld_nodes = ld_primary + ld_tail
        ld_primary_count = len(ld_primary)

        next_data_str, next_rsc_txt = extract_nextjs_hydration_raw(html_str)

        meta_curr = ""
        m_mc = re.search(r'<meta[^>]+(?:property|name|itemprop)=["\'](?:product:price:currency|og:price:currency|priceCurrency)["\'][^>]+content=["\']([^"\']+)["\']', head_html, flags=re.I)
        if not m_mc:
            m_mc = re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name|itemprop)=["\'](?:product:price:currency|og:price:currency|priceCurrency)["\']', head_html, flags=re.I)
        if m_mc:
            meta_curr = m_mc.group(1).strip()

        # Only read OpenGraph / Product price meta tags from <head> (never body card itemprop="price" here)
        meta_price = ""
        m_mp = re.search(r'<meta[^>]+(?:property|name)=["\'](?:product:price:amount|og:price:amount)["\'][^>]+content=["\']([^"\']+)["\']', head_html, flags=re.I)
        if not m_mp:
            m_mp = re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\'](?:product:price:amount|og:price:amount)["\']', head_html, flags=re.I)
        if m_mp:
            meta_price = m_mp.group(1).strip()

        # Strip out related/recommended/carousel/footer/aside/strikeout/rrp/withoutTax blocks on truncated main HTML
        main_html = re.sub(r"<(script|style|noscript|aside|footer|nav|header|del|s)[^>]*>.*?</\1>", " ", truncated_raw_html, flags=re.I | re.S)
        main_html = re.sub(
            r'<(div|section|ul|span)[^>]+(?:class|id|data-testid)=["\'][^"\']*(?:related|recommend|productCarousel|related-carousel|related-slider|upsell|cross-sell|similar|also-bought|alternatives|old-price|price-old|rrp|non-sale|withoutTax|strike)[^"\']*["\'][^>]*>.*?</\1>',
            " ",
            main_html,
            flags=re.I | re.S
        )

        # Detect if the main product form/options mix an Ex-Rental / Ex-Demo / Second-Hand variant inside the same PDP
        used_ctx_tokens = USED_ITEM_TOKENS
        main_text_only = re.sub(r"<[^>]+>", " ", main_html[h1_raw_idx:] if h1_raw_idx < len(main_html) else main_html).lower()
        has_ex_rental_opt = any(ut in main_text_only for ut in used_ctx_tokens)

        dom_prices = []
        for m_p in re.finditer(r'id=["\'](?:js-precio|productPrice|product-price)["\'][^>]*>([^<]+)<', main_html, flags=re.I):
            dom_prices.append({"selector": "#productPrice", "text": m_p.group(1).strip(), "attrCurr": meta_curr})
        for m_ip in re.finditer(r'(?:itemprop=["\']price["\'][^>]*content=["\']([^"\']+)["\']|content=["\']([^"\']+)["\'][^>]*itemprop=["\']price["\'])', main_html, flags=re.I):
            ip_val = (m_ip.group(1) or m_ip.group(2) or "").strip()
            ctx_prev = main_html[max(0, m_ip.start() - 450):m_ip.start()].lower()
            if ip_val and not any(ut in ctx_prev for ut in used_ctx_tokens):
                dom_prices.append({"selector": "[itemprop=price]", "text": ip_val, "attrCurr": meta_curr})
        for m_dpa in re.finditer(r'data-price-type=["\']finalPrice["\'][^>]*data-price-amount=["\']([\d.]+)["\']|data-price-amount=["\']([\d.]+)["\'][^>]*data-price-type=["\']finalPrice["\']', main_html, flags=re.I):
            dpa_val = (m_dpa.group(1) or m_dpa.group(2) or "").strip()
            ctx_prev = main_html[max(0, m_dpa.start() - 450):m_dpa.start()].lower()
            if dpa_val and not any(ut in ctx_prev for ut in used_ctx_tokens):
                dom_prices.append({"selector": "[data-price-amount]", "text": dpa_val, "attrCurr": meta_curr})
        for m_dt in re.finditer(r'data-testid=["\'](?:product-price|price|current-price|final-price)["\'][^>]*>(.*?)</(?:span|div|p|strong)>', main_html, flags=re.I | re.S):
            txt_dt = re.sub(r"<[^>]+>", " ", m_dt.group(1)).strip()
            if txt_dt and len(txt_dt) < 35:
                dom_prices.append({"selector": "[data-testid=product-price]", "text": txt_dt, "attrCurr": meta_curr})
        for m_cls in re.finditer(r'class=["\'][^"\']*(?:product-detail-price|pdp-price|product-page-price|price--main|price--withTax|product-price__price|now-price|price-now|current-price-value|price-item--sale|product__price)[^"\']*["\'][^>]*>(.*?)</(?:span|div|p|strong)>', main_html, flags=re.I | re.S):
            ctx_prev = main_html[max(0, m_cls.start() - 450):m_cls.start()].lower()
            if any(ut in ctx_prev for ut in used_ctx_tokens):
                continue
            txt_cls = re.sub(r"<[^>]+>", " ", m_cls.group(1)).strip()
            if txt_cls and len(txt_cls) < 40:
                dom_prices.append({"selector": ".pdp-price", "text": txt_cls, "attrCurr": meta_curr})
        for m_woo in re.finditer(r'<p[^>]+class=["\'][^"\']*\bprice\b[^"\']*["\'][^>]*>(.*?)</p>', main_html, flags=re.I | re.S):
            woo_inner = m_woo.group(1)
            m_ins = re.search(r'<ins[^>]*>(.*?)</ins>', woo_inner, flags=re.I | re.S)
            target_woo = m_ins.group(1) if m_ins else re.sub(r'<del[^>]*>.*?</del>', ' ', woo_inner, flags=re.I | re.S)
            txt_woo = re.sub(r'<[^>]+>', ' ', target_woo)
            txt_woo = re.sub(r'\s+', ' ', txt_woo).strip()
            if txt_woo and len(txt_woo) < 45:
                dom_prices.append({"selector": "p.price", "text": txt_woo, "attrCurr": meta_curr})

        # Extract links including title, aria-label, inner img alt, surrounding card text (for empty stretched-link overlays),
        # DuckDuckGo uddg= redirect unwrapping, and JSON/hydration product URLs (Alltricks, Wetsuit Outlet, Sportano, Sigma, etc.)
        links = []
        seen_hrefs = {}
        parsed_base = urlparse(base_url)
        base_origin = f"{parsed_base.scheme}://{parsed_base.netloc}" if parsed_base.scheme else ""

        def register_link(raw_href, raw_text):
            if not raw_href:
                return
            h = raw_href.replace("\\/", "/").strip()
            if "uddg=" in h:
                m_u = re.search(r'uddg=([^&"\s]+)', h)
                if m_u:
                    h = unquote(m_u.group(1))
            if h.startswith("//"):
                h = "https:" + h
            elif h.startswith("/") and base_origin:
                h = base_origin + h
            if not h.startswith("http"):
                return
            h_clean = h.split("#")[0].strip()
            t_clean = re.sub(r"\s+", " ", (raw_text or "")).strip()
            if h_clean in seen_hrefs:
                if t_clean and t_clean not in seen_hrefs[h_clean]:
                    seen_hrefs[h_clean] = (seen_hrefs[h_clean] + " " + t_clean).strip()
            else:
                seen_hrefs[h_clean] = t_clean

        for m_a in re.finditer(r'<a\s+([^>]*?)href=["\']([^"\']+)["\']([^>]*)>(.*?)</a>', html_str, flags=re.I | re.S):
            attrs_before, href, attrs_after, inner_html = m_a.group(1), m_a.group(2).strip(), m_a.group(3), m_a.group(4)
            all_attrs = f"{attrs_before} {attrs_after}"
            attr_texts = re.findall(r'(?:title|aria-label|data-name|data-product-name)=["\']([^"\']+)["\']', all_attrs, flags=re.I)
            img_alts = re.findall(r'alt=["\']([^"\']+)["\']', inner_html, flags=re.I)
            inner_txt = re.sub(r"<[^>]+>", " ", inner_html)
            combined_txt = " ".join([inner_txt] + attr_texts + img_alts).strip()
            # If the <a> tag is an empty stretched-link overlay inside a product card, grab nearby card heading text
            if len(re.sub(r"\s+", "", combined_txt)) < 6:
                after_slice = html_str[m_a.end():m_a.end() + 320]
                m_card_h = re.search(r'<(?:h[234]|p|span|div)[^>]+class=["\'][^"\']*(?:title|name|label|product)[^"\']*["\'][^>]*>(.*?)</', after_slice, flags=re.I | re.S)
                if m_card_h:
                    combined_txt = (combined_txt + " " + re.sub(r"<[^>]+>", " ", m_card_h.group(1))).strip()
            register_link(href, combined_txt)

        # Also extract PDP URLs embedded in JSON-LD ItemList or hydration state (Alltricks /P-, Wetsuit Outlet -p-, Sportano /p/, Sigma /item/, Sportshoes /product/)
        for m_json_u in re.finditer(
            r'["\']((?:https?:\\?/\\?/[^"\']*?|\\?/(?:es-es/|en-es/|es/)?)(?:F-\d+-[^"\']*?/P-\d+-[^"\']+|[^"\']*?-p-\d+\.html|\d+-[^"\']*zone3[^"\']*\.html|products/[^"\']*zone3[^"\']+|product/[^"\']*zone3[^"\']+|p/\d+/[^"\']+|item/Zone3/[^"\']+|product/zne\d+/[^"\']+|traje-(?:de-)?neopreno-zone3-[^"\']+|zone3-[^"\']+))["\']',
            html_str,
            flags=re.I
        ):
            u_cand = m_json_u.group(1)
            ctx_slice = html_str[max(0, m_json_u.start() - 220):min(len(html_str), m_json_u.end() + 220)]
            m_name_ctx = re.findall(r'["\'](?:name|title|productName)["\']\s*:\s*["\']([^"\']+)["\']', ctx_slice, flags=re.I)
            register_link(u_cand, " ".join(m_name_ctx))

        links = [{"href": k, "text": v} for k, v in seen_hrefs.items()]

        clean_html = re.sub(r"<(script|style|noscript)[^>]*>.*?</\1>", " ", html_str, flags=re.I | re.S)
        body_text = re.sub(r"<[^>]+>", " ", clean_html)
        body_text = re.sub(r"\s+", " ", body_text).strip()[:6000]

        info = {
            "title": title,
            "h1": h1,
            "ldNodes": ld_nodes,
            "ldPrimaryCount": ld_primary_count,
            "nextDataJson": next_data_str,
            "nextRscText": next_rsc_txt,
            "metaCurr": meta_curr,
            "metaPrice": meta_price,
            "domPrices": dom_prices,
            "bodyText": body_text,
            "links": links,
            "hasExRentalOption": has_ex_rental_opt
        }

    if isinstance(zprod, dict) and zprod.get("name"):
        if not info["h1"]:
            info["h1"] = str(zprod.get("name", "")).strip()
        if not info["title"]:
            info["title"] = str(zprod.get("name", "")).strip()
    info["zyteProduct"] = zprod or {}
    return info

async def fetch_via_zyte(page, url, country, is_pdp=True, force_refresh=False):
    global ZYTE_CONCURRENCY_SEM
    if not ZYTE_API_KEY or not url:
        return None
    cache_key = (country, url)
    if force_refresh and cache_key in ZYTE_PAGE_CACHE:
        del ZYTE_PAGE_CACHE[cache_key]
    if cache_key in ZYTE_PAGE_CACHE:
        return ZYTE_PAGE_CACHE[cache_key]
    if ZYTE_CONCURRENCY_SEM is None:
        ZYTE_CONCURRENCY_SEM = asyncio.Semaphore(3)
    async with ZYTE_CONCURRENCY_SEM:
        if not force_refresh and cache_key in ZYTE_PAGE_CACHE:
            return ZYTE_PAGE_CACHE[cache_key]
        parsed = None
        for attempt in range(2):
            zdata = await asyncio.to_thread(fetch_zyte_raw_sync, url, country)
            if zdata:
                html_str = zdata.get("browserHtml") or ""
                zprod = zdata.get("product") or {}
                parsed = parse_html_fast_stdlib(html_str, url, zprod)
                t_low = f"{parsed.get('title', '')} | {parsed.get('h1', '')}".lower()
                not_challenged = not any(c in t_low for c in ["just a moment", "un momento", "attention required", "access denied", "404", "not found", "no encontrada"])
                if is_pdp:
                    has_price_signal = bool(zprod.get("price") or parsed.get("ldNodes") or parsed.get("nextDataJson") or parsed.get("nextRscText") or parsed.get("metaPrice") or parsed.get("domPrices"))
                    has_oos_signal = any(w in (parsed.get("bodyText") or "").lower() for w in ["agotado", "out of stock", "fuera de stock", "sold out", "no disponible"])
                    is_valid_content = bool(parsed.get("h1") and (has_price_signal or has_oos_signal)) and not_challenged
                else:
                    is_valid_content = bool(parsed.get("h1") or len(parsed.get("links", [])) > 3) and not_challenged
                if is_valid_content:
                    ZYTE_PAGE_CACHE[cache_key] = parsed
                    return parsed
            if attempt == 0:
                await asyncio.sleep(1.2)
        return parsed

async def prefetch_zyte_batch(page, urls, country, is_pdp=True):
    """Pre-warms ZYTE_PAGE_CACHE concurrently (up to 3 parallel requests) for a list of URLs."""
    if not ZYTE_API_KEY or not urls:
        return
    dedup = []
    for u in urls:
        if u and (country, u) not in ZYTE_PAGE_CACHE and u not in dedup:
            dedup.append(u)
    if not dedup:
        return
    await asyncio.gather(*(fetch_via_zyte(page, u, country, is_pdp=is_pdp) for u in dedup), return_exceptions=True)

def is_operator_pdp_url(href, expected_dom):
    if not href or is_generic_category_url(href):
        return False
    h_low = href.lower()
    if expected_dom and expected_dom not in h_low:
        return False
    if "alltricks.es" in h_low:
        return "/p-" in h_low
    if "wetsuitoutlet." in h_low:
        return bool(re.search(r"-p-\d+\.html", h_low))
    if "sportano.com" in h_low:
        return bool(re.search(r"/p/\d+/", h_low))
    if "bike24.es" in h_low:
        return "/productos/" in h_low
    if "sigmasports.com" in h_low:
        return "/item/" in h_low
    if "sportsshoes.com" in h_low:
        return "/product/" in h_low
    if "tradeinn.com" in h_low:
        return "/p" in h_low and "zone3" in h_low
    if "deporvillage." in h_low:
        return "zone3" in h_low and not any(x in h_low for x in ["catalogsearch", "natacion-zone3", "swimming-triathlon"])
    if "triathlon24.nl" in h_low:
        return "zone3-" in h_low
    if "mytriathlon.co.uk" in h_low:
        return "zone3-" in h_low
    if "365rider.com" in h_low:
        return h_low.endswith(".html") and bool(re.search(r"/\d+-", h_low))
    if "startfitness.co.uk" in h_low:
        return ("/products/" in h_low or ("zone3" in h_low and "/collections/" not in h_low)) and "/search" not in h_low and not h_low.rstrip("/").endswith("/zone3")
    if "proswimwear." in h_low:
        return ("zone3" in h_low or "/product/" in h_low or "/producto/" in h_low) and not any(x in h_low for x in ["catalogsearch", "product-category", "/brands/", "?s=", "/search", "zone3.html", "zone3-wetsuits", "/page/"])
    return True

async def fetch_discovery_links(page, url, country, expected_dom, force_zyte=False):
    """Fetches product links from a catalog/search URL with session caching and automatic Zyte soft-block rescue."""
    cache_key = (country, url)
    if cache_key in DISCOVERY_LINKS_CACHE:
        return DISCOVERY_LINKS_CACHE[cache_key], force_zyte
    links = []
    used_zyte = force_zyte
    if not force_zyte:
        try:
            await throttled_domain_guard(url)
            resp = await page.goto(url, wait_until="domcontentloaded", timeout=12000)
            if resp and resp.status == 200:
                await page.wait_for_timeout(1000)
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight / 2)")
                await page.wait_for_timeout(400)
                links = await page.evaluate("""() => {
                    return Array.from(document.querySelectorAll('a[href]')).map(a => {
                        const card = a.closest('article, li, [class*="product"], [class*="item"], [class*="card"], [class*="tile"]');
                        const cardTitle = card ? Array.from(card.querySelectorAll('h2, h3, h4, [class*="title"], [class*="name"]')).map(e => e.innerText).join(' ') : '';
                        return {
                            href: a.href,
                            text: ((a.innerText || '') + ' ' + (a.getAttribute('title') || '') + ' ' + (a.getAttribute('aria-label') || '') + ' ' + Array.from(a.querySelectorAll('img[alt]')).map(i => i.getAttribute('alt')).join(' ') + ' ' + cardTitle).trim()
                        };
                    }).filter(x => x.href && x.href.startsWith('http'));
                }""")
        except Exception:
            links = []

    pdp_count = sum(1 for l in links if is_operator_pdp_url(l.get("href", ""), expected_dom))
    if pdp_count == 0 and ZYTE_API_KEY:
        used_zyte = True
        zinfo = await fetch_via_zyte(page, url, country, is_pdp=False)
        if zinfo and zinfo.get("links"):
            links.extend(zinfo["links"])
    DISCOVERY_LINKS_CACHE[cache_key] = links
    return links, used_zyte

async def discover_missing_pdps(page_es, page_uk, tracking, today_str, domain_blocks=None, broken_row_ids=None):
    """Dual-Lane (ES || UK) 100% Automatic Deep Auto-Discovery engine with per-domain throttling and Auto-Audit seal."""
    global PHASE2_START_MONOTONIC
    PHASE2_START_MONOTONIC = time.monotonic()
    COMPLETED_DISCOVERY_OPS.clear()
    domain_blocks = domain_blocks or {}
    broken_row_ids = broken_row_ids or set()
    missing_by_op = {}
    for row in tracking:
        if row.get("id") in PERMANENT_EXCLUSIONS:
            continue
        st = row.get("status", "")
        if st in ("UNMAPPED", "NOT_LISTED", "PENDING_PDP") or not row.get("url") or row.get("id") in broken_row_ids:
            # Skip already confirmed manual NOT_LISTED on Shortlist unless broken, but always audit UNMAPPED
            if st == "NOT_LISTED" and not is_secondary_operator(row["country"], row["operator"]) and row.get("id") not in broken_row_ids:
                continue
            missing_by_op.setdefault((row["country"], row["operator"]), []).append(row)

    mapped_count_by_op = {}
    for r_all in tracking:
        if r_all.get("url") and not is_generic_category_url(r_all.get("url", "")):
            ok_k = (r_all["country"], r_all["operator"])
            mapped_count_by_op[ok_k] = mapped_count_by_op.get(ok_k, 0) + 1

    def _op_discovery_priority(kv):
        op_key, op_rows = kv
        has_broken = any(r.get("id") in broken_row_ids for r in op_rows)
        if has_broken:
            return (0, 0, op_key[0], op_key[1])
        is_sec = is_secondary_operator(op_key[0], op_key[1])
        mapped_cnt = mapped_count_by_op.get(op_key, 0)
        if is_sec or mapped_cnt < 5:
            return (1, mapped_cnt, op_key[0], op_key[1])
        return (2, len(op_rows), op_key[0], op_key[1])

    es_groups = sorted([(k, v) for k, v in missing_by_op.items() if k[0] == "ES"], key=_op_discovery_priority)
    uk_groups = sorted([(k, v) for k, v in missing_by_op.items() if k[0] == "UK"], key=_op_discovery_priority)

    discovered_counter = {"count": 0}

    async def _discover_country_lane(lane_groups, page):
        for (country, operator), rows in lane_groups:
            if is_time_budget_exceeded(margin_sec=45):
                print(f"[Time Budget] Stopping Auto-Discovery cleanly before ({country}, {operator}) to guarantee commit.")
                break
            op_disc_start = time.monotonic()
            is_sec_op = is_secondary_operator(country, operator)
            per_op_cap = 165 if is_sec_op else 75

            cat_urls = OPERATOR_CATALOG_URLS.get((country, operator), [])
            expected_dom = OPERATOR_DOMAIN_FILTER.get((country, operator), "")
            dom_is_blocked = any(expected_dom in d and cnt >= 1 for d, cnt in domain_blocks.items())
            collected_links = []

            # 0. Direct candidate probes (only for historic Shortlist SKUs if any)
            if dom_is_blocked and ZYTE_API_KEY:
                all_probes = [u for r in rows for u in DIRECT_CANDIDATE_PROBES.get((country, operator, r["code"]), [])]
                await prefetch_zyte_batch(page, all_probes, country)

            for row in list(rows):
                if is_time_budget_exceeded(margin_sec=45):
                    break
                probe_urls = DIRECT_CANDIDATE_PROBES.get((country, operator, row["code"]), [])
                for p_url in probe_urls:
                    if p_url == row.get("url") and row.get("id") in broken_row_ids:
                        continue
                    try:
                        page_title_h1 = ""
                        if not dom_is_blocked:
                            await throttled_domain_guard(p_url)
                            resp = await page.goto(p_url, wait_until="domcontentloaded", timeout=10000)
                            if resp and resp.status == 200:
                                await page.wait_for_timeout(800)
                                page_title_h1 = await page.evaluate("() => (document.title || '') + ' | ' + Array.from(document.querySelectorAll('h1')).map(e => e.innerText).join(' ')")
                        if (not page_title_h1 or "moment" in page_title_h1.lower()) and ZYTE_API_KEY:
                            dom_is_blocked = True
                            zinfo = await fetch_via_zyte(page, p_url, country)
                            if zinfo:
                                page_title_h1 = f"{zinfo.get('title', '')} | {zinfo.get('h1', '')}"
                        if page_title_h1:
                            id_ok, _ = validate_product_identity(page_title_h1, p_url, row["code"], row["model"])
                            if id_ok:
                                row["url"] = p_url
                                row["_rediscovered_today"] = True
                                row["status"] = "PENDING_URL"
                                row["evidence"] = f"Auto-Discovery Probe ({today_str}): Fitxa PDP verificada a {operator} ({country})"
                                discovered_counter["count"] += 1
                                rows.remove(row)
                                break
                    except Exception:
                        continue

            if not rows or is_time_budget_exceeded(margin_sec=45):
                continue

            # 1. Build deduplicated list of catalog + targeted internal search URLs for missing models
            op_discovery_urls = list(cat_urls)
            for row in rows:
                code = row["code"]
                model_name = row["model"]
                ean = MODEL_EANS.get(code, "")
                kw_main = (MODEL_KEYWORDS.get(code) or [""])[0]
                is_w = ("W" in code[4:6] or "women" in model_name.lower())
                gender_en = "women" if is_w else "men"
                gender_es = "mujer" if is_w else "hombre"
                op_search_templates = {
                    ("ES", "Alltricks"): [
                        f"https://www.alltricks.es/s?k=zone3+{kw_main}+{gender_es}",
                        f"https://www.alltricks.es/s?k=zone3+{kw_main}"
                    ],
                    ("ES", "Wetsuit Outlet"): [
                        f"https://www.wetsuitoutlet.es/es-es/search?q=zone3+{kw_main}",
                        f"https://www.wetsuitoutlet.es/en-es/search?q=zone3+{kw_main}+{gender_en}"
                    ],
                    ("UK", "Wetsuit Outlet"): [
                        f"https://www.wetsuitoutlet.co.uk/search?q=zone3+{kw_main}+{gender_en}",
                        f"https://www.wetsuitoutlet.co.uk/search?q={code[:8]}"
                    ],
                    ("ES", "Sportano"): [
                        f"https://sportano.com/en/search?q={code}",
                        f"https://sportano.com/en/search?q=zone3+{kw_main}+{gender_en}"
                    ],
                    ("ES", "Deporvillage"): [
                        f"https://www.deporvillage.com/catalogsearch/result/?q=zone3+{kw_main}",
                        f"https://www.deporvillage.com/catalogsearch/result/?q={ean}"
                    ],
                    ("UK", "Deporvillage"): [
                        f"https://www.deporvillage.co.uk/catalogsearch/result/?q=zone3+{kw_main}",
                        f"https://www.deporvillage.co.uk/catalogsearch/result/?q={ean}"
                    ],
                    ("ES", "Bike 24"): [
                        f"https://www.bike24.es/buscar?searchTerm=zone3+{kw_main}"
                    ],
                    ("ES", "Triathlon24"): [
                        f"https://www.triathlon24.nl/search/zone3+{kw_main}/"
                    ],
                    ("UK", "Sigma"): [
                        f"https://www.sigmasports.com/search?q=zone3+{kw_main}&sort=price-high-low"
                    ],
                    ("UK", "Sportshoes"): [
                        f"https://www.sportsshoes.com/products/?q=zone3%20{kw_main}"
                    ],
                    ("ES", "365Rider"): [
                        f"https://www.365rider.com/busqueda?controller=search&s=zone3+{kw_main}",
                        f"https://www.365rider.com/busqueda?controller=search&s={code}"
                    ],
                    ("ES", "ProSwimwear"): [
                        f"https://www.proswimwear.es/?s=zone3+{kw_main}&post_type=product"
                    ],
                    ("UK", "Start Fitness"): [
                        f"https://startfitness.co.uk/search?q=zone3+{kw_main}+{gender_en}&type=product",
                        f"https://startfitness.co.uk/search?q=zone3+{kw_main}&type=product"
                    ],
                    ("UK", "ProSwimwear"): [
                        f"https://www.proswimwear.co.uk/?s=zone3+{kw_main}&post_type=product"
                    ]
                }
                for s_u in op_search_templates.get((country, operator), []):
                    if s_u not in op_discovery_urls:
                        op_discovery_urls.append(s_u)

            if dom_is_blocked and ZYTE_API_KEY:
                await prefetch_zyte_batch(page, op_discovery_urls, country, is_pdp=False)

            exhausted_all_urls = True
            for d_url in op_discovery_urls:
                if is_time_budget_exceeded(margin_sec=45) or (time.monotonic() - op_disc_start) > per_op_cap:
                    exhausted_all_urls = False
                    break
                d_links, used_zyte = await fetch_discovery_links(page, d_url, country, expected_dom, force_zyte=dom_is_blocked)
                if used_zyte and not dom_is_blocked:
                    dom_is_blocked = True
                    await prefetch_zyte_batch(page, op_discovery_urls, country, is_pdp=False)
                collected_links.extend(d_links)

            inspected_candidates = {}
            exhausted_all_rows = True
            for row in rows:
                if is_time_budget_exceeded(margin_sec=35) or (time.monotonic() - op_disc_start) > (per_op_cap + 35):
                    exhausted_all_rows = False
                    break
                code = row["code"]
                model_name = row["model"]
                found_url = None
                partial_candidates = []

                for link in collected_links:
                    href = link["href"].split("#")[0]
                    if not is_operator_pdp_url(href, expected_dom):
                        continue
                    mkt_ok, _ = validate_market_url(href, country)
                    if not mkt_ok:
                        continue
                    id_ok, _ = validate_product_identity(link["text"], href, code, model_name)
                    if id_ok:
                        if "tradeinn.com" in href.lower() and "country=" not in href.lower():
                            sep = "&" if "?" in href else "?"
                            href = f"{href}{sep}country={'uk' if country == 'UK' else 'es'}"
                        elif country == "ES" and "proswimwear.es" in href.lower() and "wmc-currency=" not in href.lower():
                            sep = "&" if "?" in href else "?"
                            href = f"{href}{sep}wmc-currency=EUR"
                        found_url = href
                        break
                    kws = MODEL_KEYWORDS.get(code, [])
                    comb_low = f"{link['text']} {href}".lower()
                    if kws and any(k in comb_low for k in kws) and href not in partial_candidates:
                        partial_candidates.append(href)

                if not found_url and partial_candidates:
                    if dom_is_blocked and ZYTE_API_KEY:
                        await prefetch_zyte_batch(page, partial_candidates[:3], country)
                    for cand_href in partial_candidates[:3]:
                        if cand_href not in inspected_candidates:
                            p_title_h1 = ""
                            if not dom_is_blocked:
                                try:
                                    await throttled_domain_guard(cand_href)
                                    r_c = await page.goto(cand_href, wait_until="domcontentloaded", timeout=10000)
                                    if r_c and r_c.status == 200:
                                        await page.wait_for_timeout(700)
                                        p_title_h1 = await page.evaluate("() => (document.title || '') + ' | ' + Array.from(document.querySelectorAll('h1')).map(e => e.innerText).join(' ')")
                                except Exception:
                                    pass
                            if (not p_title_h1 or "moment" in p_title_h1.lower()) and ZYTE_API_KEY:
                                dom_is_blocked = True
                                z_c = await fetch_via_zyte(page, cand_href, country)
                                if z_c:
                                    p_title_h1 = f"{z_c.get('title', '')} | {z_c.get('h1', '')}"
                            inspected_candidates[cand_href] = p_title_h1
                        cand_h1 = inspected_candidates.get(cand_href, "")
                        if cand_h1:
                            id_ok, _ = validate_product_identity(cand_h1, cand_href, code, model_name)
                            if id_ok:
                                if country == "ES" and "proswimwear.es" in cand_href.lower() and "wmc-currency=" not in cand_href.lower():
                                    sep = "&" if "?" in cand_href else "?"
                                    cand_href = f"{cand_href}{sep}wmc-currency=EUR"
                                found_url = cand_href
                                break

                if found_url and found_url != row.get("url"):
                    row["url"] = found_url
                    row["_rediscovered_today"] = True
                    if row.get("status") != "VERIFIED":
                        row["status"] = "PENDING_URL"
                    row["evidence"] = f"Auto-Discovery ({today_str}): Fitxa PDP localitzada per a {operator} ({country})"
                    discovered_counter["count"] += 1
                else:
                    if row.get("status") in ("UNMAPPED", "NOT_LISTED"):
                        row["status"] = "UNMAPPED"
                        if exhausted_all_urls and len(collected_links) > 0:
                            row["evidence"] = f"[Auto-Audit completat ({today_str})]: Catàleg i cercador de {operator} ({country}) verificats, model no comercialitzat actualment"
                        else:
                            row["evidence"] = f"Cerca automàtica a {operator} ({today_str}): pendent de completar escombrat de catàleg"

            if exhausted_all_urls and exhausted_all_rows and len(collected_links) > 0:
                COMPLETED_DISCOVERY_OPS.add((country, operator))

    await asyncio.gather(
        _discover_country_lane(es_groups, page_es),
        _discover_country_lane(uk_groups, page_uk)
    )
    return discovered_counter["count"]

def evaluate_page_info_candidates(page_info, row, source_prefix=""):
    url = row.get("url", "").strip()
    country = row["country"]
    operator = row["operator"]
    expected_curr = row["currency"]
    sig = EXPECTED_MARKET_SIGNALS[country]
    expected_sym = sig["symbol"]
    forbidden_sym = sig["forbidden_symbol"]
    pvp = float(row["pvp"])
    code = row["code"]
    model_name = row["model"]

    body_text_raw = page_info.get("bodyText") or ""
    body_low = body_text_raw.lower()
    title_h1 = f"{page_info.get('title', '')} | {page_info.get('h1', '')}".strip()
    title_h1_low = title_h1.lower()

    # Only flag as anti-bot challenge if the page title/H1 is an explicit challenge screen or the page is an empty shell.
    # Never trigger on 'recaptcha', 'cloudflare', or 'datadome' substrings in body_low when a real product H1 is present.
    challenge_title_phrases = [
        "just a moment", "un momento", "attention required", "verify you are human",
        "checking your browser", "access denied", "pardon our interruption",
        "please enable cookies", "security check"
    ]
    is_challenge_title = any(c in title_h1_low for c in challenge_title_phrases)
    is_empty_shell = (not page_info.get("h1") and not (page_info.get("zyteProduct") or {}).get("name") and len(body_low.strip()) < 180)
    if is_challenge_title or is_empty_shell:
        return None, False, "BLOCKED_CAPTCHA", "Bloqueig anti-bot / Challenge detectat"

    id_ok, id_msg = validate_product_identity(title_h1, url, code, model_name)
    if not id_ok:
        if any(c in body_low for c in ["verify you are human", "cf-chl-bypass", "enable javascript and cookies", "unusual traffic"]):
            return None, False, "BLOCKED_CAPTCHA", "Bloqueig anti-bot / Captcha detectat"
        return None, False, "IDENTITY_MISMATCH", id_msg

    ean = MODEL_EANS.get(code, "")
    has_exact_sku = (code.lower() in f"{title_h1} {url} {body_low}".lower()) or (ean and ean in body_low)
    # Opció C (v11.1): Doble banda + bloqueig estructural d'Ex-Rental + Safata REVIEW_DEEP_DISCOUNT (>65%)
    has_ex_rental_opt = bool(page_info.get("hasExRentalOption", False))
    is_mixed_ex_rental_pdp = has_ex_rental_opt or (country == "UK" and operator == "My Triathlon" and code in ("WS22MVAN101", "WS22WVAN101"))
    min_allowed_ratio = MIXED_EX_RENTAL_MIN_RATIO if is_mixed_ex_rental_pdp else CLEAN_NEW_MIN_RATIO
    used_tokens = USED_ITEM_TOKENS

    u_low = url.lower()
    if country == "ES" and "sportano.com" in u_low:
        market_tag = f"{expected_curr} | Sportano.com EU->ES"
    elif country == "ES" and "triathlon24.nl" in u_low:
        market_tag = f"{expected_curr} | Triathlon24.nl EU->ES"
    else:
        market_tag = f"{expected_curr} | Mercat {country}"

    candidates = []
    jsonld_base_prices = []
    instock_variant_prices = []
    oos_variant_prices = []
    ex_rental_rejected = []
    deep_discount_rejected = []
    detected_oos = False
    detected_instock = False
    currency_mismatch = False

    has_local_domain_currency = (
        (country == "ES" and any(d in u_low for d in [".es/", ".nl/", "country=es", "currency=eur", "deporvillage.com/", "sportano.com/", "wetsuitoutlet.es/", "alltricks.es/", "365rider.com/", "proswimwear.es/"])) or
        (country == "UK" and any(d in u_low for d in [".co.uk/", "country=uk", "currency=gbp", "sigmasports.com/", "sportsshoes.com/", "wetsuitoutlet.co.uk/", "startfitness.co.uk/", "proswimwear.co.uk/"]))
    )
    m_curr = str(page_info.get("metaCurr", "")).upper().strip()
    if m_curr in ("€", "EUR"):
        m_curr = "EUR"
    elif m_curr in ("£", "GBP"):
        m_curr = "GBP"

    def register_candidate_or_tray(prio, is_oos_flag, val, ev_text):
        if val is None or val <= 0 or val > (pvp * 1.20):
            return
        if is_ex_rental_anomaly(country, operator, code, val, pvp) or (is_mixed_ex_rental_pdp and val < (pvp * MIXED_EX_RENTAL_MIN_RATIO)):
            ex_rental_rejected.append((val, ev_text))
            return
        if val < (pvp * CLEAN_NEW_MIN_RATIO):
            deep_discount_rejected.append((val, ev_text))
            return
        candidates.append((prio, is_oos_flag, val, ev_text))

    # 0. Zyte Automatic Product Extraction (skipped if PDP mixes an Ex-Rental dropdown option with New options)
    zprod = page_info.get("zyteProduct") or {}
    if isinstance(zprod, dict) and zprod.get("price") and not is_mixed_ex_rental_pdp:
        z_name = str(zprod.get("name") or "").strip()
        z_sku = str(zprod.get("sku") or zprod.get("mpn") or zprod.get("gtin") or "").strip()
        z_id_ok, _ = validate_product_identity(f"{z_name} {z_sku}" if z_name else title_h1, url, code, model_name)
        z_curr = str(zprod.get("currency") or zprod.get("currencyRaw") or m_curr or "").upper().strip()
        if z_curr in ("€", "EUR"):
            z_curr = "EUR"
        elif z_curr in ("£", "GBP"):
            z_curr = "GBP"
        elif not z_curr and has_local_domain_currency and forbidden_sym not in str(zprod.get("price") or ""):
            z_curr = expected_curr
        if z_curr and z_curr != expected_curr:
            currency_mismatch = True
        elif z_curr == expected_curr and z_id_ok:
            z_val = normalize_price(zprod.get("price"))
            z_avail = str(zprod.get("availability") or "").lower()
            is_z_oos = False
            if "instock" in z_avail:
                detected_instock = True
            elif "outofstock" in z_avail or "discontinued" in z_avail:
                detected_oos = True
                is_z_oos = True
            if z_val:
                register_candidate_or_tray(
                    1,
                    is_z_oos,
                    z_val,
                    f"{source_prefix}Zyte Product API [{market_tag}] ({z_val:.2f} {expected_sym}) · '{(z_name or page_info.get('h1', ''))[:40]}'"
                )

    # 1. Structured JSON-LD Product / ProductGroup / hasVariant offers (including bottom-of-body Next.js scripts)
    ld_nodes_list = page_info.get("ldNodes", [])
    ld_primary_cnt = page_info.get("ldPrimaryCount", len(ld_nodes_list))
    parsed_main_u = urlparse(url)
    main_slug = parsed_main_u.path.strip("/").split("/")[-1].lower() if parsed_main_u.path else ""

    for ld_idx, raw_ld in enumerate(ld_nodes_list):
        is_tail_ld = (ld_idx >= ld_primary_cnt)
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
                    prod_sku = str(item.get("sku", "") or item.get("mpn", "") or item.get("gtin13", "") or item.get("productID", "")).strip()
                    prod_url = str(item.get("url", "") or item.get("@id", "")).strip()
                    if not prod_url and isinstance(item.get("offers"), dict):
                        prod_url = str(item["offers"].get("url", "")).strip()
                    item_cond = str(item.get("itemCondition", "")).lower()
                    if any(ut in f"{prod_name} {prod_sku} {item_cond}".lower() for ut in used_tokens):
                        continue
                    variant_size = str(item.get("size", "") or item.get("color", "")).strip()

                    # Strict per-node identity check so bottom JSON-LD works on Next.js while related-product JSON-LD never leaks
                    node_sig_low = f"{prod_name} {prod_sku} {prod_url}".lower()
                    exact_sku_in_ld = (code.lower() in node_sig_low) or (ean and ean in node_sig_low)
                    if is_tail_ld and not (prod_name or prod_sku or prod_url):
                        continue
                    if not exact_sku_in_ld:
                        if prod_name:
                            # First verify model keyword is inside the JSON-LD node itself (not borrowed from page URL!)
                            m_kws = MODEL_KEYWORDS.get(code, [])
                            if m_kws and not any(kw in node_sig_low for kw in m_kws):
                                continue
                            ld_ok, _ = validate_product_identity(f"{prod_name} {prod_sku}", prod_url or url, code, model_name)
                            if not ld_ok:
                                continue
                        elif is_tail_ld and not (main_slug and len(main_slug) >= 12 and main_slug in prod_url.lower()):
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
                        off_meta_low = f"{off.get('name','')} {off.get('sku','')} {off.get('description','')} {off.get('itemCondition','')}".lower()
                        if any(ut in off_meta_low for ut in used_tokens):
                            for pk in ("price", "lowPrice"):
                                vp = normalize_price(off.get(pk))
                                if vp:
                                    ex_rental_rejected.append((vp, "JSON-LD variant marcada com Ex-Rental"))
                            continue
                        curr = str(off.get("priceCurrency", "") or m_curr or "").upper().strip()
                        if curr in ("€", "EUR"):
                            curr = "EUR"
                        elif curr in ("£", "GBP"):
                            curr = "GBP"
                        elif not curr and has_local_domain_currency:
                            curr = expected_curr
                        if curr and curr != expected_curr:
                            currency_mismatch = True
                            continue
                        avail = str(off.get("availability", "")).lower()
                        off_size = str(off.get("sku", "") or off.get("name", "") or variant_size).strip()
                        is_off_oos = False
                        if "instock" in avail:
                            detected_instock = True
                        elif "outofstock" in avail or "discontinued" in avail:
                            detected_oos = True
                            is_off_oos = True
                        low_v = normalize_price(off.get("lowPrice"))
                        high_v = normalize_price(off.get("highPrice"))
                        has_both_low_high = (low_v is not None and high_v is not None and low_v != high_v)
                        if is_mixed_ex_rental_pdp and has_both_low_high:
                            if low_v < (pvp * MIXED_EX_RENTAL_MIN_RATIO):
                                ex_rental_rejected.append((low_v, "AggregateOffer lowPrice Ex-Rental"))
                            allowed_p_keys = ["highPrice"]
                        elif is_mixed_ex_rental_pdp:
                            allowed_p_keys = ["highPrice", "price"]
                        else:
                            allowed_p_keys = ["price", "lowPrice", "highPrice"]
                        for p_key in allowed_p_keys:
                            if p_key in off:
                                val = normalize_price(off[p_key])
                                if val is not None:
                                    ev_ld = f"{source_prefix}JSON-LD {p_key} [{market_tag}] ({val:.2f} {expected_sym}) · Producte: '{(prod_name or page_info.get('h1', ''))[:40]}'"
                                    if (pvp * min_allowed_ratio) <= val <= (pvp * 1.20) and not is_ex_rental_anomaly(country, operator, code, val, pvp):
                                        if not is_off_oos and p_key in ("price", "lowPrice", "highPrice"):
                                            instock_variant_prices.append((val, off_size))
                                            jsonld_base_prices.append(val)
                                        elif is_off_oos:
                                            oos_variant_prices.append((val, off_size))
                                    register_candidate_or_tray(1, is_off_oos, val, ev_ld)
        except Exception:
            pass

    # 1.5 Next.js Hydration State (__NEXT_DATA__ & App Router self.__next_f.push)
    if not is_mixed_ex_rental_pdp and (page_info.get("nextDataJson") or page_info.get("nextRscText")):
        next_cands = extract_nextjs_candidates_for_row(page_info, row)
        for nc in next_cands:
            nc_curr = nc.get("currency") or m_curr or (expected_curr if has_local_domain_currency else "")
            if nc_curr and nc_curr != expected_curr:
                currency_mismatch = True
                continue
            if nc_curr == expected_curr:
                nc_val = float(nc["price"])
                nc_oos = bool(nc.get("oos", False))
                if nc_oos:
                    detected_oos = True
                else:
                    detected_instock = True
                    if (pvp * min_allowed_ratio) <= nc_val <= (pvp * 1.20):
                        instock_variant_prices.append((nc_val, nc.get("size", "")))
                register_candidate_or_tray(
                    1,
                    nc_oos,
                    nc_val,
                    f"{source_prefix}{nc['source']} [{market_tag}] ({nc_val:.2f} {expected_sym}) · '{page_info.get('h1', '')[:38]}'"
                )

    # 2. OpenGraph / Microdata (skipped if PDP mixes an Ex-Rental option inside the same page)
    if m_curr and m_curr != expected_curr:
        currency_mismatch = True
    elif page_info.get("metaPrice") and not is_mixed_ex_rental_pdp and (m_curr == expected_curr or has_local_domain_currency):
        val = normalize_price(page_info["metaPrice"])
        if val:
            register_candidate_or_tray(
                2,
                False,
                val,
                f"{source_prefix}Meta OG [{market_tag}] ({val:.2f} {expected_sym}) · H1: '{page_info.get('h1', '')[:40]}'"
            )

    # 3. Main Product DOM elements (excluding all carousels/related/Ex-Rental blocks)
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
        extracted_nums = [normalize_price(m.group(1)) for m in re.finditer(r"([\d]{2,3}(?:[.,]\d{1,2})?)", txt)]
        extracted_nums = [v for v in extracted_nums if v is not None]
        if not extracted_nums:
            continue
        if is_mixed_ex_rental_pdp and len(extracted_nums) >= 2 and ("-" in txt or "–" in txt):
            for low_ex in [x for x in extracted_nums if x < max(extracted_nums)]:
                ex_rental_rejected.append((low_ex, "DOM rang Ex-Rental"))
            extracted_nums = [max(extracted_nums)]
        for val in extracted_nums:
            register_candidate_or_tray(
                3,
                False,
                val,
                f"{source_prefix}DOM Principal {dp['selector']} [{market_tag}] ({val:.2f} {expected_sym}) · H1: '{page_info.get('h1', '')[:38]}'"
            )

    # 4. Promo Code / Coupon Price Detection on PDP
    explicit_promo_price = None
    detected_promo_code = None
    m_code_name = re.search(r"(?:with code|con el código|amb el codi|code|código|cupón|coupon)[:\s]+([A-Z0-9_-]{4,16})", body_text_raw, flags=re.I)
    if m_code_name:
        cand_code = m_code_name.group(1).upper()
        if cand_code not in ("ZONE3", "WETSUIT", "NEOPRENE", "HTML", "JSON", "TRUE", "FALSE") and not cand_code.startswith("WS2"):
            detected_promo_code = cand_code

    promo_patterns = [
        r"([\d]{2,3}[.,]\d{2})\s*(?:€|EUR|£|GBP)?\s*(?:with code|con código|con el código|amb codi)[:\s]*([A-Z0-9_-]{4,16})?",
        r"(?:with code|con código|con el código|amb codi)[:\s]*([A-Z0-9_-]{4,16})?[^\d]{0,25}([\d]{2,3}[.,]\d{2})\s*(?:€|EUR|£|GBP)"
    ]
    for pat in promo_patterns:
        for m_pr in re.finditer(pat, body_text_raw, flags=re.I):
            g1, g2 = m_pr.group(1), m_pr.group(2)
            p_raw = g1 if (g1 and re.match(r"^[\d.,]+$", g1)) else g2
            c_raw = g2 if p_raw == g1 else g1
            p_val = normalize_price(p_raw)
            if p_val and (pvp * min_allowed_ratio) <= p_val <= (pvp * 1.15) and not is_ex_rental_anomaly(country, operator, code, p_val, pvp):
                explicit_promo_price = p_val
                if c_raw and len(c_raw) >= 4:
                    detected_promo_code = c_raw.upper()
                break

    if explicit_promo_price and not (detected_oos and not detected_instock):
        code_lbl = f" '{detected_promo_code}'" if detected_promo_code else ""
        register_candidate_or_tray(
            1,
            False,
            explicit_promo_price,
            f"{source_prefix}Preu amb codi{code_lbl} mostrat a la fitxa [{market_tag}] ({explicit_promo_price:.2f} {expected_sym})"
        )

    body_has_oos_text = any(w in body_low for w in ["agotado", "out of stock", "fuera de stock", "sold out", "no disponible", "currently unavailable", "product temporarily unavailable", "temporarily unavailable"])
    if body_has_oos_text and not detected_instock:
        detected_oos = True

    valid_candidates = [
        (prio, is_oos_cand, p, ev)
        for (prio, is_oos_cand, p, ev) in candidates
        if (pvp * min_allowed_ratio) <= p <= (pvp * 1.20) and not is_ex_rental_anomaly(country, operator, code, p, pvp)
    ]

    instock_candidates = [c for c in valid_candidates if not c[1]]
    if instock_candidates:
        valid_candidates = instock_candidates

    if not valid_candidates:
        if deep_discount_rejected and not is_mixed_ex_rental_pdp:
            deep_discount_rejected.sort(key=lambda x: x[0])
            dp_val, dp_ev = deep_discount_rejected[0]
            dp_pct = round(((pvp - dp_val) / pvp) * 100, 1)
            return round(dp_val, 2), detected_oos, "REVIEW_DEEP_DISCOUNT", f"Safata Opció C (>{MAX_CLEAN_NEW_DISC_PCT:.0f}%, -{dp_pct:.1f}%): {dp_ev}"
        if ex_rental_rejected:
            ex_rental_rejected.sort(key=lambda x: x[0])
            ex_val, _ = ex_rental_rejected[0]
            ex_pct = round(((pvp - ex_val) / pvp) * 100, 1)
            return round(ex_val, 2), detected_oos, "QUARANTINED_EX_RENTAL", f"Bloqueig Opció C Ex-Rental ({ex_val:.2f} {expected_sym}, -{ex_pct:.1f}%): sense preu d'unitat nova disponible"
        if currency_mismatch:
            return None, False, "CURRENCY_MISMATCH", f"Moneda de la pàgina no coincideix amb {expected_curr} ({country})"
        if detected_oos:
            return None, True, "OUT_OF_STOCK", f"Producte esgotat sense preu visible ({(page_info.get('h1') or page_info.get('title') or '')[:35]})"
        return None, False, "NO_VALID_PRICE", f"Cap preu principal ({expected_curr}) validat a la fitxa"

    valid_candidates.sort(key=lambda x: (1 if (x[2] >= pvp * 0.995 and len(valid_candidates) > 1) else 0, x[0], x[2]))
    _, best_cand_oos, best_price, best_evidence = valid_candidates[0]

    base_ref_prices = [round(p, 2) for p in jsonld_base_prices if round(p, 2) > round(best_price, 2) + 0.5]
    if base_ref_prices and (explicit_promo_price or detected_promo_code or "sportano.com" in u_low):
        base_p = min(base_ref_prices)
        c_name = detected_promo_code or ("BLACKBELT" if "sportano.com" in u_low else "PROMO")
        if "Nota cupó" not in best_evidence:
            best_evidence += f" · [🎟️ Codi '{c_name}' aplicat · Preu base sense codi: {base_p:.2f} {expected_sym}]"
    elif explicit_promo_price and detected_promo_code:
        if "Nota cupó" not in best_evidence and "🎟️ Codi" not in best_evidence:
            best_evidence += f" · [🎟️ Codi '{detected_promo_code}' aplicat a la fitxa]"
    elif detected_promo_code and not explicit_promo_price:
        if "Nota cupó" not in best_evidence:
            best_evidence += f" · [Nota cupó: detectat codi promocional '{detected_promo_code}' a la web sense preu final descomptat explícit]"

    unique_instock_prices = sorted(list(set(round(p, 2) for (p, _) in instock_variant_prices)))
    if len(unique_instock_prices) > 1 and not base_ref_prices:
        min_p = unique_instock_prices[0]
        max_p = unique_instock_prices[-1]
        min_sizes = [sz for (p, sz) in instock_variant_prices if round(p, 2) == min_p and sz]
        sz_note = f" ({min_sizes[0][:18]})" if min_sizes else ""
        best_evidence += f" · [Nota talles: preu mínim en talla específica{sz_note}; altres talles en estoc fins a {max_p:.2f} {expected_sym}]"

    if ex_rental_rejected:
        best_evidence += f" · [Opció C: variant Ex-Rental ({min(x[0] for x in ex_rental_rejected):.2f} {expected_sym}) descartada; llegit preu d'unitat nova]"

    final_oos = True if (best_cand_oos or (detected_oos and not detected_instock)) else False
    return round(best_price, 2), final_oos, "VERIFIED", best_evidence

WETSUIT_OUTLET_ES_EN_MAP = {
    "p-53917.html": "https://www.wetsuitoutlet.es/en-es/2026-zone3-mens-aspire-wetsuit-ws25masp-black-chalk-p-53917.html",
    "p-48572.html": "https://www.wetsuitoutlet.es/en-es/2026-zone3-mens-terraprene-vision-back-zip-swim-wetsuit-ws24mvis101-black-forest-green-p-48572.html",
    "p-48600.html": "https://www.wetsuitoutlet.es/en-es/2026-zone3-womens-terraprene-vision-back-zip-swim-wetsuit-ws24wvis101-black-eucalyptus-green-p-48600.html",
    "p-38382.html": "https://www.wetsuitoutlet.es/en-es/2026-zone3-mens-advance-swim-wetsuit-ws21madv-black-blue-p-38382.html",
    "p-38383.html": "https://www.wetsuitoutlet.es/en-es/2026-zone3-womens-advance-swim-wetsuit-ws21wadv-black-turquoise-p-38383.html",
    "p-40555.html": "https://www.wetsuitoutlet.es/en-es/2026-zone3-mens-agile-swim-wetsuit-ws21magi116-black-silver-gunmetal-p-40555.html",
    "p-40559.html": "https://www.wetsuitoutlet.es/en-es/2026-zone3-womens-agile-swim-wetsuit-ws21wagi114-black-pink-turquoise-p-40559.html",
    "p-56135.html": "https://www.wetsuitoutlet.es/en-es/2026-zone3-mens-ascend-sleeveless-swim-wetsuit-ws26mglisl101-black-grey-p-56135.html",
    "p-56136.html": "https://www.wetsuitoutlet.es/en-es/2026-zone3-womens-ascend-sleeveless-wetsuit-ws26wglisl101-black-grey-p-56136.html",
    "p-52492.html": "https://www.wetsuitoutlet.es/en-es/2026-zone3-mens-active-flex-swim-wetsuit-ws25mactf101-black-orange-p-52492.html",
    "p-52493.html": "https://www.wetsuitoutlet.es/en-es/2026-zone3-womens-active-flex-swim-wetsuit-ws25wactf101-black-orange-p-52493.html"
}

WETSUIT_OUTLET_ES_LEGACY_MAP = {
    "p-53917.html": "https://www.wetsuitoutlet.es/2026-zone3-hombres-aspire-neopreno-ws25masp-black-chalk-p-53917.html?currency=EUR",
    "p-48572.html": "https://www.wetsuitoutlet.es/2026-zone3-hombres-terraprene-vision-back-zip-swim-neopreno-ws24mvis101-black-forest-green-p-48572.html?currency=EUR",
    "p-48600.html": "https://www.wetsuitoutlet.es/2026-zone3-mujer-terraprene-vision-back-zip-swim-neopreno-ws24wvis101-black-eucalyptus-green-p-48600.html?currency=EUR",
    "p-38383.html": "https://www.wetsuitoutlet.es/2026-zone3-mujer-advance-swim-neopreno-ws21wadv-black-turquoise-p-38383.html?currency=EUR",
    "p-40555.html": "https://www.wetsuitoutlet.es/2026-zone3-hombres-agile-swim-neopreno-ws21magi116-black-silver-gunmetal-p-40555.html?currency=EUR",
    "p-40559.html": "https://www.wetsuitoutlet.es/2026-zone3-mujer-agile-swim-neopreno-ws21wagi114-black-pink-turquoise-p-40559.html?currency=EUR",
    "p-56135.html": "https://www.wetsuitoutlet.es/2026-zone3-hombres-traje-neopreno-sin-mangas-ascend-ws26mglisl101-black-grey-p-56135.html?currency=EUR",
    "p-56136.html": "https://www.wetsuitoutlet.es/2026-zone3-mujer-traje-neopreno-sin-mangas-ascend-ws26wglisl101-black-grey-p-56136.html?currency=EUR",
    "p-52492.html": "https://www.wetsuitoutlet.es/2026-zone3-hombres-active-flex-swim-neopreno-ws25mactf101-black-orange-p-52492.html?currency=EUR",
    "p-52493.html": "https://www.wetsuitoutlet.es/2026-zone3-mujer-active-flex-swim-neopreno-ws25wactf101-black-orange-p-52493.html?currency=EUR"
}

def get_canonical_url_candidates(url, country):
    """Returns ordered candidate URLs without mutating or losing fallback paths on repeated calls."""
    u = url.strip()
    if not u:
        return []
    if "wetsuitoutlet.es/" in u.lower():
        cands = []
        m_pid = re.search(r"-(p-\d+\.html)", u, flags=re.I)
        pid = m_pid.group(1).lower() if m_pid else ""
        # 1. Verified /en-es/ English slug (confirmed working 200 OK in EUR on wetsuitoutlet.es)
        if pid and pid in WETSUIT_OUTLET_ES_EN_MAP:
            cands.append(WETSUIT_OUTLET_ES_EN_MAP[pid])
        # 2. Original URL if it is NOT a broken /es-es/hombres or Danish svommedragt path
        if "svommedragt" not in u.lower() and "/es-es/2026-zone3-hombres-" not in u.lower() and "/es-es/2026-zone3-mujer-" not in u.lower():
            if u not in cands:
                cands.append(u)
        # 3. Legacy root Spanish URL with ?currency=EUR (confirmed working via 301 redirect on 19/11)
        if pid and pid in WETSUIT_OUTLET_ES_LEGACY_MAP:
            leg_u = WETSUIT_OUTLET_ES_LEGACY_MAP[pid]
            if leg_u not in cands:
                cands.append(leg_u)
            leg_no_q = leg_u.split("?")[0]
            if leg_no_q not in cands:
                cands.append(leg_no_q)
        return cands[:3] if cands else [u]
    elif "wetsuitoutlet.co.uk/" in u.lower() and "?" in u:
        base_no_q = u.split("?")[0]
        return [base_no_q, u][:2]
    elif country == "ES" and "deporvillage.com/" in u.lower():
        es_mirror = re.sub(r"https?://(?:www\.)?deporvillage\.com/", "https://www.deporvillage.es/", u, flags=re.I)
        return [u, es_mirror] if es_mirror != u else [u]
    elif country == "ES" and "deporvillage.es/" in u.lower():
        com_mirror = re.sub(r"https?://(?:www\.)?deporvillage\.es/", "https://www.deporvillage.com/", u, flags=re.I)
        return [u, com_mirror] if com_mirror != u else [u]
    elif country == "ES" and "365rider.com/en/" in u.lower():
        es_365 = re.sub(r"/en/", "/", u, count=1, flags=re.I)
        return [es_365, u]
    elif country == "ES" and "proswimwear.es/" in u.lower() and "wmc-currency=eur" not in u.lower():
        sep = "&" if "?" in u else "?"
        u_eur = f"{u}{sep}wmc-currency=EUR"
        return [u_eur, u]
    return [u]

async def extract_verified_pdp_price(page, row, force_zyte_only=False):
    raw_url = row.get("url", "").strip()
    country = row["country"]
    url_candidates = get_canonical_url_candidates(raw_url, country)
    primary_url = url_candidates[0] if url_candidates else raw_url

    if is_generic_category_url(primary_url):
        return None, False, "PENDING_PDP", "En quarantena: URL de categoria genèrica (cal fitxa individual PDP)"

    mkt_ok, mkt_msg = validate_market_url(primary_url, country)
    if not mkt_ok:
        return None, False, "MARKET_MISMATCH", mkt_msg

    # If domain already tripped the Playwright circuit breaker and ZYTE_API_KEY is configured, go straight to Zyte
    if force_zyte_only and ZYTE_API_KEY:
        last_st, last_ev = "BLOCKED_HTTP", "Accés bloquejat i sense resposta vàlida de Zyte API"
        for cand_u in url_candidates:
            z_info = await fetch_via_zyte(page, cand_u, country, is_pdp=True)
            if z_info is None:
                await asyncio.sleep(0.6)
                z_info = await fetch_via_zyte(page, cand_u, country, is_pdp=True, force_refresh=True)
            if z_info:
                r_copy = dict(row)
                r_copy["url"] = cand_u
                z_price, z_oos, z_status, z_ev = evaluate_page_info_candidates(z_info, r_copy, source_prefix="[Zyte] ")
                # If cached Zyte page had a transient incomplete render, force one fresh uncached Zyte fetch
                if z_status in ("NO_VALID_PRICE", "BLOCKED_CAPTCHA"):
                    z_info_retry = await fetch_via_zyte(page, cand_u, country, is_pdp=True, force_refresh=True)
                    if z_info_retry:
                        z_price, z_oos, z_status, z_ev = evaluate_page_info_candidates(z_info_retry, r_copy, source_prefix="[Zyte] ")
                last_st, last_ev = z_status, z_ev
                if z_status in ("VERIFIED", "OUT_OF_STOCK"):
                    row["url"] = cand_u
                    return z_price, z_oos, z_status, z_ev
        return None, False, last_st, last_ev

    status_code = "ERROR"
    evidence_str = ""

    try:
        if country == "UK":
            await page.set_extra_http_headers({"Accept-Language": "en-GB,en;q=0.9"})
        else:
            await page.set_extra_http_headers({"Accept-Language": "es-ES,es;q=0.9"})

        for cand_u in url_candidates[:2]:
            resp = await page.goto(cand_u, wait_until="domcontentloaded", timeout=18000)
            if not resp:
                status_code, evidence_str = "HTTP_ERROR", "Timeout sense resposta HTTP"
                continue
            elif resp.status in (403, 429, 503):
                status_code, evidence_str = "BLOCKED_HTTP", f"Accés bloquejat per l'operador (HTTP {resp.status})"
                break
            elif resp.status >= 400:
                status_code, evidence_str = "HTTP_ERROR", f"Error HTTP {resp.status}"
                continue
            else:
                is_depor_or_next = ("deporvillage." in cand_u.lower())
                if is_depor_or_next:
                    try:
                        await page.evaluate("""() => {
                            const btn = document.querySelector('#onetrust-accept-btn-handler');
                            if (btn) btn.click();
                        }""")
                    except Exception:
                        pass
                try:
                    await page.wait_for_function(
                        """() => {
                            const h1 = document.querySelector('h1');
                            const hasH1 = Boolean(h1 && h1.innerText && h1.innerText.trim().length > 3);
                            const hasLd = Array.from(document.querySelectorAll('script[type="application/ld+json"]')).some(s => /price|Offer/i.test(s.innerText || ''));
                            const hasNext = Boolean(document.getElementById('__NEXT_DATA__') || (window.__next_f && window.__next_f.length));
                            const mainTxt = (document.querySelector('main') || document.body || {}).innerText || '';
                            const hasPriceOrOos = /(\\d{2,3}[.,]\\d{2}\\s*[€£]|[€£]\\s*\\d{2,3}[.,]\\d{2}|agotado|out of stock|no disponible)/i.test(mainTxt);
                            return hasH1 && (hasLd || hasPriceOrOos || hasNext);
                        }""",
                        timeout=(4800 if is_depor_or_next else 2200)
                    )
                except Exception:
                    pass
                await page.wait_for_timeout(750 if is_depor_or_next else 450)

                page_info = await page.evaluate("""() => {
                    const forbiddenContainers = [
                        '.related', '.recommendations', '.cross-sell', '.upsell', '.similar-products',
                        '.product-carousel', '.productCarousel', '.also-bought', '.alternatives', 'aside', 'footer', 'nav', 'header',
                        '#tab-related', '#tab-similar', '[data-list-name*="Related"]', '[data-list-name*="Viewed"]',
                        '[data-testid*="recommend"]', '[data-testid*="carousel"]', '[data-testid*="related"]',
                        '[class*="recommend"]', '[class*="related"]', '[class*="related-carousel"]', '[class*="related-slider"]',
                        '[class*="cross-sell"]', '[class*="upsell"]', '[class*="similar"]', '[class*="other-products"]',
                        '[id*="related"]', '[id*="recommend"]'
                    ].join(', ');

                    const ldForbiddenContainers = '#tab-related, #tab-similar, .related-products, .similar-products, .cross-sell, .upsell, aside, footer';

                    const title = document.title || "";
                    let h1 = Array.from(document.querySelectorAll("h1")).map(e => e.innerText.trim()).filter(Boolean).join(" | ");
                    if (!h1) {
                        const mainImg = document.querySelector('img[alt*="Zone3" i][alt*="#1"]');
                        if (mainImg) h1 = (mainImg.getAttribute('alt') || '').replace(/\\s*-\\s*#1.*$/, '').trim();
                    }
                    const ldNodes = Array.from(document.querySelectorAll('script[type="application/ld+json"]'))
                        .filter(s => !s.closest(ldForbiddenContainers))
                        .map(s => s.innerText);

                    let nextDataJson = "";
                    const ndEl = document.getElementById('__NEXT_DATA__');
                    if (ndEl && ndEl.textContent) {
                        nextDataJson = ndEl.textContent.slice(0, 250000);
                    } else if (window.__NEXT_DATA__) {
                        try { nextDataJson = JSON.stringify(window.__NEXT_DATA__).slice(0, 250000); } catch (e) {}
                    }

                    let nextRscText = "";
                    if (Array.isArray(window.__next_f) && window.__next_f.length) {
                        try {
                            nextRscText = window.__next_f
                                .map(chunk => Array.isArray(chunk) && typeof chunk[1] === 'string' ? chunk[1] : '')
                                .filter(s => /price|pvp|ws2|zone3|stock|agotado/i.test(s))
                                .join('\\n')
                                .slice(0, 220000);
                        } catch (e) {}
                    }

                    const metaCurrEl = Array.from(document.querySelectorAll('head meta[property="product:price:currency"], head meta[property="og:price:currency"], [itemprop="priceCurrency"]'))
                        .find(el => !el.closest(forbiddenContainers));
                    const metaCurr = metaCurrEl ? (metaCurrEl.content || metaCurrEl.getAttribute("content") || "") : "";

                    // Only read head OG/product price or main-product itemprop=price outside forbidden/Ex-Rental cards
                    let metaPrice = (document.querySelector('head meta[property="product:price:amount"], head meta[property="og:price:amount"]') || {}).content || "";
                    if (!metaPrice) {
                        const ipEl = Array.from(document.querySelectorAll('meta[itemprop="price"], [itemprop="price"][content]')).find(el => {
                            if (el.closest(forbiddenContainers)) return false;
                            const cardCtx = el.closest('article, li, .card, .productCarousel-slide, [class*="productCard"]');
                            if (cardCtx && /ex-rental|ex rental|ex-demo|second-hand|refurbished|grade b|b-stock/i.test(cardCtx.innerText || '')) return false;
                            return true;
                        });
                        if (ipEl) metaPrice = ipEl.getAttribute("content") || "";
                    }

                    const mainScope = document.querySelector('.productView, [data-testid="product-detail"], main') || document.body;
                    const optEls = mainScope ? Array.from(mainScope.querySelectorAll('.productView-options, form[data-cart-item-add], .product-options, [class*="option"], label, select'))
                        .filter(el => !el.closest(forbiddenContainers)) : [];
                    const optText = optEls.map(e => e.innerText || "").join(" ");
                    const hasExRentalOption = /ex-rental|ex rental|ex-hire|ex hire|ex-demo|ex demo|second-hand|second hand|pre-owned|pre owned|refurbished|grade b|b-stock/i.test(optText);

                    const selectors = [
                        '#js-precio', '#productPrice', '[data-testid="product-price"]',
                        '.product-detail-price', '.pdp-price', '.product-page-price',
                        '[data-product-price-with-tax]', '[data-price-type="finalPrice"]', '.price--withTax', '.price--main', '.product-price__price',
                        '.current-price-value', '.current-price span[content]', '.price__sale .price-item--sale', '.price-item--sale', '.summary p.price ins .woocommerce-Price-amount', '.summary p.price > .woocommerce-Price-amount', 'p.price ins .woocommerce-Price-amount', 'p.price > .woocommerce-Price-amount'
                    ];
                    const domPrices = [];
                    selectors.forEach(sel => {
                        document.querySelectorAll(sel).forEach(el => {
                            if (el.closest('del, s, .old-price, .price-old, .rrp, .price--rrp, .price--non-sale, .price--withoutTax, [data-product-price-without-tax], .strike')) return;
                            if (el.closest(forbiddenContainers)) return;
                            const cardCtx = el.closest('article, li, .card, .productCarousel-slide, [class*="productCard"]');
                            if (cardCtx && /ex-rental|ex rental|ex-demo|second-hand|refurbished|grade b|b-stock/i.test(cardCtx.innerText || '')) return;
                            const txt = (el.innerText || el.getAttribute("content") || el.getAttribute("data-price-amount") || "").trim();
                            const attrCurr = (el.getAttribute("data-currency") || el.getAttribute("currency") || "").trim();
                            if (txt) domPrices.push({ selector: sel, text: txt, attrCurr });
                        });
                    });

                    // Next.js / Deporvillage H1 Buy-Box visual price fallback (checks non-strikethrough € / £ near H1)
                    if (domPrices.length === 0) {
                        const h1El = document.querySelector('h1');
                        let box = h1El ? h1El.parentElement : null;
                        for (let step = 0; step < 4 && box && box !== document.body; step++) {
                            if (/€|£/.test(box.innerText || '')) break;
                            box = box.parentElement;
                        }
                        if (box && !box.closest(forbiddenContainers)) {
                            Array.from(box.querySelectorAll('span, div, p, strong')).forEach(el => {
                                if (el.children.length > 1) return;
                                if (el.closest('del, s, .old-price, .price-old, .rrp, .strike')) return;
                                if (el.closest(forbiddenContainers)) return;
                                const clsLow = String(el.className || '').toLowerCase();
                                if (/old|rrp|pvp|cross|strike|recommend|before|prev|discount|save|pct|badge/.test(clsLow)) return;
                                const st = window.getComputedStyle(el);
                                if (st && st.textDecorationLine && st.textDecorationLine.includes('line-through')) return;
                                const t = (el.innerText || '').trim();
                                if (t.length >= 4 && t.length <= 18 && /(^\d{2,3}[.,]\d{2}\s*[€£]$|^[€£]\s*\d{2,3}[.,]\d{2}$|^\d{2,3}\s*[€£]$)/.test(t) && !/49\s*€/.test(t)) {
                                    domPrices.push({ selector: 'nextjs-buybox', text: t, attrCurr: metaCurr });
                                }
                            });
                        }
                    }

                    const bodyText = (document.body ? document.body.innerText : "").slice(0, 6000);
                    return { title, h1, ldNodes, ldPrimaryCount: ldNodes.length, nextDataJson, nextRscText, metaCurr, metaPrice, domPrices, bodyText, hasExRentalOption };
                }""")

                r_copy = dict(row)
                r_copy["url"] = cand_u
                price_val, is_oos, status_code, evidence_str = evaluate_page_info_candidates(page_info, r_copy, source_prefix="")
                if status_code in ("VERIFIED", "OUT_OF_STOCK"):
                    row["url"] = cand_u
                    return price_val, is_oos, status_code, evidence_str

    except Exception as e:
        status_code, evidence_str = "ERROR", f"Error de lectura: {str(e)[:60]}"

    # Hybrid Zyte Fallback: if Playwright hit anti-bot (403/429/503/Captcha), HTTP 404 on primary, soft challenge redirect (IDENTITY_MISMATCH) or empty JS render
    if ZYTE_API_KEY and status_code in ("BLOCKED_HTTP", "BLOCKED_CAPTCHA", "HTTP_ERROR", "NO_VALID_PRICE", "IDENTITY_MISMATCH", "ERROR"):
        for cand_u in url_candidates:
            z_info = await fetch_via_zyte(page, cand_u, country, is_pdp=True)
            if z_info is None:
                await asyncio.sleep(0.6)
                z_info = await fetch_via_zyte(page, cand_u, country, is_pdp=True, force_refresh=True)
            if z_info:
                r_copy = dict(row)
                r_copy["url"] = cand_u
                z_price, z_oos, z_status, z_ev = evaluate_page_info_candidates(z_info, r_copy, source_prefix="[Zyte] ")
                if z_status in ("NO_VALID_PRICE", "BLOCKED_CAPTCHA"):
                    z_info_retry = await fetch_via_zyte(page, cand_u, country, is_pdp=True, force_refresh=True)
                    if z_info_retry:
                        z_price, z_oos, z_status, z_ev = evaluate_page_info_candidates(z_info_retry, r_copy, source_prefix="[Zyte] ")
                status_code, evidence_str = z_status, z_ev
                if z_status in ("VERIFIED", "OUT_OF_STOCK"):
                    row["url"] = cand_u
                    return z_price, z_oos, z_status, z_ev

    return None, False, status_code, evidence_str

def enforce_history_hygiene(history):
    """Applies Option C & structural hygiene across all history entries (both before and after scanning)."""
    for h in history:
        if h.get("audit_status", "VALID") != "VALID":
            continue
        p_val = h.get("price")
        d_pct = h.get("disc_pct")
        if p_val is None or float(p_val) <= 0:
            h["audit_status"] = "QUARANTINED_INVALID_PRICE"
            continue
        if "advance-plus" in str(h.get("url", "")).lower() or (h.get("country") == "UK" and h.get("operator") == "Deporvillage" and h.get("code") == "WS21WADV101" and float(p_val) > 300):
            h["audit_status"] = "QUARANTINED_MODEL_MISMATCH"
            continue
        if h.get("country") == "UK" and h.get("operator") == "Start Fitness" and h.get("code") == "WS25MSRV101":
            h["audit_status"] = "QUARANTINED_EXCLUDED_MODEL"
            h["quarantine_reason"] = PERMANENT_EXCLUSIONS["UK-STA-WS25MSRV101"]
            continue
        if is_ex_rental_anomaly(h.get("country"), h.get("operator"), h.get("code"), p_val, h.get("pvp")):
            h["audit_status"] = "QUARANTINED_EX_RENTAL"
            h["quarantine_reason"] = h.get("quarantine_reason") or "Exclòs automàticament (Opció C v11.1): Preu Vanquish-X < £420 a My Triathlon UK correspon a variant Ex-Rental (lloguer/segona mà)."
            continue
        if d_pct is not None and float(d_pct) > MAX_CLEAN_NEW_DISC_PCT:
            h["audit_status"] = "REVIEW_DEEP_DISCOUNT"
            h["quarantine_reason"] = h.get("quarantine_reason") or f"Safata Opció C: descompte superior al {MAX_CLEAN_NEW_DISC_PCT:.0f}% pendent de validació manual."

def upsert_valid_history_entry(history, row, effective_price, effective_oos, effective_evidence, today_str, run_slot, now_iso):
    """Consolidates same-day readings using the Daily Lowest Price rule without creating duplicate VALID rows."""
    existing_same_day = next(
        (
            h for h in history
            if str(h.get("timestamp", ""))[:10] == today_str
            and h.get("country") == row["country"]
            and h.get("operator") == row["operator"]
            and h.get("code") == row["code"]
            and h.get("audit_status", "VALID") == "VALID"
        ),
        None
    )
    prev_price = row.get("price")
    prev_date = row.get("last_read", "")

    if existing_same_day and existing_same_day.get("price") is not None:
        old_day_price = float(existing_same_day["price"])
        if effective_price < old_day_price:
            existing_same_day["intraday_higher_price"] = old_day_price
            existing_same_day["audit_note"] = f"Preu mínim diari actualitzat a {run_slot} ({effective_price:.2f} vs lectura prèvia d'avui {old_day_price:.2f})"
            existing_same_day["price"] = effective_price
            existing_same_day["disc_imp"] = round(row["pvp"] - effective_price, 2)
            existing_same_day["disc_pct"] = round((existing_same_day["disc_imp"] / row["pvp"]) * 100, 1)
            existing_same_day["out_of_stock"] = bool(effective_oos)
            existing_same_day["is_from"] = False
            existing_same_day["evidence"] = effective_evidence
            existing_same_day["run_slot"] = run_slot
            existing_same_day["timestamp_iso"] = now_iso
        elif effective_price > old_day_price:
            existing_same_day["intraday_higher_price"] = effective_price
            existing_same_day["audit_note"] = f"Mantingut preu mínim diari ({old_day_price:.2f}); lectura posterior a {run_slot}: {effective_price:.2f}"
            effective_price = old_day_price
            effective_oos = bool(existing_same_day.get("out_of_stock", False))
            effective_evidence = f"{existing_same_day.get('evidence', effective_evidence)} · [Mínim diari mantingut a {run_slot}]"
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
            "out_of_stock": bool(effective_oos),
            "is_from": False,
            "url": row.get("url", ""),
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
    row["retention_status"] = "LIVE_TODAY"
    row["last_read"] = today_str
    row["out_of_stock"] = bool(effective_oos)
    row["is_from"] = False
    row["evidence"] = effective_evidence

def upsert_non_valid_tray_entry(history, row, tray_price, tray_oos, tray_status, tray_evidence, today_str, run_slot, now_iso):
    """Records REVIEW_DEEP_DISCOUNT (>65%) or QUARANTINED_EX_RENTAL in history.json without polluting VALID."""
    if tray_price is None or tray_price <= 0:
        return
    existing_tray = next(
        (
            h for h in history
            if str(h.get("timestamp", ""))[:10] == today_str
            and h.get("country") == row["country"]
            and h.get("operator") == row["operator"]
            and h.get("code") == row["code"]
            and h.get("audit_status") == tray_status
        ),
        None
    )
    disc_imp = round(row["pvp"] - tray_price, 2)
    disc_pct = round((disc_imp / row["pvp"]) * 100, 1)
    q_reason = (
        f"Safata Opció C: descompte del {disc_pct:.1f}% ({tray_price:.2f} {row['currency']}) supera el llindar automàtic del {MAX_CLEAN_NEW_DISC_PCT:.0f}%; pendent de validació manual."
        if tray_status == "REVIEW_DEEP_DISCOUNT"
        else f"Bloqueig Opció C: preu ({tray_price:.2f} {row['currency']}, -{disc_pct:.1f}%) identificat com a variant Ex-Rental / 2a mà."
    )
    if existing_tray:
        existing_tray["price"] = tray_price
        existing_tray["disc_imp"] = disc_imp
        existing_tray["disc_pct"] = disc_pct
        existing_tray["evidence"] = tray_evidence
        existing_tray["timestamp_iso"] = now_iso
    else:
        history.append({
            "timestamp": today_str,
            "run_slot": run_slot,
            "timestamp_iso": now_iso,
            "country": row["country"],
            "currency": row["currency"],
            "operator": row["operator"],
            "code": row["code"],
            "model": row["model"],
            "pvp": row["pvp"],
            "price": tray_price,
            "disc_imp": disc_imp,
            "disc_pct": disc_pct,
            "out_of_stock": bool(tray_oos),
            "is_from": False,
            "url": row.get("url", ""),
            "audit_status": tray_status,
            "quarantine_reason": q_reason,
            "evidence": tray_evidence
        })

def save_all_state(tracking, history):
    """Atomically persists tracking.json, history.json, and embedded index.html data with Option C & RetentionGuard."""
    for r in tracking:
        r.pop("_rediscovered_today", None)
        r.pop("_last_scan_code", None)
        r["tier"] = "SECONDARY" if is_secondary_operator(r.get("country"), r.get("operator")) else "SHORTLIST"
        if "deporvillage." in str(r.get("url", "")).lower() and "glide" in str(r.get("url", "")).lower():
            r["url"] = ""
            r["status"] = "UNMAPPED"
            r["price"] = None
            r["disc_imp"] = None
            r["disc_pct"] = None
            r["last_read"] = ""
            r["out_of_stock"] = False
            r["freshness"] = "NONE"
            r["retention_status"] = "NONE"
            r["evidence"] = "URL Glide descartada a Deporvillage (es monitoritza exclusivament Ascend)"
        elif r.get("disc_pct") is not None and float(r.get("disc_pct")) > MAX_CLEAN_NEW_DISC_PCT:
            r["price"] = None
            r["disc_imp"] = None
            r["disc_pct"] = None
            r["last_read"] = ""
            r["out_of_stock"] = False
            r["freshness"] = "NONE"
            r["status"] = "PENDING_URL" if r.get("url") else "UNMAPPED"
            r["retention_status"] = "REVIEW_DEEP_DISCOUNT"
        if r.get("id") in PERMANENT_EXCLUSIONS:
            r["url"] = ""
            r["status"] = "NOT_LISTED"
            r["price"] = None
            r["disc_imp"] = None
            r["disc_pct"] = None
            r["last_read"] = ""
            r["out_of_stock"] = False
            r["freshness"] = "NONE"
            r["retention_status"] = "NONE"
            r["evidence"] = PERMANENT_EXCLUSIONS[r["id"]]

    enforce_history_hygiene(history)
    history.sort(key=lambda x: (str(x.get("timestamp", "")), str(x.get("run_slot", "")), x.get("country", ""), x.get("operator", ""), x.get("code", "")))

    with open("data/tracking.json", "w", encoding="utf-8") as f:
        json.dump(tracking, f, indent=2, ensure_ascii=False)
    with open("data/history.json", "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2, ensure_ascii=False)

    valid_history = [
        h for h in history
        if h.get("audit_status", "VALID") == "VALID"
        and h.get("price") is not None
        and float(h.get("price")) > 0
        and float(h.get("disc_pct", 0)) <= MAX_CLEAN_NEW_DISC_PCT
        and not is_ex_rental_anomaly(h.get("country"), h.get("operator"), h.get("code"), h.get("price"), h.get("pvp"))
    ]
    daily_min_map = {}
    for h in valid_history:
        d_str = str(h.get("timestamp", ""))[:10]
        k = (d_str, h["country"], h["operator"], h["code"])
        if k not in daily_min_map or float(h["price"]) < daily_min_map[k][4]:
            daily_min_map[k] = [
                d_str,
                h["country"],
                h["operator"],
                h["code"],
                float(h["price"]),
                round(float(h["disc_pct"]), 1),
                1 if h.get("out_of_stock") else 0,
                0
            ]
    history_compact = list(daily_min_map.values())

    all_valid_dates = sorted(list({x[0] for x in history_compact if x[0]}))
    latest_date = all_valid_dates[-1] if all_valid_dates else ""
    cutoff_tray_date = all_valid_dates[-2] if len(all_valid_dates) >= 2 else latest_date
    review_tray = [
        {
            "date": str(h.get("timestamp", ""))[:10],
            "country": h.get("country"),
            "currency": h.get("currency"),
            "operator": h.get("operator"),
            "code": h.get("code"),
            "model": h.get("model"),
            "pvp": h.get("pvp"),
            "price": h.get("price"),
            "disc_pct": h.get("disc_pct"),
            "audit_status": h.get("audit_status"),
            "url": h.get("url", ""),
            "evidence": h.get("evidence", "")
        }
        for h in history
        if h.get("audit_status") in ("REVIEW_DEEP_DISCOUNT", "QUARANTINED_EX_RENTAL")
        and (not cutoff_tray_date or str(h.get("timestamp", ""))[:10] >= cutoff_tray_date)
    ]

    with open("index.html", "r", encoding="utf-8") as f:
        html_doc = f.read()

    quarantined_total = sum(1 for h in history if h.get("audit_status", "VALID") != "VALID")
    html_doc = re.sub(r"(?:const|let) QUARANTINED_COUNT = \d+;", f"let QUARANTINED_COUNT = {quarantined_total};", html_doc)
    if "REVIEW_TRAY =" in html_doc:
        html_doc = re.sub(r"(?:const|let) REVIEW_TRAY = \[.*?\];", lambda _: "let REVIEW_TRAY = " + json.dumps(review_tray, ensure_ascii=False) + ";", html_doc, flags=re.S)
    html_doc = re.sub(r"(?:const|let) DATA_ROWS = \[.*?\];", lambda _: "let DATA_ROWS = " + json.dumps(tracking, ensure_ascii=False) + ";", html_doc, flags=re.S)
    html_doc = re.sub(r"(?:const|let) HISTORY_COMPACT = \[.*?\];", lambda _: "let HISTORY_COMPACT = " + json.dumps(history_compact, ensure_ascii=False) + ";", html_doc, flags=re.S)
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html_doc)

async def main():
    with open("data/tracking.json", "r", encoding="utf-8") as f:
        tracking = json.load(f)
    with open("data/history.json", "r", encoding="utf-8") as f:
        history = json.load(f)

    enforce_history_hygiene(history)

    now_dt = get_madrid_now()
    today_str = now_dt.strftime("%Y-%m-%d")
    slot_suffix = "AM" if now_dt.hour < 14 else "PM"
    run_slot = f"{today_str}-{slot_suffix}"
    now_iso = now_dt.isoformat(timespec="seconds")

    latest_hist_by_key = {}
    prior_dates = sorted({
        str(h.get("timestamp", ""))[:10]
        for h in history
        if h.get("audit_status", "VALID") == "VALID"
        and h.get("price") is not None
        and float(h.get("price")) > 0
        and float(h.get("disc_pct", 0)) <= MAX_CLEAN_NEW_DISC_PCT
        and str(h.get("timestamp", ""))[:10] < today_str
    })
    prev_scan_date = prior_dates[-1] if prior_dates else ""
    t_minus_1_keys = set()

    for h in history:
        if h.get("audit_status", "VALID") != "VALID":
            continue
        p_val = h.get("price")
        d_pct = h.get("disc_pct")
        if p_val is None or float(p_val) <= 0 or (d_pct is not None and float(d_pct) > MAX_CLEAN_NEW_DISC_PCT):
            continue
        if is_ex_rental_anomaly(h.get("country"), h.get("operator"), h.get("code"), p_val, h.get("pvp")):
            continue
        d_str = str(h.get("timestamp", ""))[:10]
        if not d_str:
            continue
        k = (h.get("country"), h.get("operator"), h.get("code"))
        if d_str == prev_scan_date:
            t_minus_1_keys.add(k)
        cur = latest_hist_by_key.get(k)
        if not cur or d_str > cur["date"] or (d_str == cur["date"] and float(p_val) < cur["price"]):
            latest_hist_by_key[k] = {
                "date": d_str,
                "price": float(p_val),
                "out_of_stock": bool(h.get("out_of_stock", False)),
                "evidence": h.get("evidence") or ""
            }

    for row in tracking:
        if row.get("id") in PERMANENT_EXCLUSIONS:
            continue
        if "deporvillage." in str(row.get("url", "")).lower() and "glide" in str(row.get("url", "")).lower():
            row["url"] = ""
            row["status"] = "UNMAPPED"
            row["price"] = None
            row["disc_imp"] = None
            row["disc_pct"] = None
            row["last_read"] = ""
            row["out_of_stock"] = False
            row["freshness"] = "NONE"
            row["retention_status"] = "NONE"
        elif row.get("disc_pct") is not None and float(row.get("disc_pct")) > MAX_CLEAN_NEW_DISC_PCT:
            row["price"] = None
            row["disc_imp"] = None
            row["disc_pct"] = None
            row["last_read"] = ""
            row["out_of_stock"] = False
            row["freshness"] = "NONE"
            row["status"] = "PENDING_URL" if row.get("url") else "UNMAPPED"
            row["retention_status"] = "REVIEW_DEEP_DISCOUNT"
        k = (row.get("country"), row.get("operator"), row.get("code"))
        best_h = latest_hist_by_key.get(k)
        if best_h and row.get("url") and not is_generic_category_url(row.get("url", "")):
            r_date = str(row.get("last_read") or "").strip()
            r_price = row.get("price")
            is_cur_ex = is_ex_rental_anomaly(row.get("country"), row.get("operator"), row.get("code"), r_price, row.get("pvp"))
            if is_cur_ex or row.get("status") != "VERIFIED" or best_h["date"] > r_date or (best_h["date"] == r_date and (r_price is None or best_h["price"] < float(r_price))):
                row["price"] = round(best_h["price"], 2)
                row["disc_imp"] = round(float(row["pvp"]) - row["price"], 2)
                row["disc_pct"] = round((row["disc_imp"] / float(row["pvp"])) * 100, 1)
                row["status"] = "VERIFIED"
                row["last_read"] = best_h["date"]
                row["out_of_stock"] = best_h["out_of_stock"]
                if best_h["evidence"]:
                    row["evidence"] = best_h["evidence"]

    domain_blocks = {}
    CIRCUIT_BREAKER_LIMIT = 1 if ZYTE_API_KEY else 2

    print(f"Starting Zone3 RetentionGuard v12.6 (Dual-Lane ES||UK + Sostre <=50% Verificat) ({now_iso}) | Opció C (<=50% Automàtic, >50% Safata Revisió) | Baseline T-1 ({prev_scan_date}): {len(t_minus_1_keys)} lectures | Zyte: {'ENABLED' if ZYTE_API_KEY else 'PLAYWRIGHT_ONLY'}")

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

        updated_count = 0
        zyte_rescued_count = 0
        quarantined_count = 0
        circuit_skipped = 0
        broken_row_ids = set()

        # PHASE 1: Dual-Lane Parallel Primary PDP Price Verification (ES || UK, Shortlist first in each lane)
        stats = {"updated": 0, "zyte": 0, "quarantined": 0, "circuit": 0}

        async def _process_p1_row(row, page):
            if row.get("id") in PERMANENT_EXCLUSIONS:
                return
            row["is_from"] = False
            url = row.get("url", "").strip()
            if not url:
                if row.get("status") not in ("NOT_LISTED", "UNMAPPED"):
                    row["status"] = "UNMAPPED"
                row["freshness"] = "NONE"
                row["retention_status"] = "NONE"
                if not row.get("evidence"):
                    row["evidence"] = "Cerca automàtica: cap fitxa PDP localitzada al catàleg de l'operador"
                return

            if is_generic_category_url(url):
                row["status"] = "PENDING_PDP"
                row["freshness"] = "NONE"
                row["retention_status"] = "NONE"
                row["price"] = None
                row["disc_imp"] = None
                row["disc_pct"] = None
                row["evidence"] = "En quarantena: URL de categoria genèrica (cal URL de fitxa individual PDP)"
                stats["quarantined"] += 1
                return

            dom = get_domain(url)
            playwright_blocked_for_dom = domain_blocks.get(dom, 0) >= CIRCUIT_BREAKER_LIMIT

            if playwright_blocked_for_dom and not ZYTE_API_KEY:
                stats["circuit"] += 1
                row["_last_scan_code"] = "CIRCUIT_SKIPPED"
                row["freshness"] = "HISTORICAL_PDP" if (row.get("status") == "VERIFIED" and row.get("last_read") != today_str) else row.get("freshness", "NONE")
                row["evidence"] = f"Aturada preventiva (Circuit Breaker) a {dom} · Lectura del {row.get('last_read') or 'històric'}"
                return

            if playwright_blocked_for_dom and ZYTE_API_KEY:
                rem_urls = []
                for r in tracking:
                    if r.get("country") == row["country"] and get_domain(r.get("url", "")) == dom and not is_generic_category_url(r.get("url", "")):
                        c_list = get_canonical_url_candidates(r.get("url", ""), r["country"])
                        if c_list:
                            rem_urls.append(c_list[0])
                await prefetch_zyte_batch(page, rem_urls, row["country"], is_pdp=True)

            min_price, is_oos, status_code, evidence_str = await extract_verified_pdp_price(
                page, row, force_zyte_only=playwright_blocked_for_dom
            )
            row["_last_scan_code"] = status_code

            if status_code in ("BLOCKED_HTTP", "BLOCKED_CAPTCHA", "NO_VALID_PRICE"):
                domain_blocks[dom] = domain_blocks.get(dom, 0) + 1

            if status_code == "VERIFIED" and min_price is not None and min_price > 0:
                if "[Zyte]" in evidence_str:
                    stats["zyte"] += 1
                    domain_blocks[dom] = domain_blocks.get(dom, 0) + 1
                upsert_valid_history_entry(history, row, min_price, is_oos, evidence_str, today_str, run_slot, now_iso)
                stats["updated"] += 1
            elif status_code in ("REVIEW_DEEP_DISCOUNT", "QUARANTINED_EX_RENTAL"):
                upsert_non_valid_tray_entry(history, row, min_price, is_oos, status_code, evidence_str, today_str, run_slot, now_iso)
                row["freshness"] = "LIVE_TODAY" if row.get("last_read") == today_str else "HISTORICAL_PDP"
                row["retention_status"] = status_code
                row["evidence"] = f"Lectura històrica ({row.get('last_read', '')}) · [{run_slot}: {evidence_str}]"
            else:
                if status_code in ("HTTP_ERROR", "IDENTITY_MISMATCH"):
                    broken_row_ids.add(row["id"])
                if status_code == "OUT_OF_STOCK":
                    row["out_of_stock"] = True
                    row["retention_status"] = "OOS_NO_PRICE"
                if row.get("price") is not None and row.get("status") == "VERIFIED":
                    row["freshness"] = "LIVE_TODAY" if row.get("last_read") == today_str else "HISTORICAL_PDP"
                    row["evidence"] = f"Lectura històrica ({row.get('last_read', '')}) · Revisió avui ({run_slot}): {evidence_str}"
                else:
                    row["status"] = "PENDING_URL"
                    row["freshness"] = "NONE"
                    row["evidence"] = f"Revisat ({run_slot}): {evidence_str}"

        async def _run_p1_lane(lane_rows, page):
            ordered = sorted(lane_rows, key=lambda r: 1 if is_secondary_operator(r.get("country"), r.get("operator")) else 0)
            for row in ordered:
                if is_time_budget_exceeded(margin_sec=180) and is_secondary_operator(row.get("country"), row.get("operator")):
                    break
                await _process_p1_row(row, page)

        es_p1_rows = [r for r in tracking if r.get("country") == "ES"]
        uk_p1_rows = [r for r in tracking if r.get("country") == "UK"]
        await asyncio.gather(
            _run_p1_lane(es_p1_rows, page_es),
            _run_p1_lane(uk_p1_rows, page_uk)
        )

        # PHASE 1.5: Dual-Lane (ES || UK) RetentionGuard T vs T-1 Rescue Pass
        lost_rows = [
            r for r in tracking
            if r.get("id") not in PERMANENT_EXCLUSIONS
            and r.get("status") == "VERIFIED"
            and r.get("last_read") != today_str
            and r.get("url")
            and not is_generic_category_url(r.get("url", ""))
            and r.get("retention_status") not in ("REVIEW_DEEP_DISCOUNT", "QUARANTINED_EX_RENTAL")
        ]
        lost_rows.sort(key=lambda r: (1 if is_secondary_operator(r["country"], r["operator"]) else 0, 0 if (r["country"], r["operator"], r["code"]) in t_minus_1_keys else 1, r["id"]))

        if lost_rows:
            print(f"[RETENTION T vs T-1 RESCUE] {len(lost_rows)} VERIFIED PDPs unread in Phase 1 ({sum(1 for r in lost_rows if (r['country'], r['operator'], r['code']) in t_minus_1_keys)} from T-1). Running Dual-Lane Rescue...")
            rescue_stats = {"rescued": 0}

            async def _run_rescue_lane(lane_lost, page):
                for r_lost in lane_lost:
                    if is_time_budget_exceeded(margin_sec=65):
                        break
                    is_t1 = (r_lost["country"], r_lost["operator"], r_lost["code"]) in t_minus_1_keys
                    tag_t1 = "[T-1 PRIORITY]" if is_t1 else "[HIST]"
                    print(f"  -> {tag_t1} Rescuing {r_lost['id']} ({r_lost['operator']} {r_lost['country']}): {r_lost.get('evidence', '')[:90]}")

                    for cand_u in get_canonical_url_candidates(r_lost["url"], r_lost["country"]):
                        ZYTE_PAGE_CACHE.pop((r_lost["country"], cand_u), None)

                    r_price, r_oos, r_st, r_ev = None, False, "ERROR", ""
                    if ZYTE_API_KEY:
                        r_price, r_oos, r_st, r_ev = await extract_verified_pdp_price(page, r_lost, force_zyte_only=True)

                    if r_st not in ("VERIFIED", "REVIEW_DEEP_DISCOUNT", "QUARANTINED_EX_RENTAL"):
                        await asyncio.sleep(0.8)
                        pw_price, pw_oos, pw_st, pw_ev = await extract_verified_pdp_price(page, r_lost, force_zyte_only=False)
                        if pw_st in ("VERIFIED", "REVIEW_DEEP_DISCOUNT", "QUARANTINED_EX_RENTAL") or not ZYTE_API_KEY:
                            r_price, r_oos, r_st, r_ev = pw_price, pw_oos, pw_st, pw_ev

                    r_lost["_last_scan_code"] = r_st

                    if r_st == "VERIFIED" and r_price is not None and r_price > 0:
                        rescue_stats["rescued"] += 1
                        stats["updated"] += 1
                        if "[Zyte]" in r_ev:
                            stats["zyte"] += 1
                        broken_row_ids.discard(r_lost["id"])
                        upsert_valid_history_entry(history, r_lost, r_price, r_oos, f"[RetentionGuard Rescue] {r_ev}", today_str, run_slot, now_iso)
                        print(f"     [RESCUED] {r_lost['id']} -> {r_price} {r_lost['currency']}")
                    elif r_st in ("REVIEW_DEEP_DISCOUNT", "QUARANTINED_EX_RENTAL"):
                        broken_row_ids.discard(r_lost["id"])
                        upsert_non_valid_tray_entry(history, r_lost, r_price, r_oos, r_st, r_ev, today_str, run_slot, now_iso)
                        r_lost["retention_status"] = r_st
                        r_lost["evidence"] = f"Lectura històrica ({r_lost.get('last_read', '')}) · [Rescue {run_slot}: {r_ev}]"
                    elif r_st in ("HTTP_ERROR", "IDENTITY_MISMATCH") or (r_st == "NO_VALID_PRICE" and is_t1):
                        broken_row_ids.add(r_lost["id"])
                    elif r_st == "OUT_OF_STOCK":
                        r_lost["out_of_stock"] = True
                        r_lost["retention_status"] = "OOS_NO_PRICE"

            await asyncio.gather(
                _run_rescue_lane([r for r in lost_rows if r["country"] == "ES"], page_es),
                _run_rescue_lane([r for r in lost_rows if r["country"] == "UK"], page_uk)
            )
            print(f"[RETENTION RESCUE RESULT] Rescued {rescue_stats['rescued']}/{len(lost_rows)} missed PDPs; {len(broken_row_ids)} broken URLs sent to Phase 2 catalog check.")

        # Checkpoint Phase 1 + 1.5 before Phase 2
        save_all_state(tracking, history)

        # PHASE 2: Dual-Lane 100% Automatic Discovery + Dual-Lane Immediate Price Verification
        discovered_count = await discover_missing_pdps(page_es, page_uk, tracking, today_str, domain_blocks=domain_blocks, broken_row_ids=broken_row_ids)
        if discovered_count > 0:
            new_p2_rows = [
                r for r in tracking
                if r.get("id") not in PERMANENT_EXCLUSIONS
                and (r.get("_rediscovered_today") or (r.get("status") == "PENDING_URL" and f"({today_str})" in str(r.get("evidence", ""))))
                and r.get("url")
            ]

            async def _verify_p2_lane(lane_p2, page):
                for row in lane_p2:
                    row.pop("_rediscovered_today", None)
                    dom = get_domain(row["url"])
                    min_price, is_oos, status_code, evidence_str = await extract_verified_pdp_price(
                        page, row, force_zyte_only=(domain_blocks.get(dom, 0) >= CIRCUIT_BREAKER_LIMIT)
                    )
                    row["_last_scan_code"] = status_code
                    if status_code == "VERIFIED" and min_price is not None and min_price > 0:
                        if "[Zyte]" in evidence_str:
                            stats["zyte"] += 1
                        upsert_valid_history_entry(history, row, min_price, is_oos, evidence_str, today_str, run_slot, now_iso)
                        stats["updated"] += 1
                    elif status_code in ("REVIEW_DEEP_DISCOUNT", "QUARANTINED_EX_RENTAL"):
                        upsert_non_valid_tray_entry(history, row, min_price, is_oos, status_code, evidence_str, today_str, run_slot, now_iso)
                        row["retention_status"] = status_code

            await asyncio.gather(
                _verify_p2_lane([r for r in new_p2_rows if r["country"] == "ES"], page_es),
                _verify_p2_lane([r for r in new_p2_rows if r["country"] == "UK"], page_uk)
            )

        updated_count = stats["updated"]
        zyte_rescued_count = stats["zyte"]
        quarantined_count = stats["quarantined"]
        circuit_skipped = stats["circuit"]

        await browser.close()

    # Final T vs T-1 Retention Audit Classification
    t1_losses_unjustified = []
    t1_delisted_confirmed = []
    for row in tracking:
        if row.get("status") != "VERIFIED":
            continue
        k = (row["country"], row["operator"], row["code"])
        if row.get("last_read") == today_str:
            row["retention_status"] = "LIVE_TODAY"
            continue
        last_code = row.get("_last_scan_code", "")
        if row.get("retention_status") == "DELISTED_CONFIRMED" and last_code in ("HTTP_ERROR", "IDENTITY_MISMATCH", "NO_VALID_PRICE", ""):
            if k in t_minus_1_keys:
                t1_delisted_confirmed.append(row["id"])
            continue
        if row["id"] in broken_row_ids and (row["country"], row["operator"]) in COMPLETED_DISCOVERY_OPS:
            row["retention_status"] = "DELISTED_CONFIRMED"
            row["evidence"] = f"Lectura històrica ({row.get('last_read', '')}: {row['currency']} {row['price']:.2f}) · [{today_str}: Desllistat confirmat — fitxa inactiva i model absent al catàleg de {row['operator']}]"
            if k in t_minus_1_keys:
                t1_delisted_confirmed.append(row["id"])
        elif row.get("retention_status") not in ("REVIEW_DEEP_DISCOUNT", "QUARANTINED_EX_RENTAL", "OOS_NO_PRICE"):
            if k in t_minus_1_keys:
                row["retention_status"] = "UNJUSTIFIED_LOSS"
                t1_losses_unjustified.append(row["id"])
            else:
                row["retention_status"] = "HISTORICAL_WATCH"

    save_all_state(tracking, history)

    print(
        f"[RETENTION T vs T-1 SUMMARY] Baseline {prev_scan_date}: {len(t_minus_1_keys)} | "
        f"Valid Today ({today_str}): {updated_count} | "
        f"Confirmed Delisted: {len(t1_delisted_confirmed)} {t1_delisted_confirmed} | "
        f"Unjustified T-1 Losses: {len(t1_losses_unjustified)} {t1_losses_unjustified}"
    )

if __name__ == "__main__":
    asyncio.run(main())
