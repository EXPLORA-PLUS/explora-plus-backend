# Uso: docker compose exec -T [-e FIXTURE_AREAS=santos] backend python manage.py shell < tour_routes/fixtures/capture.py
# Baixa POIs reais do Overpass por categoria e salva como fixture local (com bbox de cobertura).
import json, os, time
from tour_routes.services.http import JsonHttpClient

AREAS = {
    "santos": (-23.995, -46.390, -23.925, -46.295),
    "praia_grande": (-24.065, -46.530, -23.990, -46.395),
}
FILTERS = [
    'nwr["tourism"~"museum|gallery|attraction|artwork"]',
    'nwr["historic"]',
    'nwr["amenity"~"theatre|arts_centre"]',
    'nwr["leisure"~"park|garden"]',
    'nwr["tourism"="viewpoint"]',
    'nwr["amenity"~"restaurant|cafe"]',
]
ENDPOINTS = [
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]
ONLY = os.environ.get("FIXTURE_AREAS")  # ex.: FIXTURE_AREAS=praia_grande
client = JsonHttpClient()
for area, (s, w, n, e) in AREAS.items():
    if ONLY and area not in ONLY.split(","):
        continue
    bbox = f"({s},{w},{n},{e})"
    seen = {}
    for flt in FILTERS:
        query = f"[out:json][timeout:90];\n({flt}{bbox};);\nout center tags;"
        done = False
        for attempt in range(3):
            for endpoint in ENDPOINTS:
                try:
                    data = client.post_text_json(endpoint, body=query, timeout=100)
                except Exception as exc:
                    print("  fail", area, flt[:30], endpoint.split("/")[2], repr(exc)[:60], flush=True)
                    continue
                for el in data.get("elements", []):
                    seen[(el["type"], el["id"])] = el
                print("OK", area, flt[:30], endpoint.split("/")[2], len(data.get("elements", [])), flush=True)
                done = True
                break
            if done:
                break
            time.sleep(10)
        if not done:
            print("GAVE UP", area, flt, flush=True)
    out = {"bbox": [s, w, n, e], "generator": "explora-plus fixture", "elements": list(seen.values())}
    with open(f"tour_routes/fixtures/overpass_{area}.json", "w") as fh:
        json.dump(out, fh, ensure_ascii=False)
    print("SAVED", area, len(seen), flush=True)
