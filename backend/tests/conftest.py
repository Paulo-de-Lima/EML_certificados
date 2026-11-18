"""Os testes rodam sem Docker: SQLite no lugar do MySQL e um servidor de
e-mail falso (uma lista em memória) no lugar do Mailpit."""
import os
import tempfile

_dir = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{_dir}/teste.db"
os.environ["BROKER_URL"] = "memory://"
os.environ["MAX_TENTATIVAS"] = "3"

from datetime import datetime  # noqa: E402

import pytest  # noqa: E402

from app import mailer  # noqa: E402
from app.database import Base, SessionLocal, engine  # noqa: E402
from app.models import Certificado, Lote  # noqa: E402


class CaixaFalsa:
    """Faz o papel do Mailpit: guarda os e-mails 'entregues'."""

    def __init__(self):
        self.entregues = []  # códigos dos certificados, na ordem de chegada
        self.falhar_com = None  # exceção a levantar ANTES de entregar
        self.morrer_depois_de_entregar = False

    def enviar(self, destinatario, nome, codigo, pdf):
        if self.falhar_com is not None:
            raise self.falhar_com
        assert pdf.startswith(b"%PDF")
        self.entregues.append(codigo)
        if self.morrer_depois_de_entregar:
            raise WorkerMorreu()

    def ja_foi_entregue(self, codigo, destinatario):
        return codigo in self.entregues


class WorkerMorreu(BaseException):
    """Simula o processo sendo encerrado (kill) no meio da tarefa."""


@pytest.fixture(autouse=True)
def banco_limpo():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield


@pytest.fixture
def caixa(monkeypatch):
    c = CaixaFalsa()
    monkeypatch.setattr(mailer, "enviar", c.enviar)
    monkeypatch.setattr(mailer, "ja_foi_entregue", c.ja_foi_entregue)
    return c


@pytest.fixture
def cert_id():
    """Cria um lote com um certificado pendente e devolve o id dele."""
    with SessionLocal() as db:
        lote = Lote(nome_arquivo="t.csv", total=1, criado_em=datetime(2026, 11, 16))
        cert = Certificado(
            lote=lote, linha=2, nome="Ana Souza", email="ana@exemplo.com", codigo="abc123"
        )
        db.add(cert)
        db.commit()
        return cert.id


def buscar(cert_id):
    with SessionLocal() as db:
        return db.get(Certificado, cert_id)
