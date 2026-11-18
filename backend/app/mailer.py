"""Envio de e-mail (SMTP) e consultas à API do Mailpit."""
import smtplib
import time
from collections import Counter
from email.message import EmailMessage

import httpx

from . import config


class ErroTransitorio(Exception):
    """Falha passageira (servidor fora do ar, timeout): vale tentar de novo."""


class ErroDefinitivo(Exception):
    """Falha que não se resolve repetindo (destinatário recusado)."""


def message_id(codigo: str) -> str:
    """Identificador FIXO do e-mail de um certificado.

    Como depende só do código do certificado, duas tentativas de envio do mesmo
    certificado produzem o mesmo Message-ID. É isso que permite perguntar ao
    servidor "este e-mail já chegou?" e detectar duplicatas na auditoria.
    """
    return f"{codigo}@certificados.local"


def enviar(destinatario: str, nome: str, codigo: str, pdf: bytes) -> None:
    msg = EmailMessage()
    msg["From"] = config.EMAIL_REMETENTE
    msg["To"] = destinatario
    msg["Subject"] = f"Seu certificado - {config.NOME_EVENTO}"
    msg["Message-ID"] = f"<{message_id(codigo)}>"
    msg.set_content(
        f"Olá, {nome}!\n\n"
        f"Segue em anexo o seu certificado de participação no evento "
        f"{config.NOME_EVENTO}.\n\n"
        f"Código de verificação: {codigo}\n"
    )
    msg.add_attachment(
        pdf, maintype="application", subtype="pdf", filename=f"certificado-{codigo}.pdf"
    )

    if config.ATRASO_SIMULADO_MS:
        time.sleep(config.ATRASO_SIMULADO_MS / 1000)

    try:
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=10) as smtp:
            smtp.send_message(msg)
    except (smtplib.SMTPRecipientsRefused, smtplib.SMTPSenderRefused) as exc:
        raise ErroDefinitivo(f"Servidor recusou o envio: {exc}") from exc
    except smtplib.SMTPResponseException as exc:
        # 5xx = erro permanente; 4xx = temporário.
        if 500 <= exc.smtp_code < 600:
            raise ErroDefinitivo(f"SMTP {exc.smtp_code}: {exc.smtp_error!r}") from exc
        raise ErroTransitorio(f"SMTP {exc.smtp_code}: {exc.smtp_error!r}") from exc
    except (smtplib.SMTPException, OSError) as exc:
        raise ErroTransitorio(f"Servidor de e-mail indisponível: {exc}") from exc


def ja_foi_entregue(codigo: str, destinatario: str) -> bool:
    """Pergunta ao Mailpit se o e-mail deste certificado já está na caixa.

    Usada quando uma tentativa anterior pode ter sido interrompida depois de o
    servidor aceitar o e-mail e antes de gravarmos ENVIADO no banco.
    Se não der para saber, levanta ErroTransitorio: é melhor esperar do que
    arriscar um e-mail duplicado.
    """
    if not config.MAILPIT_API_URL:
        return False
    try:
        r = httpx.get(
            f"{config.MAILPIT_API_URL}/api/v1/search",
            params={"query": f"to:{destinatario}", "limit": 100},
            timeout=5,
        )
        r.raise_for_status()
        mensagens = r.json().get("messages", [])
    except (httpx.HTTPError, ValueError) as exc:
        raise ErroTransitorio(f"Não foi possível consultar o Mailpit: {exc}") from exc
    esperado = message_id(codigo)
    return any((m.get("MessageID") or "").strip("<>") == esperado for m in mensagens)


def contar_message_ids() -> Counter:
    """Lê todos os e-mails do Mailpit e conta quantas vezes cada Message-ID aparece."""
    contagem: Counter = Counter()
    inicio, pagina = 0, 1000
    while True:
        r = httpx.get(
            f"{config.MAILPIT_API_URL}/api/v1/messages",
            params={"start": inicio, "limit": pagina},
            timeout=30,
        )
        r.raise_for_status()
        mensagens = r.json().get("messages", [])
        for m in mensagens:
            contagem[(m.get("MessageID") or "").strip("<>")] += 1
        if len(mensagens) < pagina:
            return contagem
        inicio += pagina
