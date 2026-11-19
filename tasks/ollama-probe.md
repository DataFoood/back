# Prova inicial de geração local

Preparada em 19/11/2026; não executada na VPS por esta sessão. Requisitos confirmados pelo usuário: Ollama 0.34.4 em backend-ollama-1, sem modelo residente, qwen3:0.6b baixado; aplicação ativa em backend-web-1. Os dois contêineres estão sem teto de RAM/swap e sem reinícios registrados. O teste não muda o contrato da aplicação.

## 1. Orçamento experimental

No terminal da EC2, aplicar somente ao Ollama:

```bash
sudo docker update --memory=900m --memory-swap=1200m backend-ollama-1
```

São 900 MiB de RAM e até 300 MiB adicionais de swap; não é uma reserva ou garantia de capacidade. Esse orçamento inicial deixa espaço para os serviços existentes. Se o comando falhar, não prosseguir com geração. O limite pode encerrar processos do Ollama se excedido; registrar a falha antes de ampliá-lo. A alteração não exige recriar a stack e não altera volumes, mas pode afetar buscas que dependem do Ollama durante o teste. Não realizar outras buscas enquanto mede.

## 2. Duas chamadas sequenciais

Executar o bloco inteiro. O cliente usa Python já presente no contêiner web e o nome do serviço na rede interna; não publica a porta Ollama. O catálogo abaixo é fictício e serve somente para testar cumprimento de instruções em português.

```bash
sudo docker exec -i backend-web-1 python - <<'PY'
import json
import urllib.request

payload = {
    "model": "qwen3:0.6b",
    "stream": False,
    "think": False,
    "keep_alive": "2m",
    "options": {"num_ctx": 1024, "num_predict": 120, "num_thread": 1, "temperature": 0.2},
    "messages": [
        {"role": "system", "content": "Responda em português, em até três frases. Use apenas os dados fornecidos. Não invente informações."},
        {"role": "user", "content": "Cenário fictício de teste: Restaurante A oferece almoço vegetariano por R$ 30; Restaurante B oferece churrasco por R$ 60. Quero almoçar sem carne e gastar até R$ 35. Qual recomenda e por quê?"},
    ],
}
for tentativa in (1, 2):
    print(f"Tentativa {tentativa}", flush=True)
    request = urllib.request.Request(
        "http://ollama:11434/api/chat",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=90) as response:
        result = json.load(response)
    assert result.get("done") is True and result.get("message", {}).get("content", "").strip(), "Resposta vazia ou incompleta"
    print(json.dumps({
        "resposta": result["message"]["content"],
        "total_s": round(result["total_duration"] / 1e9, 2),
        "carga_s": round(result.get("load_duration", 0) / 1e9, 2),
        "tokens": result.get("eval_count"),
        "fim": result.get("done_reason"),
    }, ensure_ascii=False, indent=2), flush=True)
PY
```

O assert confere término do protocolo e conteúdo não vazio; não comprova qualidade nem término natural. Conferir o campo fim e se a resposta atende ao pedido. A segunda chamada tenta reutilizar o modelo, mas o teste não impede outra tarefa da aplicação de disputar o Ollama; observar carga_s.

## 3. Estado e liberação do modelo

Executar também se a geração falhar; copiar a saída junto das respostas ou do erro:

```bash
sudo docker exec backend-ollama-1 ollama ps
sudo docker stats --no-stream
free -h
vmstat 1 5
sudo docker inspect --format '{{.Name}} restarts={{.RestartCount}} oom={{.State.OOMKilled}}' backend-ollama-1 backend-web-1
sudo docker exec backend-ollama-1 ollama stop qwen3:0.6b
```

As leituras são posteriores e podem perder o pico de memória durante geração; um resultado positivo ainda exige acompanhamento simultâneo e prompts representativos maiores. O modelo permanece residente por até dois minutos após cada chamada; stop libera o gerador antecipadamente sem apagar o download. Não altera EMBEDDING_MODEL.

## Retorno ao estado sem teto

Se for necessário remover o limite experimental:

```bash
sudo docker update --memory=0 --memory-swap=-1 backend-ollama-1
```

Isso restaura RAM/swap sem teto individual efetivo; o valor de MemorySwap passa a -1, em vez do 0 original. A configuração remota Compose não foi editada: recriar o contêiner poderá substituir os limites de runtime. Após resultado satisfatório, persistir a configuração aprovada no Compose efetivo e fixar a versão da imagem em tarefa própria.

Referências: [API chat Ollama](https://docs.ollama.com/api/chat), [restrições de recursos Docker](https://docs.docker.com/engine/containers/resource_constraints/), [docker update](https://docs.docker.com/reference/cli/docker/container/update/).
