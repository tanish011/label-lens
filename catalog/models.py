from decimal import Decimal
from django.core.validators import MinValueValidator
from django.db import models

class Brand(models.Model):
    name = models.CharField(max_length=180, unique=True, db_index=True)
    def __str__(self): return self.name

class Category(models.Model):
    name = models.CharField(max_length=180, unique=True, db_index=True)
    def __str__(self): return self.name

class Product(models.Model):
    barcode = models.CharField(max_length=32, unique=True, null=True, blank=True, db_index=True)
    name = models.CharField(max_length=300, db_index=True)
    brands = models.ManyToManyField(Brand, blank=True, related_name="products")
    categories = models.ManyToManyField(Category, blank=True, related_name="products")
    image_url = models.URLField(max_length=1000, blank=True)
    quantity = models.CharField(max_length=120, blank=True)
    serving_size = models.CharField(max_length=100, blank=True)
    ingredients_text = models.TextField(blank=True)
    allergens = models.CharField(max_length=500, blank=True)
    traces = models.CharField(max_length=500, blank=True)
    labels = models.CharField(max_length=1000, blank=True)
    additives = models.CharField(max_length=1000, blank=True)
    countries = models.CharField(max_length=300, blank=True)
    nutriscore = models.CharField(max_length=8, blank=True)
    nova_group = models.PositiveSmallIntegerField(null=True, blank=True)
    source = models.CharField(max_length=80, default="Open Food Facts")
    source_url = models.URLField(max_length=500, blank=True)
    source_modified = models.DateTimeField(null=True, blank=True)
    source_retrieved = models.DateTimeField(null=True, blank=True)
    imported_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    validation_status = models.CharField(max_length=24, default="source_data")
    class Meta:
        ordering = ["name"]
        indexes = [models.Index(fields=["name"]), models.Index(fields=["validation_status", "updated_at"])]
    def __str__(self): return self.name

class Nutrient(models.Model):
    code = models.SlugField(max_length=80, unique=True)
    name = models.CharField(max_length=100)
    display_unit = models.CharField(max_length=24, blank=True)
    order = models.PositiveSmallIntegerField(default=100)
    def __str__(self): return self.name

class NutrientValue(models.Model):
    BASIS_CHOICES = [("100g", "per 100 g"), ("100ml", "per 100 ml"), ("serving", "per serving")]
    STATUS_CHOICES = [("available", "Available"), ("invalid", "Invalid / rejected")]
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="nutrient_values")
    nutrient = models.ForeignKey(Nutrient, on_delete=models.PROTECT, related_name="values")
    value = models.DecimalField(max_digits=12, decimal_places=4, validators=[MinValueValidator(Decimal("0"))])
    unit = models.CharField(max_length=24)
    basis = models.CharField(max_length=12, choices=BASIS_CHOICES)
    provenance = models.CharField(max_length=80, default="Open Food Facts")
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="available")
    calculated = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=["product", "nutrient", "basis"], name="unique_product_nutrient_basis")]
        indexes = [models.Index(fields=["nutrient", "basis", "value"])]
    def __str__(self): return f"{self.product}: {self.nutrient} {self.value} {self.unit}/{self.basis}"

class ImportLog(models.Model):
    barcode = models.CharField(max_length=32, blank=True, db_index=True)
    query = models.CharField(max_length=250, blank=True)
    status = models.CharField(max_length=24)
    detail = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    def __str__(self): return f"{self.status} {self.barcode or self.query}"

class DiscoveryCheckpoint(models.Model):
    key = models.CharField(max_length=180, unique=True)
    group_name = models.CharField(max_length=100)
    country = models.CharField(max_length=80, blank=True)
    cursor = models.PositiveIntegerField(default=0, help_text="Last fully processed search page or product ID")
    completed = models.BooleanField(default=False)
    matched_count = models.PositiveIntegerField(default=0)
    imported_count = models.PositiveIntegerField(default=0)
    duplicate_count = models.PositiveIntegerField(default=0)
    failed_count = models.PositiveIntegerField(default=0)
    last_successful_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        ordering = ["group_name", "country"]
    def __str__(self): return f"{self.group_name} ({self.country or 'all countries'})"

class RecommendationRun(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    priority = models.CharField(max_length=32)
    method = models.CharField(max_length=80)
    created_at = models.DateTimeField(auto_now_add=True)
