from django.core.management.base import BaseCommand, CommandError
from integrations.openfoodfacts import import_product, OpenFoodFactsError

class Command(BaseCommand):
    help = "Import or refresh a product by its Open Food Facts barcode."
    def add_arguments(self, parser): parser.add_argument("barcode")
    def handle(self, *args, **options):
        try: product = import_product(options["barcode"])
        except OpenFoodFactsError as exc: raise CommandError(str(exc))
        if not product: raise CommandError("No product record was returned for that barcode.")
        self.stdout.write(self.style.SUCCESS(f"Saved {product.name} ({product.barcode}) from Open Food Facts."))
