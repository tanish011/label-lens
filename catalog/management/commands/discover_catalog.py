import math
import time
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from catalog.brand_registry import BRAND_GROUPS
from catalog.models import DiscoveryCheckpoint, ImportLog, Product
from integrations.openfoodfacts import structured_search, import_search_result, OpenFoodFactsError

class Command(BaseCommand):
    help = "Discover real Open Food Facts products by priority brand group and import them resumably."

    def add_arguments(self, parser):
        parser.add_argument("--country", default="India", help="Country filter; use 'all' to omit it.")
        parser.add_argument("--group", help="One registry group key, for example dairy or drinks.")
        parser.add_argument("--brand", help="Limit a selected group to one exact registered brand.")
        parser.add_argument("--limit", type=int, default=500, help="Maximum new products imported this run.")
        parser.add_argument("--page-size", type=int, default=25)
        parser.add_argument("--pages-per-group", type=int, default=1)
        parser.add_argument("--sleep", type=float, default=6.5, help="Delay between uncached search requests; minimum 6.2 seconds.")
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--restart", action="store_true", help="Start selected groups at page 1 without deleting existing records.")

    def handle(self, *args, **opts):
        if opts["limit"] < 0: raise CommandError("--limit must be zero or greater.")
        if not 1 <= opts["page_size"] <= 100: raise CommandError("--page-size must be between 1 and 100.")
        if opts["pages_per_group"] < 1: raise CommandError("--pages-per-group must be at least 1.")
        delay = max(6.2, opts["sleep"])
        groups = BRAND_GROUPS
        if opts["group"]:
            groups = [g for g in groups if g["key"].casefold() == opts["group"].casefold()]
            if not groups: raise CommandError("Unknown group. Use one of: " + ", ".join(g["key"] for g in BRAND_GROUPS))
        if opts["brand"]:
            wanted = opts["brand"].casefold()
            groups = [{**g, "brands": [b for b in g["brands"] if b.casefold() == wanted]} for g in groups]
            groups = [g for g in groups if g["brands"]]
            if not groups: raise CommandError("That brand is not registered in the selected group.")

        totals = {"imported": 0, "duplicates": 0, "rejected": 0, "failed": 0, "matched": 0, "requests": 0}
        for group in groups:
            country = "" if opts["country"].casefold() in {"all", "world"} else opts["country"]
            checkpoint_key = f"off:{country.casefold() or 'all'}:{group['key']}"
            checkpoint = None if opts["dry_run"] else DiscoveryCheckpoint.objects.filter(key=checkpoint_key).first()
            if checkpoint and checkpoint.completed and not opts["restart"]:
                self.stdout.write(f"SKIP {group['key']}: already complete at page {checkpoint.cursor}; use --restart to rescan.")
                continue
            page = 1 if opts["restart"] or not checkpoint else checkpoint.cursor + 1
            if checkpoint and opts["restart"] and not opts["dry_run"]:
                checkpoint.cursor = 0; checkpoint.completed = False; checkpoint.save(update_fields=["cursor", "completed", "updated_at"])
            page_budget = opts["pages_per_group"]
            for _ in range(page_budget):
                if totals["imported"] >= opts["limit"]: break
                if totals["requests"]: time.sleep(delay)
                totals["requests"] += 1
                try:
                    payload = structured_search(brands=group["brands"], country=country, page=page, page_size=opts["page_size"])
                except OpenFoodFactsError as exc:
                    totals["failed"] += 1
                    self.stderr.write(f"FAILED {group['key']} page {page}: {exc}")
                    if not opts["dry_run"]:
                        entry, _ = DiscoveryCheckpoint.objects.get_or_create(key=checkpoint_key, defaults={"group_name": group["category"], "country": country})
                        entry.failed_count += 1; entry.save(update_fields=["failed_count", "updated_at"])
                        ImportLog.objects.create(query=checkpoint_key, status="failed", detail=str(exc)[:500])
                    break
                products = payload.get("products", []) if isinstance(payload, dict) else []
                reported_count = int(payload.get("count") or 0) if isinstance(payload, dict) else 0
                page_count = int(payload.get("page_count") or len(products)) if isinstance(payload, dict) else len(products)
                totals["matched"] += page_count
                page_imported = page_duplicates = page_rejected = 0
                limit_hit = False
                for row in products:
                    code = str(row.get("code") or "").strip()
                    if not code:
                        page_rejected += 1; totals["rejected"] += 1
                        if not opts["dry_run"]: ImportLog.objects.create(query=checkpoint_key, status="rejected", detail="Source result had no barcode")
                        continue
                    existing = Product.objects.filter(barcode=code).exists()
                    if existing:
                        page_duplicates += 1; totals["duplicates"] += 1
                    elif totals["imported"] >= opts["limit"]:
                        limit_hit = True; break
                    if opts["dry_run"]:
                        if not existing and row.get("product_name"): page_imported += 1; totals["imported"] += 1
                        continue
                    try:
                        product = import_search_result(row)
                        if product:
                            if existing: pass
                            else: page_imported += 1; totals["imported"] += 1
                        else:
                            page_rejected += 1; totals["rejected"] += 1
                    except Exception as exc:
                        page_rejected += 1; totals["rejected"] += 1
                        ImportLog.objects.create(barcode=code[:32], query=checkpoint_key, status="rejected", detail=str(exc)[:500])
                self.stdout.write(f"{group['key']} page {page}: source {page_count}/{reported_count}; new {page_imported}, existing {page_duplicates}, rejected {page_rejected}.")
                if opts["dry_run"]:
                    if limit_hit: break
                else:
                    entry, _ = DiscoveryCheckpoint.objects.get_or_create(key=checkpoint_key, defaults={"group_name": group["category"], "country": country})
                    entry.matched_count += page_count
                    entry.imported_count += page_imported
                    entry.duplicate_count += page_duplicates
                    entry.last_successful_at = timezone.now()
                    fully_processed = not limit_hit
                    entry.cursor = page if fully_processed else max(0, page - 1)
                    entry.completed = fully_processed and (page_count < opts["page_size"] or (reported_count and page >= math.ceil(reported_count / opts["page_size"])))
                    entry.save()
                    ImportLog.objects.create(query=checkpoint_key, status="discovery", detail=f"Page {page}: {page_imported} new, {page_duplicates} existing, {page_rejected} rejected")
                if limit_hit or page_count == 0 or page_count < opts["page_size"] or (reported_count and page >= math.ceil(reported_count / opts["page_size"])): break
                page += 1
        self.stdout.write(self.style.SUCCESS("Run summary: " + ", ".join(f"{key}={value}" for key, value in totals.items())))
        if opts["dry_run"]: self.stdout.write("Dry run: no product, import-log, or checkpoint rows were written.")
