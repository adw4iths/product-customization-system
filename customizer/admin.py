from django.contrib import admin
from .models import Product, ProductImage, ProductImageAnalysis, DesignUpload, CustomizationJob


class ProductImageInline(admin.TabularInline):
    model = ProductImage
    extra = 1
    fields = ("view", "base_image", "print_area_x", "print_area_y", "print_area_w", "print_area_h", "max_tilt_deg")


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "created_at")
    inlines = [ProductImageInline]


@admin.register(ProductImage)
class ProductImageAdmin(admin.ModelAdmin):
    list_display = ("product", "view", "print_area_x", "print_area_y", "print_area_w", "print_area_h")


@admin.register(ProductImageAnalysis)
class ProductImageAnalysisAdmin(admin.ModelAdmin):
    list_display = ("product_image", "tilt_deg", "foreshorten", "computed_at")
    readonly_fields = ("quad_json", "tilt_deg", "foreshorten", "computed_at")


@admin.register(CustomizationJob)
class CustomizationJobAdmin(admin.ModelAdmin):
    list_display = ("id", "product_image", "status", "created_at", "finished_at")
    list_filter = ("status",)


admin.site.register(DesignUpload)
