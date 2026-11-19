# Cupom premium da apresentação

O resgate é feito em **Perfil → Meus dados → Cupom premium**. O código não tem
limite total de usos nem prazo automático de expiração: pode ser usado por
diversas contas, e repetir na mesma conta é idempotente. Cada conta fica com
`level >= 2`; não há cobrança. Quem tem nível maior não perde esse nível.

O resgate não muda `role`, permissões administrativas, senha ou `allow_info`.
Para usar preferências no chat, a pessoa precisa autorizar a personalização em
**Privacidade** e ter sinais/preferências na própria conta.

## Configuração

O backend recebe somente o SHA-256 do código em `PREMIUM_TEST_COUPON_SHA256`.
Vazio desativa novos resgates; retirar o hash não remove premium já concedido.
O código real não é versionado nem incluído no frontend.

No terminal Linux, gerar o hash de um código sem colocar o código no histórico:

```bash
read -r -s -p 'Cupom: ' premium_code; printf '\n'
printf '%s' "$premium_code" | sha256sum
unset premium_code
```

Adicionar o hash (os 64 caracteres, sem o `-` final) ao arquivo de ambiente que
alimenta o serviço web, conforme `.env.prod.example`, e recriar o serviço para
receber a variável. Não é necessária migração de banco. Manter o cupom somente
no ambiente autorizado para a apresentação; qualquer pessoa com o código e uma
conta pode resgatá-lo enquanto estiver habilitado.

## API

`POST /api/users/premium/redeem/`, autenticado, recebe `{"code": "..."}` e retorna
o próprio usuário atualizado no mesmo formato de `/api/users/me/`.
Código inválido retorna 400; resgate desabilitado retorna 503. Tentativas têm
limite de 10 por minuto por usuário, separado do login; isso não limita o número
total de usos do cupom. IDs e níveis enviados no corpo não escolhem outra conta
ou privilégio.

## Embeddings

`CHAT_MODEL=qwen3:0.6b` é o gerador de texto; `EMBEDDING_MODEL=nomic-embed-text`
continua sendo o modelo de vetores. Trocar somente o gerador não invalida vetores.
O fluxo conversacional usa SQL/filtros e não depende de embeddings. Na VPS
pequena, manter `SEMANTIC_SEARCH_ENABLED=False` em todos os processos evita
indexação agendada e carregamento do modelo de embeddings durante a demonstração.
Se a busca vetorial for reativada, novos restaurantes precisam ser indexados;
trocar o modelo de embeddings exige refazer vetores compatíveis, incluindo a
dimensão do índice quando aplicável.
