from catalog.models import NutrientValue
from django.db.models import Prefetch

PRIORITIES = {"lower_sugar": "sugars", "lower_salt": "salt", "lower_sat_fat": "saturated-fat", "higher_protein": "proteins", "higher_fiber": "fiber"}
def alternatives(product, priority="lower_sugar", limit=6):
    code = PRIORITIES.get(priority)
    if not code: return [], "Choose a supported nutrition priority."
    baseline = product.nutrient_values.filter(nutrient__code=code, basis__in=["100g", "100ml"], status="available").first()
    if not baseline: return [], "This product does not have a comparable value for that nutrient."
    qs = NutrientValue.objects.filter(nutrient__code=code, basis=baseline.basis, status="available", product__categories__in=product.categories.all()).exclude(product=product).select_related("product").prefetch_related("product__brands", "product__categories").distinct()
    lower = priority not in ("higher_protein", "higher_fiber")
    rows = []
    for item in qs:
        if (lower and item.value >= baseline.value) or (not lower and item.value <= baseline.value): continue
        rows.append((item.product, item.value, abs(baseline.value - item.value)))
    # Optional TF-IDF similarity contributes a small, explainable relevance signal.
    # The nutrient requirement remains a hard filter; without sklearn we rank by the
    # deterministic nutrient/category rule above.
    from .ml import text_similarities
    candidates = [row[0] for row in rows]
    similarities = text_similarities(product, candidates) if candidates else []
    if similarities is not None:
        rows = [(p, value, diff, similarities[i]) for i, (p, value, diff) in enumerate(rows)]
        rows.sort(key=lambda row: (row[1] if lower else -row[1], -row[3]))
        rows = [(p, value, diff) for p, value, diff, _score in rows]
    else:
        rows.sort(key=lambda row: row[1] if lower else -row[1])
    return rows[:limit], f"Compared {code.replace('-', ' ')} per {baseline.basis}; only source values on the same measurement basis are ranked."
