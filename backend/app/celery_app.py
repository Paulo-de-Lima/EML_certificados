from celery import Celery
from celery.signals import worker_process_init

from . import config
from .database import engine

celery = Celery("certificados", broker=config.BROKER_URL, include=["app.tasks"])

celery.conf.update(
    # --- As três linhas que respondem "dois certificados ou nenhum?" ---
    # 1) Só confirma (ack) a mensagem DEPOIS de a tarefa terminar. Se o worker
    #    morrer no meio, o RabbitMQ devolve a mensagem à fila. O padrão do Celery
    #    é confirmar ANTES de executar, e aí a tarefa se perderia.
    task_acks_late=True,
    # 2) Se o processo filho do worker for morto (kill -9, falta de memória),
    #    a mensagem também volta à fila em vez de ser descartada.
    task_reject_on_worker_lost=True,
    # 3) Cada processo reserva só 1 mensagem por vez. Sem isso, um worker
    #    "seguraria" várias mensagens que os outros poderiam estar processando.
    worker_prefetch_multiplier=1,
    # Não guardamos o retorno das tarefas: o estado fica no MySQL.
    task_ignore_result=True,
    broker_connection_retry_on_startup=True,
    timezone="America/Sao_Paulo",
)


@worker_process_init.connect
def _nova_conexao_por_processo(**_):
    # O Celery cria processos filhos com fork; conexões de banco herdadas do
    # processo pai não podem ser compartilhadas. Cada filho abre as suas.
    engine.dispose(close=False)
