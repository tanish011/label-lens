import re
import time
import hashlib
import unicodedata
import requests
from django.conf import settings
from django.core.cache import cache
from catalog.models import ImportLog
from catalog.services import save_off_product

FIELDS = "code,product_name,product_name_en,brands,categories,image_url,image_front_url,quantity,serving_size,ingredients_text,allergens,traces,labels,additives_tags,countries,nutriscore_grade,nutrition_grade_fr,nova_group,nutriments,last_modified_t"
class OpenFoodFactsError(Exception): pass

def _guard_rate(key, seconds):
    if not cache.add(f"off-rate-{key}", True, timeout=seconds):
        raise OpenFoodFactsError("Open Food Facts rate limit reached. Please try again shortly.")

def _get(path, params=None):
    for attempt in range(3):
        try:
            response = requests.get(settings.OFF_BASE_URL + path, params=params, headers={"User-Agent": settings.OFF_USER_AGENT}, timeout=settings.OFF_TIMEOUT_SECONDS)
            if response.status_code == 429 and attempt < 2:
                wait = response.headers.get("Retry-After", "6")
                try: delay = min(60, max(1, int(wait)))
                except (TypeError, ValueError): delay = 6
                time.sleep(delay)
                continue
            response.raise_for_status()
            return response.json()
        except requests.RequestException as exc:
            if attempt == 2: raise OpenFoodFactsError("Open Food Facts is temporarily unavailable. Please try again later.") from exc
            time.sleep(2 ** attempt)
        except ValueError as exc:
            raise OpenFoodFactsError("Open Food Facts returned an unreadable response.") from exc

def lookup(barcode, force_refresh=False):
    barcode = str(barcode).strip()
    if not barcode.isdigit() or not 8 <= len(barcode) <= 32:
        raise ValueError("Enter a valid numeric product barcode.")
    key = f"off-product-{barcode}"
    cached = None if force_refresh else cache.get(key)
    if cached: return cached
    _guard_rate("product", 4)
    payload = _get(f"/api/v3.6/product/{barcode}", {"fields": FIELDS})
    product = payload.get("product") if isinstance(payload, dict) else None
    if not product or payload.get("status") not in (1, "success", True): return None
    cache.set(key, product, 3600)
    return product

def search(query, page=1, page_size=24):
    key = f"off-search-{query.lower()}-{page}-{page_size}"
    cached = cache.get(key)
    if cached: return cached
    _guard_rate("search", 6.2)
    payload = _get("/cgi/search.pl", {"search_terms": query, "search_simple": 1, "action": "process", "json": 1, "page": page, "page_size": page_size, "fields": FIELDS})
    cache.set(key, payload, 600)
    return payload

def normalize_brand_tag(name):
    normalized = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii").casefold()
    return re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")

def structured_search(*, brands=None, category=None, country="India", page=1, page_size=25):
    """Search a bounded page using Open Food Facts v2 structured tag filters."""
    params = {"page": page, "page_size": page_size, "fields": FIELDS, "sort_by": "popularity_key"}
    if brands:
        tags = [normalize_brand_tag(value) for value in brands if value.strip()]
        if tags: params["brands_tags"] = "|".join(tags)
    if category: params["categories_tags"] = normalize_brand_tag(category)
    if country and country.casefold() not in {"all", "world", ""}:
        params["countries_tags_en"] = normalize_brand_tag(country)
    stable_query = "&".join(f"{key}={value}" for key, value in sorted(params.items()))
    cache_key = "off-structured-" + hashlib.sha256(stable_query.encode("utf-8")).hexdigest()
    cached = cache.get(cache_key)
    if cached: return cached
    _guard_rate("search", 6.2)
    payload = _get("/api/v2/search", params)
    cache.set(cache_key, payload, 900)
    return payload

def import_product(barcode):
    try:
        data = lookup(barcode)
        if not data: return None
        return save_off_product(data)
    except (OpenFoodFactsError, ValueError) as exc:
        ImportLog.objects.create(barcode=str(barcode)[:32], status="failed", detail=str(exc)[:500])
        raise

def refresh_product(barcode):
    try:
        data = lookup(barcode, force_refresh=True)
        if not data: return None
        return save_off_product(data)
    except (OpenFoodFactsError, ValueError) as exc:
        ImportLog.objects.create(barcode=str(barcode)[:32], status="failed", detail=str(exc)[:500])
        raise

def import_search_result(data):
    try: return save_off_product(data)
    except ValueError as exc:
        ImportLog.objects.create(barcode=str(data.get("code", ""))[:32], status="rejected", detail=str(exc)[:500])
        return None
