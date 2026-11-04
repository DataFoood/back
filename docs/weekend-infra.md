# Operação local e infraestrutura temporária

A aplicação pode rodar localmente. Isso não torna localhost acessível aos
clientes: antes de divulgar links, configure um endereço público controlado e
`FRONTEND_URL`, com HTTPS, origens CORS/CSRF e cookies adequados.

## Medir antes de recomendar

POST `/api/search/` registra contagem, erros 5xx e histograma de latência por
minuto em `OperationalBucket`, sem texto da busca, usuário ou IP. O histórico
usado na projeção não é mais `SearchHistory` (consentido, limitado e incompleto).
O p95 exibido é um limite superior por faixa, não uma medição exata do percentil.
São 28 dias de retenção operacional; quantidade de dias observados é informada.
Dias sem observação não comprovam ausência de demanda.

`LOCAL_CAPACITY_CALIBRATED=False` é o padrão. Sem calibração, o painel não
apresenta máquina local como suficiente nem recomenda compra automaticamente.
Fila atrasada ou latência alta acionam atenção, pedindo diagnóstico. Mesmo com
calibração, a projeção por dia da semana é uma heurística, não previsão garantida.
Limite de SMTP/Bot API não é corrigido com VPS maior.

```bash
cd dtfd
uv run python manage.py benchmark_search --user-email CONTA_CONTROLADA --samples 10
```

Esse comando usa a autenticação normal da API e o motor configurado, sem
imprimir tokens. No máximo 20 amostras para respeitar o throttle padrão. Mede
latência da instalação, sem simular concorrência ou calibrar automaticamente a
capacidade. Em desenvolvimento com Ollama falso, os números **não** estimam
produção. Use modelo real e carga concorrente representativa antes de editar
`LOCAL_CAPACITY_CALIBRATED` e as capacidades diárias nas configurações.

## Backup com restauração verificada

```bash
# Na raiz do back, escolha destino novo fora do Git:
bash scripts/verify-backup.sh docker-compose.yml /caminho/privado/backup.dump PROJETO_COMPOSE
```

O script não sobrescreve arquivos e não restaura no banco ativo. Cria um dump,
restaura em banco temporário com checagem de erro e remove somente esse banco
criado pelo ensaio. A conta do banco precisa poder criar banco temporário.
Proteja o dump (pode conter dados pessoais); defina retenção e armazenamento
seguro. Isso testa o banco, não mídia externa nem configuração/segredos: inclua
os demais itens na política de backup. Meça tempos e recuperação aceitáveis.

## Transferência de fim de semana

1. Escolher provedor, região e orçamento, incluindo banco, armazenamento,
   transferência e APIs. O cálculo horário do painel cobre só o valor configurado
   de compute; 54 horas não representam necessariamente a conta total.
2. Preparar a stack de destino e o backup restaurável, com a mesma versão e
   extensões. Ensaiar antes de trocar o tráfego real.
3. No MVP, pausar escritas e workers, transferir/restaurar, verificar integridade
   e só então mudar o endereço público. Não deixar dois bancos graváveis e
   tentar reconciliá-los depois por dump.
4. Garantir uma única instância de beat/polling de Telegram. Banco/outbox são
   a fonte das tarefas; reconstituir trabalho pendente após restaurar.
5. Fazer o retorno com a mesma disciplina. Desligar infraestrutura paga apenas
   após verificar dados e acesso no destino de retorno.

Contratação automática e migração sem pausa não estão implementadas. Exigem
provedor e estratégia de replicação/fonte de verdade definidos. Não mover
apenas por calendário sem comprovar gargalo e benefício da expansão.

Em Linux com cgroup v2, o endpoint também informa um snapshot opcional de CPU
e memória do contêiner da API. Não cobre automaticamente worker, banco ou
Ollama em outros contêineres. Sem suporte, os recursos ficam indisponíveis;
ausência de medição não é interpretada como capacidade livre.
