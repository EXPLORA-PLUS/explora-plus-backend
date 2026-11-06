import time

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db.models import Q
from rest_framework.test import APIClient

from core.domain import DETAIL_STATUS_COMPLETE, DETAIL_STATUS_UNAVAILABLE
from places.models import Place

# Mesmas sugestoes de ROUTE_SUGGESTIONS no ExploreScreen do frontend.
DEMO_ROUTES = [
    ("Unisantos, Santos", "Museu Pele, Santos"),
    ("Aquario Municipal de Santos", "Praca da Independencia, Santos"),
    ("Portinho, Praia Grande", "Palacio das Artes, Praia Grande"),
]


class Command(BaseCommand):
    help = (
        "Pre-calcula as rotas de demonstracao e busca devagar os detalhes "
        "(Wikidata/Wikipedia) de cada POI, para a apresentacao nao depender das APIs."
    )

    def add_arguments(self, parser):
        parser.add_argument("--username", default="demo")
        parser.add_argument("--delay", type=float, default=2.5)
        parser.add_argument("--passes", type=int, default=3)

    def handle(self, *args, username, delay, passes, **options):
        client = APIClient(SERVER_NAME="localhost")
        client.force_authenticate(get_user_model().objects.get(username=username))

        stop_ids: list[str] = []
        for origin, destination in DEMO_ROUTES:
            response = client.post(
                "/api/tour-routes/",
                {"origin": {"address": origin}, "destination": {"address": destination}},
                format="json",
            )
            if response.status_code != 200:
                self.stderr.write(f"Falhou {origin} -> {destination}: {response.status_code}")
                continue
            places = response.json()["route"]["places_to_pass"]
            self.stdout.write(f"{origin} -> {destination}: {len(places)} POIs")
            stop_ids.extend(place["stop_id"] for place in places)
            time.sleep(delay)

        done_statuses = {DETAIL_STATUS_COMPLETE, DETAIL_STATUS_UNAVAILABLE}
        for attempt in range(1, passes + 1):
            pending = list(
                Place.objects.filter(source_ref__in=stop_ids, is_curated=False)
                .filter(
                    Q(details_fetched_at__isnull=True) | ~Q(detail_status__in=done_statuses)
                )
                .values_list("source_ref", flat=True)
            )
            if not pending:
                break
            self.stdout.write(f"Passada {attempt}: {len(pending)} POIs sem detalhe")
            for stop_id in pending:
                client.get(f"/api/tour-routes/pois/{stop_id}/")
                time.sleep(delay)

        places = Place.objects.filter(source_ref__in=stop_ids)
        with_summary = places.exclude(summary="").count()
        with_image = places.filter(images__isnull=False).distinct().count()
        errors = places.filter(is_curated=False).exclude(detail_status__in=done_statuses).count()
        self.stdout.write(
            self.style.SUCCESS(
                f"{places.count()} POIs | {with_summary} com resumo | "
                f"{with_image} com imagem | {errors} ainda com erro"
            )
        )
