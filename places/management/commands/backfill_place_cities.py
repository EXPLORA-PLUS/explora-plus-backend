from django.core.management.base import BaseCommand

from places.cities import ensure_place_city
from places.models import Place


class Command(BaseCommand):
    help = "Preenche Place.city dos lugares que ainda estao sem cidade."

    def handle(self, *args, **options):
        pending = list(Place.objects.filter(city="").order_by("pk"))
        self.stdout.write(f"{len(pending)} lugares sem cidade")
        for place in pending:
            city = ensure_place_city(place)
            self.stdout.write(f"  {'+' if city else '!'} {place.name}: {city or 'nao resolvida'}")

        missing = Place.objects.filter(city="").count()
        style = self.style.SUCCESS if missing == 0 else self.style.WARNING
        self.stdout.write(style(f"Concluido. Sem cidade: {missing}"))
