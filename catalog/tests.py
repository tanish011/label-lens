from decimal import Decimal
from unittest.mock import patch
from django.test import TestCase, Client
from django.urls import reverse
from catalog.models import Product, Nutrient, NutrientValue, Category, DiscoveryCheckpoint
from catalog.services import parse_decimal, nutrient_values, completeness, per_serving, save_off_product
from integrations.openfoodfacts import OpenFoodFactsError
from recommendations.ml import text_similarities
from recommendations.ranking import alternatives
from unittest.mock import patch
from django.core.management import call_command
from io import StringIO

class DataHandlingTests(TestCase):
    def test_invalid_or_missing_nutrient_is_missing_not_zero(self):
        self.assertIsNone(parse_decimal(None)); self.assertIsNone(parse_decimal("nan")); self.assertEqual(parse_decimal("0"), Decimal("0"))
    def test_salt_and_sodium_stay_separate(self):
        rows = nutrient_values({"salt_100g": "1.2", "sodium_100g": "0.48"}, "100g")
        self.assertEqual({row[0] for row in rows}, {"salt", "sodium"})
    def test_liquid_and_solid_bases_are_separate(self):
        data = {"code": "1234567890123", "product_name": "Sample", "nutriments": {"sugars_100g": "4", "sugars_100ml": "3"}}
        product = save_off_product(data)
        self.assertEqual(set(product.nutrient_values.values_list("basis", flat=True)), {"100g", "100ml"})
    def test_duplicate_import_updates_same_product(self):
        payload = {"code": "1234567890123", "product_name": "Original", "nutriments": {"sugars_100g": "5"}}
        first = save_off_product(payload)
        second = save_off_product({**payload, "product_name": "Updated"})
        self.assertEqual(Product.objects.count(), 1); self.assertEqual(first.pk, second.pk)
        self.assertEqual(second.nutrient_values.get().value, Decimal("5"))
    def test_empty_refresh_does_not_erase_existing_nutrients(self):
        p = save_off_product({"code": "1234567890123", "product_name": "Sample", "nutriments": {"sugars_100g": "5"}})
        save_off_product({"code": p.barcode, "product_name": "Sample"})
        self.assertEqual(p.nutrient_values.get().value, Decimal("5"))
    def test_catalog_seed_skips_nonempty_database(self):
        Product.objects.create(barcode="1234567890123", name="Existing product")
        output = StringIO()
        call_command("seed_catalog", stdout=output)
        self.assertEqual(Product.objects.count(), 1)
        self.assertIn("seed skipped", output.getvalue())
    def test_catalog_seed_loads_bundled_source_data(self):
        call_command("seed_catalog", stdout=StringIO())
        self.assertEqual(Product.objects.count(), 654)
        self.assertGreater(NutrientValue.objects.count(), 5000)
    def test_serving_calculation_needs_declared_size(self):
        p = Product.objects.create(name="Food", serving_size="30 g")
        self.assertEqual(per_serving(Decimal("10"), p, "100g")[0], Decimal("3.00"))
        p.serving_size = "30 ml"; self.assertIsNone(per_serving(Decimal("10"), p, "100g"))
        p.serving_size = ""; self.assertIsNone(per_serving(Decimal("10"), p))
    def test_completeness_has_documented_eight_field_basis(self):
        p = save_off_product({"code": "1234567890123", "product_name": "Sample", "nutriments": {"sugars_100g": "5"}})
        self.assertEqual(completeness(p), 13)

class PageAndApiTests(TestCase):
    def test_homepage_and_empty_search(self):
        self.assertEqual(self.client.get(reverse("home")).status_code, 200)
        self.assertEqual(self.client.get(reverse("discover"), {"q": "missing", "local": 1}).status_code, 200)
    def test_homepage_shows_recent_imports_and_real_categories(self):
        save_off_product({"code": "1234567890123", "product_name": "Older product", "categories": "123"})
        save_off_product({"code": "2234567890123", "product_name": "Latest product", "categories": "Packaged beverages"})
        response = self.client.get(reverse("home"))
        shown = [product.name for product in response.context["products"]]
        categories = [category.name for category in response.context["categories"]]
        self.assertEqual(shown[0], "Latest product")
        self.assertIn("Packaged beverages", categories)
        self.assertNotIn("123", categories)
    def test_secondary_pages_render(self):
        for name in ("compare", "dashboard", "about", "login", "register"):
            with self.subTest(page=name): self.assertEqual(self.client.get(reverse(name)).status_code, 200)
    def test_dashboard_explains_its_catalogue_metrics(self):
        response = self.client.get(reverse("dashboard"))
        self.assertContains(response, "Product records")
        self.assertContains(response, "Nutrition available")
        self.assertContains(response, "not anyone’s eating habits")
    @patch("integrations.openfoodfacts.lookup", return_value={"code": "1234567890123", "product_name": "OFF test", "nutriments": {}})
    def test_product_api_imports_real_response_shape(self, mocked):
        response = self.client.get(reverse("api_detail", args=["1234567890123"]))
        self.assertEqual(response.status_code, 200); self.assertEqual(response.json()["name"], "OFF test")
    def test_not_found_is_friendly(self):
        with patch("catalog.views.import_product", return_value=None):
            self.assertEqual(self.client.get(reverse("product_detail", args=["0000000000000"])).status_code, 404)
    def test_comparison_endpoint(self):
        p = Product.objects.create(barcode="1234567890123", name="One")
        response = self.client.get(reverse("api_compare"), {"codes": p.barcode})
        self.assertEqual(response.status_code, 200); self.assertEqual(len(response.json()["products"]), 1)
    def test_comparison_marks_missing_nutrients_as_not_reported(self):
        reported = save_off_product({"code": "1234567890123", "product_name": "Apple juice", "nutriments": {"sugars_100g": "10"}})
        missing = save_off_product({"code": "2234567890123", "product_name": "Cranberry juice", "nutriments": {}})
        self.assertEqual(reported.nutrient_values.filter(status="available").count(), 1)
        response = self.client.get(reverse("compare"), {"codes": f"{reported.barcode},{missing.barcode}"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["nutrition_matrix"]), 1)
        self.assertContains(response, "Not reported")
        self.assertContains(response, "10.00 g")
        self.assertNotContains(response, "N/A")
    def test_comparison_can_select_products_by_name_or_brand(self):
        first = save_off_product({"code": "1234567890123", "product_name": "Oat cereal", "brands": "Sample Foods"})
        second = save_off_product({"code": "2234567890123", "product_name": "Rice cereal", "brands": "Other Foods"})
        response = self.client.get(reverse("compare"), {"a": first.barcode, "b": second.barcode})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Search a name or brand")
        self.assertContains(response, "Oat cereal — Sample Foods")
        self.assertContains(response, "2 products selected")
    def test_comparison_chooser_can_narrow_suggestions_by_category(self):
        product = save_off_product({"code": "1234567890123", "product_name": "Breakfast cereal", "categories": "Breakfast cereals"})
        other = save_off_product({"code": "2234567890123", "product_name": "Black tea", "categories": "Teas"})
        response = self.client.get(reverse("compare"))
        category = product.categories.get()
        self.assertContains(response, "Narrow suggestions by category")
        self.assertContains(response, f'value="{category.pk}"')
        self.assertTrue(any(str(category.pk) in item["categories"].split("|") for item in response.context["chooser_products"] if item["barcode"] == product.barcode))
        filtered = self.client.get(reverse("compare"), {"category": category.pk})
        self.assertEqual([item["barcode"] for item in filtered.context["chooser_products"]], [product.barcode])
        self.assertNotContains(filtered, "Black tea —")
    def test_discovery_prioritizes_products_with_more_reported_nutrition(self):
        sparse = save_off_product({"code": "1234567890123", "product_name": "A sparse product"})
        complete = save_off_product({"code": "2234567890123", "product_name": "Z better described product", "nutriments": {"energy-kcal_100g": "100", "fat_100g": "2", "saturated-fat_100g": "1", "carbohydrates_100g": "14", "sugars_100g": "8", "fiber_100g": "3", "proteins_100g": "4", "salt_100g": "0.2"}})
        response = self.client.get(reverse("discover"), {"local": "1"})
        self.assertEqual(response.context["page_obj"].object_list[0].pk, complete.pk)
        named = self.client.get(reverse("discover"), {"local": "1", "sort": "name"})
        self.assertEqual(named.context["page_obj"].object_list[0].pk, sparse.pk)
    def test_product_card_replaces_missing_score_with_reported_fact(self):
        save_off_product({"code": "1234567890123", "product_name": "Sugar cereal", "nutriments": {"sugars_100g": "10"}})
        response = self.client.get(reverse("home"))
        self.assertContains(response, "Sugars 10.0 g / 100g")
        self.assertNotContains(response, "Score unavailable")
    def test_how_it_works_link_is_separate_from_data_page(self):
        response = self.client.get(reverse("home"))
        self.assertContains(response, 'href="/#how-it-works"')
    def test_nutrition_filter_uses_reported_values_only(self):
        low = save_off_product({"code": "1234567890123", "product_name": "Low sugar", "nutriments": {"sugars_100g": "3"}})
        high = save_off_product({"code": "2234567890123", "product_name": "High sugar", "nutriments": {"sugars_100g": "8"}})
        response = self.client.get(reverse("discover"), {"q": "sugar", "max_sugar": "5", "local": "1"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, low.name); self.assertNotContains(response, high.name)
    def test_detail_page_renders_missing_nutrients_honestly(self):
        product = save_off_product({"code": "1234567890123", "product_name": "Sparse product"})
        response = self.client.get(reverse("product_detail", args=[product.barcode]))
        self.assertEqual(response.status_code, 200); self.assertContains(response, "does not include a nutrition panel")
    def test_discover_facets_hide_numeric_noise_and_case_duplicates(self):
        save_off_product({"code": "1234567890123", "product_name": "Sample tea", "brands": "Amul, amul", "categories": "123, Packaged beverages"})
        response = self.client.get(reverse("discover"), {"local": "1"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(sum(brand.name.casefold() == "amul" for brand in response.context["brands"]), 1)
        self.assertIn("Packaged beverages", [category.name for category in response.context["categories"]])
        self.assertNotIn("123", [category.name for category in response.context["categories"]])
    @patch("integrations.openfoodfacts._get", side_effect=OpenFoodFactsError("offline"))
    def test_api_external_failure_returns_friendly_error(self, mocked):
        response = self.client.get(reverse("api_detail", args=["1234567890123"]))
        self.assertEqual(response.status_code, 503); self.assertNotContains(response, "Traceback", status_code=503)
    def test_alternative_ranking_requires_comparable_source_data(self):
        target = save_off_product({"code": "1234567890123", "product_name": "Oat cereal", "categories": "Breakfast cereals", "nutriments": {"sugars_100g": "12"}})
        candidate = save_off_product({"code": "2234567890123", "product_name": "Oat flakes", "categories": "Breakfast cereals", "nutriments": {"sugars_100g": "5"}})
        rows, explanation = alternatives(target, "lower_sugar")
        self.assertEqual(rows[0][0].pk, candidate.pk); self.assertIn("same", explanation)
    def test_similarity_uses_runtime_fallback_when_artifact_is_missing(self):
        target = Product.objects.create(name="oat cereal")
        candidate = Product.objects.create(name="oat flakes")
        with patch("recommendations.ml.ARTIFACT", target._meta.apps.get_app_config("catalog").path + "/missing.joblib"):
            scores = text_similarities(target, [candidate])
        self.assertEqual(len(scores), 1); self.assertGreater(scores[0], 0)

class EnrichmentCommandTests(TestCase):
    @patch("catalog.management.commands.enrich_catalog.time.sleep")
    @patch("catalog.management.commands.enrich_catalog.lookup", return_value=None)
    def test_empty_nutrition_mode_skips_partially_documented_products(self, mocked_lookup, _sleep):
        save_off_product({"code": "1234567890123", "product_name": "Partial product", "nutriments": {"sugars_100g": "2"}})
        empty = save_off_product({"code": "2234567890123", "product_name": "Empty nutrition product"})
        call_command("enrich_catalog", limit=1, min_completeness=100, dry_run=True, only_empty_nutrition=True, stdout=StringIO())
        self.assertEqual(mocked_lookup.call_count, 1)
        self.assertEqual(mocked_lookup.call_args.args[0], empty.barcode)
        self.assertFalse(DiscoveryCheckpoint.objects.exists())
