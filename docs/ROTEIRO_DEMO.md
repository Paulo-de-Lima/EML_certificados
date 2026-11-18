# Roteiro da demonstração

Objetivo: encerrar um worker durante o processamento e mostrar que o lote termina
**sem certificado duplicado e sem certificado perdido**.

Duração: cerca de 5 minutos. O lote de 5.000 leva perto de 1,5 minuto com os 3
workers (o tempo é controlado por `ATRASO_SIMULADO_MS` no `docker-compose.yml`).

## Antes da apresentação

1. Abra o Docker Desktop.
2. Suba tudo do zero, para a caixa de e-mail começar vazia:

   ```bash
   docker compose down -v
   docker compose up --build -d
   docker compose ps
   ```

   Todos os serviços devem aparecer como `running`, com três workers:
   `certificados-worker-1`, `-2` e `-3`.

3. Deixe abertas três abas do navegador:
   - Painel: http://localhost:5173
   - Mailpit: http://localhost:8025
   - RabbitMQ: http://localhost:15672 (`guest` / `guest`), aba **Queues**
4. Deixe dois terminais abertos na pasta do projeto. No primeiro, rode:

   ```bash
   docker compose logs -f worker
   ```

5. Faça um ensaio completo e depois repita o passo 2.

## Parte 1 — A requisição não espera

1. No painel, escolha `participantes.csv` e clique em **Enviar CSV**.
2. Mostre a mensagem verde: `202 Accepted em … ms`. A API respondeu em uma fração
   de segundo, sem ter emitido nenhum certificado.
3. Mostre o contador subindo ("1.240 de 5.000") e, no Mailpit, os e-mails chegando.
4. As 10 falhas que aparecem logo no início são linhas inválidas do CSV
   (e-mail sem `@`, nome vazio, e-mail repetido).

Fala sugerida: "A API só gravou o lote e colocou o trabalho na fila. Quem gera os
PDFs são os workers, que são processos separados."

## Parte 2 — Encerrar um worker

1. Com o contador por volta de 1.500, no segundo terminal:

   ```bash
   docker kill certificados-worker-2
   ```

   `docker kill` encerra o processo na hora, sem dar chance de terminar o que
   estava fazendo. É o equivalente a puxar o cabo da tomada.

2. Mostre:
   - No terminal de logs, o worker 2 para de escrever e os outros dois continuam.
   - No painel, o contador continua subindo, um pouco mais devagar.
   - No RabbitMQ, a coluna **Unacked** são as mensagens em andamento. As que
     estavam com o worker morto voltaram para **Ready** e foram pegas pelos outros.

3. (Opcional) Traga o worker de volta e mostre que ele retoma o trabalho:

   ```bash
   docker compose up -d worker
   ```

Fala sugerida: "O worker morreu segurando duas mensagens. Como ele só confirma a
mensagem depois de terminar, o RabbitMQ percebeu a queda e entregou as duas a
outro worker."

## Parte 3 — A prova

1. Espere o painel mostrar **Concluído**: 5.000 de 5.000, com 4.990 enviados e 10 falhas.
2. Clique em **Auditar (banco × caixa de e-mail)**. O resultado esperado:

   > Tudo certo. 4.990 enviados no banco · 4.990 e-mails na caixa · 0 duplicados · 0 perdidos

3. Mostre o total de 4.990 mensagens no Mailpit e abra uma delas para exibir o PDF anexo.
4. (Opcional) Confira direto no banco:

   ```bash
   docker compose exec mysql mysql -uapp -papp certificados -e "SELECT status, COUNT(*) FROM certificados GROUP BY status"
   ```

Fala sugerida: "A auditoria lê todos os e-mails da caixa e compara com o banco, um
por um, usando o identificador fixo de cada certificado. Nenhum chegou duas vezes
e nenhum ficou faltando."

## Parte 4 (opcional) — Retry

Mostra a nova tentativa com espera crescente.

1. Envie o `participantes.csv` de novo (vira o lote 2).
2. Com o lote em andamento, derrube o servidor de e-mail:

   ```bash
   docker compose stop mailpit
   ```

3. No terminal de logs aparecem linhas `Retry in 2s`, depois `4s`, `8s`… O contador
   do painel para.
4. Depois de uns 20 segundos, religue:

   ```bash
   docker compose start mailpit
   ```

5. O contador volta a subir e o lote termina. Clique em **Auditar** no lote 2.

Se o Mailpit ficar desligado por mais de um minuto, os certificados esgotam as 6
tentativas e aparecem na lista de falhas com o motivo "Servidor de e-mail
indisponível". Nesse caso, religue o Mailpit e clique em **Reprocessar pendentes e
falhas**: eles voltam para a fila e o lote termina.

## Se algo der errado

| Sintoma | O que fazer |
|---|---|
| Painel não abre | `docker compose ps` e `docker compose logs api frontend` |
| Contador parado em 0 | `docker compose logs worker`; confira se os workers estão `running` |
| Lote parado com pendentes | Clique em **Reprocessar pendentes e falhas** (é seguro) |
| Nome do contêiner não existe | `docker compose ps` mostra os nomes reais dos workers |
| Quer começar do zero | `docker compose down -v` e `docker compose up --build -d` |
| Porta ocupada | Troque o número da esquerda em `ports:` no `docker-compose.yml` |
