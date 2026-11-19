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
    "/brands/zone3",
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
        "https://www.tradeinn.com/swiminn/es/s?q=zone3+versa",
        "https://www.tradeinn.com/swiminn/es/s?q=WS25WSRV101",
        "https://www.tradeinn.com/swiminn/es/s?q=5056305746940"
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
        "https://sportano.com/en/zone3?p=3",
        "https://sportano.com/en/zone3?p=4",
        "https://sportano.com/en/search?q=zone3+wetsuit",
        "https://sportano.com/en/search?q=zone3+vision",
        "https://sportano.com/en/search?q=zone3+terraprene",
        "https://sportano.com/en/search?q=WS24MVIS101",
        "https://sportano.com/en/search?q=WS24WVIS101",
        "https://sportano.com/en/search?q=5056305737726",
        "https://sportano.com/en/search?q=5056305739447",
        "https://sportano.com/en/search?q=zone3+vanquish",
        "https://sportano.com/en/search?q=WS22WVAN101",
        "https://sportano.com/en/search?q=zone3+aspire",
        "https://sportano.com/en/search?q=WS25WASP101",
        "https://sportano.com/en/search?q=zone3+active+flex",
        "https://sportano.com/en/search?q=WS25MACTF101",
        "https://sportano.com/en/search?q=WS25WACTF101",
        "https://sportano.com/en/search?q=zone3+glide",
        "https://sportano.com/en/search?q=zone3+ascend",
        "https://sportano.com/en/search?q=WS26WGLISL101",
        "https://sportano.com/en/search?q=zone3+versa",
        "https://sportano.com/en/search?q=WS25MSRV101",
        "https://sportano.com/en/search?q=WS25WSRV101"
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
        "https://www.deporvillage.co.uk/catalogsearch/result/?q=zone3+glide",
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
        "https://www.sigmasports.com/brand/zone3/wetsuits",
        "https://www.sigmasports.com/brand/zone3",
        "https://www.sigmasports.com/search?query=zone3+wetsuit",
        "https://www.sigmasports.com/search?query=zone3+vision",
        "https://www.sigmasports.com/search?query=zone3+agile",
        "https://www.sigmasports.com/search?query=zone3+active+flex",
        "https://www.sigmasports.com/search?query=zone3+ascend",
        "https://www.sigmasports.com/search?query=zone3+glide",
        "https://www.sigmasports.com/search?query=zone3+versa"
    ],
    ("UK", "Wetsuit Outlet"): [
        "https://www.wetsuitoutlet.co.uk/brands/zone3",
        "https://www.wetsuitoutlet.co.uk/zone3-m-123.html",
        "https://www.wetsuitoutlet.co.uk/search?q=zone3+wetsuit",
        "https://www.wetsuitoutlet.co.uk/advanced_search_result.php?keywords=zone3+vanquish",
        "https://www.wetsuitoutlet.co.uk/advanced_search_result.php?keywords=zone3+aspire",
        "https://www.wetsuitoutlet.co.uk/advanced_search_result.php?keywords=zone3+versa"
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
        "https://www.deporvillage.co.uk/zone3-glide-sleeveless-wetsuit-black-grey",
        "https://www.deporvillage.co.uk/zone3-ascend-sleeveless-wetsuit"
    ],
    ("UK", "Deporvillage", "WS26WGLISL101"): [
        "https://www.deporvillage.co.uk/zone3-ascend-sleeveless-wetsuit-black-grey-women",
        "https://www.deporvillage.co.uk/zone3-glide-sleeveless-wetsuit-black-grey-women",
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

    if any(re.search(r"\b" + re.escape(bad) + r"\b", combined) for bad in ["goggles", "gafas", "gloves", "guantes", "socks", "calcetines", "buoy", "boya", "cap", "caps", "gorro", "trisuit", "kneeskin", "jammer"]):
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

        # Strip out related/recommended/carousel/footer/aside/strikeout blocks before extracting main-product DOM prices
        main_html = re.sub(r"<(script|style|noscript|aside|footer|nav|header|del|s)[^>]*>.*?</\1>", " ", html_str, flags=re.I | re.S)
        main_html = re.sub(
            r'<(div|section|ul)[^>]+(?:class|id|data-testid)=["\'][^"\']*(?:related|recommend|carousel|slider|upsell|cross-sell|similar|also-bought|alternatives|old-price|price-old|rrp|strike)[^"\']*["\'][^>]*>.*?</\1>',
            " ",
            main_html,
            flags=re.I | re.S
        )
        dom_prices = []
        for m_p in re.finditer(r'id=["\'](?:js-precio|productPrice|product-price)["\'][^>]*>([^<]+)<', main_html, flags=re.I):
            dom_prices.append({"selector": "#productPrice", "text": m_p.group(1).strip(), "attrCurr": meta_curr})
        for m_ip in re.finditer(r'itemprop=["\']price["\'][^>]*content=["\']([^"\']+)["\']', main_html, flags=re.I):
            dom_prices.append({"selector": "[itemprop=price]", "text": m_ip.group(1).strip(), "attrCurr": meta_curr})
        for m_dt in re.finditer(r'data-testid=["\'](?:product-price|price|current-price|final-price)["\'][^>]*>(.*?)</(?:span|div|p|strong)>', main_html, flags=re.I | re.S):
            txt_dt = re.sub(r"<[^>]+>", " ", m_dt.group(1)).strip()
            if txt_dt and len(txt_dt) < 35:
                dom_prices.append({"selector": "[data-testid=product-price]", "text": txt_dt, "attrCurr": meta_curr})
        for m_cls in re.finditer(r'class=["\'][^"\']*(?:product-detail-price|pdp-price|product-page-price|price--main|price--withoutTax|product-price__price|now-price|price-now)[^"\']*["\'][^>]*>(.*?)</(?:span|div|p|strong)>', main_html, flags=re.I | re.S):
            txt_cls = re.sub(r"<[^>]+>", " ", m_cls.group(1)).strip()
            if txt_cls and len(txt_cls) < 35:
                dom_prices.append({"selector": ".pdp-price", "text": txt_cls, "attrCurr": meta_curr})

        # Extract links including title, aria-label, and inner img alt attributes (crucial for Sportano & Alltricks product cards)
        links = []
        parsed_base = urlparse(base_url)
        base_origin = f"{parsed_base.scheme}://{parsed_base.netloc}" if parsed_base.scheme else ""
        for m_a in re.finditer(r'<a\s+([^>]*?)href=["\']([^"\']+)["\']([^>]*)>(.*?)</a>', html_str, flags=re.I | re.S):
            attrs_before, href, attrs_after, inner_html = m_a.group(1), m_a.group(2).strip(), m_a.group(3), m_a.group(4)
            if href.startswith("/") and base_origin:
                href = base_origin + href
            if href.startswith("http"):
                all_attrs = f"{attrs_before} {attrs_after}"
                attr_texts = re.findall(r'(?:title|aria-label)=["\']([^"\']+)["\']', all_attrs, flags=re.I)
                img_alts = re.findall(r'alt=["\']([^"\']+)["\']', inner_html, flags=re.I)
                inner_txt = re.sub(r"<[^>]+>", " ", inner_html)
                combined_txt = " ".join([inner_txt] + attr_texts + img_alts)
                combined_txt = re.sub(r"\s+", " ", combined_txt).strip()
                links.append({"href": href, "text": combined_txt})

        clean_html = re.sub(r"<(script|style|noscript)[^>]*>.*?</\1>", " ", html_str, flags=re.I | re.S)
        body_text = re.sub(r"<[^>]+>", " ", clean_html)
        body_text = re.sub(r"\s+", " ", body_text).strip()[:6000]

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
                            text: ((a.innerText || '') + ' ' + (a.getAttribute('title') || '') + ' ' + (a.getAttribute('aria-label') || '') + ' ' + Array.from(a.querySelectorAll('img[alt]')).map(i => i.getAttribute('alt')).join(' ')).trim()
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

            # 1b. Direct Operator Internal Search by exact SKU & EAN (especially for Sportano, Deporvillage, Sigma, Alltricks)
            if not found_url:
                ean = MODEL_EANS.get(code, "")
                kw_main = (MODEL_KEYWORDS.get(code) or [""])[0]
                gender_q = "women" if ("W" in code[4:6] or "women" in model_name.lower()) else "men"
                op_search_templates = {
                    ("ES", "Sportano"): [f"https://sportano.com/en/search?q={code}", f"https://sportano.com/en/search?q=zone3+{kw_main}+{gender_q}"],
                    ("ES", "Deporvillage"): [f"https://www.deporvillage.com/catalogsearch/result/?q={code}", f"https://www.deporvillage.com/catalogsearch/result/?q={ean}"],
                    ("UK", "Deporvillage"): [f"https://www.deporvillage.co.uk/catalogsearch/result/?q={code}", f"https://www.deporvillage.co.uk/catalogsearch/result/?q={ean}"],
                    ("ES", "Alltricks"): [f"https://www.alltricks.es/s?k=zone3+{kw_main}"],
                    ("UK", "Sigma"): [f"https://www.sigmasports.com/search?query=zone3+{kw_main}"]
                }
                for s_url in op_search_templates.get((country, operator), []):
                    if found_url:
                        break
                    try:
                        s_links = []
                        resp = await page.goto(s_url, wait_until="domcontentloaded", timeout=18000)
                        if resp and resp.status == 200:
                            await page.wait_for_timeout(1200)
                            s_links = await page.evaluate("""() => {
                                return Array.from(document.querySelectorAll('a[href]')).map(a => ({
                                    href: a.href,
                                    text: ((a.innerText || '') + ' ' + (a.getAttribute('title') || '') + ' ' + (a.getAttribute('aria-label') || '') + ' ' + Array.from(a.querySelectorAll('img[alt]')).map(i => i.getAttribute('alt')).join(' ')).trim()
                                })).filter(x => x.href && x.href.startsWith('http'));
                            }""")
                        elif ZYTE_API_KEY:
                            zinfo = await fetch_via_zyte(page, s_url, country)
                            if zinfo and zinfo.get("links"):
                                s_links = zinfo["links"]
                        for slink in s_links:
                            href = slink["href"].split("#")[0]
                            if expected_dom and expected_dom not in href.lower():
                                continue
                            if is_generic_category_url(href):
                                continue
                            mkt_ok, _ = validate_market_url(href, country)
                            if not mkt_ok:
                                continue
                            id_ok, _ = validate_product_identity(slink["text"], href, code, model_name)
                            if id_ok:
                                found_url = href
                                break
                    except Exception:
                        pass

            # 2. Fallback: DuckDuckGo HTML search (`site:<operator_domain> zone3 <model> <code/EAN>`)
            if not found_url and expected_dom:
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
    # Regla d'auditoria: descartar descomptes superiors al 50% (pressuposant error, liquidació residual o unitat de 2a mà / outlet B-stock)
    min_allowed_ratio = 0.50

    # Market tag for evidence (explicitly clarifying EU-wide .com / .nl stores shipping in EUR to ES)
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
    detected_oos = False
    detected_instock = False
    currency_mismatch = False

    has_local_domain_currency = (
        (country == "ES" and any(d in u_low for d in [".es/", ".nl/", "country=es", "currency=eur", "deporvillage.com/", "sportano.com/", "wetsuitoutlet.es/", "alltricks.es/"])) or
        (country == "UK" and any(d in u_low for d in [".co.uk/", "country=uk", "currency=gbp", "sigmasports.com/", "sportsshoes.com/", "wetsuitoutlet.co.uk/"]))
    )
    m_curr = str(page_info.get("metaCurr", "")).upper().strip()
    if m_curr in ("€", "EUR"):
        m_curr = "EUR"
    elif m_curr in ("£", "GBP"):
        m_curr = "GBP"

    # 0. Zyte Automatic Product Extraction (individually validated for product identity & currency)
    zprod = page_info.get("zyteProduct") or {}
    if isinstance(zprod, dict) and zprod.get("price"):
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
                candidates.append((
                    1,
                    is_z_oos,
                    z_val,
                    f"{source_prefix}Zyte Product API [{market_tag}] ({z_val:.2f} {expected_sym}) · '{(z_name or page_info.get('h1', ''))[:40]}'"
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
                        for p_key in ["price", "lowPrice", "highPrice"]:
                            if p_key in off:
                                val = normalize_price(off[p_key])
                                if val and (pvp * min_allowed_ratio) <= val <= (pvp * 1.20):
                                    if not is_off_oos and p_key in ("price", "lowPrice"):
                                        instock_variant_prices.append((val, off_size))
                                        jsonld_base_prices.append(val)
                                    elif is_off_oos:
                                        oos_variant_prices.append((val, off_size))
                                    candidates.append((
                                        1,
                                        is_off_oos,
                                        val,
                                        f"{source_prefix}JSON-LD {p_key} [{market_tag}] ({val:.2f} {expected_sym}) · Producte: '{(prod_name or page_info.get('h1', ''))[:40]}'"
                                    ))
        except Exception:
            pass

    # 2. OpenGraph / Microdata
    if m_curr and m_curr != expected_curr:
        currency_mismatch = True
    elif page_info.get("metaPrice") and (m_curr == expected_curr or has_local_domain_currency):
        val = normalize_price(page_info["metaPrice"])
        if val:
            candidates.append((
                2,
                False,
                val,
                f"{source_prefix}Meta OG [{market_tag}] ({val:.2f} {expected_sym}) · H1: '{page_info.get('h1', '')[:40]}'"
            ))

    # 3. Main Product DOM elements (excluding all carousels/related blocks)
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
                    f"{source_prefix}DOM Principal {dp['selector']} [{market_tag}] ({val:.2f} {expected_sym}) · H1: '{page_info.get('h1', '')[:38]}'"
                ))

    # 4. Promo Code / Coupon Price Detection on PDP:
    #    - Case 4A: The page explicitly displays the discounted price with a promo code (e.g., Sportano "598,49 € with code: BLACKBELT") ->
    #      Use the displayed discounted price as priority 1 and annotate both the promo code and the base price in the tooltip.
    #    - Case 4B: The page mentions a promo code/coupon discount (e.g. "extra 10% off with code X") without displaying the resulting discounted price ->
    #      Keep the base price and add a hidden tooltip note that a coupon exists.
    explicit_promo_price = None
    detected_promo_code = None
    m_code_name = re.search(r"(?:with code|con el código|amb el codi|code|código|cupón|coupon)[:\s]+([A-Z0-9_-]{4,16})", body_text_raw, flags=re.I)
    if m_code_name:
        cand_code = m_code_name.group(1).upper()
        if cand_code not in ("ZONE3", "WETSUIT", "NEOPRENE", "HTML", "JSON", "TRUE", "FALSE") and not cand_code.startswith("WS2"):
            detected_promo_code = cand_code

    # Look for explicit price near promo code in body text (e.g. "598,49 € with code BLACKBELT" or "with code BLACKBELT: 598.49 €")
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
            if p_val and (pvp * min_allowed_ratio) <= p_val <= (pvp * 1.15):
                explicit_promo_price = p_val
                if c_raw and len(c_raw) >= 4:
                    detected_promo_code = c_raw.upper()
                break

    if explicit_promo_price and not (detected_oos and not detected_instock):
        code_lbl = f" '{detected_promo_code}'" if detected_promo_code else ""
        candidates.append((
            1,
            False,
            explicit_promo_price,
            f"{source_prefix}Preu amb codi{code_lbl} mostrat a la fitxa [{market_tag}] ({explicit_promo_price:.2f} {expected_sym})"
        ))

    body_has_oos_text = any(w in body_low for w in ["agotado", "out of stock", "fuera de stock", "sold out", "no disponible", "currently unavailable", "product temporarily unavailable", "temporarily unavailable"])
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

    # Sort by: (is_undiscounted_rrp_metadata, priority, lowest_price)
    # This ensures that if a metadata tag holds the full RRP (>= 99.5% of PVP) while another verified main-product source holds the active sale price, the active sale price is selected.
    valid_candidates.sort(key=lambda x: (1 if (x[2] >= pvp * 0.995 and len(valid_candidates) > 1) else 0, x[0], x[2]))
    _, best_cand_oos, best_price, best_evidence = valid_candidates[0]

    # Add coupon badge & tooltip note if the selected price is a promo-code price and we also know the higher base price (e.g. Sportano BLACKBELT)
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

    # Subtle note in tooltip if multiple in-stock sizes have different prices (and not already a base vs promo difference)
    unique_instock_prices = sorted(list(set(round(p, 2) for (p, _) in instock_variant_prices)))
    if len(unique_instock_prices) > 1 and not base_ref_prices:
        min_p = unique_instock_prices[0]
        max_p = unique_instock_prices[-1]
        min_sizes = [sz for (p, sz) in instock_variant_prices if round(p, 2) == min_p and sz]
        sz_note = f" ({min_sizes[0][:18]})" if min_sizes else ""
        best_evidence += f" · [Nota talles: preu mínim en talla específica{sz_note}; altres talles en estoc fins a {max_p:.2f} {expected_sym}]"

    final_oos = True if (best_cand_oos or (detected_oos and not detected_instock)) else False
    return round(best_price, 2), final_oos, "VERIFIED", best_evidence

def get_canonical_url_candidates(url, country):
    """Returns primary URL plus clean locale-prefixed fallback variants (e.g. Wetsuit Outlet /es-es/ and /en-es/ without legacy osCommerce query strings)."""
    u = url.strip()
    if not u:
        return []
    cands = [u]
    if "wetsuitoutlet.es/" in u.lower():
        base_no_q = u.split("?")[0]
        # If URL had a non-Spanish/non-English slug (like Danish 'svommedragt...sortbla-p-38382.html'), also add the standard English/Spanish slug for that product ID
        m_pid = re.search(r"-(p-\d+\.html)$", base_no_q, flags=re.I)
        path_part = re.sub(r"^https?://(?:www\.)?wetsuitoutlet\.es/(?:(?:es-es|en-es)/)?", "", base_no_q, flags=re.I)
        for cand_u in [
            f"https://www.wetsuitoutlet.es/es-es/{path_part}",
            f"https://www.wetsuitoutlet.es/en-es/{path_part}",
            base_no_q
        ]:
            if cand_u not in cands:
                cands.append(cand_u)
    elif "wetsuitoutlet.co.uk/" in u.lower() and "?" in u:
        base_no_q = u.split("?")[0]
        if base_no_q not in cands:
            cands.append(base_no_q)
    return cands

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
        for cand_u in get_canonical_url_candidates(url, country):
            for attempt in range(2):
                z_info = await fetch_via_zyte(page, cand_u, country)
                if z_info:
                    r_copy = dict(row)
                    r_copy["url"] = cand_u
                    z_price, z_oos, z_status, z_ev = evaluate_page_info_candidates(z_info, r_copy, source_prefix="[Zyte] ")
                    if z_status in ("VERIFIED", "OUT_OF_STOCK"):
                        if cand_u != url:
                            row["url"] = cand_u
                        return z_price, z_oos, z_status, z_ev
                if attempt == 0:
                    await asyncio.sleep(0.6)
        return None, False, "BLOCKED_HTTP", "Accés bloquejat i sense resposta vàlida de Zyte API"

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
                    '.product-carousel', '.also-bought', '.alternatives', 'aside', 'footer', 'nav', 'header',
                    '[data-testid*="recommend"]', '[data-testid*="carousel"]', '[data-testid*="related"]',
                    '[class*="recommend"]', '[class*="related"]', '[class*="carousel"]', '[class*="slider"]',
                    '[class*="cross"]', '[class*="upsell"]', '[class*="similar"]', '[class*="other-products"]',
                    '[id*="related"]', '[id*="recommend"]', '[id*="carousel"]'
                ].join(', ');

                const selectors = [
                    '#js-precio', '#productPrice', '[data-testid="product-price"]',
                    '.product-detail-price', '.pdp-price', '.product-page-price',
                    '.price--main', '.price--withoutTax', '.product-price__price'
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

    # Hybrid Zyte Fallback: if Playwright hit anti-bot (403/429/503/Captcha), soft challenge redirect (IDENTITY_MISMATCH) or empty JS render and ZYTE_API_KEY is available
    if ZYTE_API_KEY and status_code in ("BLOCKED_HTTP", "BLOCKED_CAPTCHA", "HTTP_ERROR", "NO_VALID_PRICE", "IDENTITY_MISMATCH", "ERROR"):
        url_cands = get_canonical_url_candidates(url, country)
        for cand_u in url_cands:
            for attempt in range(2):
                z_info = await fetch_via_zyte(page, cand_u, country)
                if z_info:
                    r_copy = dict(row)
                    r_copy["url"] = cand_u
                    z_price, z_oos, z_status, z_ev = evaluate_page_info_candidates(z_info, r_copy, source_prefix="[Zyte] ")
                    if z_status in ("VERIFIED", "OUT_OF_STOCK"):
                        if cand_u != url:
                            row["url"] = cand_u
                        return z_price, z_oos, z_status, z_ev
                if attempt == 0:
                    await asyncio.sleep(0.6)

    return None, False, status_code, evidence_str

def save_all_state(tracking, history):
    """Atomically persists tracking.json, history.json, and embedded index.html data so progress is never lost on timeout."""
    history.sort(key=lambda x: (str(x.get("timestamp", "")), str(x.get("run_slot", "")), x.get("country", ""), x.get("operator", ""), x.get("code", "")))
    with open("data/tracking.json", "w", encoding="utf-8") as f:
        json.dump(tracking, f, indent=2, ensure_ascii=False)
    with open("data/history.json", "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2, ensure_ascii=False)

    valid_history = [h for h in history if h.get("audit_status", "VALID") == "VALID" and h.get("price") is not None and float(h.get("disc_pct", 0)) <= 50.0]
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

    with open("index.html", "r", encoding="utf-8") as f:
        html_doc = f.read()

    html_doc = re.sub(r"(?:const|let) DATA_ROWS = \[.*?\];", lambda _: "let DATA_ROWS = " + json.dumps(tracking, ensure_ascii=False) + ";", html_doc, flags=re.S)
    html_doc = re.sub(r"(?:const|let) HISTORY_COMPACT = \[.*?\];", lambda _: "let HISTORY_COMPACT = " + json.dumps(history_compact, ensure_ascii=False) + ";", html_doc, flags=re.S)
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html_doc)

async def main():
    with open("data/tracking.json", "r", encoding="utf-8") as f:
        tracking = json.load(f)
    with open("data/history.json", "r", encoding="utf-8") as f:
        history = json.load(f)

    # Auto-reconcile tracking.json from history.json before scanning:
    # ensures that if history.json has a more recent valid reading (or a lower valid price on the same latest date),
    # tracking.json never regresses to an older date.
    latest_hist_by_key = {}
    for h in history:
        if h.get("audit_status", "VALID") != "VALID":
            continue
        p_val = h.get("price")
        d_pct = h.get("disc_pct")
        if p_val is None or float(p_val) <= 0 or (d_pct is not None and float(d_pct) > 50.0):
            continue
        if "advance-plus" in str(h.get("url", "")).lower():
            continue
        d_str = str(h.get("timestamp", ""))[:10]
        if not d_str:
            continue
        k = (h.get("country"), h.get("operator"), h.get("code"))
        cur = latest_hist_by_key.get(k)
        if not cur or d_str > cur["date"] or (d_str == cur["date"] and float(p_val) < cur["price"]):
            latest_hist_by_key[k] = {
                "date": d_str,
                "price": float(p_val),
                "out_of_stock": bool(h.get("out_of_stock", False)),
                "evidence": h.get("evidence") or ""
            }

    for row in tracking:
        if row.get("id") == "UK-DEP-WS21WADV101":
            continue
        k = (row.get("country"), row.get("operator"), row.get("code"))
        best_h = latest_hist_by_key.get(k)
        if best_h and row.get("url") and not is_generic_category_url(row.get("url", "")):
            r_date = str(row.get("last_read") or "").strip()
            r_price = row.get("price")
            if row.get("status") != "VERIFIED" or best_h["date"] > r_date or (best_h["date"] == r_date and (r_price is None or best_h["price"] < float(r_price))):
                row["price"] = round(best_h["price"], 2)
                row["disc_imp"] = round(float(row["pvp"]) - row["price"], 2)
                row["disc_pct"] = round((row["disc_imp"] / float(row["pvp"])) * 100, 1)
                row["status"] = "VERIFIED"
                row["last_read"] = best_h["date"]
                row["out_of_stock"] = best_h["out_of_stock"]
                if best_h["evidence"]:
                    row["evidence"] = best_h["evidence"]

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

        updated_count = 0
        zyte_rescued_count = 0
        quarantined_count = 0
        circuit_skipped = 0

        # PHASE 1 (Priority): Price Verification on all mapped PDPs first (clean session, zero rate-limit saturation)
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

            if status_code in ("BLOCKED_HTTP", "BLOCKED_CAPTCHA", "NO_VALID_PRICE"):
                domain_blocks[dom] = domain_blocks.get(dom, 0) + 1

            if status_code == "VERIFIED" and min_price is not None and min_price > 0:
                if "[Zyte]" in evidence_str:
                    zyte_rescued_count += 1
                    domain_blocks[dom] = domain_blocks.get(dom, 0) + 1
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

                if existing_same_day and existing_same_day.get("price") is not None and float(existing_same_day["price"]) >= (row["pvp"] * 0.50):
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

        # Checkpoint all Phase 1 PDP price readings to disk immediately before starting Phase 2 Auto-Discovery
        save_all_state(tracking, history)

        # PHASE 2: Auto-Discovery of remaining unmapped PDP URLs (runs after mapped PDPs are safely read)
        discovered_count = await discover_missing_pdps(page_es, page_uk, tracking, today_str)
        if discovered_count > 0:
            for row in tracking:
                if row.get("status") == "PENDING_URL" and row.get("url") and f"({today_str})" in str(row.get("evidence", "")):
                    dom = get_domain(row["url"])
                    page = page_uk if row["country"] == "UK" else page_es
                    min_price, is_oos, status_code, evidence_str = await extract_verified_pdp_price(
                        page, row, force_zyte_only=(domain_blocks.get(dom, 0) >= CIRCUIT_BREAKER_LIMIT)
                    )
                    if status_code == "VERIFIED" and min_price is not None and min_price > 0:
                        if "[Zyte]" in evidence_str:
                            zyte_rescued_count += 1
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
                            "price": min_price,
                            "disc_imp": row["disc_imp"],
                            "disc_pct": row["disc_pct"],
                            "out_of_stock": bool(is_oos),
                            "is_from": False,
                            "url": row["url"],
                            "audit_status": "VALID",
                            "evidence": evidence_str
                        })

        await browser.close()

    save_all_state(tracking, history)

    print(f"Scan finished ({now_iso}). Auto-discovered PDPs: {discovered_count} | Live today: {updated_count} (Zyte rescued: {zyte_rescued_count}) | Quarantined: {quarantined_count} | Circuit-breaker skipped: {circuit_skipped} | Total history: {len(history)}")

if __name__ == "__main__":
    asyncio.run(main())
