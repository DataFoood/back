<div align="center">

<img src="assets/logo_bg_none.png" alt="DataFood" width="180"/>

# DataFood

**Plataforma de descoberta de restaurantes com busca semântica.**

[![Python](https://img.shields.io/badge/Python-3.12-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![Django](https://img.shields.io/badge/Django-6.0-092E20?style=flat-square&logo=django&logoColor=white)](https://www.djangoproject.com/)
[![DRF](https://img.shields.io/badge/DRF-3.17-A30000?style=flat-square&logo=django&logoColor=white)](https://www.django-rest-framework.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.138-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-4169E1?style=flat-square&logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![pgvector](https://img.shields.io/badge/pgvector-vetorial-4169E1?style=flat-square&logo=postgresql&logoColor=white)](https://github.com/pgvector/pgvector)
[![Redis](https://img.shields.io/badge/Redis-broker%2Fcache-DC382D?style=flat-square&logo=redis&logoColor=white)](https://redis.io/)
[![Celery](https://img.shields.io/badge/Celery-async-37814A?style=flat-square&logo=celery&logoColor=white)](https://docs.celeryq.dev/)
[![Ollama](https://img.shields.io/badge/Ollama-embeddings-000000?style=flat-square&logo=ollama&logoColor=white)](https://ollama.com/)
[![JWT](https://img.shields.io/badge/Auth-JWT-000000?style=flat-square&logo=jsonwebtokens&logoColor=white)](https://jwt.io/)
[![Docker](https://img.shields.io/badge/Docker-compose-2496ED?style=flat-square&logo=docker&logoColor=white)](https://www.docker.com/)

</div>

---

## O que é

DataFood ajuda o usuário a encontrar onde comer a partir de uma busca em
linguagem natural ("lugar tranquilo pra comer feijoada"). Combina cadastro de
restaurantes, avaliações e favoritos com um motor de **busca semântica** que
entende intenção e personaliza o resultado pelas preferências de cada usuário.

A API REST entrega:

- Contas, autenticação JWT e perfis.
- Restaurantes, cardápio, avaliações, horários, favoritos e endereços.
- Busca semântica personalizada e ranqueada.
- Preferências do usuário derivadas do comportamento.

Documentação interativa da API em `/api/docs/` (Swagger). Visão de arquitetura e
módulos na pasta [`docs/`](docs/).

---

## Como rodar

Tudo roda em containers — o passo a passo é o mesmo em **Linux, macOS e
Windows**. A única diferença é a instalação do Docker e um comando de cópia.

### Pré-requisitos

- **Docker** + **Docker Compose v2**
  - **Linux:** [Docker Engine](https://docs.docker.com/engine/install/)
  - **macOS / Windows:** [Docker Desktop](https://www.docker.com/products/docker-desktop/) (no Windows, recomendado com WSL 2)
- **Git**

> Não precisa instalar Python, Postgres, Redis nem Ollama na máquina — o Compose
> sobe tudo.

### 1. Clonar

```bash
git clone <url-do-repositorio>
cd dtfd_bke
```

### 2. Criar o `.env`

A partir do template. Edite os segredos (`SECRET_KEY`, `SHINZOU_SERVICE_TOKEN`)
antes de subir.

**Linux / macOS:**
```bash
cp .env.example .env
```

**Windows (PowerShell):**
```powershell
Copy-Item .env.example .env
```

**Windows (CMD):**
```cmd
copy .env.example .env
```

### 3. Subir

```bash
docker compose up -d --build
```

A primeira subida baixa o modelo de embeddings no Ollama — pode demorar alguns
minutos. As subidas seguintes são rápidas.

### 4. Acessar

| Recurso | URL |
|---|---|
| API | http://localhost:8000 |
| Swagger (docs) | http://localhost:8000/api/docs/ |
| Django Admin | http://localhost:8000/admin/ |

Para criar um usuário admin:

```bash
docker compose exec -w /app/dtfd web uv run python manage.py createsuperuser
```

### Parar

```bash
docker compose down            # mantém os dados
docker compose down -v         # apaga os volumes (zera o banco)
```

> **Windows:** rode os comandos `docker compose` no PowerShell, CMD ou num
> terminal WSL — todos funcionam.

---

## Coleção de testes (API)

`postman_collection.json` na raiz: importe no Postman, rode **"Login (salva
tokens)"** e o token é injetado automaticamente nas demais requisições.

---

## Manutenção

Mantido e atualizado por **Estevão Santos**, com **Claude Opus** como
co-autor.
