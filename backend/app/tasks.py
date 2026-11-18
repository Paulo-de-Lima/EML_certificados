"""Tarefas executadas pelos workers.

A regra de negócio fica em `processar_certificado`, uma função comum (testável
sem RabbitMQ). As tarefas Celery são só uma casca fina em volta dela.
"""
import random
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from . import config, mailer
from .celery_app import celery
from .database import SessionLocal
from .models import ENVIADO, FALHOU, PENDENTE, Certificado
from .pdf import gerar_pdf


@dataclass
class Resultado:
    situacao: str  # "enviado" | "ja_enviado" | "ignorado" | "falhou" | "tentar_de_novo"
    espera: int = 0  # segundos até a próxima tentativa


def _espera(tentativas: int) -> int:
    """Espera exponencial (2, 4, 8... até 60 s) com um pouco de aleatoriedade,
    para que milhares de tarefas não tentem de novo todas no mesmo instante."""
    return min(2 ** tentativas, 60) + random.randint(0, 2)


def processar_certificado(cert_id: int, reentrega: bool = False) -> Resultado:
    """Emite UM certificado. Pode ser chamada várias vezes para o mesmo
    certificado: o e-mail só sai uma vez (idempotência)."""
    with SessionLocal() as db:
        # SELECT ... FOR UPDATE: trava a linha até o commit. Se duas mensagens
        # iguais chegarem a dois workers ao mesmo tempo, o segundo espera aqui
        # e, quando for liberado, já encontra o status ENVIADO.
        # Se este worker morrer, o MySQL desfaz a transação e solta a trava.
        cert = db.execute(
            select(Certificado).where(Certificado.id == cert_id).with_for_update()
        ).scalar_one_or_none()

        if cert is None:
            return Resultado("ignorado")  # lote apagado
        if cert.status == ENVIADO:
            return Resultado("ja_enviado")  # <- a checagem de idempotência
        if cert.status != PENDENTE:
            return Resultado("ignorado")

        try:
            # Reentrega (worker anterior morreu) ou nova tentativa: o e-mail
            # pode ter saído sem que o banco ficasse sabendo. Antes de reenviar,
            # perguntamos ao servidor de e-mail.
            if (reentrega or cert.tentativas > 0) and mailer.ja_foi_entregue(cert.codigo, cert.email):
                pass
            else:
                pdf = gerar_pdf(
                    cert.nome, config.NOME_EVENTO, config.CARGA_HORARIA,
                    cert.lote.criado_em, cert.codigo,
                )
                mailer.enviar(cert.email, cert.nome, cert.codigo, pdf)
        except mailer.ErroTransitorio as exc:
            cert.tentativas += 1
            cert.erro = str(exc)[:500]
            if cert.tentativas >= config.MAX_TENTATIVAS:
                cert.status = FALHOU
                db.commit()
                return Resultado("falhou")
            db.commit()
            return Resultado("tentar_de_novo", espera=_espera(cert.tentativas))
        except mailer.ErroDefinitivo as exc:
            cert.tentativas += 1
            cert.erro = str(exc)[:500]
            cert.status = FALHOU
            db.commit()
            return Resultado("falhou")

        cert.status = ENVIADO
        cert.erro = None
        cert.enviado_em = datetime.now()
        db.commit()
        return Resultado("enviado")


@celery.task(bind=True, name="certificados.emitir", max_retries=None)
def emitir_certificado(self, cert_id: int) -> str:
    reentrega = bool((self.request.delivery_info or {}).get("redelivered"))
    try:
        resultado = processar_certificado(cert_id, reentrega=reentrega)
    except OperationalError as exc:
        # Banco fora do ar ou trava demorada: tenta de novo em alguns segundos.
        raise self.retry(exc=exc, countdown=5)
    if resultado.situacao == "tentar_de_novo":
        # Retry: publica a tarefa de novo na fila, para rodar após `espera` s.
        # O limite de tentativas é controlado pela coluna `tentativas`.
        raise self.retry(countdown=resultado.espera)
    return resultado.situacao


@celery.task(bind=True, name="certificados.despachar", max_retries=None)
def despachar_lote(self, lote_id: int) -> int:
    """Coloca na fila uma tarefa por certificado pendente do lote.

    Roda no worker (e não na requisição HTTP) para a API responder 202 na hora.
    Se rodar duas vezes, publica mensagens repetidas — sem problema, porque
    `emitir_certificado` é idempotente.
    """
    try:
        with SessionLocal() as db:
            ids = db.scalars(
                select(Certificado.id).where(
                    Certificado.lote_id == lote_id, Certificado.status == PENDENTE
                )
            ).all()
    except OperationalError as exc:
        raise self.retry(exc=exc, countdown=5)

    with celery.producer_or_acquire() as producer:
        for cert_id in ids:
            emitir_certificado.apply_async(args=[cert_id], producer=producer)
    return len(ids)
