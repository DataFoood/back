# Catálogo real de Marília/SP

A fonte inicial é OpenStreetMap (município IBGE 3529005), por consulta Overpass
manual. Não é Google Places nem coleta de páginas. O endpoint público não tem
SLA: limite a frequência, não execute importação em cada busca de usuário e
respeite erros/pausas do serviço. Reimportação por ID é idempotente.

```bash
cd dtfd
uv run python manage.py migrate
uv run python manage.py import_osm --dry-run
uv run python manage.py import_osm
uv run python manage.py reindex_restaurants
```

A rede precisa permitir `overpass-api.de` por HTTPS. Para reprocessar uma
resposta Overpass obtida legitimamente para esse município:
`import_osm --file /caminho/marilia.json`. `--dry-run` cria só o registro de
execução (contagens), sem estabelecimentos. Arquivos de testes não são dados
reais e não devem ser usados para popular produção.

`RestaurantSource` conserva a referência, atribuição, licença, data da consulta
e apenas tags públicas selecionadas. Fonte: © OpenStreetMap contributors,
[ODbL 1.0](https://www.openstreetmap.org/copyright). Ao distribuir uma base
derivada, cumprir também as obrigações de licença e compartilhamento da base;
a atribuição visível sozinha não substitui essas obrigações. Manter a
proveniência ao exportar e separar dados próprios/licenciados de outras fontes.

Nenhuma avaliação, foto, preço ou horário é inventado. `opening_hours` é mantido
na fonte, sem conversão automática: até um parser validado, “aberto agora” não
é informado para importados sem cadastro de horários. Telefone não comprova
WhatsApp. Mesmo nome gera revisão de duplicata; não há fusão automática.
Filiais com IDs distintos permanecem distintas. Donos mantêm precedência no
cadastro, mas a fonte continua atualizada. Reimportação não ressuscita registro
removido. Reivindicar um cadastro exige intervenção de admin/verificação da
empresa; conhecer um ID do OSM não concede propriedade.

`is_demo` marca dados do protótipo. A migração identifica registros legados
somente quando slug, nome e descrição correspondem exatamente ao seed; revisar
manualmente registros demo editados. `SHOW_DEMO_RESTAURANTS` é False por padrão
em produção; em desenvolvimento segue DEBUG. Nunca use `seed_demo --demo-users`
em produção. Catálogo real não deve herdar os preços e descrições do seed.

O importador é uma operação administrativa; não há endpoint público que cause
consultas externas/custo. `CatalogImport` registra status e contagens para
acompanhamento. Uma falha parcial pode ser retomada reexecutando o mesmo lote.

## Localização e recuperação de busca

A listagem aceita `city`, `lat`, `lon`, `radius_km` (0 < raio ≤ 100 km) e
`ordering=distance`. Coordenadas precisam vir em par; valores não finitos são
recusados. Distância é geodésica aproximada em km, calculada antes de ordenar
e paginar. Registros sem coordenadas não entram em buscas por raio.

POST `/api/search/` aceita os mesmos campos de localização. O Django limita
os candidatos e o shinzou aplica esse conjunto antes do kNN; a hidratação
revalida os IDs permitidos. Se o motor estiver indisponível, a API responde
200 com `mode=text`, `notice` e resultados textuais sem `match`, preservando
localização e filtros. `mode=semantic` continua usando o motor de embeddings.
Não interpretar similaridade como probabilidade de satisfação.
