from django.contrib.gis import admin as gis_admin

from .models import Place, PlaceCategory, PlaceImage, UserPlaceState


class PlaceImageInline(gis_admin.TabularInline):
    model = PlaceImage
    extra = 1
    fields = ("url", "order", "caption")


@gis_admin.register(PlaceCategory)
class PlaceCategoryAdmin(gis_admin.ModelAdmin):
    list_display = ("name", "slug", "icon_name", "is_active")
    prepopulated_fields = {"slug": ("name",)}
    search_fields = ("name", "slug")


@gis_admin.register(Place)
class PlaceAdmin(gis_admin.GISModelAdmin):
    list_display = (
        "name",
        "category",
        "source",
        "source_ref",
        "is_curated",
        "is_sponsored",
        "event_start_at",
        "event_end_at",
        "is_active",
        "updated_at",
    )
    list_filter = ("category", "source", "is_curated", "is_sponsored", "is_active")
    search_fields = ("name", "slug", "source_ref", "address", "wikidata_id")
    prepopulated_fields = {"slug": ("name",)}
    inlines = [PlaceImageInline]
    readonly_fields = ("created_at", "updated_at", "details_fetched_at")
    fieldsets = (
        (
            None,
            {
                "fields": (
                    "name",
                    "slug",
                    "category",
                    "source",
                    "source_ref",
                    "is_curated",
                    "is_sponsored",
                    "is_active",
                )
            },
        ),
        ("Content", {"fields": ("description", "summary", "address", "opening_hours")}),
        ("Location", {"fields": ("location",)}),
        ("Commercial", {"fields": ("price_cents", "currency")}),
        (
            "External metadata",
            {
                "fields": (
                    "osm_type",
                    "osm_id",
                    "wikidata_id",
                    "wikipedia_title",
                    "source_url",
                    "website",
                    "detail_status",
                    "details_fetched_at",
                    "raw_payload",
                )
            },
        ),
        (
            "Event (optional)",
            {
                "fields": ("event_start_at", "event_end_at"),
                "description": "Preencha inicio e fim para o lugar virar um evento temporario.",
            },
        ),
        ("Audit", {"fields": ("created_at", "updated_at")}),
    )


@gis_admin.register(PlaceImage)
class PlaceImageAdmin(gis_admin.ModelAdmin):
    list_display = ("place", "order", "caption", "url")
    list_filter = ("place",)


@gis_admin.register(UserPlaceState)
class UserPlaceStateAdmin(gis_admin.ModelAdmin):
    list_display = ("user", "place", "is_visited", "seen_count", "last_seen_at")
    list_filter = ("is_visited",)
    search_fields = ("user__username", "place__name", "place__source_ref")
    readonly_fields = ("first_seen_at", "last_seen_at", "visited_at")
