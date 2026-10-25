import time
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Count, Q
from django.utils import timezone
from catalog.models import DiscoveryCheckpoint, ImportLog, Product
from catalog.services import completeness, nutrient_values
from integrations.openfoodfacts import lookup, refresh_product, OpenFoodFactsError

class Command(BaseCommand):
    help = "Refresh incomplete local products from their own Open Food Facts barcode records without filling missing values with guesses."
    KEY = "enrichment:open-food-facts"

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=25)
        parser.add_argument("--min-completeness", type=int, default=100)
        parser.add_argument("--sleep", type=float, default=4.2)
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--restart", action="store_true")
        parser.add_argument("--only-empty-nutrition", action="store_true", help="Prioritize records with no usable nutrition values at all.")

    def handle(self, *args, **opts):
        if opts["limit"] < 0: raise CommandError("--limit must be zero or greater.")
        if not 0 <= opts["min_completeness"] <= 100: raise CommandError("--min-completeness must be from 0 to 100.")
        delay = max(4.1, opts["sleep"])
        checkpoint_key = f"{self.KEY}:empty" if opts["only_empty_nutrition"] else self.KEY
        checkpoint = None if opts["dry_run"] else DiscoveryCheckpoint.objects.filter(key=checkpoint_key).first()
        base_checkpoint = DiscoveryCheckpoint.objects.filter(key=self.KEY).first() if opts["only_empty_nutrition"] else None
        if opts["restart"]:
            cursor = 0
        elif checkpoint:
            cursor = checkpoint.cursor
        else:
            cursor = base_checkpoint.cursor if base_checkpoint else 0
        qs = Product.objects.filter(pk__gt=cursor).exclude(barcode__isnull=True).exclude(barcode="").order_by("pk")
        if opts["only_empty_nutrition"]:
            qs = qs.annotate(available_nutrient_count=Count("nutrient_values__nutrient", filter=Q(nutrient_values__status="available"), distinct=True)).filter(available_nutrient_count=0)
        candidates = [product for product in qs if completeness(product) < opts["min_completeness"]][:opts["limit"]]
        if not candidates:
            self.stdout.write("No products below the requested nutrition completeness threshold.")
            if not opts["dry_run"]:
                job, _ = DiscoveryCheckpoint.objects.get_or_create(key=checkpoint_key, defaults={"group_name": "Nutrition enrichment (empty records)" if opts["only_empty_nutrition"] else "Nutrition enrichment"})
                job.completed = True; job.save(update_fields=["completed", "updated_at"])
            return
        if opts["restart"] and checkpoint and not opts["dry_run"]:
            checkpoint.cursor = 0; checkpoint.completed = False; checkpoint.save(update_fields=["cursor", "completed", "updated_at"])
        totals = {"products": 0, "nutrients_added": 0, "refreshed": 0, "not_found": 0, "failed": 0}
        for index, product in enumerate(candidates):
            if index: time.sleep(delay)
            before = set(product.nutrient_values.filter(status="available").values_list("nutrient__code", "basis"))
            success_this = False
            failed_this = False
            try:
                if opts["dry_run"]:
                    data = lookup(product.barcode, force_refresh=True)
                    if not data:
                        totals["not_found"] += 1
                    else:
                        raw = data.get("nutriments") or {}
                        found = [("100g", row) for row in nutrient_values(raw, "100g")] + [("100ml", row) for row in nutrient_values(raw, "100ml")]
                        after_keys = {(row[0], basis) for basis, row in found}
                        totals["nutrients_added"] += len(after_keys - before)
                        totals["refreshed"] += 1
                        success_this = True
                else:
                    refreshed = refresh_product(product.barcode)
                    if not refreshed:
                        totals["not_found"] += 1
                        ImportLog.objects.create(barcode=product.barcode, query=self.KEY, status="not_found", detail="No matching Open Food Facts product returned")
                    else:
                        after = set(refreshed.nutrient_values.filter(status="available").values_list("nutrient__code", "basis"))
                        totals["nutrients_added"] += len(after - before)
                        totals["refreshed"] += 1
                        success_this = True
            except (OpenFoodFactsError, ValueError) as exc:
                totals["failed"] += 1
                failed_this = True
                self.stderr.write(f"FAILED {product.barcode}: {exc}")
                if not opts["dry_run"] and not ImportLog.objects.filter(barcode=product.barcode, query=self.KEY, status="failed", detail=str(exc)[:500]).exists(): ImportLog.objects.create(barcode=product.barcode, query=self.KEY, status="failed", detail=str(exc)[:500])
            totals["products"] += 1
            if not opts["dry_run"]:
                job, _ = DiscoveryCheckpoint.objects.get_or_create(key=checkpoint_key, defaults={"group_name": "Nutrition enrichment (empty records)" if opts["only_empty_nutrition"] else "Nutrition enrichment"})
                job.cursor = product.pk; job.completed = False
                if success_this: job.last_successful_at = timezone.now()
                if failed_this: job.failed_count += 1
                job.save()
        if not opts["dry_run"] and len(candidates) < opts["limit"]:
            job, _ = DiscoveryCheckpoint.objects.get_or_create(key=checkpoint_key, defaults={"group_name": "Nutrition enrichment (empty records)" if opts["only_empty_nutrition"] else "Nutrition enrichment"})
            job.completed = True; job.save(update_fields=["completed", "updated_at"])
        self.stdout.write(self.style.SUCCESS("Enrichment summary: " + ", ".join(f"{key}={value}" for key, value in totals.items())))
        if opts["dry_run"]: self.stdout.write("Dry run: no product, import-log, or checkpoint rows were written.")
