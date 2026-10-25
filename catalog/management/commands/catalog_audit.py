from django.core.management.base import BaseCommand
from django.db.models import Count
from catalog.brand_registry import BRAND_GROUPS
from catalog.models import Brand, Category, DiscoveryCheckpoint, ImportLog, Product, NutrientValue
from catalog.services import completeness

class Command(BaseCommand):
    help = "Report catalogue, brand/category coverage, nutrition completeness and import outcomes from the database."

    def add_arguments(self, parser): parser.add_argument("--country", default="India", help="Discovery country whose last successful group runs to show.")

    def safe(self, value):
        encoding = getattr(self.stdout._out, "encoding", None) or "ascii"
        return str(value).encode(encoding, errors="backslashreplace").decode(encoding, errors="strict")

    def handle(self, *args, **opts):
        total = Product.objects.count()
        barcodes = Product.objects.exclude(barcode__isnull=True).exclude(barcode="").values("barcode").distinct().count()
        brands = Brand.objects.annotate(products_count=Count("products", distinct=True)).filter(products_count__gt=0)
        categories = Category.objects.annotate(products_count=Count("products", distinct=True)).filter(products_count__gt=0)
        with_nutrition = Product.objects.filter(nutrient_values__status="available").distinct().count()
        nutrition_complete = sum(completeness(product) >= 75 for product in Product.objects.all())
        logs = dict(ImportLog.objects.values_list("status").annotate(total=Count("id")))
        self.stdout.write(self.style.MIGRATE_HEADING("LabelLens catalogue audit"))
        self.stdout.write(f"Unique products: {total} (unique barcodes: {barcodes})")
        self.stdout.write(f"Distinct linked brands: {brands.count()} | categories: {categories.count()}")
        self.stdout.write(f"Products with at least one usable nutrient: {with_nutrition}")
        self.stdout.write(f"Products with 75 percent or more of key nutrition fields: {nutrition_complete}; missing at least one key field: {total - nutrition_complete}")
        self.stdout.write(f"With images: {Product.objects.exclude(image_url='').count()} | ingredients: {Product.objects.exclude(ingredients_text='').count()} | barcodes: {barcodes}")
        self.stdout.write("Import-log outcomes: " + (", ".join(f"{key}={value}" for key, value in sorted(logs.items())) or "none"))

        checkpoint_by_key = {item.key: item for item in DiscoveryCheckpoint.objects.filter(country__iexact=opts["country"])}
        self.stdout.write("\nPriority brand coverage (product count; last group discovery):")
        brand_groups = {}
        for group in BRAND_GROUPS:
            checkpoint = checkpoint_by_key.get(f"off:{opts['country'].casefold()}:{group['key']}")
            stamp = checkpoint.last_successful_at.strftime("%Y-%m-%d %H:%M UTC") if checkpoint and checkpoint.last_successful_at else "not discovered"
            for brand in group["brands"]:
                brand_groups.setdefault(brand, []).append(stamp)
        for brand in sorted(brand_groups, key=str.casefold):
            count = Brand.objects.filter(name__iexact=brand).aggregate(n=Count("products", distinct=True))["n"] or 0
            stamps = [stamp for stamp in brand_groups[brand] if stamp != "not discovered"]
            stamp = max(stamps) if stamps else "not discovered"
            self.stdout.write(self.safe(f"  {brand}: {count}; {stamp}"))

        low_brands = [(brand.name, brand.products_count) for brand in brands if brand.products_count < 3]
        low_categories = [(category.name, category.products_count) for category in categories if category.products_count < 3]
        self.stdout.write(f"\nBrands with fewer than 3 products: {len(low_brands)}")
        for name, count in sorted(low_brands): self.stdout.write(self.safe(f"  {name}: {count}"))
        self.stdout.write(f"Categories with fewer than 3 products: {len(low_categories)}")
        for name, count in sorted(low_categories): self.stdout.write(self.safe(f"  {name}: {count}"))
