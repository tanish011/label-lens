from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.core.paginator import Paginator
from django.db.models import Q, Count, Avg, Prefetch, Case, When, Value, IntegerField
from django.db.models.query import prefetch_related_objects
from decimal import Decimal, InvalidOperation
from math import ceil
import re
from django.shortcuts import get_object_or_404, redirect, render
from .models import Product, Brand, Category, NutrientValue, ImportLog
from .services import completeness, per_serving
from integrations.openfoodfacts import search as off_search, structured_search, import_product, import_search_result, OpenFoodFactsError
from recommendations.ranking import alternatives

CARD_NUTRIENT_PRIORITY = {"sugars": 0, "energy-kcal": 1, "proteins": 2, "salt": 3, "fat": 4, "carbohydrates": 5}

def prepare_product_cards(products):
    products = list(products)
    if products:
        prefetch_related_objects(products, "brands", "categories", Prefetch("nutrient_values", queryset=NutrientValue.objects.filter(status="available").select_related("nutrient").order_by("nutrient__order", "basis")))
    for product in products:
        values = [value for value in product.nutrient_values.all() if value.basis in {"100g", "100ml"}]
        product.card_nutrient = min(values, key=lambda value: (CARD_NUTRIENT_PRIORITY.get(value.nutrient.code, 99), value.nutrient.order, value.basis), default=None)
    return products

def rank_product_cards(products):
    def key(product):
        values = list(product.nutrient_values.all())
        reported_codes = {value.nutrient.code for value in values if value.basis in {"100g", "100ml"}}
        return (-len(reported_codes), -bool(product.nutriscore), -bool(product.image_url), -bool(product.ingredients_text), product.name.casefold())
    return sorted(products, key=key)

def order_by_data_quality(queryset):
    return queryset.annotate(
        coverage_count=Count("nutrient_values__nutrient", filter=Q(nutrient_values__status="available", nutrient_values__nutrient__code__in=["energy-kcal", "energy-kj", "fat", "saturated-fat", "carbohydrates", "sugars", "fiber", "proteins", "salt"]), distinct=True),
        score_rank=Case(When(nutriscore__in=["a", "b", "c", "d", "e"], then=Value(1)), default=Value(0), output_field=IntegerField()),
        image_rank=Case(When(image_url__gt="", then=Value(1)), default=Value(0), output_field=IntegerField()),
        ingredient_rank=Case(When(ingredients_text__gt="", then=Value(1)), default=Value(0), output_field=IntegerField()),
    ).order_by("-coverage_count", "-score_rank", "-image_rank", "-ingredient_rank", "name")

def visible_categories(limit=None):
    categories, seen = [], set()
    candidates = Category.objects.annotate(product_count=Count("products", distinct=True)).filter(product_count__gt=0).order_by("-product_count", "name")
    for category in candidates:
        name, normalized = category.name.strip(), category.name.strip().casefold()
        if len(name) < 3 or re.fullmatch(r"[\d\s.,/%-]+", name) or normalized in seen:
            continue
        seen.add(normalized); categories.append(category)
        if limit and len(categories) >= limit:
            break
    return categories

def visible_brands():
    brands, seen = [], set()
    candidates = Brand.objects.annotate(product_count=Count("products", distinct=True)).filter(product_count__gt=0).order_by("-product_count", "name")
    for brand in candidates:
        normalized = brand.name.strip().casefold()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized); brands.append(brand)
    return brands

def home(request):
    products = prepare_product_cards(order_by_data_quality(Product.objects.all())[:4])
    return render(request, "catalog/home.html", {"products": products, "categories": visible_categories(limit=10)})

class ExternalPaginator:
    def __init__(self, count, per_page):
        self.count = count
        self.per_page = per_page
        self.num_pages = max(1, ceil(count / per_page))

class ExternalPage:
    def __init__(self, products, count, number, per_page):
        self.object_list = products
        self.paginator = ExternalPaginator(count, per_page)
        self.number = number
    def has_previous(self): return self.number > 1
    def has_next(self): return self.number < self.paginator.num_pages
    def previous_page_number(self): return max(1, self.number - 1)
    def next_page_number(self): return min(self.paginator.num_pages, self.number + 1)

def discover(request):
    query = request.GET.get("q", "").strip()[:120]
    page = request.GET.get("page", "1")
    qs = Product.objects.all().prefetch_related("brands", "categories")
    if query:
        qs = qs.filter(Q(name__icontains=query) | Q(barcode__icontains=query) | Q(brands__name__icontains=query) | Q(categories__name__icontains=query)).distinct()
    brand = request.GET.get("brand", "").strip()[:100]
    category = request.GET.get("category", "").strip()[:120]
    if brand: qs = qs.filter(brands__name__icontains=brand)
    if category: qs = qs.filter(categories__name__icontains=category)
    nutrient_filters = {"energy": "energy-kcal", "sugar": "sugars", "sat_fat": "saturated-fat", "salt": "salt", "protein": "proteins", "fiber": "fiber"}
    basis = request.GET.get("basis", "100g")
    if basis not in ("100g", "100ml"): basis = "100g"
    error = ""
    for key, code in nutrient_filters.items():
        for bound, operation in (("max", "lte"), ("min", "gte")):
            raw = request.GET.get(f"{bound}_{key}", "").strip()
            if not raw: continue
            try:
                limit = Decimal(raw)
                if not limit.is_finite() or limit < 0 or limit > 1000000: raise InvalidOperation
            except (InvalidOperation, ValueError):
                error = "A nutrition filter value was invalid and has been ignored."
                continue
            qs = qs.filter(**{f"nutrient_values__nutrient__code": code, "nutrient_values__basis": basis, "nutrient_values__status": "available", f"nutrient_values__value__{operation}": limit})
    if request.GET.get("allergens") == "declared": qs = qs.exclude(allergens="")
    if request.GET.get("label", "").strip(): qs = qs.filter(labels__icontains=request.GET["label"].strip()[:100])
    try:
        min_complete = int(request.GET.get("completeness", "0"))
        if min_complete:
            min_complete = max(0, min(100, min_complete))
            count_needed = ceil(min_complete * 8 / 100)
            qs = qs.annotate(key_nutrients=Count("nutrient_values__nutrient", filter=Q(nutrient_values__basis=basis, nutrient_values__status="available", nutrient_values__nutrient__code__in=["energy-kcal", "fat", "saturated-fat", "carbohydrates", "sugars", "fiber", "proteins", "salt"]), distinct=True)).filter(key_nutrients__gte=count_needed)
    except (ValueError, TypeError): error = "Nutrition completeness must be a number from 0 to 100."
    ordering = request.GET.get("sort", "coverage")
    if ordering == "recent": qs = qs.order_by("-updated_at", "name")
    elif ordering == "name": qs = qs.order_by("name")
    else: qs = order_by_data_quality(qs)
    paginator = Paginator(qs, 18)
    local_page = paginator.get_page(page)
    used_external = False
    external_page = max(1, min(local_page.number, 1000))
    active_filters = bool(request.GET.get("allergens") or request.GET.get("label") or min_complete)
    active_filters = active_filters or any(request.GET.get(f"{bound}_{key}") for key in nutrient_filters for bound in ("max", "min"))
    if query and (brand or category): active_filters = True
    local_has_full_page = len(local_page.object_list) >= 18
    if (query or brand or category) and not request.GET.get("local") and not active_filters and not local_has_full_page:
        try:
            if query:
                data = off_search(query, external_page, 18)
            else:
                data = structured_search(brands=[brand] if brand else None, category=category or None, page=external_page, page_size=18)
            external_products = []
            for item in data.get("products", []):
                product = import_search_result(item)
                if product: external_products.append(product)
            if external_products:
                try: external_count = max(0, int(data.get("count") or 0))
                except (ValueError, TypeError): external_count = len(external_products)
                local_page = ExternalPage(external_products, external_count, external_page, 18)
                used_external = True
        except (OpenFoodFactsError, ValueError): error = "The external catalogue is unavailable. Showing any matching products stored locally."
    local_page.object_list = prepare_product_cards(local_page.object_list)
    if used_external:
        local_page.object_list = rank_product_cards(local_page.object_list)
    pagination_params = request.GET.copy(); pagination_params.pop("page", None)
    return render(request, "catalog/discover.html", {"page_obj": local_page, "query": query, "categories": visible_categories(), "brands": visible_brands(), "error": error, "brand": brand, "category": category, "pagination_query": pagination_params.urlencode()})

def product_detail(request, barcode):
    if not barcode.isdigit() or not 8 <= len(barcode) <= 32:
        return render(request, "catalog/not_found.html", {"barcode": barcode, "error": "Enter a valid numeric product barcode."}, status=400)
    product = Product.objects.filter(barcode=barcode).prefetch_related("brands", "categories", "nutrient_values__nutrient").first()
    error = ""
    if not product:
        try: product = import_product(barcode)
        except OpenFoodFactsError as exc: error = str(exc)
        except ValueError: error = "The source did not provide a valid product record."
    if not product: return render(request, "catalog/not_found.html", {"barcode": barcode, "error": error}, status=404)
    vals = product.nutrient_values.filter(status="available").select_related("nutrient").order_by("nutrient__order", "nutrient__name")
    nutrition = []
    for value in vals:
        serving = per_serving(value.value, product, value.basis)
        nutrition.append({"row": value, "serving": serving})
    macros = [value for value in vals if value.nutrient.code in {"fat", "carbohydrates", "sugars", "fiber", "proteins"} and value.unit == "g"]
    chart_basis = "100g" if any(value.basis == "100g" for value in macros) else "100ml"
    chart_values = [value for value in macros if value.basis == chart_basis]
    chart_data = {"labels": [value.nutrient.name for value in chart_values], "values": [float(value.value) for value in chart_values], "basis": chart_basis} if chart_values else None
    recs, explanation = alternatives(product)
    baseline = product.nutrient_values.filter(nutrient__code="sugars", basis__in=["100g", "100ml"], status="available").first()
    recommendations_display = [(p, value, difference, baseline.basis) for p, value, difference in recs] if baseline else []
    return render(request, "catalog/detail.html", {"product": product, "nutrition": nutrition, "completeness": completeness(product), "recommendations": recs, "recommendations_display": recommendations_display, "recommendation_explanation": explanation, "chart_data": chart_data, "chart_basis": chart_basis})

def compare(request):
    codes = [x for x in (request.GET.get("a", ""), request.GET.get("b", "")) if x.strip()]
    if not codes:
        codes = [x for x in request.GET.get("codes", "").split(",")[:4] if x.strip()]
    found_products = Product.objects.filter(barcode__in=codes).prefetch_related("brands", "categories", "nutrient_values__nutrient")
    products_by_code = {product.barcode: product for product in found_products}
    products = [products_by_code[code] for code in codes if code in products_by_code]
    available_products = order_by_data_quality(Product.objects.exclude(barcode__isnull=True).exclude(barcode="").prefetch_related("brands", "categories"))
    grouped = {}
    for product in products:
        for value in product.nutrient_values.filter(status="available").select_related("nutrient"):
            key = (value.nutrient.order, value.nutrient.name, value.nutrient.code, value.basis, value.unit)
            grouped.setdefault(key, {})[product.pk] = value.value
    compare_rows = []
    nutrition_matrix = []
    for (_order, name, _code, basis, unit), values_by_product in sorted(grouped.items()):
        reported_values = list(values_by_product.values())
        nutrition_matrix.append({"name": name, "basis": basis, "unit": unit, "values": [{"value": values_by_product.get(product.pk), "reported": product.pk in values_by_product} for product in products]})
        if len(reported_values) >= 2:
            compare_rows.append({"name": name, "basis": basis, "unit": unit, "spread": max(reported_values) - min(reported_values), "count": len(reported_values)})
    selected_by_code = {product.barcode: product for product in products}
    chooser_products = []
    comparison_categories = visible_categories(limit=30)
    comparison_category_ids = {category.pk for category in comparison_categories}
    category_labels = {category.pk: category.name for category in comparison_categories}
    category_rank = {category.pk: index for index, category in enumerate(comparison_categories)}
    chooser_labels = {}
    selected_category = request.GET.get("category", "")
    if selected_category not in {str(category.pk) for category in comparison_categories}:
        selected_category = ""
    for product in available_products:
        if re.fullmatch(r"\d{8,32}", product.name.strip()):
            continue
        brand = ", ".join(item.name for item in product.brands.all()) or "Brand not provided"
        product_category_ids = [category.pk for category in product.categories.all() if category.pk in comparison_category_ids]
        if selected_category and int(selected_category) not in product_category_ids:
            continue
        primary_category_id = min(product_category_ids, key=lambda category_id: category_rank[category_id]) if product_category_ids else None
        category_name = category_labels.get(primary_category_id, "Other foods")
        detail = product.quantity or product.countries
        descriptor = f" · {category_name}" + (f" · {detail}" if detail else "")
        label, brand_label = f"{product.name} — {brand}{descriptor}", f"{brand} — {product.name}{descriptor}"
        chooser_labels[product.barcode] = label
        chooser_products.append({"barcode": product.barcode, "name": product.name, "brand": brand, "label": label, "brand_label": brand_label, "categories": "|".join(str(category_id) for category_id in product_category_ids)})
    if "a" in request.GET or "b" in request.GET:
        selected_a, selected_b = selected_by_code.get(request.GET.get("a", "")), selected_by_code.get(request.GET.get("b", ""))
    else:
        selected_a, selected_b = (products[0] if products else None), (products[1] if len(products) > 1 else None)
    category_options = [{"value": str(category.pk), "name": category.name} for category in comparison_categories]
    return render(request, "catalog/compare.html", {"products": products, "codes": ",".join(codes), "compare_rows": compare_rows, "nutrition_matrix": nutrition_matrix, "comparison_ready": len(products) >= 2, "chooser_products": chooser_products, "comparison_categories": category_options, "comparison_category": selected_category, "selected_a": selected_a, "selected_b": selected_b, "selected_a_label": chooser_labels.get(selected_a.barcode, "") if selected_a else "", "selected_b_label": chooser_labels.get(selected_b.barcode, "") if selected_b else ""})

def dashboard(request):
    insights = []
    for category in Category.objects.annotate(product_count=Count("products", distinct=True)).filter(product_count__gte=3).order_by("name")[:12]:
        stats = NutrientValue.objects.filter(product__categories=category, nutrient__code="sugars", basis="100g", status="available").aggregate(average=Avg("value"), products=Count("product", distinct=True))
        if stats["products"] >= 3 and stats["average"] is not None:
            insights.append({"name": category.name, "average": float(stats["average"]), "products": stats["products"]})
    count = Product.objects.count()
    with_nutrition = Product.objects.filter(nutrient_values__status="available").distinct().count()
    recent = prepare_product_cards(order_by_data_quality(Product.objects.all())[:8])
    return render(request, "catalog/dashboard.html", {"count": count, "brands_count": Brand.objects.filter(products__isnull=False).distinct().count(), "categories_count": Category.objects.filter(products__isnull=False).distinct().count(), "with_nutrition": with_nutrition, "nutrition_percent": round(with_nutrition * 100 / count) if count else 0, "recent": recent, "imports": ImportLog.objects.order_by("-created_at")[:5], "insights": insights})

def about(request):
    total = Product.objects.count()
    nutrition = Product.objects.filter(nutrient_values__status="available").distinct().count()
    return render(request, "catalog/about.html", {"total": total, "nutrition": nutrition, "brands": Brand.objects.filter(products__isnull=False).distinct().count(), "categories": Category.objects.filter(products__isnull=False).distinct().count()})

def login_view(request):
    form = AuthenticationForm(request, data=request.POST or None)
    if request.method == "POST" and form.is_valid():
        login(request, form.get_user()); return redirect("dashboard")
    return render(request, "catalog/auth.html", {"form": form, "title": "Welcome back", "button": "Sign in"})

def logout_view(request):
    if request.method == "POST": logout(request)
    return redirect("home")

def register(request):
    form = UserCreationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save(); login(request, user); return redirect("dashboard")
    return render(request, "catalog/auth.html", {"form": form, "title": "Create your account", "button": "Create account"})
