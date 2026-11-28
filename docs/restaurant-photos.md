# Fotos reais no catálogo

Os 41 estabelecimentos importados de Marília não têm fotos no lote OSM.
`cover_image` é a capa e `RestaurantImage.url` alimenta a galeria. Não é
necessário gerar embeddings, usar a IA ou hospedar os arquivos na VPS.

## Para a apresentação

1. Separe fotos próprias ou autorizadas de cinco a dez estabelecimentos que
   serão usados na demonstração. Confira nome, endereço e filial. Uma foto
   genérica da rede não comprova a unidade de Marília.
2. Hospede os arquivos em um endereço público HTTPS. Uma opção já compatível
   com o projeto é adicionar arquivos otimizados em
   `front-end/public/restaurantes/`, publicar o frontend e usar URLs como
   `https://SEU-DOMINIO/restaurantes/di-carlotta.jpg`. Esses arquivos são fotos
   reais fornecidas por você, não imagens geradas. JPG/WebP com cerca de
   1200 pixels de largura atende à capa; evite arquivos de vários megabytes.
3. Abra a URL em uma aba anônima: precisa mostrar a imagem diretamente, sem
   login. URL de página do Instagram, Google Maps ou página HTML não é imagem.
4. No Django Admin, entre em **Restaurants → Restaurants**, pesquise o local
   e confira seu endereço. Preencha **Cover image** com a URL da capa.
5. Em **Restaurant images**, adicione uma URL por foto e salve. A capa
   participa do carrossel automaticamente; não precisa repeti-la na galeria.
6. Confira a listagem e abra “Ver recomendações” no chat. Os cards consultam
   a galeria ao abrir. Uma conversa já salva usa as fotos atuais do restaurante.

Cadastros importados sem dono podem ser editados pelo admin; não é preciso
criar contas de restaurante nem transferir a propriedade para colocar fotos.
No painel de um dono existente, **Informações → Foto de capa (URL)** e o
editor de fotos oferecem as mesmas funções, respeitando as permissões.

Mantenha o crédito e a autorização junto ao arquivo original; se a licença
exigir crédito visível, publique-o na descrição do estabelecimento. Não use
uma imagem sem identificar a fonte e as condições de uso. Fotos de clientes
em mapas/redes sociais não se tornam reutilizáveis apenas por estarem públicas.

## Importação automática

O lote atual não contém `image` ou `wikimedia_commons`. Não existe fonte de
fotos reais para um preenchimento automático confiável desses 41 locais.
Uma integração futura deve resolver a unidade exata por endereço/coordenadas,
respeitar a atribuição e as condições da fonte e preservar a foto cadastrada
pelo dono. Buscar por nome e usar a primeira imagem pode associar outro local.

Reimportar o lote OSM não altera capa nem galeria. Não rode `seed_demo` para
preencher imagens de estabelecimentos reais.
