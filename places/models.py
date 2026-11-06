from __future__ import annotations

from django.conf import settings
from django.contrib.gis.db import models

from core.domain import DETAIL_STATUS_PENDING, PLACE_SOURCE_CHOICES, PLACE_SOURCE_CURATED


class PlaceCategory(models.Model):
    slug = models.SlugField(max_length=32, unique=True)
    name = models.CharField(max_length=120)
    icon_name = models.CharField(max_length=64, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Place category"
        verbose_name_plural = "Place categories"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Place(models.Model):
    slug = models.SlugField(max_length=160, unique=True)
    category = models.ForeignKey(
        PlaceCategory,
        on_delete=models.PROTECT,
        related_name="places",
    )
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    summary = models.TextField(blank=True)
    source = models.CharField(
        max_length=32,
        choices=PLACE_SOURCE_CHOICES,
        default=PLACE_SOURCE_CURATED,
    )
    source_ref = models.CharField(max_length=64, unique=True, null=True, blank=True)
    location = models.PointField(geography=True, srid=4326)
    address = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=120, blank=True, db_index=True)
    opening_hours = models.CharField(max_length=255, blank=True)
    price_cents = models.PositiveIntegerField(null=True, blank=True)
    currency = models.CharField(max_length=3, default="BRL")
    event_start_at = models.DateTimeField(null=True, blank=True)
    event_end_at = models.DateTimeField(null=True, blank=True)
    osm_type = models.CharField(max_length=16, blank=True)
    osm_id = models.BigIntegerField(null=True, blank=True)
    wikidata_id = models.CharField(max_length=64, blank=True)
    wikipedia_title = models.CharField(max_length=255, blank=True)
    source_url = models.URLField(blank=True)
    website = models.URLField(blank=True)
    detail_status = models.CharField(max_length=32, default=DETAIL_STATUS_PENDING)
    raw_payload = models.JSONField(default=dict, blank=True)
    details_fetched_at = models.DateTimeField(null=True, blank=True)
    is_curated = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Place"
        verbose_name_plural = "Places"
        ordering = ["name"]
        indexes = [
            models.Index(fields=["category", "is_active"]),
            models.Index(fields=["source", "is_active"]),
        ]

    def __str__(self) -> str:
        return self.name

    @property
    def about_text(self) -> str:
        return self.description or self.summary

    @property
    def primary_image(self):
        return self.images.order_by("order", "id").first()

    @property
    def primary_image_url(self) -> str | None:
        image = self.primary_image
        return image.url if image is not None else None

    @property
    def is_event(self) -> bool:
        return self.event_start_at is not None

    @property
    def is_free(self) -> bool:
        return self.price_cents in (None, 0)


class PlaceImage(models.Model):
    place = models.ForeignKey(
        Place,
        on_delete=models.CASCADE,
        related_name="images",
    )
    url = models.URLField(max_length=500)
    order = models.PositiveSmallIntegerField(default=0)
    caption = models.CharField(max_length=200, blank=True)

    class Meta:
        verbose_name = "Place image"
        verbose_name_plural = "Place images"
        ordering = ["place", "order", "id"]

    def __str__(self) -> str:
        return f"{self.place.name} #{self.order}"


class UserPlaceState(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="place_states",
    )
    place = models.ForeignKey(
        Place,
        on_delete=models.CASCADE,
        related_name="user_states",
    )
    is_visited = models.BooleanField(default=False)
    visited_at = models.DateTimeField(null=True, blank=True)
    first_seen_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now=True)
    seen_count = models.PositiveIntegerField(default=1)
    last_seen_route = models.ForeignKey(
        "tour_routes.TourRoute",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="seen_place_states",
    )

    class Meta:
        verbose_name = "User place state"
        verbose_name_plural = "User place states"
        ordering = ["-last_seen_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "place"],
                name="places_unique_user_place_state",
            )
        ]
        indexes = [
            models.Index(fields=["user", "-last_seen_at"]),
            models.Index(fields=["user", "is_visited"]),
        ]

    def __str__(self) -> str:
        return f"{self.user_id} -> {self.place.name}"
