# Catálogo público de Marília

Snapshots consultados em 28/11/2026. Dados reais de fontes públicas, sem contas
demo, preços, notas ou avaliações inventados.

| Arquivo | Origem | Conteúdo |
| --- | --- | --- |
| `marilia-osm.json` | OpenStreetMap / Overpass | 54 objetos, 49 com nome e coordenadas válidas |
| `marilia-tourism.json` | Diretório de Turismo da Prefeitura de Marília | 152 registros de alimentação, todos com imagem vinculada; 143 com endereço extraído |

Os registros de origem podem representar o mesmo estabelecimento. Na carga
local vazia, a união conservadora resultou em **194 cadastros**, **151 com capa**
e **185 com endereço**. Há 6 registros sinalizados para revisão de nomes
coincidentes. Esses números não comprovam que todos os cadastros são negócios
distintos ou que continuam operando. A segunda carga não criou duplicatas.

## Carregar sem rede

```bash
cd back
uv run python dtfd/manage.py migrate
uv run python dtfd/manage.py load_catalog
```

No container atualizado, `docker compose exec web uv run python manage.py load_catalog`.
A imagem inclui `catalog/`. A carga não é automática na inicialização e não
apaga o catálogo existente. Atualizações do dono e registros removidos são
preservados. Restaurantes demo permanecem sujeitos a `SHOW_DEMO_RESTAURANTS`.
Para a rota vetorial, execute `reindex_restaurants` após a importação.

O diretório turístico fornece imagens, contato, endereço, categorias e textos
de horários. Só os formatos de horários representáveis com segurança viram
horários estruturados; o texto da fonte aparece no detalhe nos outros casos.
O orçamento do chat só é confirmado quando há prato com preço cadastrado.

## Atualizar manualmente

```bash
python scripts/fetch_tourism_catalog.py --output catalog/marilia-tourism.json
uv run python dtfd/manage.py import_osm   # consulta atual ao Overpass
uv run python dtfd/manage.py load_catalog
```

Para atualizar também o snapshot OSM, salve a resposta da consulta `QUERY` de
`restaurants/catalog/osm.py` em `marilia-osm.json` e revise os dados antes de
versionar. `load_catalog` reaplica o snapshot versionado; não o execute depois
de uma carga OSM mais recente sem atualizar também esse arquivo.

O coletor turístico faz uma requisição por segundo, em páginas públicas do
domínio oficial. É uma execução manual, sem agendamento ou consulta por busca
do usuário. Categorias com mais de 100 registros exigem revisão do coletor.

Para sites específicos, a ferramenta opcional abaixo lê somente metadados
públicos de hosts HTTPS expressamente autorizados:

```bash
uv run python dtfd/manage.py enrich_catalog --allow-host www.freakburguer.com.br --limit 1
```

## Procedência e imagens

- Dados OSM: © OpenStreetMap contributors, ODbL-1.0, com link por objeto.
- Diretório turístico: https://turismo.marilia.sp.gov.br/-onde-comer-e-beber/
- Fotos: URLs das páginas de origem; os arquivos não são copiados para este
  repositório. Atribuição e página de origem aparecem na API e na galeria.
- A licença das fotos não é presumida ODbL. O campo `license` permanece vazio
  quando a fonte não declara uma licença específica. Antes de uma operação
  pública, confirmar as condições de uso e priorizar fotos fornecidas/autorizadas
  pelos donos. URLs podem mudar e devem ser revistas.
- Os 43 cadastros sem capa continuam com ilustração identificada. Uma foto da
  galeria vira capa na API mesmo se o campo de capa estiver vazio.

As fontes externas não verificam titularidade. A união entre fontes exige
evidência adicional de endereço/telefone e nome compatível; filiais com
endereços conflitantes são preservadas separadamente.
