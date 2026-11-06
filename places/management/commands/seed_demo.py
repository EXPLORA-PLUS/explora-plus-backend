from datetime import datetime, timedelta, timezone

from django.contrib.gis.geos import Point
from django.core.management.base import BaseCommand
from django.db import transaction

from places.models import Place, PlaceCategory, PlaceImage

CATEGORIES = [
    {"slug": "culture", "name": "Cultura", "icon_name": "camera"},
    {"slug": "park", "name": "Parques", "icon_name": "leaf"},
    {"slug": "food", "name": "Comida", "icon_name": "restaurant"},
]


def now_plus(days: int) -> datetime:
    return datetime.now(tz=timezone.utc) + timedelta(days=days)


# Os 8 primeiros têm os mesmos nomes, coordenadas e fotos dos documentos
# `monumentos` do Firestore do Explora+ Passaporte.
PLACES = [
    {
        "slug": "unisantos",
        "category": "culture",
        "name": "Unisantos",
        "description": "Campus Dom Idílio José Soares da Universidade Católica de Santos, onde o Explora+ nasceu. Ponto de partida da demonstração do passaporte.",
        "lat": -23.946622,
        "lng": -46.322171,
        "address": "Av. Conselheiro Nébias, 300 – Vila Mathias",
        "hours_open": "",
        "price_cents": 0,
        "images": ["https://www.unisantos.br/wp-content/themes/tema-unisantos2026/images/icon.png"],
    },
    {
        "slug": "museu-do-cafe",
        "category": "culture",
        "name": "Museu do Café",
        "description": "Funciona no prédio da antiga Bolsa Oficial de Café, ícone do auge do ciclo cafeeiro. O salão do pregão é o destaque da visita, e a cafeteria serve cafés especiais de todo o país.",
        "lat": -23.932517,
        "lng": -46.330095,
        "address": "Rua XV de Novembro, 95 – Centro Histórico",
        "hours_open": "Ter–Sáb 09:00–18:00 · Dom 10:00–18:00 (grátis aos sábados)",
        "price_cents": 1600,
        "images": ["https://commons.wikimedia.org/wiki/Special:FilePath/Bolsa_do_Caf%C3%A9_-_Centro_hist%C3%B3rico.jpg?width=960"],
    },
    {
        "slug": "monte-serrat",
        "category": "culture",
        "name": "Monte Serrat",
        "description": "Santuário de Nossa Senhora do Monte Serrat, padroeira de Santos, no alto do morro do Centro. O acesso é pelo funicular ou pela escadaria, e lá de cima se vê o porto, o centro e a orla.",
        "lat": -23.939688,
        "lng": -46.330513,
        "address": "Pç. Correia de Mello, 33 (estação do funicular) – Centro Histórico",
        "hours_open": "Funicular: seg–qui 08:00–20:00 · sex e sáb 08:00–02:00 · dom 08:00–20:30",
        "price_cents": 3300,
        "images": ["https://commons.wikimedia.org/wiki/Special:FilePath/Igreja_Nsa._Senhora_do_Monte_Serrat_-_panoramio.jpg?width=960"],
    },
    {
        "slug": "orquidario-municipal",
        "category": "park",
        "name": "Orquidário Municipal",
        "description": "Parque zoobotânico inaugurado em 1945, com mais de 3.500 orquídeas de cerca de 120 espécies, mata atlântica, lago com aves e cerca de 500 animais.",
        "lat": -23.965891,
        "lng": -46.349648,
        "address": "Pç. Washington, s/n – José Menino",
        "hours_open": "Ter–Dom 09:00–17:00",
        "price_cents": 1000,
        "images": ["https://commons.wikimedia.org/wiki/Special:FilePath/Orquid%C3%A1rio_Municipal_de_Santos_(36566252891).jpg?width=960"],
    },
    {
        "slug": "fortaleza-de-itaipu",
        "category": "culture",
        "name": "Fortaleza de Itaipu",
        "description": "Complexo militar iniciado em 1902 na Ponta de Itaipu, com três fortes que protegiam a entrada do Porto de Santos. Pelé serviu ali em 1959. Hoje sedia o 2º GAAAe e a visitação pública está suspensa; o check-in vale na portaria, no fim do Canto do Forte.",
        "lat": -24.015,
        "lng": -46.399,
        "address": "Av. Marechal Mallet, 1 – Canto do Forte",
        "hours_open": "Visitação pública suspensa",
        "price_cents": 0,
        "images": ["https://commons.wikimedia.org/wiki/Special:FilePath/Itaip%C3%BA_Fortress.JPG?width=960"],
    },
    {
        "slug": "estatua-de-iemanja",
        "category": "culture",
        "name": "Estátua de Iemanjá",
        "description": "Estátua de cerca de 9 metros sobre espelhos d'água na Praia do Mirim, ao lado do calçadão. Recebe milhares de devotos nos Festejos de Iemanjá, entre o fim de novembro e o início de dezembro.",
        "lat": -24.032609,
        "lng": -46.481946,
        "address": "Av. Pres. Castelo Branco (orla) – Mirim",
        "hours_open": "Aberto 24h",
        "price_cents": 0,
        "images": ["https://commons.wikimedia.org/wiki/Special:FilePath/Monumento_a_Iemanj%C3%A1_-_Praia_Grande_-_SP_-_panoramio.jpg?width=960"],
    },
    {
        "slug": "palacio-das-artes",
        "category": "culture",
        "name": "Palácio das Artes",
        "description": "Complexo cultural inaugurado em 2008 que reúne o Teatro Serafim Gonzalez, o Museu da Cidade, a Galeria Nilton Zanotti, uma biblioteca e oficinas culturais.",
        "lat": -23.999455,
        "lng": -46.412003,
        "address": "Av. Pres. Costa e Silva, 1600 – Boqueirão",
        "hours_open": "Consultar programação",
        "price_cents": 0,
        "images": ["https://commons.wikimedia.org/wiki/Special:FilePath/Pal%C3%A1cio_das_Artes_Centro_Cultural_Praia_Grande-SP_4.jpg?width=960"],
    },
    {
        "slug": "portinho",
        "category": "park",
        "name": "Portinho",
        "description": "Área de Lazer Ézio Dall'Acqua, onde no século XVII funcionava um porto que levava a produção local para Santos e São Vicente. Tem deck de pesca de 73 metros, quadras, escola de vela e canoagem, museu ambiental e quiosques.",
        "lat": -23.990089,
        "lng": -46.405779,
        "address": "Rua Paulo Sérgio Garcia, s/n – Sítio do Campo",
        "hours_open": "Diariamente 06:00–18:00",
        "price_cents": 0,
        "images": ["https://commons.wikimedia.org/wiki/Special:FilePath/Praia_Grande-_Portinho-SP_-Brasil_-_panoramio.jpg?width=960"],
    },
    {
        "slug": "aquario-municipal-santos",
        "category": "culture",
        "name": "Aquário Municipal de Santos",
        "description": "Inaugurado em 1945 na Ponta da Praia, foi um dos primeiros aquários públicos do estado. São 32 tanques com mais de 200 espécies, entre tubarões, pinguins e leões-marinhos.",
        "lat": -23.986274,
        "lng": -46.308375,
        "address": "Pç. Vereador Luiz La Scala, s/n – Ponta da Praia",
        "hours_open": "Ter–Dom 09:00–18:00",
        "price_cents": 1000,
        "images": ["https://commons.wikimedia.org/wiki/Special:FilePath/Aqu%C3%A1rio_Municipal_de_Santos_-_panoramio.jpg?width=960"],
    },
    {
        "slug": "museu-pele",
        "category": "culture",
        "name": "Museu Pelé",
        "description": "Casarão do Valongo, tombado e restaurado para contar a história do maior jogador de futebol de todos os tempos, com arquivos pessoais, troféus, vídeos e instalações interativas.",
        "lat": -23.931401,
        "lng": -46.33313,
        "address": "Largo Marquês de Monte Alegre, 1 – Valongo",
        "hours_open": "Ter–Dom 10:00–17:30",
        "price_cents": 0,
        "images": ["https://commons.wikimedia.org/wiki/Special:FilePath/Casar%C3%A3o_do_Valongo_-_Museu_Pel%C3%A9_-_panoramio.jpg?width=960"],
    },
    {
        "slug": "pinacoteca-benedicto-calixto",
        "category": "culture",
        "name": "Pinacoteca Benedicto Calixto",
        "description": "Casarão histórico na orla do Boqueirão com acervo do pintor santista Benedicto Calixto, célebre por suas marinhas, e exposições temporárias. Entrada gratuita.",
        "lat": -23.973261,
        "lng": -46.322207,
        "address": "Av. Bartolomeu de Gusmão, 15 – Boqueirão",
        "hours_open": "Ter–Dom 09:00–18:00",
        "price_cents": 0,
        "images": ["https://commons.wikimedia.org/wiki/Special:FilePath/Pinacoteca_Benedito_Calixto_-_Santos_-_20250309155421.jpg?width=960"],
    },
    {
        "slug": "catedral-de-santos",
        "category": "culture",
        "name": "Catedral de Santos",
        "description": "Catedral neogótica projetada por Maximilian Hehl, com obras de 1909 a 1967. Tem vitrais alemães sobre a vida de Nossa Senhora e afrescos de Benedicto Calixto na capela do Santíssimo.",
        "lat": -23.936899,
        "lng": -46.3241,
        "address": "Pç. Patriarca José Bonifácio, s/n – Centro",
        "hours_open": "",
        "price_cents": 0,
        "images": ["https://commons.wikimedia.org/wiki/Special:FilePath/Catedral_de_Santos%2C.jpg?width=960"],
    },
    {
        "slug": "bonde-turistico-santos",
        "category": "culture",
        "name": "Bonde Turístico de Santos",
        "description": "Bondes antigos restaurados que fazem um circuito pelo Centro Histórico, passando por casarões, igrejas e pelo prédio da Bolsa do Café.",
        "lat": -23.9319,
        "lng": -46.3306,
        "address": "Estação Valongo – Largo Marquês de Monte Alegre – Centro",
        "hours_open": "11:00–17:00",
        "price_cents": 700,
        "images": ["https://commons.wikimedia.org/wiki/Special:FilePath/Bonde_de_Santos_e_o_Museu_Pel%C3%A9_-_panoramio.jpg?width=960"],
    },
    {
        "slug": "festival-do-cafe",
        "category": "food",
        "name": "Festival do Café Santista",
        "description": "Festival anual no Museu do Café reunindo torrefadores, baristas, produtores rurais e cafeterias artesanais. Tem degustação, workshops, latte art e palestras sobre cafés especiais.",
        "lat": -23.932517,
        "lng": -46.330095,
        "address": "Museu do Café – Rua XV de Novembro, 95",
        "hours_open": "09:00 - 19:00",
        "price_cents": 2500,
        "event_start_at": now_plus(7),
        "event_end_at": now_plus(10),
        "images": ["https://commons.wikimedia.org/wiki/Special:FilePath/Bolsa_do_Caf%C3%A9_-_Centro_hist%C3%B3rico.jpg?width=960"],
    },
    {
        "slug": "mostra-verao-pinacoteca",
        "category": "culture",
        "name": "Mostra de Verão da Pinacoteca",
        "description": "Mostra coletiva anual da Pinacoteca Benedicto Calixto trazendo artistas contemporâneos do litoral paulista. Entrada gratuita, com mediação cultural nos fins de semana.",
        "lat": -23.973261,
        "lng": -46.322207,
        "address": "Pinacoteca – Av. Bartolomeu de Gusmão, 15",
        "hours_open": "09:00 - 18:00",
        "price_cents": 0,
        "event_start_at": now_plus(30),
        "event_end_at": now_plus(75),
        "images": ["https://commons.wikimedia.org/wiki/Special:FilePath/Pinacoteca_Benedito_Calixto_-_Santos_-_20250309155421.jpg?width=960"],
    },
]


class Command(BaseCommand):
    help = "Popula categorias e os pontos turísticos de Santos e Praia Grande usados na demonstração."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Apaga todos os Places/PlaceImages antes de popular.",
        )

    @transaction.atomic
    def handle(self, *args, **opts):
        if opts.get("reset"):
            self.stdout.write(self.style.WARNING("Apagando Places existentes…"))
            PlaceImage.objects.all().delete()
            Place.objects.all().delete()

        cats_by_slug: dict[str, PlaceCategory] = {}
        for c in CATEGORIES:
            obj, created = PlaceCategory.objects.update_or_create(
                slug=c["slug"], defaults={"name": c["name"], "icon_name": c["icon_name"]}
            )
            cats_by_slug[c["slug"]] = obj
            self.stdout.write(f"  {'+' if created else '·'} Categoria: {obj.name}")

        for p in PLACES:
            place, created = Place.objects.update_or_create(
                slug=p["slug"],
                defaults={
                    "category": cats_by_slug[p["category"]],
                    "name": p["name"],
                    "description": p["description"],
                    "location": Point(p["lng"], p["lat"], srid=4326),
                    "address": p["address"],
                    "opening_hours": p["hours_open"],
                    "summary": p["description"],
                    "source": "curated",
                    "is_curated": True,
                    "price_cents": p["price_cents"],
                    "currency": "BRL",
                    "event_start_at": p.get("event_start_at"),
                    "event_end_at": p.get("event_end_at"),
                    "is_active": True,
                },
            )
            place.images.all().delete()
            for i, url in enumerate(p["images"]):
                PlaceImage.objects.create(place=place, url=url, order=i)
            self.stdout.write(f"  {'+' if created else '·'} {place.name} ({len(p['images'])} imagens)")

        self.stdout.write(self.style.SUCCESS("\nSeed concluído ✓"))
