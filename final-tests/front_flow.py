"""Fluxos do front (dtfd_fte) contra a API rodando: mesmos paths e bodies do
`lib/api` dele. Cobre proximidade, métricas do dono e console admin.

Pré-requisitos: API em API_URL, Ollama (real ou fake_ollama.py) e Nominatim
falso (NOMINATIM_URL=http://127.0.0.1:11600 + fake_nominatim.py) — senão o
geocoding bate no OSM. Superuser admin-fte@fte.test / SenhaForte123:
    DJANGO_SUPERUSER_PASSWORD=SenhaForte123 python manage.py createsuperuser \
        --noinput --email admin-fte@fte.test --name "Admin Fte"
Uso: uv run python final-tests/front_flow.py
"""
import os
import sys
import uuid

import httpx

API = os.environ.get("API_URL", "http://127.0.0.1:8000")
ok = fail = 0
def check(cond, label, extra=""):
    global ok, fail
    ok, fail = ok + bool(cond), fail + (not cond)
    print(("  ✓ " if cond else "  ✗ ") + label + ("" if cond else f"  -> {extra}"))

c = httpx.Client(base_url=API, timeout=30)
def auth(t): return {"Authorization": f"Bearer {t['access']}"}
tag = uuid.uuid4().hex[:6]
PWD = "SenhaForte123"

print("auth")
r = c.post("/api/users/register/", json={"name": "Dono Fte", "email": f"dono-{tag}@fte.test", "password": PWD, "confirm_password": PWD, "account_type": "owner"})
check(r.status_code == 201 and {"access", "refresh", "user"} <= r.json().keys(), "register devolve tokens + user (front já entra)", r.text)
owner = r.json()
check(c.get("/api/users/me/", headers=auth(owner)).json()["role"] == "owner", "GET /me/")
r = c.post("/api/users/register/", json={"name": "Cliente Fte", "email": f"cli-{tag}@fte.test", "password": PWD, "confirm_password": PWD})
cli = r.json()

print("dono: cadastro + endereço geocodificado")
tax = c.get("/api/restaurants/taxonomies/").json()
check(len(tax["cuisines"]) > 5, "taxonomias (catálogo do form)")
r = c.post("/api/restaurants/", headers=auth(owner), json={"name": f"Cantina Fte {tag}", "description": "massas frescas e vinho, ambiente tranquilo", "phone": "14999990000"})
check(r.status_code == 201, "POST restaurante", r.text)
rid = r.json()["id"]
r = c.patch(f"/api/restaurants/{rid}/", headers=auth(owner), json={"cuisines": [tax["cuisines"][0]["id"]], "has_dine_in": True})
check(r.status_code == 200 and r.json()["cuisines"], "PATCH taxonomias/flags", r.text)
r = c.post("/api/addresses/", headers=auth(owner), json={"entity_type": "restaurant", "object_id": rid, "street": "Rua Nove de Julho", "number": "100", "neighborhood": "Centro", "city": "Marília", "state": "SP", "zipcode": "17500-000", "is_default": True})
check(r.status_code == 201, "POST endereço", r.text)
addr = [a for a in c.get("/api/addresses/", headers=auth(owner)).json() if a["object_id"] == rid][0]
check(addr["latitude"] is not None, "endereço geocodificado (Nominatim falso, eager)", addr)
r = c.post(f"/api/restaurants/{rid}/hours/", headers=auth(owner), json={"day_week": 0, "is_closed": False, "meta_interval": {"open": ["11:00", "22:00"]}})
check(r.status_code == 201, "horário formato do editor {open: [hh:mm, hh:mm]}", r.text)
mine = c.get("/api/restaurants/mine/", headers=auth(owner)).json()
check([m["id"] for m in mine] == [rid], "GET /mine/")

print("admin")
r = c.post("/api/users/login/", json={"email": "admin-fte@fte.test", "password": PWD})
check(r.status_code == 200 and r.json()["user"]["role"] == "admin", "superuser entra com role admin", r.text)
adm = r.json()
r = c.post(f"/api/restaurants/{rid}/reindex/", headers=auth(adm))
check(r.status_code == 202, "reindex (embedding gerado, eager)", r.text)
w = c.get("/api/preferences/weights/", headers=auth(adm)).json()
check(set(w) == {"semantic", "preference", "review", "distance"}, "GET pesos", w)
check(c.patch("/api/preferences/weights/", headers=auth(adm), json={"distance": 0.8}).json()["distance"] == 0.8, "PATCH peso distância")
c.patch("/api/preferences/weights/", headers=auth(adm), json={"distance": 0.5})

print("cliente: busca perto de mim -> clique -> métricas do dono")
body = {"query": "massas e vinho num lugar tranquilo", "limit": 3, "lat": -22.214, "lon": -49.946, "radius_km": 5}
r = c.post("/api/search/", headers=auth(cli), json=body)
res = r.json().get("results", [])
hit = next((x for x in res if x["restaurant"]["id"] == rid), None)
check(r.status_code == 200 and hit is not None, "busca acha o restaurante dentro do raio", r.text[:300])
check(hit and hit["distance_km"] is not None and hit["distance_km"] < 1, "distance_km no resultado", hit)
check(hit and isinstance(hit["match"], int), "match 0-100", hit)
r = c.post("/api/search/", headers=auth(cli), json={**body, "lat": -23.55, "lon": -46.63})
check(all(x["restaurant"]["id"] != rid for x in r.json()["results"]), "fora do raio (São Paulo) não aparece")
r = c.get(f"/api/restaurants/{rid}/", headers=auth(cli), params={"src": "search", "lat": "-22.21", "lon": "-49.95"})
check(r.status_code == 200 and r.json()["address"]["latitude"], "detalhe com ?src=search&lat&lon")
near = c.get("/api/restaurants/", params={"lat": -22.214, "lon": -49.946, "ordering": "distance", "radius_km": 5}).json()
check(any(x["id"] == rid and x["distance_km"] is not None for x in near["results"]), "catálogo perto de mim (ordering=distance)")

st = c.get(f"/api/restaurants/{rid}/stats/", headers=auth(owner)).json()
check(st["views_window"] == 1 and st["search_clicks_window"] == 1, "stats: 1 visita, 1 clique vindo da busca", st)
check(st["search_impressions_window"] >= 1, "stats: impressão na busca", st)
check(st["regions"] and st["regions"][0]["label"] == "Centro, Marília", "stats: região rotulada (reverse falso)", st["regions"])
check(c.get(f"/api/restaurants/{rid}/stats/", headers=auth(cli)).status_code == 403, "cliente não vê stats alheias")

print("admin: métricas, usuários, moderação")
m = c.get("/api/analytics/platform/", headers=auth(adm)).json()
check(m["searches_window"] >= 2, "plataforma conta buscas", m)
u = c.get("/api/users/", headers=auth(adm), params={"q": f"cli-{tag}"}).json()["results"]
check(len(u) == 1, "busca de usuário ?q=")
r = c.patch(f"/api/users/{u[0]['id']}/admin/", headers=auth(adm), json={"is_active": False})
check(r.status_code == 200 and r.json()["is_active"] is False, "desativa conta")
check(c.post("/api/users/login/refresh/", json={"refresh": cli["refresh"]}).status_code == 401, "refresh do desativado morre")
c.patch(f"/api/users/{u[0]['id']}/admin/", headers=auth(adm), json={"is_active": True})
c.delete(f"/api/restaurants/{rid}/", headers=auth(adm))
gone = c.get("/api/restaurants/admin/", headers=auth(adm), params={"deleted": "true", "q": tag}).json()["results"]
check([g["id"] for g in gone] == [rid], "moderação lista removido")
check(c.post(f"/api/restaurants/{rid}/restore/", headers=auth(adm)).status_code == 200, "restaura")

print("sessão")
r = c.post(f"/api/users/{owner['user']['id']}/change-password/", headers=auth(owner), json={"current_password": PWD, "new_password": "OutraSenha456", "confirm_password": "OutraSenha456"})
check(r.status_code == 200 and "access" in r.json(), "troca de senha devolve par novo (front grava)", r.text)
new = r.json()
check(c.post("/api/users/logout/", json={"refresh": new["refresh"]}).status_code == 204, "logout blacklist")
check(c.post("/api/users/login/refresh/", json={"refresh": new["refresh"]}).status_code == 401, "refresh pós-logout inválido")

print(f"\n{ok}/{ok + fail} checagens ok")
sys.exit(1 if fail else 0)
