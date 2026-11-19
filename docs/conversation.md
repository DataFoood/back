# Assistente de descoberta

O chat conversa antes de mostrar os cards. Cada mensagem pode refinar ou retirar
filtros; o botão **Ver recomendações (N)** abre a seleção em tela cheia. Fechar ou
pressionar Escape mantém o rascunho e o progresso enquanto a conversa permanece
montada. Recarregar recupera as mensagens e seleções, reiniciando o percurso dos cards.

## Regras de negócio

- Free (`User.level < 2`) usa o pedido, os filtros acumulados e o último pedido
  do usuário entre as quatro mensagens recentes (até 80 caracteres). Não usa o
  perfil comportamental.
- Premium (`level >= 2`) com `allow_info` também usa um resumo das preferências,
  favoritos, locais acessados e pesquisas da própria conta. Preferências manuais
  têm prioridade. O contexto ajuda na resposta e na ordenação; não cria filtros
  obrigatórios que o usuário não pediu. Sem consentimento, funciona como free.
- O backend determina plano e contexto. `role` representa permissões de acesso,
  não assinatura. Nesta demonstração, o operador atribui `level` pelo admin;
  não há pagamento ou treinamento do modelo.
- Cidade, nome de restaurante, cozinha, ambiente, faixa de preço e delivery são os filtros
  disponíveis. “Lugar aberto” significa ambiente ao ar livre, não aberto agora.
  Faixa de preço não garante um orçamento exato nem restrições alimentares.
- O banco calcula a seleção de restaurantes públicos. São até 50 opções por
  mensagem; `limited` informa quando há mais candidatos. A contagem é da seleção,
  nunca um número inventado pelo modelo. Nenhum restaurante é criado pela IA.
- O backend reconhece filtros explícitos antes de buscar: cidades e nomes do
  catálogo, nomes de taxonomias e sinônimos limitados, como “lugar aberto”,
  “pizza” e “sushi”. Não é interpretação livre pelo modelo. Um pedido não
  reconhecido pede esclarecimento; ambiguidades não escolhem arbitrariamente.
  “Não precisa ser ao ar livre” retira o filtro; excluir uma categoria é uma
  operação diferente, não suportada. “Aberto agora” não vira ambiente externo.
- O modelo recebe somente até dois restaurantes já selecionados, rótulos dos
  filtros e o resumo autorizado. Escreve até duas frases e não controla filtros,
  IDs ou contagens. Não recebe a lista inteira de taxonomias nem gera JSON.
- Falha de escrita preserva a seleção e informa explicitamente a falha. Não há
  chamada ao modelo sem candidatos; saudação/pedido incompleto recebe pergunta
  de esclarecimento. Uma seleção pronta usa uma chamada, sem ferramentas autônomas.
- Pesquisas interpretadas e prontas para seleção entram no histórico somente com
  consentimento, com retenção das últimas 50. E-mail, CPF e telefone não entram no
  contexto do modelo. O contexto não é copiado para o histórico da conversa.

## Contrato

`POST /api/chats/respond/`, autenticado:

```json
{"query": "e que seja em um lugar aberto", "conversation_id": 42}
```

`query` tem de 1 a 500 caracteres; `conversation_id` é opcional/nulo para uma
nova conversa. A resposta é a conversa completa (`id`, `title`, `messages`, datas),
persistida pelo servidor. A mensagem do assistente contém:

```json
{
  "role": "assistant",
  "content": {
    "kind": "results", "answer": "Vamos considerar os ambientes ao ar livre.",
    "results": [], "filters": {"city": "Marília", "ambient": 2},
    "recommendation_ids": [11, 12, 13, 14], "count": 4,
    "limited": false, "plan": "free", "personalized": false
  }
}
```

IDs acima são ilustrativos. O backend calcula as alterações de filtros;
`null` mantém o anterior e `remove_filters` retira explicitamente um filtro.
São mantidos os limites existentes de 200 mensagens, 256 KiB e 50 conversas.
Atualização simultânea em outra aba retorna 409 para reabrir a conversa; não
sobrescreve silenciosamente as mensagens. Geração desabilitada retorna 503.

`GET /api/chats/42/recommendations/3/` recupera `{count, results: RestaurantCard[]}`
da mensagem de índice 3 (começa em zero). Somente o dono acessa a conversa e a
seleção; outra conta recebe 404. A ordem é preservada, mas locais removidos ou
ocultos deixam de aparecer. Assim, uma seleção antiga pode abrir com menos cards.
Os cards são carregados ao abrir a tela, sem duplicá-los em cada mensagem.

Escolher à direita salva idempotentemente nos favoritos; recusar à esquerda só
avança nessa seleção. Fotos, botões e teclado continuam disponíveis. Conversas
antigas com cards completos ainda abrem; o CRUD existente e `/api/search/`
continuam compatíveis.

## Operação e validação

Publicar o backend antes do frontend que usa as novas rotas. Não há migração de
banco nesta entrega. Configuração do backend para a demonstração:

```dotenv
CHAT_GENERATION_ENABLED=True
CHAT_MODEL=qwen3:0.6b
SEMANTIC_SEARCH_ENABLED=False
```

A geração permanece desabilitada por padrão. O Ollama precisa disponibilizar o
modelo, com uma inferência e um modelo residente por vez na instância pequena.
As variáveis precisam chegar aos processos, não somente ao arquivo `.env`.
Antes de recriar serviços, conferir o Compose efetivamente usado na VPS.

O chat usa contexto 1024 e até 120 tokens de saída, uma thread e thinking
desabilitado. O ensaio real da versão anterior, com JSON e contexto 2048,
ignorou os filtros e levou 14,09/23,67 s; não foi aprovado para a apresentação.
A versão atual reduz a tarefa do modelo à escrita sobre a seleção real. Ainda
é necessário medir qualidade em português, latência, RAM disponível, swap,
OOM e créditos CPU com a aplicação ativa, incluindo a conta premium.

Para o ensaio gratuito do fluxo real no container:

```bash
sudo docker exec backend-web-1 python manage.py probe_chat
sudo docker exec backend-ollama-1 ollama ps
sudo docker stats --no-stream
free -h
vmstat 1 5
```

`probe_chat` não grava contas, conversas ou pesquisas. No lote fornecido, os três
pedidos selecionam 41 locais, cinco com tag Pizza & Massas e zero com área externa
declarada. O único objeto OSM com essa última tag não tem nome e foi ignorado.
O comando mede o tempo total de cada turno e falha explicitamente se o modelo
não escrever uma resposta válida para candidatos disponíveis. Também testar
o perfil premium pelo site, com preferências autorizadas e favoritas reais.

Testes automatizados usam respostas de modelo simuladas. Cobrem refinamento
12→4, retirada de filtros, isolamento de contas, consentimento, planos, falhas,
concorrência e seleção limitada. O E2E isolado do frontend cobre três tamanhos de
tela; o E2E de modo escolha integra banco, cookies e favoritos reais de teste,
simulando somente a resposta gerada.
