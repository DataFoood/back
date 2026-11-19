# Conversa e seleção em tela cheia

Pedido aprovado pelo usuário: conversar/refinar antes de abrir as recomendações, contagem real e cards de escolha em tela cheia no celular e desktop. Fechar preserva conversa e progresso da seleção. Mesmo modelo local; contexto varia por plano.

## Regras e contrato

- Free usa somente a conversa atual. Premium (User.level >= 2, atribuído pelo operador) também usa preferências, favoritos e sinais da própria conta com allow_info; role não equivale a plano. O cliente não escolhe plano/perfil.
- Uma chamada estruturada ao Ollama por turno interpreta o pedido e devolve resposta curta e alterações dos filtros. Null mantém o filtro anterior; remove_filters permite retirá-lo explicitamente. Histórico e contexto têm limites. Filtros explícitos prevalecem; preferências apenas ordenam, sem excluir opções por gosto inferido.
- POST /api/chats/respond/ recebe query (1..500 caracteres) e conversation_id opcional. Carrega somente conversa do usuário, valida filtros contra taxonomias existentes e seleciona até 50 restaurantes públicos. Salva pergunta/resposta no servidor e devolve a conversa atualizada. Sem candidato, avisa sem inventar dados.
- Mensagens persistem texto, filtros e IDs da seleção, sem repetir todos os cards a cada turno. Isso mantém o limite de 256 KiB existente para conversas.
- GET /api/chats/<id>/recommendations/<message_index>/ entrega os cards públicos daquela seleção, preservando ordem; apenas para o dono da conversa. A contagem do botão é a quantidade efetivamente selecionada, com indicação quando o limite de 50 for atingido.
- A UI mostra resposta + Ver recomendações (N). A seleção abre em dialog nativo de tela cheia, com swipe, teclado e botões; escolher salva idempotentemente, recusar só avança. Fechar/Escape devolve foco e preserva rascunho/conversa/progresso durante a sessão.
- Falha/saída inválida do modelo preserva os filtros anteriores e oferece nova tentativa; não afirma ter aplicado uma alteração não interpretada. Erros de autorização não chamam o modelo. Sem geração habilitada, responder indisponibilidade explícita.
- API de busca e conversas antigas continuam compatíveis. Não há cobrança ou treinamento de pesos; o premium utiliza dados existentes autorizados.

## Verificação

- [x] Regressão backend: 12 opções passando para 4 com filtro externo, persistência e ausência de cards duplicados no histórico.
- [x] Regressão: outra conta não acessa conversa/seleção; plano enviado no corpo não altera contexto; free/sem consentimento não usam perfil.
- [x] Regressão: saída inválida, timeout, filtro inexistente e catálogo vazio.
- [x] Frontend: respostas, contagem, abrir/fechar/Escape, rascunho, refinar, swipe, salvar/erro e recarregar conversa; mobile/desktop e console.
- [x] Tipos, lint, build standalone com Node 22, OpenAPI, suíte backend/integração e documentação.

## Limites de operação

O teste anterior na VPS usou contexto 1024. A interpretação conversacional usa contexto 2048 e até 256 tokens para JSON, exigindo novo ensaio no destino. Não publicar nem prometer a latência anterior sem esse ensaio. Testes locais usam modelo simulado e banco/Redis de teste isolados.

Verificação backend em Linux: 314 testes Django, 16 regressões de segurança e
11 testes de serviços/deploy aprovados. Nenhuma migração pendente. Contrato e
operação em [conversation.md](../docs/conversation.md). Pesquisas prontas são
registradas pelo mesmo helper de consentimento/retenção usado na busca legada.

Frontend: tipos/lint, seis testes de configuração e build de produção aprovados.
Modo escolha integrado à API local: 18 verificações aprovadas, com geração
simulada e banco real isolado. Fluxo conversacional no build standalone: 51
verificações em três resoluções, incluindo console, com API simulada. A remoção
temporária da proteção de contexto privado fez o teste de consentimento falhar;
proteção restaurada e 23 testes focados aprovados. Roteiro geral de navigation.mjs
adaptado ao novo contrato e validado sintaticamente; não reexecutado por completo.
