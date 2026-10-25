from django.core.management import BaseCommand, call_command

from catalog.models import Product


class Command(BaseCommand):
    help = "Load the bundled Open Food Facts catalogue into an empty database."

    def handle(self, *args, **options):
        if Product.objects.exists():
            self.stdout.write(self.style.WARNING("Catalogue already contains products; seed skipped."))
            return
        call_command("loaddata", "catalog_seed", verbosity=options["verbosity"])
        self.stdout.write(self.style.SUCCESS("Initial catalogue loaded."))
