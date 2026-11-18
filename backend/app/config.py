"""Configuração lida de variáveis de ambiente (definidas no docker-compose.yml)."""
import os

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "mysql+pymysql://app:app@localhost:3307/certificados?charset=utf8mb4",
)
BROKER_URL = os.getenv("BROKER_URL", "amqp://guest:guest@localhost:5672//")

SMTP_HOST = os.getenv("SMTP_HOST", "localhost")
SMTP_PORT = int(os.getenv("SMTP_PORT", "1025"))
EMAIL_REMETENTE = os.getenv("EMAIL_REMETENTE", "certificados@evento.local")

# API HTTP do Mailpit. Usada para (1) perguntar "este e-mail já chegou?" antes
# de reenviar numa reentrega e (2) auditar o lote no final. Vazio = desativado.
MAILPIT_API_URL = os.getenv("MAILPIT_API_URL", "http://localhost:8025")

NOME_EVENTO = os.getenv("NOME_EVENTO", "Semana Acadêmica de Computação 2026")
CARGA_HORARIA = os.getenv("CARGA_HORARIA", "20")

# Quantas vezes tentar enviar antes de marcar o certificado como FALHOU.
MAX_TENTATIVAS = int(os.getenv("MAX_TENTATIVAS", "6"))

# O Mailpit responde em ~1 ms; um servidor de e-mail real leva bem mais.
# Este atraso simula essa latência para a demonstração durar o suficiente.
ATRASO_SIMULADO_MS = int(os.getenv("ATRASO_SIMULADO_MS", "0"))
