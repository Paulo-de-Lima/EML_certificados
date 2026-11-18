"""Upload do CSV, progresso, falhas e reprocessamento."""
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app import main, mailer
from app.pdf import gerar_pdf
from app.tasks import processar_certificado

CSV = (
    "nome,email\n"
    "Ana Souza,ana@exemplo.com\n"
    "Bruno Lima,bruno@exemplo.com\n"
    "Carla Dias,email-invalido\n"
    "Ana de Novo,ANA@exemplo.com\n"
)


@pytest.fixture
def api(monkeypatch):
    despachados = []
    monkeypatch.setattr(main.despachar_lote, "delay", despachados.append)
    with TestClient(main.app) as cliente:
        cliente.despachados = despachados
        yield cliente


def enviar_csv(api, conteudo=CSV):
    return api.post("/api/lotes", files={"arquivo": ("participantes.csv", conteudo, "text/csv")})


def test_upload_responde_202_sem_enviar_nada(api, caixa):
    r = enviar_csv(api)
    assert r.status_code == 202
    lote = r.json()
    assert (lote["total"], lote["enviados"], lote["pendentes"], lote["falhas"]) == (4, 0, 2, 2)
    assert lote["status"] == "PROCESSANDO"
    assert api.despachados == [lote["id"]]  # uma mensagem na fila
    assert caixa.entregues == []  # nenhum e-mail saiu durante a requisição


def test_linhas_invalidas_aparecem_na_lista_de_falhas(api):
    lote_id = enviar_csv(api).json()["id"]
    falhas = api.get(f"/api/lotes/{lote_id}/falhas").json()
    assert [(f["linha"], f["erro"]) for f in falhas] == [
        (4, "E-mail inválido"),
        (5, "E-mail repetido (já aparece na linha 2)"),
    ]
    assert not any(f["pode_reprocessar"] for f in falhas)


def test_csv_sem_as_colunas_certas_e_recusado(api):
    assert enviar_csv(api, "a,b\n1,2\n").status_code == 400
    assert enviar_csv(api, "nome,email\n").status_code == 400
    assert api.despachados == []


def test_progresso_avanca_ate_concluir(api, caixa):
    lote_id = enviar_csv(api).json()["id"]
    processar_certificado(1)
    lote = api.get(f"/api/lotes/{lote_id}").json()
    assert (lote["processados"], lote["status"]) == (3, "PROCESSANDO")
    processar_certificado(2)
    lote = api.get(f"/api/lotes/{lote_id}").json()
    assert (lote["processados"], lote["enviados"], lote["status"]) == (4, 2, "CONCLUIDO")
    assert api.get("/api/lotes").json()[0]["id"] == lote_id


def test_reprocessar_devolve_falhas_para_a_fila(api, caixa):
    lote_id = enviar_csv(api).json()["id"]
    caixa.falhar_com = mailer.ErroDefinitivo("recusado")
    processar_certificado(1)
    assert len(api.get(f"/api/lotes/{lote_id}/falhas").json()) == 3

    r = api.post(f"/api/lotes/{lote_id}/reprocessar")
    assert r.status_code == 202
    assert r.json()["pendentes"] == 2
    assert api.despachados == [lote_id, lote_id]

    caixa.falhar_com = None
    processar_certificado(1)
    processar_certificado(2)
    assert api.get(f"/api/lotes/{lote_id}").json()["enviados"] == 2


def test_lote_inexistente(api):
    assert api.get("/api/lotes/999").status_code == 404


def test_auditoria_detecta_duplicado_e_perdido(api, caixa, monkeypatch):
    lote_id = enviar_csv(api).json()["id"]
    processar_certificado(1)
    processar_certificado(2)
    ids = [mailer.message_id(c) for c in caixa.entregues]

    monkeypatch.setattr(mailer, "contar_message_ids", lambda: {ids[0]: 1, ids[1]: 1})
    a = api.get(f"/api/lotes/{lote_id}/auditoria").json()
    assert (a["ok"], a["enviados_no_banco"], a["emails_na_caixa"]) == (True, 2, 2)

    monkeypatch.setattr(mailer, "contar_message_ids", lambda: {ids[0]: 2})
    a = api.get(f"/api/lotes/{lote_id}/auditoria").json()
    assert (a["ok"], a["duplicados"], a["perdidos"]) == (False, 1, 1)


def test_pdf_e_deterministico():
    args = ("José Ação", "Evento", "20", datetime(2026, 11, 16), "abc")
    pdf = gerar_pdf(*args)
    assert pdf.startswith(b"%PDF")
    assert pdf == gerar_pdf(*args)
