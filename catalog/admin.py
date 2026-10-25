from django.contrib import admin
from .models import Brand, Category, Product, Nutrient, NutrientValue, ImportLog, RecommendationRun, DiscoveryCheckpoint

class NutrientValueInline(admin.TabularInline):
    model = NutrientValue
    extra = 0
    readonly_fields = ("updated_at",)

@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("name", "barcode", "validation_status", "source_retrieved", "updated_at")
    search_fields = ("name", "barcode", "brands__name")
    list_filter = ("validation_status", "nutriscore", "nova_group")
    inlines = [NutrientValueInline]
    filter_horizontal = ("brands", "categories")
@admin.register(NutrientValue)
class NutrientValueAdmin(admin.ModelAdmin):
    list_display = ("product", "nutrient", "value", "unit", "basis", "status", "provenance")
    list_filter = ("basis", "status", "calculated", "nutrient")
    search_fields = ("product__name", "product__barcode", "nutrient__name")
admin.site.register([Brand, Category, Nutrient, ImportLog, RecommendationRun])
@admin.register(DiscoveryCheckpoint)
class DiscoveryCheckpointAdmin(admin.ModelAdmin):
    list_display = ("group_name", "country", "cursor", "completed", "matched_count", "imported_count", "last_successful_at")
    list_filter = ("completed", "country")
    search_fields = ("group_name", "key")
    readonly_fields = ("updated_at",)
