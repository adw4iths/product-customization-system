import uuid
import django.db.models.deletion
from django.db import migrations, models

import customizer.models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="Product",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=120)),
                ("slug", models.SlugField(unique=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
        ),
        migrations.CreateModel(
            name="DesignUpload",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("file", models.ImageField(upload_to=customizer.models.design_upload_path)),
                ("uploaded_at", models.DateTimeField(auto_now_add=True)),
            ],
        ),
        migrations.CreateModel(
            name="ProductImage",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("view", models.CharField(choices=[("front", "Front"), ("back", "Back"), ("side", "Side")], max_length=10)),
                ("base_image", models.ImageField(upload_to="products/%Y/%m/")),
                ("print_area_x", models.PositiveIntegerField()),
                ("print_area_y", models.PositiveIntegerField()),
                ("print_area_w", models.PositiveIntegerField()),
                ("print_area_h", models.PositiveIntegerField()),
                ("max_tilt_deg", models.FloatField(default=18.0)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("product", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="images", to="customizer.product")),
            ],
            options={
                "unique_together": {("product", "view")},
            },
        ),
        migrations.CreateModel(
            name="ProductImageAnalysis",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("quad_json", models.JSONField()),
                ("height_map_file", models.FileField(upload_to="analysis/")),
                ("tilt_deg", models.FloatField(default=0.0)),
                ("foreshorten", models.FloatField(default=0.0)),
                ("computed_at", models.DateTimeField(auto_now=True)),
                ("product_image", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="analysis", to="customizer.productimage")),
            ],
        ),
        migrations.CreateModel(
            name="CustomizationJob",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("status", models.CharField(choices=[("pending", "Pending"), ("processing", "Processing"), ("done", "Done"), ("failed", "Failed")], default="pending", max_length=12)),
                ("result_image", models.ImageField(blank=True, null=True, upload_to="output/%Y/%m/")),
                ("error_message", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
                ("design", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="customizer.designupload")),
                ("product_image", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="customizer.productimage")),
            ],
        ),
    ]
