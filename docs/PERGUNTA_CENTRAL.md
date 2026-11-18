# Pergunta central

> Por que a requisição HTTP não pode esperar o fim do lote? Um worker para no meio
> do trabalho: o participante recebe dois certificados ou nenhum? Como a equipe
> garante a idempotência e a nova tentativa (retry)?

## Vocabulário

| Termo | O que é | Onde está |
|---|---|---|
| **Fila** | Lista de recados guardada pelo RabbitMQ. Cada recado diz "emita o certificado nº X". | serviço `rabbitmq` |
| **Worker** | Processo Python separado da API que pega um recado, executa e pega o próximo. Rodamos 3 contêineres com 2 processos cada. | serviço `worker` |
| **Tarefa** | A função que o worker executa para cada recado. | `backend/app/tasks.py` |
| **Ack** | Confirmação que o worker manda ao RabbitMQ: "terminei, pode apagar o recado". | `celery_app.py` |
| **Idempotência** | Repetir a mesma tarefa não muda o resultado: o e-mail sai uma vez só. | `processar_certificado` |
| **Retry** | Tentar de novo depois de uma falha passageira. | `emitir_certificado` |

## 1. Por que a requisição HTTP não pode esperar o fim do lote?

Emitir 5.000 certificados leva minutos. Manter a requisição aberta esse tempo todo
dá errado por quatro motivos:

1. **Timeout.** Navegadores, proxies e balanceadores cortam conexões longas
   (em geral entre 30 e 60 segundos). O trabalho seria interrompido no meio.
2. **O usuário fica no escuro.** Se a conexão cai, ele não sabe se foram emitidos
   0, 3.000 ou 5.000 certificados. Se clicar de novo, o lote recomeça.
3. **A API fica presa.** O processo que atende aquela requisição não atende mais
   ninguém enquanto o lote roda.
4. **Não dá para dividir o trabalho.** Uma requisição roda em um processo. Com
   fila, basta subir mais workers para ir mais rápido.

O que fazemos: a rota `POST /api/lotes` (`main.py`, função `criar_lote`) só faz o que
é rápido — lê o CSV, valida as linhas, grava tudo no MySQL e publica **uma**
mensagem na fila. Responde `202 Accepted`, que significa "recebi e vou processar,
mas ainda não terminei". O painel então pergunta o progresso a cada segundo em
`GET /api/lotes/{id}`.

## 2. Um worker para no meio: dois certificados ou nenhum?

Depende de **quando** o worker confirma a mensagem (ack):

| Configuração | O que acontece quando o worker morre | Resultado |
|---|---|---|
| Ack **antes** de executar (padrão do Celery) | A mensagem já foi apagada da fila. Ninguém refaz. | **Nenhum** certificado |
| Ack **depois**, tarefa sem idempotência | A mensagem volta à fila e a tarefa roda inteira de novo. | Possivelmente **dois** |
| Ack **depois**, tarefa idempotente | A mensagem volta, e a tarefa percebe o que já foi feito. | **Exatamente um** |

Escolhemos a terceira linha. A teoria por trás: uma fila só consegue garantir
"no máximo uma vez" (pode perder) ou "pelo menos uma vez" (pode repetir).
Escolhemos "pelo menos uma vez" e tornamos a repetição inofensiva.

Configuração em `celery_app.py`:

- `task_acks_late=True` — confirma só depois de a tarefa terminar. Se o worker
  morre, o RabbitMQ nota a conexão caída e devolve a mensagem à fila.
- `task_reject_on_worker_lost=True` — o mesmo vale se só o processo filho for morto.
- `worker_prefetch_multiplier=1` — cada processo reserva uma mensagem por vez,
  então um worker morto devolve poucas mensagens.

## 3. Como garantimos a idempotência?

Cada participante é **uma linha** na tabela `certificados`, com um `status`
(`PENDENTE`, `ENVIADO`, `FALHOU`, `INVALIDO`). Essa linha é a fonte da verdade.
A tarefa (`processar_certificado` em `tasks.py`) faz, dentro de uma única transação:

1. **Trava a linha** com `SELECT ... FOR UPDATE`. Se duas mensagens iguais chegarem
   a dois workers ao mesmo tempo, o segundo fica esperando.
2. **Se o status já é `ENVIADO`, sai sem fazer nada.** Esta é a checagem de idempotência.
3. Gera o PDF. A geração é determinística: os mesmos dados produzem os mesmos bytes.
4. Envia o e-mail.
5. Grava `ENVIADO` e faz o commit, o que solta a trava.

Se o worker morre em qualquer ponto antes do passo 5, o MySQL desfaz a transação
sozinho: a linha continua `PENDENTE` e a trava é solta. A mensagem volta à fila e
outro worker refaz.

Outras proteções:

- Restrição `UNIQUE (lote_id, linha)` no banco: a mesma linha do CSV nunca vira dois certificados.
- E-mail repetido no CSV: só a primeira ocorrência é emitida; a outra vai para a lista de falhas.
- A tarefa que desdobra o lote (`despachar_lote`) pode rodar duas vezes e publicar
  mensagens repetidas — não há problema, porque a tarefa de emissão é idempotente.

### O caso difícil: morrer entre o e-mail e o commit

Existe uma janela de milissegundos entre o passo 4 e o passo 5: o servidor de
e-mail já aceitou a mensagem, mas o banco ainda diz `PENDENTE`. Se o worker morre
exatamente aí, a reentrega mandaria um segundo e-mail. O banco e o servidor de
e-mail são sistemas separados e não existe transação que cubra os dois.

Como fechamos essa janela:

- Cada e-mail leva um **`Message-ID` fixo**, derivado do código do certificado
  (`mailer.message_id`). Duas tentativas do mesmo certificado têm o mesmo identificador.
- Quando a mensagem é uma **reentrega** (o RabbitMQ marca com `redelivered`) ou uma
  nova tentativa, a tarefa primeiro **pergunta ao servidor de e-mail** se aquele
  `Message-ID` já chegou (`mailer.ja_foi_entregue`). Se chegou, só grava `ENVIADO`.
- Se não for possível consultar o servidor, a tarefa espera e tenta depois, em vez
  de arriscar a duplicata.

Limite honesto: essa consulta usa a API do Mailpit. Um provedor de e-mail real
precisaria oferecer algo equivalente (alguns aceitam uma chave de idempotência no
envio). Sem isso, restaria uma chance muito pequena de duplicata, que o
`Message-ID` fixo ao menos permite detectar.

## 4. Como funciona a nova tentativa (retry)?

Separamos dois tipos de falha (`mailer.py`):

| Tipo | Exemplo | O que fazemos |
|---|---|---|
| **Passageira** (`ErroTransitorio`) | Servidor de e-mail fora do ar, timeout, erro SMTP 4xx | Tenta de novo mais tarde |
| **Definitiva** (`ErroDefinitivo`) | Destinatário recusado, erro SMTP 5xx | Marca `FALHOU` na hora |
| **Dado inválido** | E-mail sem `@`, nome vazio | Marca `INVALIDO` já no upload; nem entra na fila |

Na falha passageira:

- A tarefa grava o erro e soma 1 em `tentativas`, depois se reagenda com
  `self.retry(countdown=...)`.
- A espera **cresce** a cada tentativa: cerca de 2, 4, 8, 16, 32 segundos
  (`_espera` em `tasks.py`). Isso dá tempo de o servidor voltar.
- Há um pouco de **aleatoriedade** na espera, para milhares de tarefas não
  tentarem todas no mesmo instante.
- Depois de 6 tentativas (`MAX_TENTATIVAS`), o certificado vira `FALHOU` e aparece
  na lista de falhas com o motivo.
- O botão **Reprocessar** do painel devolve as falhas para a fila. Pode ser
  clicado a qualquer momento sem risco, justamente por causa da idempotência.

## 5. Como provamos

- **Testes** (`backend/tests/test_tarefa.py`): rodar a tarefa duas vezes envia um
  e-mail; worker que morre antes de enviar não perde o certificado; worker que
  morre depois de enviar não duplica; falha passageira tenta de novo; tentativas
  esgotadas viram falha.
- **Auditoria** (`GET /api/lotes/{id}/auditoria`, botão no painel): lê todos os
  e-mails do Mailpit e compara com o banco. Mostra quantos certificados chegaram
  mais de uma vez (duplicados) e quantos constam como enviados sem estar na caixa
  (perdidos). Na demonstração, os dois números devem ser zero.
