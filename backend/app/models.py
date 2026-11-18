from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base

# Estados de um certificado.
PENDENTE = "PENDENTE"  # ainda não enviado (na fila ou aguardando nova tentativa)
ENVIADO = "ENVIADO"    # e-mail entregue ao servidor; estado final
FALHOU = "FALHOU"      # esgotou as tentativas ou o servidor recusou; pode ser reprocessado
INVALIDO = "INVALIDO"  # linha do CSV com problema; nunca entra na fila


class Lote(Base):
    __tablename__ = "lotes"

    id: Mapped[int] = mapped_column(primary_key=True)
    nome_arquivo: Mapped[str] = mapped_column(String(255))
    total: Mapped[int] = mapped_column(Integer)
    criado_em: Mapped[datetime] = mapped_column(DateTime)

    certificados: Mapped[list["Certificado"]] = relationship(
        back_populates="lote", cascade="all, delete-orphan"
    )


class Certificado(Base):
    """Uma linha por participante do lote. É a 'fonte da verdade' da idempotência:
    a tarefa só envia o e-mail se o status ainda não for ENVIADO."""

    __tablename__ = "certificados"
    __table_args__ = (
        # Garante no banco que a mesma linha do CSV não vira dois certificados.
        UniqueConstraint("lote_id", "linha", name="uq_lote_linha"),
        Index("ix_lote_status", "lote_id", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    lote_id: Mapped[int] = mapped_column(ForeignKey("lotes.id", ondelete="CASCADE"))
    linha: Mapped[int] = mapped_column(Integer)  # número da linha no CSV
    nome: Mapped[str] = mapped_column(String(255))
    email: Mapped[str] = mapped_column(String(255))
    # Código de verificação impresso no PDF; também vira o Message-ID do e-mail.
    codigo: Mapped[str] = mapped_column(String(32), unique=True)
    status: Mapped[str] = mapped_column(String(10), default=PENDENTE)
    tentativas: Mapped[int] = mapped_column(Integer, default=0)
    erro: Mapped[str | None] = mapped_column(String(500), nullable=True)
    enviado_em: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    lote: Mapped[Lote] = relationship(back_populates="certificados")
