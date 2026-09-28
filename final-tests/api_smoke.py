"""Smoke test de integração contra a API rodando (fim a fim, sem mocks).

Percorre os mesmos fluxos que o frontend usa — visitante, cliente e dono —
e as checagens de segurança que dependem do stack real (CORS, rotação de
refresh, blacklist, revogação de sessão, isolamento entre contas).

Pré-requisito: API em API_URL (default http://localhost:8000) com o seed de
demonstração (`seed_demo --demo-users` + `reindex_restaurants`). A busca
semântica aceita 200 (shinzou + Ollama de pé) ou 503 (indisponível) — o
script informa qual foi.

Uso:
    uv run python final-tests/api_smoke.py
    API_URL=https://api.seudominio.com.br uv run python final-tests/api_smoke.py

Cria contas descartáveis (e-mail aleatório @smoke.test) e as encerra no fim.
Faz 2 logins: rodar duas vezes seguidas pode bater no limite de 5/min.
Sai com código 1 se alguma checagem falhar.
"""

import os
import sys
import uuid

import httpx

API = os.environ.get("API_URL", "http://localhost:8000").rstrip("/")
FRONT_ORIGIN = os.environ.get("FRONT_ORIGIN", "http://localhost:3000")
PASSWORD = "Smoke@Teste123"
DEMO_PASSWORD = "Demo@12345"

client = httpx.Client(base_url=API, timeout=90)
results: list[tuple[bool, str]] = []


def check(ok: bool, label: str, detail: object = "") -> bool:
    results.append((ok, label))
    mark = "\033[32m✓\033[0m" if ok else "\033[31m✗\033[0m"
    print(f"  {mark} {label}" + (f"  [{detail}]" if detail != "" and not ok else ""))
    return ok


def section(title: str) -> None:
    print(f"\n\033[1m{title}\033[0m")


def auth(access: str) -> dict:
    return {"Authorization": f"Bearer {access}"}


def register(account_type="customer", allow_info=False):
    email = f"smoke-{uuid.uuid4().hex[:10]}@smoke.test"
    r = client.post("/api/users/register/", json={
        "name": "Smoke Tester", "email": email, "password": PASSWORD,
        "confirm_password": PASSWORD, "account_type": account_type, "allow_info": allow_info,
    })
    return email, r


def main() -> int:
    section("infra")
    r = client.get("/api/health/")
    check(r.status_code == 200 and r.json().get("db") is True, "health com banco", r.text)
    r = client.options("/api/restaurants/", headers={
        "Origin": FRONT_ORIGIN, "Access-Control-Request-Method": "GET",
        "Access-Control-Request-Headers": "authorization,content-type",
    })
    check(r.headers.get("access-control-allow-origin") == FRONT_ORIGIN, f"CORS libera {FRONT_ORIGIN}", r.headers)
    r = client.options("/api/restaurants/", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"})
    check("access-control-allow-origin" not in r.headers, "CORS nega origem desconhecida")

    section("visitante (sem login)")
    tax = client.get("/api/restaurants/taxonomies/").json()
    check(set(tax) >= {"cuisines", "ambients", "price_ranges"}, "taxonomias")
    page = client.get("/api/restaurants/", params={"ordering": "rating", "page_size": 3}).json()
    check(page["count"] > 0 and len(page["results"]) <= 3, "lista paginada (seed carregado?)", page.get("count"))
    card = page["results"][0]
    check({"slug", "address", "is_open_now", "is_favorited"} <= set(card), "card tem o contrato do front")
    check(card["is_favorited"] is False, "anônimo nunca vê favorito")
    if tax["cuisines"]:
        cid = tax["cuisines"][0]["id"]
        filtered = client.get("/api/restaurants/", params={"cuisine": cid}).json()
        check(all(any(c["id"] == cid for c in r["cuisines"]) for r in filtered["results"]), "filtro por cozinha")
    r = client.get("/api/restaurants/", params={"page_size": 500})
    check(len(r.json()["results"]) <= 50, "page_size limitado a 50")
    detail = client.get(f"/api/restaurants/by-slug/{card['slug']}/").json()
    check(detail["id"] == card["id"] and "reviews" in detail, "detalhe por slug")
    check(client.get("/api/restaurants/by-slug/nao-existe-xyz/").status_code == 404, "slug inexistente -> 404")
    for method, path in [("get", "/api/users/me/"), ("get", "/api/restaurants/favorites/"),
                         ("post", "/api/search/"), ("get", "/api/preferences/"),
                         ("post", f"/api/restaurants/{card['id']}/favorite/"), ("get", "/api/addresses/")]:
        check(getattr(client, method)(path).status_code == 401, f"{method.upper()} {path} exige login")

    section("cliente")
    email, r = register(allow_info=True)
    check(r.status_code == 201 and {"access", "refresh", "user"} <= set(r.json()), "cadastro já autentica", r.text)
    tokens = r.json()
    user = tokens["user"]
    h = auth(tokens["access"])
    check(user["role"] == "customer" and user["allow_info"] is True, "role/consentimento do cadastro")
    check(client.get("/api/users/me/", headers=h).json()["email"] == email, "GET me")
    r = client.post("/api/users/login/refresh/", json={"refresh": tokens["refresh"]})
    rotated = r.json()
    check(r.status_code == 200 and rotated["refresh"] != tokens["refresh"], "refresh rotaciona")
    check(client.post("/api/users/login/refresh/", json={"refresh": tokens["refresh"]}).status_code == 401,
          "refresh antigo vai pra blacklist")
    check(client.get("/api/users/me/", headers=auth(rotated["refresh"])).status_code == 401,
          "refresh não serve como access")
    h = auth(rotated["access"])
    tokens.update(rotated)

    rid = card["id"]
    r1 = client.post(f"/api/restaurants/{rid}/favorite/", headers=h)
    r2 = client.post(f"/api/restaurants/{rid}/favorite/", headers=h)
    check((r1.status_code, r2.status_code) == (201, 200), "favoritar é idempotente", (r1.status_code, r2.status_code))
    favs = client.get("/api/restaurants/favorites/", headers=h).json()
    check([f["restaurant"]["id"] for f in favs] == [rid], "lista de favoritos")
    check(client.get(f"/api/restaurants/by-slug/{card['slug']}/", headers=h).json()["is_favorited"], "detalhe marca favorito")
    check(client.delete(f"/api/restaurants/{rid}/favorite/", headers=h).status_code == 204, "desfavoritar")

    r = client.post("/api/search/", headers=h, json={"query": "jantar tranquilo com vinho", "limit": 6})
    if r.status_code == 200:
        res = r.json()["results"]
        check(len(res) <= 6 and all(0 <= (x["match"] or 0) <= 100 for x in res), f"busca semântica ({len(res)} resultados)")
        hist = client.get("/api/preferences/searches/", headers=h).json()
        check(any(x["query"] == "jantar tranquilo com vinho" for x in hist), "com consentimento a busca vai pro histórico")
    else:
        check(r.status_code == 503, "busca indisponível responde 503 (fallback do front)", r.status_code)
    check(client.post("/api/search/", headers=h, json={"query": " "}).status_code == 400, "busca vazia -> 400")
    check(client.post("/api/search/", headers=h, json={"query": "x", "limit": "abc"}).status_code == 400, "limit inválido -> 400")

    r = client.post(f"/api/restaurants/{rid}/reviews/", headers=h, json={"rating": 5, "title": "ótimo", "description": "smoke"})
    check(r.status_code == 201 and r.json()["author_name"] == "Smoke", "avaliar (autor só com primeiro nome)", r.text)
    review_id = r.json().get("id")
    check(client.post(f"/api/restaurants/{rid}/reviews/", headers=h, json={"rating": 4}).status_code == 400,
          "uma avaliação por pessoa")
    check(client.delete(f"/api/restaurants/{rid}/reviews/{review_id}/", headers=h).status_code == 204, "excluir a própria avaliação")

    r = client.patch("/api/users/me/", headers=h, json={"phone": "14991234567", "role": "admin", "is_staff": True})
    me = client.get("/api/users/me/", headers=h).json()
    check(r.status_code == 200 and me["phone"] == "14991234567" and me["role"] == "customer", "PATCH me sem escalar privilégio")
    r = client.patch("/api/users/consent/", headers=h, json={"allow_info": False})
    check(r.json() == {"allow_info": False}, "desligar consentimento (LGPD)")
    check(client.patch("/api/users/consent/", headers=h, json={"allow_info": "sim"}).status_code == 400, "consentimento só booleano")
    prefs = client.get("/api/preferences/", headers=h).json()
    check(set(prefs) == {"cuisines", "ambients", "price_ranges"}, "afinidades")

    section("dono")
    demo = client.post("/api/users/login/", json={"email": "dono@datafood.demo", "password": DEMO_PASSWORD})
    if check(demo.status_code == 200, "login do dono demo", demo.status_code):
        dh = auth(demo.json()["access"])
        mine = client.get("/api/restaurants/mine/", headers=dh).json()
        check(len(mine) > 0, "meus restaurantes")
        stats = client.get(f"/api/restaurants/{mine[0]['id']}/stats/", headers=dh).json()
        before = stats["view_count"]
        client.get(f"/api/restaurants/{mine[0]['id']}/", headers=dh)
        after = client.get(f"/api/restaurants/{mine[0]['id']}/stats/", headers=dh).json()["view_count"]
        check(after == before, "dono não infla as próprias visualizações", (before, after))
        check(len(stats["series"]) == stats["window_days"], "série diária do painel")
        check(client.get(f"/api/restaurants/{mine[0]['id']}/stats/", headers=h).status_code == 403,
              "cliente não vê métricas de outro")
        check(client.patch(f"/api/restaurants/{mine[0]['id']}/", headers=h, json={"name": "hack"}).status_code == 403,
              "cliente não edita restaurante alheio")

    email2, r = register(account_type="customer")
    owner = r.json()
    oh = auth(owner["access"])
    r = client.post("/api/restaurants/", headers=oh, json={"name": f"Smoke Bistrô {uuid.uuid4().hex[:4]}", "description": "teste", "phone": "1433334444"})
    check(r.status_code == 201, "cadastrar restaurante", r.text)
    new_id = r.json()["id"]
    check(client.get("/api/users/me/", headers=oh).json()["role"] == "owner", "customer vira owner ao cadastrar")
    detail = client.patch(f"/api/restaurants/{new_id}/", headers=oh, json={
        "cuisines": [tax["cuisines"][0]["id"]], "price_ranges": [tax["price_ranges"][0]["id"]], "has_delivery": True,
    })
    check(detail.status_code == 200 and detail.json()["has_delivery"] is True and "items" in detail.json(),
          "PATCH devolve a representação de leitura")
    codes = [client.post(f"/api/restaurants/{new_id}/items/", headers=oh, json={"name": f"prato {i}", "price": "10.50"}).status_code
             for i in range(7)]
    check(codes == [201] * 6 + [400], "máximo de 6 pratos", codes)
    hours = [client.post(f"/api/restaurants/{new_id}/hours/", headers=oh, json={
        "day_week": d, "is_closed": False, "meta_interval": {"turno1": ["11:00:00", "23:59:59"]}}).status_code for d in range(7)]
    check(hours == [201] * 7, "horários da semana", hours)
    bad = client.post(f"/api/restaurants/{new_id}/hours/", headers=oh, json={"day_week": 0, "meta_interval": {"x": ["12:00:00", "11:00:00"]}})
    check(bad.status_code == 400, "horário invertido rejeitado")
    addr = client.post("/api/addresses/", headers=oh, json={
        "entity_type": "restaurant", "object_id": new_id, "street": "Av. Sampaio Vidal", "number": "100",
        "neighborhood": "Centro", "city": "Marília", "state": "SP", "zipcode": "17500-020", "is_default": True})
    check(addr.status_code == 201, "endereço do restaurante", addr.text)
    img = client.post(f"/api/restaurants/{new_id}/images/", headers=oh, json={"url": "https://images.example.com/capa.jpg"})
    check(img.status_code == 201, "adicionar foto")
    check(client.post(f"/api/restaurants/{new_id}/images/", headers=oh, json={"url": "javascript:alert(1)"}).status_code == 400,
          "URL javascript: rejeitada")
    pub = client.get(f"/api/restaurants/{new_id}/").json()
    check(pub["address"] and pub["address"]["city"] == "Marília" and pub["is_open_now"] is not None, "página pública completa")
    check(client.get("/api/addresses/", headers=h).json() == [], "endereços de outro dono não vazam")
    check(client.delete(f"/api/restaurants/{new_id}/", headers=oh).status_code == 204, "remover restaurante (soft)")
    check(client.get(f"/api/restaurants/{new_id}/").status_code == 404, "restaurante removido some")

    section("sessão e conta")
    other_device = client.post("/api/users/login/", json={"email": email, "password": PASSWORD}).json()
    r = client.post(f"/api/users/{user['id']}/change-password/", headers=h, json={
        "current_password": PASSWORD, "new_password": "Smoke@Nova456", "confirm_password": "Smoke@Nova456"})
    check(r.status_code == 200 and "refresh" in r.json(), "trocar senha devolve par novo", r.text)
    check(client.post("/api/users/login/refresh/", json={"refresh": other_device["refresh"]}).status_code == 401,
          "troca de senha derruba outras sessões")
    new_pair = r.json()
    check(client.post("/api/users/login/refresh/", json={"refresh": new_pair["refresh"]}).status_code == 200,
          "sessão atual continua")
    check(client.post("/api/users/logout/", json={"refresh": owner["refresh"]}).status_code == 204, "logout")
    check(client.post("/api/users/login/refresh/", json={"refresh": owner["refresh"]}).status_code == 401, "refresh pós-logout inválido")

    section("limpeza")
    # usa os tokens já emitidos: logar de novo esbarraria no rate limit (5/min)
    for uid, mail, access, refresh in [(user["id"], email, new_pair["access"], new_pair["refresh"]),
                                       (owner["user"]["id"], email2, owner["access"], None)]:
        r = client.delete(f"/api/users/{uid}/delete/", headers=auth(access))
        check(r.status_code == 204, f"encerrar conta {mail}")
        if refresh:
            check(client.post("/api/users/login/refresh/", json={"refresh": refresh}).status_code == 401,
                  "refresh de conta encerrada -> 401")
        check(client.get("/api/users/me/", headers=auth(access)).status_code == 401, "access de conta encerrada -> 401")

    failed = [label for ok, label in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checagens ok")
    for label in failed:
        print(f"  falhou: {label}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
