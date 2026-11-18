# Emissão de certificados em lote

Sistema que recebe um CSV com os participantes de um evento, responde na hora com
`202 Accepted` e emite os certificados em segundo plano: cada participante recebe
um PDF por e-mail. Um painel mostra o progresso e a lista de falhas.

- **Backend:** FastAPI + SQLAlchemy (MySQL)
- **Segundo plano:** Celery (workers) + RabbitMQ (fila)
- **PDF:** fpdf2
- **E-mail de teste:** Mailpit
- **Frontend:** React (Vite)

Documentos para a apresentação:

- [docs/PERGUNTA_CENTRAL.md](docs/PERGUNTA_CENTRAL.md) — conceitos e respostas à pergunta central, ligados ao código
- [docs/ROTEIRO_DEMO.md](docs/ROTEIRO_DEMO.md) — passo a passo da demonstração

## Como rodar

Pré-requisito: [Docker Desktop](https://www.docker.com/products/docker-desktop/) instalado e aberto.

```bash
docker compose up --build -d
```

| O quê | Endereço |
|---|---|
| Painel | http://localhost:5173 |
| Caixa de e-mail (Mailpit) | http://localhost:8025 |
| Fila (RabbitMQ) | http://localhost:15672 — usuário `guest`, senha `guest` |
| Documentação da API | http://localhost:8000/docs |

No painel, envie o arquivo `participantes.csv` que está na raiz do repositório.
Ele tem 5.000 linhas, 10 delas com problema de propósito (e-mail inválido, nome
vazio, e-mail repetido), então o resultado esperado é **4.990 enviados e 10 falhas**.

Comandos úteis:

```bash
docker compose ps                    # o que está rodando
docker compose logs -f worker        # acompanha os workers
docker compose run --rm api pytest   # roda os testes
docker compose down -v               # derruba tudo e apaga os dados
```

Depois de mudar o código, rode `docker compose up --build -d` de novo.

## Como funciona

```
Navegador ──POST /api/lotes (CSV)──> API (FastAPI) ──grava lote + 5.000 linhas──> MySQL
    │                                   │
    │ <──────── 202 Accepted ───────────┤
    │                                   └─ 1 mensagem "despachar lote" ─> RabbitMQ
    │                                                                        │
    │                                        worker: desdobra em 5.000 mensagens
    │                                                                        │
    │                              3 workers (Celery) <── 1 mensagem por certificado
    │                                   │  1. trava a linha no MySQL; já ENVIADO? para.
    │                                   │  2. gera o PDF (fpdf2)
    │                                   │  3. envia o e-mail (Mailpit)
    │                                   │  4. grava ENVIADO e confirma a mensagem (ack)
    │
    └──GET /api/lotes/{id} a cada 1 s──> API conta as linhas por status ("3.120 de 5.000")
```

## Estrutura

```
backend/app/
  main.py        rotas da API (upload, progresso, falhas, reprocessar, auditoria)
  tasks.py       tarefas dos workers — a idempotência e o retry estão aqui
  celery_app.py  configuração do Celery (acks_late etc.)
  models.py      tabelas Lote e Certificado
  mailer.py      envio SMTP e consultas ao Mailpit
  pdf.py         desenho do certificado
backend/tests/   testes (rodam sem Docker, com SQLite e um e-mail falso)
frontend/src/    painel React
scripts/gerar_participantes.py   gera o participantes.csv
docker-compose.yml
```

## API

| Método | Rota | O que faz |
|---|---|---|
| POST | `/api/lotes` | Recebe o CSV (campo `arquivo`), responde `202` com o lote |
| GET | `/api/lotes` | Últimos lotes |
| GET | `/api/lotes/{id}` | Progresso: total, enviados, falhas, pendentes |
| GET | `/api/lotes/{id}/falhas` | Lista de falhas com o motivo |
| POST | `/api/lotes/{id}/reprocessar` | Enfileira de novo o que falhou ou está pendente |
| GET | `/api/lotes/{id}/auditoria` | Compara o banco com a caixa do Mailpit |

## Rodar os testes sem Docker

```bash
cd backend
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python -m pytest
```
