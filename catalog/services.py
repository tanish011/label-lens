from decimal import Decimal, InvalidOperation
from django.db import transaction
from django.utils import timezone
from .models import Product, Brand, Category, Nutrient, NutrientValue, ImportLog

NUTRIENTS = {"energy-kj": ("Energy", "kJ"), "energy-kcal": ("Energy", "kcal"), "fat": ("Total fat", "g"), "saturated-fat": ("Saturated fat", "g"), "trans-fat": ("Trans fat", "g"), "carbohydrates": ("Carbohydrates", "g"), "sugars": ("Sugars", "g"), "added-sugars": ("Added sugars", "g"), "fiber": ("Fiber", "g"), "proteins": ("Protein", "g"), "salt": ("Salt", "g"), "sodium": ("Sodium", "g"), "cholesterol": ("Cholesterol", "mg")}
def parse_decimal(value):
    try:
        number = Decimal(str(value))
        return number if number.is_finite() and 0 <= number <= Decimal("1000000") else None
    except (InvalidOperation, TypeError, ValueError): return None

def nutrient_values(raw, basis):
    result = []
    for code, (name, unit) in NUTRIENTS.items():
        val = parse_decimal(raw.get(f"{code}_{basis}"))
        if val is not None: result.append((code, name, val, raw.get(f"{code}_unit", unit) or unit))
    # Preserve additional source nutrients without requiring a schema migration.
    suffix = f"_{basis}"
    for key, source_value in raw.items():
        if not key.endswith(suffix): continue
        code = key[:-len(suffix)]
        if code in NUTRIENTS: continue
        val = parse_decimal(source_value)
        unit = str(raw.get(f"{code}_unit") or "").strip()
        if val is None or not unit: continue
        result.append((code[:80], code.replace("-", " ").replace("_", " ").title()[:100], val, unit[:24]))
    return result

@transaction.atomic
def save_off_product(data):
    code = str(data.get("code") or "").strip()
    if not code.isdigit() or not 8 <= len(code) <= 32: raise ValueError("A valid numeric source barcode is required")
    name = (data.get("product_name") or data.get("product_name_en") or "").strip()
    if not name: raise ValueError("Source product has no product name")
    product, created = Product.objects.get_or_create(barcode=code)
    product.name = name[:300]
    for field, source in [("image_url", "image_front_url"), ("quantity", "quantity"), ("serving_size", "serving_size"), ("ingredients_text", "ingredients_text"), ("allergens", "allergens"), ("traces", "traces"), ("labels", "labels"), ("additives", "additives_tags"), ("countries", "countries")]:
        product_value = data.get(source, "")
        if isinstance(product_value, str) and product_value.strip(): setattr(product, field, product_value[:1000])
    if not product.image_url and data.get("image_url"): product.image_url = data["image_url"]
    score = data.get("nutriscore_grade") or data.get("nutrition_grade_fr")
    if score and str(score).lower() in {"a", "b", "c", "d", "e"}: product.nutriscore = str(score).lower()
    try: product.nova_group = int(data.get("nova_group")) if data.get("nova_group") else product.nova_group
    except (ValueError, TypeError): product.nova_group = None
    if product.nova_group not in (1, 2, 3, 4): product.nova_group = None
    product.source_url = f"https://world.openfoodfacts.org/product/{code}"
    product.source = "Open Food Facts"
    product.source_retrieved = timezone.now()
    modified = data.get("last_modified_t")
    if modified:
        from datetime import datetime, timezone as dt_timezone
        try: product.source_modified = datetime.fromtimestamp(int(modified), tz=dt_timezone.utc)
        except (ValueError, TypeError, OSError): pass
    product.validation_status = "source_data"
    product.save()
    brands = [b.strip() for b in (data.get("brands") or "").split(",") if b.strip()][:8]
    if brands:
        product.brands.clear()
        for brand in brands: product.brands.add(Brand.objects.get_or_create(name=brand[:180])[0])
    categories = [c.strip() for c in (data.get("categories") or "").split(",") if c.strip()][:12]
    if categories:
        product.categories.clear()
        for category in categories: product.categories.add(Category.objects.get_or_create(name=category[:180])[0])
    raw = data.get("nutriments") or {}
    parsed = [("100g", row) for row in nutrient_values(raw, "100g")] + [("100ml", row) for row in nutrient_values(raw, "100ml")]
    for basis, (code, label, value, unit) in parsed:
        nutrient, _ = Nutrient.objects.get_or_create(code=code, defaults={"name": label, "display_unit": unit})
        NutrientValue.objects.update_or_create(product=product, nutrient=nutrient, basis=basis, defaults={"value": value, "unit": unit, "provenance": "Open Food Facts", "status": "available", "calculated": False})
    ImportLog.objects.create(barcode=code, status="updated" if not created else "imported", detail="Product stored from Open Food Facts")
    return product

def completeness(product):
    code_groups = [["energy-kcal", "energy-kj"], ["fat"], ["saturated-fat"], ["carbohydrates"], ["sugars"], ["fiber"], ["proteins"], ["salt"]]
    found = set(product.nutrient_values.filter(status="available").values_list("nutrient__code", flat=True))
    present = sum(bool(found.intersection(group)) for group in code_groups)
    return int(100 * present / len(code_groups) + 0.5)

def serving_amount(product):
    import re
    match = re.search(r"([0-9]+(?:[.,][0-9]+)?)\s*(g|ml)\b", product.serving_size or "", re.I)
    if not match: return None
    return parse_decimal(match.group(1).replace(",", ".")), match.group(2).lower()

def per_serving(value, product, basis="100g"):
    size = serving_amount(product)
    if not size: return None
    amount, unit = size
    if (basis == "100g" and unit != "g") or (basis == "100ml" and unit != "ml"):
        return None
    if basis not in ("100g", "100ml"):
        return None
    return (value * amount / Decimal(100)).quantize(Decimal("0.01")), unit
