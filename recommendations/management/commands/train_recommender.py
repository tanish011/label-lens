from django.core.management.base import BaseCommand, CommandError
from catalog.models import Product
from recommendations.ml import train_artifact

class Command(BaseCommand):
    help = "Fit the explainable TF-IDF product-text similarity corpus from saved products."
    def handle(self, *args, **options):
        try: count = train_artifact(Product.objects.prefetch_related("brands", "categories").order_by("pk"))
        except ImportError: raise CommandError("Install the optional scikit-learn dependency to train the similarity model.")
        except ValueError as exc: raise CommandError(str(exc))
        self.stdout.write(self.style.SUCCESS(f"Built TF-IDF similarity corpus for {count} saved products."))
