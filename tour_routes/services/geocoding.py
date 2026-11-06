from __future__ import annotations

import re
from urllib.error import HTTPError, URLError

from tour_routes.types import GeoPoint, ResolvedPoint

from .exceptions import AddressResolutionError
from .http import JsonHttpClient


# Area de foco do app (Baixada Santista: Praia Grande ate Guaruja), no formato
# do Nominatim: lon_oeste,lat_norte,lon_leste,lat_sul.
FOCUS_VIEWBOX = "-46.65,-23.85,-46.15,-24.12"

# Abreviacoes comuns em enderecos copiados do Google Maps que o Nominatim nao
# reconhece ("R. Cunha Moreira, 16 - Centro, Itanhaem - SP, 11740-000").
_ABBREVIATIONS = {
    "r": "Rua",
    "av": "Avenida",
    "pc": "Praça",
    "pç": "Praça",
    "pca": "Praça",
    "pça": "Praça",
    "al": "Alameda",
    "tv": "Travessa",
    "trav": "Travessa",
    "rod": "Rodovia",
    "estr": "Estrada",
    "lgo": "Largo",
}
_ABBREVIATION_RE = re.compile(
    r"\b(" + "|".join(_ABBREVIATIONS) + r")\.(?=\s)", re.IGNORECASE
)
_CEP_RE = re.compile(r"\b\d{5}-?\d{3}\b")
_STATE_SUFFIX_RE = re.compile(r"\s*[-,]\s*[A-Z]{2}\s*(?=,|$)")


def normalize_address(address: str) -> str:
    normalized = _ABBREVIATION_RE.sub(
        lambda match: _ABBREVIATIONS[match.group(1).lower()], address
    )
    normalized = _CEP_RE.sub("", normalized)
    normalized = _STATE_SUFFIX_RE.sub("", normalized)
    normalized = normalized.replace(" - ", ", ")
    parts = [part.strip() for part in normalized.split(",") if part.strip()]
    return ", ".join(parts)


def address_query_variants(address: str) -> list[str]:
    # Bairro do Google costuma divergir do OSM ("Centro" x "Jardim Mosteiro"),
    # entao tambem tenta so rua + numero + cidade e rua + cidade.
    normalized = normalize_address(address)
    parts = normalized.split(", ")
    variants = [normalized]
    if len(parts) >= 3:
        street, city = parts[0], parts[-1]
        if parts[1].isdigit():
            variants.append(f"{street}, {parts[1]}, {city}")
        variants.append(f"{street}, {city}")
    return list(dict.fromkeys(variants))


class NominatimGeocoder:
    endpoint = "https://nominatim.openstreetmap.org/search"

    def __init__(self, client: JsonHttpClient | None = None):
        self.client = client or JsonHttpClient()

    def resolve(self, address: str) -> ResolvedPoint:
        # Primeiro so dentro da Baixada Santista; se nada bater, qualquer lugar
        # do Brasil. Sem isso "balsa" virava uma cidade na Hungria.
        queries = list(dict.fromkeys([*address_query_variants(address), address]))
        try:
            payload = self._first_match(queries)
        except (HTTPError, URLError, TimeoutError, ValueError) as exc:
            raise AddressResolutionError(
                f"Nao foi possivel localizar o endereco '{address}'."
            ) from exc

        if not payload:
            raise AddressResolutionError(
                f"Nao foi possivel localizar o endereco '{address}'."
            )

        match = payload[0]
        return ResolvedPoint(
            label=match.get("display_name") or address,
            location=GeoPoint(
                lat=float(match["lat"]),
                lng=float(match["lon"]),
            ),
        )

    def _search(self, address: str, *, viewbox: str | None = None) -> list:
        params = {
            "q": address,
            "format": "jsonv2",
            "limit": "1",
            "countrycodes": "br",
        }
        if viewbox:
            params.update({"viewbox": viewbox, "bounded": "1"})
        return self.client.get_json(self.endpoint, params=params)

    def _first_match(self, queries: list[str]) -> list:
        for query in queries:
            payload = self._search(query, viewbox=FOCUS_VIEWBOX) or self._search(query)
            if payload:
                return payload
        return []
