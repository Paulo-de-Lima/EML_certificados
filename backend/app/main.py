import csv
import io
import re
import uuid
from contextlib import asynccontextmanager
from datetime import datetime

import httpx
from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from sqlalchemy import func, insert, select, update
from sqlalchemy.orm import Session

from . import mailer
from .database import Base, engine, get_db
from .models import ENVIADO, FALHOU, INVALIDO, PENDENTE, Certificado, Lote
from .tasks import despachar_lote

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MAX_LINHAS = 100_000


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(engine)
    yield


app = FastAPI(title="Emissão de certificados em lote", lifespan=lifespan)


def _resumo(db: Session, lote: Lote) -> dict:
    """Progresso do lote, calculado contando os certificados por status."""
    contagem = dict(
        db.execute(
            select(Certificado.status, func.count())
            .where(Certificado.lote_id == lote.id)
            .group_by(Certificado.status)
        ).all()
    )
    enviados = contagem.get(ENVIADO, 0)
    falhas = contagem.get(FALHOU, 0) + contagem.get(INVALIDO, 0)
    pendentes = contagem.get(PENDENTE, 0)
    return {
        "id": lote.id,
        "nome_arquivo": lote.nome_arquivo,
        "criado_em": lote.criado_em.isoformat(),
        "total": lote.total,
        "enviados": enviados,
        "falhas": falhas,
        "pendentes": pendentes,
        "processados": enviados + falhas,
        "status": "PROCESSANDO" if pendentes else "CONCLUIDO",
    }


def _buscar_lote(db: Session, lote_id: int) -> Lote:
    lote = db.get(Lote, lote_id)
    if lote is None:
        raise HTTPException(404, "Lote não encontrado")
    return lote


def _enfileirar(lote_id: int) -> None:
    try:
        despachar_lote.delay(lote_id)
    except Exception as exc:  # RabbitMQ fora do ar
        raise HTTPException(
            503,
            f"Lote {lote_id} foi salvo, mas a fila está indisponível. "
            "Use 'Reprocessar' quando o RabbitMQ voltar.",
        ) from exc


@app.get("/api/saude")
def saude():
    return {"ok": True}


@app.post("/api/lotes", status_code=202)
def criar_lote(arquivo: UploadFile = File(...), db: Session = Depends(get_db)):
    """Recebe o CSV, grava o lote e responde 202 sem gerar nenhum PDF.

    O trabalho feito aqui é só o que é rápido: ler o arquivo, validar as linhas
    e gravar tudo no banco de uma vez. A emissão fica para os workers.
    """
    try:
        texto = arquivo.file.read().decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(400, "O arquivo precisa estar em UTF-8")

    leitor = csv.DictReader(io.StringIO(texto))
    colunas = [c.strip().lower() for c in (leitor.fieldnames or [])]
    if "nome" not in colunas or "email" not in colunas:
        raise HTTPException(400, "O CSV precisa ter as colunas 'nome' e 'email'")
    leitor.fieldnames = colunas

    linhas = []
    emails_vistos: dict[str, int] = {}
    for numero, linha in enumerate(leitor, start=2):  # linha 1 é o cabeçalho
        if len(linhas) >= MAX_LINHAS:
            raise HTTPException(400, f"O CSV passa de {MAX_LINHAS} linhas")
        nome = (linha.get("nome") or "").strip()
        email = (linha.get("email") or "").strip().lower()
        if not nome and not email:
            continue

        status, erro = PENDENTE, None
        if not nome:
            status, erro = INVALIDO, "Nome vazio"
        elif not EMAIL_RE.match(email):
            status, erro = INVALIDO, "E-mail inválido"
        elif email in emails_vistos:
            # Mesma pessoa duas vezes no arquivo: só a primeira recebe.
            status, erro = INVALIDO, f"E-mail repetido (já aparece na linha {emails_vistos[email]})"
        else:
            emails_vistos[email] = numero

        linhas.append({
            "linha": numero, "nome": nome[:255], "email": email[:255],
            "codigo": uuid.uuid4().hex, "status": status, "erro": erro, "tentativas": 0,
        })

    if not linhas:
        raise HTTPException(400, "O CSV não tem participantes")

    lote = Lote(
        nome_arquivo=arquivo.filename or "participantes.csv",
        total=len(linhas),
        criado_em=datetime.now(),
    )
    db.add(lote)
    db.flush()
    db.execute(insert(Certificado), [{**l, "lote_id": lote.id} for l in linhas])
    db.commit()

    # Uma única mensagem na fila; o worker desdobra em uma tarefa por certificado.
    _enfileirar(lote.id)
    return _resumo(db, lote)


@app.get("/api/lotes")
def listar_lotes(db: Session = Depends(get_db)):
    lotes = db.scalars(select(Lote).order_by(Lote.id.desc()).limit(20)).all()
    return [_resumo(db, lote) for lote in lotes]


@app.get("/api/lotes/{lote_id}")
def progresso(lote_id: int, db: Session = Depends(get_db)):
    return _resumo(db, _buscar_lote(db, lote_id))


@app.get("/api/lotes/{lote_id}/falhas")
def falhas(lote_id: int, db: Session = Depends(get_db)):
    _buscar_lote(db, lote_id)
    certs = db.scalars(
        select(Certificado)
        .where(Certificado.lote_id == lote_id, Certificado.status.in_([FALHOU, INVALIDO]))
        .order_by(Certificado.linha)
        .limit(500)
    ).all()
    return [
        {
            "linha": c.linha, "nome": c.nome, "email": c.email, "erro": c.erro,
            "tentativas": c.tentativas, "pode_reprocessar": c.status == FALHOU,
        }
        for c in certs
    ]


@app.post("/api/lotes/{lote_id}/reprocessar", status_code=202)
def reprocessar(lote_id: int, db: Session = Depends(get_db)):
    """Devolve as falhas para PENDENTE e enfileira de novo tudo o que falta.

    É seguro chamar a qualquer momento, mesmo com o lote em andamento: quem já
    foi enviado é ignorado pela tarefa.
    """
    lote = _buscar_lote(db, lote_id)
    db.execute(
        update(Certificado)
        .where(Certificado.lote_id == lote_id, Certificado.status == FALHOU)
        .values(status=PENDENTE, tentativas=0, erro=None)
    )
    db.commit()
    _enfileirar(lote_id)
    return _resumo(db, lote)


@app.get("/api/lotes/{lote_id}/auditoria")
def auditoria(lote_id: int, db: Session = Depends(get_db)):
    """Confere o banco contra a caixa do Mailpit: prova de que não há
    certificado duplicado nem perdido."""
    _buscar_lote(db, lote_id)
    certs = db.execute(
        select(Certificado.codigo, Certificado.email, Certificado.status)
        .where(Certificado.lote_id == lote_id)
    ).all()
    try:
        na_caixa = mailer.contar_message_ids()
    except httpx.HTTPError as exc:
        raise HTTPException(503, f"Não foi possível consultar o Mailpit: {exc}") from exc

    duplicados, perdidos, nao_registrados, emails = [], [], [], 0
    for codigo, email, status in certs:
        n = na_caixa.get(mailer.message_id(codigo), 0)
        emails += n
        if n > 1:
            duplicados.append(email)
        if status == ENVIADO and n == 0:
            perdidos.append(email)
        if status != ENVIADO and n > 0:
            nao_registrados.append(email)

    return {
        "enviados_no_banco": sum(1 for c in certs if c.status == ENVIADO),
        "emails_na_caixa": emails,
        # Mesmo certificado entregue mais de uma vez.
        "duplicados": len(duplicados),
        # Banco diz ENVIADO, mas o e-mail não está na caixa.
        "perdidos": len(perdidos),
        # E-mail na caixa, mas o banco ainda não diz ENVIADO (tarefa em andamento).
        "nao_registrados": len(nao_registrados),
        "exemplos": {
            "duplicados": duplicados[:10],
            "perdidos": perdidos[:10],
            "nao_registrados": nao_registrados[:10],
        },
        "ok": not duplicados and not perdidos and not nao_registrados,
    }
