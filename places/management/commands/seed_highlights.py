from datetime import datetime
from zoneinfo import ZoneInfo

from django.contrib.gis.geos import Point
from django.core.management.base import BaseCommand
from django.db import transaction

from places.models import Place, PlaceCategory, PlaceImage

TZ = ZoneInfo("America/Sao_Paulo")
EVENT_START = datetime(2026, 11, 1, 0, 0, tzinfo=TZ)
EVENT_END = datetime(2026, 12, 15, 23, 59, tzinfo=TZ)

IMG = "https://commons.wikimedia.org/wiki/Special:FilePath/"

# Eventos temporarios cadastrados pelo admin (nao ha API publica que cubra a
# agenda da Baixada). Ficam ativos de 01/11 a 15/12/2026, perto das rotas da demo.
EVENTS = [
    {
        "slug": "feira-artesanato-praca-maua",
        "category": "culture",
        "name": "Feira de Artesanato da Praça Mauá",
        "description": "Artesãos santistas expõem cerâmica, bordados e peças em madeira no coração do Centro Histórico.",
        "lat": -23.93345,
        "lng": -46.32880,
        "city": "Santos",
        "address": "Praça Mauá – Centro Histórico",
        "hours_open": "Sex–Dom 09:00–17:00",
        "price_cents": 0,
        "images": [IMG + "At%20Santos%2C%20Brazil%202017%20077.jpg?width=1200"],
    },
    {
        "slug": "concertos-fim-de-ano-catedral",
        "category": "culture",
        "name": "Concertos de Fim de Ano na Catedral",
        "description": "Ciclo de concertos de coral e órgão sob os vitrais da Catedral de Santos.",
        "lat": -23.93712,
        "lng": -46.32440,
        "city": "Santos",
        "address": "Pç. Patriarca José Bonifácio, s/n – Centro",
        "hours_open": "Sáb 19:00",
        "price_cents": 0,
        "images": [IMG + "Catedral_de_Santos%2C.jpg?width=960"],
    },
    {
        "slug": "exposicao-orquideas-orquidario",
        "category": "park",
        "name": "Exposição de Orquídeas de Primavera",
        "description": "Mostra temporária com orquídeas raras de produtores do litoral paulista, dentro do Orquidário.",
        "lat": -23.96565,
        "lng": -46.34935,
        "city": "Santos",
        "address": "Pç. Washington, s/n – José Menino",
        "hours_open": "Ter–Dom 09:00–17:00",
        "price_cents": 1000,
        "images": [IMG + "Orquid%C3%A1rio_Municipal_de_Santos_(36566252891).jpg?width=960"],
    },
    {
        "slug": "noite-no-aquario",
        "category": "culture",
        "name": "Noite no Aquário",
        "description": "Visitação noturna guiada aos tanques, com monitores falando sobre a vida marinha da Baixada.",
        "lat": -23.98605,
        "lng": -46.30865,
        "city": "Santos",
        "address": "Pç. Vereador Luiz La Scala, s/n – Ponta da Praia",
        "hours_open": "Sex e Sáb 18:00–21:00",
        "price_cents": 1500,
        "images": [IMG + "Aqu%C3%A1rio_Municipal_de_Santos_-_panoramio.jpg?width=960"],
    },
    {
        "slug": "festival-gastronomico-orla",
        "category": "food",
        "name": "Festival Gastronômico da Orla",
        "description": "Barracas de restaurantes locais com frutos do mar e comida caiçara nos jardins da orla do Gonzaga.",
        "lat": -23.96930,
        "lng": -46.33250,
        "city": "Santos",
        "address": "Jardins da Orla – Gonzaga",
        "hours_open": "Qui–Dom 17:00–23:00",
        "price_cents": 0,
        "images": [],
    },
    {
        "slug": "feira-artes-palacio-praia-grande",
        "category": "culture",
        "name": "Feira de Artes do Palácio",
        "description": "Feira de artistas plásticos e música ao vivo no complexo cultural Palácio das Artes.",
        "lat": -23.99920,
        "lng": -46.41160,
        "city": "Praia Grande",
        "address": "Av. Pres. Costa e Silva, 1600 – Boqueirão",
        "hours_open": "Sáb e Dom 10:00–18:00",
        "price_cents": 0,
        "images": [IMG + "Pal%C3%A1cio_das_Artes_Centro_Cultural_Praia_Grande-SP_4.jpg?width=960"],
    },
]

# Parceiros patrocinados ficticios (exemplo do modelo de monetizacao): ganham
# prioridade nas rotas e selo "Patrocinado" no app.
SPONSORED = [
    {
        "slug": "parceiro-cafe-do-valongo",
        "category": "food",
        "name": "Café do Valongo",
        "lat": -23.93175,
        "lng": -46.33255,
        "city": "Santos",
        "address": "Largo Marquês de Monte Alegre – Valongo",
        "hours_open": "Diariamente 08:00–19:00",
    },
    {
        "slug": "parceiro-cantina-xv",
        "category": "food",
        "name": "Cantina XV de Novembro",
        "lat": -23.93315,
        "lng": -46.33060,
        "city": "Santos",
        "address": "Rua XV de Novembro – Centro Histórico",
        "hours_open": "Seg–Sáb 11:30–15:30",
    },
    {
        "slug": "parceiro-quiosque-sabor-da-orla",
        "category": "food",
        "name": "Quiosque Sabor da Orla",
        "lat": -23.97080,
        "lng": -46.32930,
        "city": "Santos",
        "address": "Av. Vicente de Carvalho (orla) – Gonzaga",
        "hours_open": "Diariamente 09:00–22:00",
    },
    {
        "slug": "parceiro-sorveteria-do-portinho",
        "category": "food",
        "name": "Sorveteria do Portinho",
        "lat": -23.99070,
        "lng": -46.40620,
        "city": "Praia Grande",
        "address": "Rua Paulo Sérgio Garcia – Sítio do Campo",
        "hours_open": "Diariamente 10:00–20:00",
    },
]

SPONSORED_DESCRIPTION = (
    "Parceiro patrocinado do Explora+ (exemplo de demonstração do modelo de "
    "lugares patrocinados)."
)


class Command(BaseCommand):
    help = "Cadastra eventos temporarios e parceiros patrocinados de demonstracao."

    @transaction.atomic
    def handle(self, *args, **options):
        categories = {category.slug: category for category in PlaceCategory.objects.all()}
        missing = {item["category"] for item in [*EVENTS, *SPONSORED]} - categories.keys()
        if missing:
            self.stderr.write(f"Categorias ausentes ({', '.join(sorted(missing))}); rode seed_demo antes.")
            return

        for item in EVENTS:
            place = self._upsert(
                item,
                categories,
                description=item["description"],
                defaults={
                    "price_cents": item["price_cents"],
                    "event_start_at": EVENT_START,
                    "event_end_at": EVENT_END,
                    "is_sponsored": False,
                },
            )
            self.stdout.write(f"  evento: {place.name} ({place.city})")

        for item in SPONSORED:
            place = self._upsert(
                item,
                categories,
                description=SPONSORED_DESCRIPTION,
                defaults={
                    "price_cents": None,
                    "event_start_at": None,
                    "event_end_at": None,
                    "is_sponsored": True,
                },
            )
            self.stdout.write(f"  patrocinado: {place.name} ({place.city})")

        self.stdout.write(self.style.SUCCESS("Destaques cadastrados ✓"))

    def _upsert(self, item, categories, *, description, defaults):
        place, _ = Place.objects.update_or_create(
            slug=item["slug"],
            defaults={
                "category": categories[item["category"]],
                "name": item["name"],
                "description": description,
                "summary": description,
                "location": Point(item["lng"], item["lat"], srid=4326),
                "address": item["address"],
                "city": item["city"],
                "opening_hours": item["hours_open"],
                "source": "curated",
                "is_curated": True,
                "currency": "BRL",
                "is_active": True,
                **defaults,
            },
        )
        place.images.all().delete()
        for index, url in enumerate(item.get("images", [])):
            PlaceImage.objects.create(place=place, url=url, order=index)
        return place
