"""Idempotência e retry da tarefa de emissão."""
import pytest

from app import mailer
from app.models import ENVIADO, FALHOU, PENDENTE
from app.tasks import processar_certificado

from .conftest import WorkerMorreu, buscar


def test_envia_e_marca_como_enviado(caixa, cert_id):
    assert processar_certificado(cert_id).situacao == "enviado"
    assert caixa.entregues == ["abc123"]
    assert buscar(cert_id).status == ENVIADO


def test_idempotencia_rodar_duas_vezes_envia_um_email(caixa, cert_id):
    processar_certificado(cert_id)
    assert processar_certificado(cert_id).situacao == "ja_enviado"
    assert processar_certificado(cert_id, reentrega=True).situacao == "ja_enviado"
    assert caixa.entregues == ["abc123"]


def test_worker_morre_antes_de_enviar_nao_perde_o_certificado(caixa, cert_id):
    caixa.falhar_com = WorkerMorreu()
    with pytest.raises(WorkerMorreu):
        processar_certificado(cert_id)
    # Nada saiu e o banco continua dizendo PENDENTE: nenhum certificado "sumiu".
    assert caixa.entregues == []
    assert buscar(cert_id).status == PENDENTE

    # O RabbitMQ reentrega a mensagem a outro worker.
    caixa.falhar_com = None
    assert processar_certificado(cert_id, reentrega=True).situacao == "enviado"
    assert caixa.entregues == ["abc123"]


def test_worker_morre_depois_de_enviar_nao_duplica(caixa, cert_id):
    # O pior caso: o e-mail saiu, mas o worker morreu antes do commit.
    caixa.morrer_depois_de_entregar = True
    with pytest.raises(WorkerMorreu):
        processar_certificado(cert_id)
    assert caixa.entregues == ["abc123"]
    assert buscar(cert_id).status == PENDENTE  # o banco não ficou sabendo

    # Na reentrega, a tarefa pergunta ao servidor de e-mail antes de reenviar.
    caixa.morrer_depois_de_entregar = False
    assert processar_certificado(cert_id, reentrega=True).situacao == "enviado"
    assert caixa.entregues == ["abc123"]  # continua um só
    assert buscar(cert_id).status == ENVIADO


def test_falha_passageira_pede_nova_tentativa_e_depois_envia(caixa, cert_id):
    caixa.falhar_com = mailer.ErroTransitorio("servidor fora do ar")
    r = processar_certificado(cert_id)
    assert r.situacao == "tentar_de_novo" and r.espera > 0
    cert = buscar(cert_id)
    assert (cert.status, cert.tentativas, cert.erro) == (PENDENTE, 1, "servidor fora do ar")

    caixa.falhar_com = None
    assert processar_certificado(cert_id).situacao == "enviado"
    cert = buscar(cert_id)
    assert (cert.status, cert.erro) == (ENVIADO, None)
    assert caixa.entregues == ["abc123"]


def test_espera_entre_tentativas_cresce(caixa, cert_id):
    caixa.falhar_com = mailer.ErroTransitorio("x")
    primeira = processar_certificado(cert_id).espera
    segunda = processar_certificado(cert_id).espera
    assert 2 <= primeira <= 4 and 4 <= segunda <= 6


def test_esgotar_as_tentativas_marca_como_falhou(caixa, cert_id):
    caixa.falhar_com = mailer.ErroTransitorio("servidor fora do ar")
    situacoes = [processar_certificado(cert_id).situacao for _ in range(3)]  # MAX_TENTATIVAS=3
    assert situacoes == ["tentar_de_novo", "tentar_de_novo", "falhou"]
    assert buscar(cert_id).status == FALHOU
    # Mensagens atrasadas que ainda cheguem não fazem nada.
    assert processar_certificado(cert_id).situacao == "ignorado"


def test_falha_definitiva_nao_tenta_de_novo(caixa, cert_id):
    caixa.falhar_com = mailer.ErroDefinitivo("destinatário recusado")
    assert processar_certificado(cert_id).situacao == "falhou"
    cert = buscar(cert_id)
    assert (cert.status, cert.tentativas) == (FALHOU, 1)


def test_certificado_inexistente_e_ignorado(caixa):
    assert processar_certificado(999).situacao == "ignorado"
