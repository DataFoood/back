# Avaliação local do chat — 23/11/2026

## Resultado

O pedido “lanche” não era um problema de capacidade do modelo: o intérprete
determinístico não reconhecia o termo e devolvia uma pergunta fixa antes de
chamar o Ollama. Os novos sinônimos usam a categoria Fast Food já cadastrada.
No lote OSM de Marília, são 15 candidatos, contra 41 na seleção sem categoria;
pizza seleciona cinco. Isso não comprova um item específico do cardápio.

Saudações, esclarecimentos, ausência de resultados e falhas agora têm mensagens
mais acolhedoras, mantendo a cidade conhecida. Não exigem modelo maior.

## Método

Ensaio local em CPU AMD Ryzen 5 5600G, Docker com cota de duas CPUs, Ollama
0.30.11, limite de 2 GiB **apenas no container do Ollama**, sem swap adicional.
Postgres/Redis de teste ficam fora desse limite. Isso não simula uma VPS inteira
de 2 GiB nem os créditos, processador e contenção de uma EC2.

Foi importado o arquivo versionado `data/marilia-osm-20261119.json` em banco
isolado. O teste usou `interpret_turn`, `select_restaurants`, `compose_reply`
e o HTTP real do Ollama. A escrita recebeu dois candidatos reais, contexto
1024, saída máxima 120 tokens, uma thread, temperatura 0,2, thinking desligado
e timeout de 30 segundos, como a aplicação. Nenhuma inferência foi simulada.

Cada modelo recebeu “quero um lanche em Marília” após descarregamento explícito
e “quero pizza em Marília” com o modelo residente. Arquivos já estavam baixados;
“após descarregamento” não significa cache de disco frio. Cada medição é uma
amostra, sem repetição estatística. As comparações exploratórias de prompt não
são um benchmark geral de qualidade.

## Medições com o prompt final

| Modelo Q4_K_M | Lanche, após descarregar | Pizza, residente | Memória residente informada por `/api/ps` |
| --- | ---: | ---: | ---: |
| `qwen3:0.6b` (`7df6b6e09427`) | 3,28 s | 1,64 s | 663 MB (632 MiB) |
| `qwen3:1.7b` (`8f68893c685c`) | 7,64 s | 3,48 s | 1.527 MB (1.456 MiB) |

Os quatro textos terminaram com `done_reason=stop` e passaram pela validação de
nome da aplicação. O 0.6B respondeu “Bora escolher! Que tal conhecer Burger King?”
e “Bora escolher! Que tal conhecer Di Carlotta Pizzeria?”, acrescentando um emoji.
O 1.7B produziu os mesmos convites sem emoji. O exemplo curto de tom foi mais
eficaz nesta amostra que instruções longas de personalidade.

Na exploração anterior, os dois modelos inventaram experiências ou atributos:
“Comprei pizza”, “ambientes vazios”, comida deliciosa e atmosfera agradável.
O contexto agora omite listas de tags vazias, e o prompt usa um exemplo neutro.
Isso reduz os problemas observados, mas **não garante correção factual**.
A validação existente exige um nome real; não verifica todas as afirmações.

O container não registrou OOM nesse ensaio. O cgroup reteve cache de arquivos
dos downloads; seu `memory.current` chegou ao teto e não representa só memória
do modelo. `/api/ps` também não representa todo o processo: a memória anônima
do cgroup após as consultas foi aproximadamente 723–748 MiB no 0.6B e
1.510–1.515 MiB no 1.7B. Não são picos amostrados durante a inferência.

## Escolha de infraestrutura

Manter o 0.6B e validar a conversa corrigida é o primeiro passo. O ensaio não
mostrou ganho de qualidade que justifique trocar automaticamente para o 1.7B.
Uma pessoa usando reduz concorrência, mas não a memória necessária para carregar
o modelo e manter aplicação, banco, worker e sistema operacional.

Se a máquina for uma AWS T3, a `t3.medium` dobra a RAM da `t3.small` de 2 para
4 GiB, mantendo duas vCPUs e a mesma linha de base de créditos CPU. Pode dar
folga para experimentar o 1.7B; não promete respostas mais rápidas. A memória
residente local de aproximadamente 1,46 GiB do modelo maior deixa pouco espaço
num host inteiro de 2 GiB. Não aprovar esse cenário só por ter um usuário.

Antes de qualquer troca, repetir o ensaio **na VPS com a aplicação ativa**,
incluindo conta com personalização consentida, memória disponível, swap,
OOM e créditos CPU. O registro histórico em `tasks/vps-baseline.md` usava Ollama
0.34.4; não é o mesmo runtime deste teste local. Nenhuma configuração de produção
ou plano de hospedagem foi alterado nesta avaliação.

```bash
python manage.py probe_chat --query "Marília" --query "lanche"
python manage.py probe_chat --query "quero pizza em Marília"
```

`probe_chat` não grava contas, conversas ou pesquisas. As variáveis
`CHAT_GENERATION_ENABLED`, `CHAT_MODEL` e `OLLAMA_URL` devem apontar para o
ambiente a medir. Não confundir esses ensaios reais com os testes automatizados,
que simulam somente a inferência para verificar os contratos.

Fontes: [AWS T3](https://aws.amazon.com/ec2/instance-types/t3/),
[Qwen3 0.6B](https://ollama.com/library/qwen3:0.6b),
[Qwen3 1.7B](https://ollama.com/library/qwen3:1.7b) e
[memória/contexto no Ollama](https://docs.ollama.com/faq).
