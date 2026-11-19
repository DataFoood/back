# Conversa premium e fotos reais

- Premium com consentimento pode iniciar por “Sugira algo pelos meus gostos”.
  Sem consentimento ou histórico, recebe orientação útil, sem inventar um perfil.
- Preferências ordenam opções; filtros explícitos continuam tendo precedência.
- Explicação da personalização usa somente afinidades reais com o primeiro
  candidato. Os próximos passos sugerem tags presentes na seleção ou retiram
  filtros que não deram resultado. O cliente pode abrir os cards a qualquer hora.
- Free continua conversando sem receber dados pessoais. Nenhum modelo novo,
  treinamento, migração ou aumento do contexto do Ollama.
- Front apresenta os próximos passos somente no último turno, bloqueia cliques
  durante envio e mantém compatibilidade com mensagens antigas.
- Fotos continuam sendo URLs reais de capa/galeria, com cadastro pelo admin ou
  painel. O lote OSM não contém imagens. Documentar o processo e facilitar a
  galeria no admin, sem fotos genéricas nem coleta automática por nome.

Validar início personalizado, consentimento, perfil vazio, precedência dos
filtros, refinamentos disponíveis, recuperação sem resultados e uso no navegador.

Validação local: 338 testes Django e 16 regressões de segurança passaram em
Linux, OpenAPI validado sem avisos e nenhuma migração pendente. O teste do início
pelos gostos e dos refinamentos falhou antes da implementação. A revisão também
reproduziu e corrigiu a retirada da faixa “Premium”, sem confundir plano com preço.

Frontend: 69 verificações de conversa em Chromium (390, 1440 e 320 pixels) e
16 de cupom/consentimento, tipos, lint, testes de configuração e build de produção
aprovados. APIs/inferência simuladas nos testes de navegador; banco real e
inferência simulada na suíte Django. O navegador local não tinha DevTools MCP;
foi usado o Playwright já existente, em perfil isolado. O dev com Turbopack teve
uma falha local de resolução de picocolors; a navegação foi conferida com webpack
e o build padrão com Turbopack passou. Dependências e lockfiles não foram alterados.

Pendente: ensaio da nova conversa premium no Ollama da VPS, com conta autorizada.
Nenhuma foto foi cadastrada: os arquivos/URLs reais precisam ser fornecidos e
confirmados por unidade. A galeria administrativa usa o modelo existente.
