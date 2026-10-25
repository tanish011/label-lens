from django.db.models import Q
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
from .models import Product
from integrations.openfoodfacts import search as off_search, import_product, import_search_result, OpenFoodFactsError
from recommendations.ranking import alternatives

def serialize(product):
    return {"barcode": product.barcode, "name": product.name, "brands": [b.name for b in product.brands.all()], "categories": [c.name for c in product.categories.all()], "image_url": product.image_url, "quantity": product.quantity, "serving_size": product.serving_size, "ingredients": product.ingredients_text, "allergens": product.allergens, "traces": product.traces, "labels": product.labels, "nutriscore": product.nutriscore, "nova_group": product.nova_group, "source": product.source, "source_url": product.source_url, "source_retrieved": product.source_retrieved, "nutrients": [{"code": n.nutrient.code, "name": n.nutrient.name, "value": str(n.value), "unit": n.unit, "basis": n.basis, "calculated": n.calculated} for n in product.nutrient_values.filter(status="available").select_related("nutrient")]}

@api_view(["GET"])
def search_api(request):
    query = request.query_params.get("q", "").strip()[:120]
    qs = Product.objects.all().prefetch_related("brands", "categories")
    if query: qs = qs.filter(Q(name__icontains=query) | Q(barcode__icontains=query) | Q(brands__name__icontains=query) | Q(categories__name__icontains=query)).distinct()
    try: page = max(1, min(int(request.query_params.get("page", "1")), 1000))
    except (ValueError, TypeError): return Response({"detail": "Page must be a positive integer."}, status=400)
    if query and not request.query_params.get("local"):
        try:
            response = off_search(query, page, 24)
            for row in response.get("products", []): import_search_result(row)
            qs = Product.objects.filter(Q(name__icontains=query) | Q(barcode__icontains=query) | Q(brands__name__icontains=query) | Q(categories__name__icontains=query)).distinct().prefetch_related("brands", "categories")
        except (OpenFoodFactsError, ValueError): pass
    start = (page - 1) * 24
    return Response({"count": qs.count(), "page": page, "results": [serialize(x) for x in qs[start:start+24]]})

@api_view(["GET"])
def detail_api(request, barcode):
    if not barcode.isdigit() or not 8 <= len(barcode) <= 32:
        return Response({"detail": "Enter a valid numeric product barcode."}, status=400)
    product = Product.objects.filter(barcode=barcode).first()
    if not product:
        try: product = import_product(barcode)
        except OpenFoodFactsError as exc: return Response({"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except ValueError as exc: return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
    if not product: return Response({"detail": "Product not found"}, status=404)
    return Response(serialize(product))

@api_view(["GET"])
def compare_api(request):
    codes = [c.strip() for c in request.query_params.get("codes", "").split(",")[:4] if c.strip()]
    products = list(Product.objects.filter(barcode__in=codes).prefetch_related("brands", "categories", "nutrient_values__nutrient"))
    values = {}
    for product in products:
        for nv in product.nutrient_values.filter(status="available"):
            values.setdefault(nv.nutrient.code, {}).setdefault(nv.basis, {})[product.barcode] = {"value": str(nv.value), "unit": nv.unit}
    differences = {code: {basis: rows for basis, rows in bases.items() if len(rows) > 1 and len({v["unit"] for v in rows.values()}) == 1} for code, bases in values.items()}
    return Response({"products": [serialize(p) for p in products], "comparable_nutrients": differences})

@api_view(["GET"])
def alternatives_api(request, barcode):
    product = Product.objects.filter(barcode=barcode).first()
    if not product: return Response({"detail": "Product not found"}, status=404)
    rows, explanation = alternatives(product, request.query_params.get("priority", "lower_sugar"))
    return Response({"explanation": explanation, "results": [{"product": serialize(p), "value": str(v), "difference": str(d)} for p, v, d in rows]})
