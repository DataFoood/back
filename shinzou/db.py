"""Acesso ao Postgres do Django via SQL puro (psycopg2). shinzou não importa
models Django — lê as tabelas direto.

Conexões vêm de um pool (quentes, reusadas). O ciclo de vida é gerido pela
rota via Depends(get_db): uma conexão por request, passada às funções."""

import psycopg2
import psycopg2.extras
from psycopg2.pool import ThreadedConnectionPool

from .config import settings

_pool = ThreadedConnectionPool(
    minconn=1,
    maxconn=settings.DB_POOL_MAX,
    dbname=settings.DB_NAME,
    user=settings.DB_USER,
    password=settings.DB_PASS,
    host=settings.DB_HOST,
    port=settings.DB_PORT,
)


def get_db():
    """Dependency do FastAPI: pega uma conexão do pool e devolve no fim."""
    conn = _pool.getconn()
    try:
        yield conn
    finally:
        _pool.putconn(conn)


def _vec_literal(vector: list[float]) -> str:
    return "[" + ",".join(str(x) for x in vector) + "]"


def knn_candidates(conn, vector: list[float], pool: int) -> list[tuple[int, float]]:
    """kNN no pgvector. Retorna [(restaurant_id, similaridade 0..1)].
    Ignora restaurantes soft-deleted."""
    vec = _vec_literal(vector)
    sql = """
        SELECT e.restaurant_id, 1 - (e.embedding <=> %s::vector) AS similarity
        FROM embeddings_restaurantembedding e
        JOIN restaurants_restaurant r ON r.id = e.restaurant_id
        WHERE r.deleted_at IS NULL
        ORDER BY e.embedding <=> %s::vector
        LIMIT %s
    """
    with conn.cursor() as cur:
        cur.execute(sql, (vec, vec, pool))
        return [(row[0], float(row[1])) for row in cur.fetchall()]


def _m2m_map(cur, table: str, value_col: str, restaurant_ids: list[int]) -> dict[int, set[int]]:
    cur.execute(
        f"SELECT restaurant_id, {value_col} FROM {table} WHERE restaurant_id = ANY(%s)",
        (restaurant_ids,),
    )
    out: dict[int, set[int]] = {}
    for rid, vid in cur.fetchall():
        out.setdefault(rid, set()).add(vid)
    return out


def restaurant_signals(conn, restaurant_ids: list[int]) -> dict:
    """Taxonomias (cuisine/ambient/price ids) + rating por restaurante."""
    with conn.cursor() as cur:
        cuisines = _m2m_map(cur, "restaurants_restaurant_cuisines", "cuisine_id", restaurant_ids)
        ambients = _m2m_map(cur, "restaurants_restaurant_ambients", "ambient_id", restaurant_ids)
        prices = _m2m_map(cur, "restaurants_restaurant_price_ranges", "pricerange_id", restaurant_ids)
        cur.execute(
            "SELECT id, average_rating FROM restaurants_restaurant WHERE id = ANY(%s)",
            (restaurant_ids,),
        )
        ratings = {row[0]: float(row[1]) for row in cur.fetchall()}
    return {"cuisines": cuisines, "ambients": ambients, "prices": prices, "ratings": ratings}


def user_affinities(conn, user_id: int) -> dict:
    """{dimensão: {valor_id: score}} pro usuário."""
    queries = {
        "cuisines": ("preferences_usercuisineaffinity", "cuisine_id"),
        "ambients": ("preferences_userambientaffinity", "ambient_id"),
        "prices": ("preferences_userpriceaffinity", "price_range_id"),
    }
    out: dict[str, dict[int, float]] = {}
    with conn.cursor() as cur:
        for key, (table, col) in queries.items():
            cur.execute(f"SELECT {col}, score FROM {table} WHERE user_id = %s", (user_id,))
            out[key] = {row[0]: float(row[1]) for row in cur.fetchall()}
    return out


def ranking_weights(conn) -> dict[str, float]:
    """Pesos gerenciáveis do ranking (tabela editável no admin Django)."""
    with conn.cursor() as cur:
        cur.execute("SELECT key, weight FROM preferences_rankingweight")
        return {row[0]: float(row[1]) for row in cur.fetchall()}


def hydrate(conn, restaurant_ids: list[int]) -> dict[int, dict]:
    """Dados básicos pra resposta."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT id, name, slug, average_rating FROM restaurants_restaurant WHERE id = ANY(%s)",
            (restaurant_ids,),
        )
        return {row["id"]: dict(row) for row in cur.fetchall()}
