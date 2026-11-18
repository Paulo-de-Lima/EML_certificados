"""Geração do certificado em PDF com fpdf2.

A função é pura: os mesmos dados produzem sempre os mesmos bytes (a data de
criação do PDF é fixada). Gerar de novo numa nova tentativa não muda nada.
"""
from datetime import datetime

from fpdf import FPDF

MESES = [
    "janeiro", "fevereiro", "março", "abril", "maio", "junho",
    "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
]


def _latin1(texto: str) -> str:
    # As fontes embutidas do PDF só cobrem Latin-1 (suficiente para português).
    return texto.encode("latin-1", "replace").decode("latin-1")


def gerar_pdf(nome: str, evento: str, carga_horaria: str, data: datetime, codigo: str) -> bytes:
    pdf = FPDF(orientation="L", unit="mm", format="A4")
    pdf.set_creation_date(data)
    pdf.set_title(_latin1(f"Certificado - {nome}"))
    pdf.set_auto_page_break(False)
    pdf.add_page()

    # Moldura dupla
    pdf.set_draw_color(30, 64, 120)
    pdf.set_line_width(1.5)
    pdf.rect(10, 10, 277, 190)
    pdf.set_line_width(0.4)
    pdf.rect(14, 14, 269, 182)

    pdf.set_text_color(30, 64, 120)
    pdf.set_font("Helvetica", "B", 38)
    pdf.set_y(38)
    pdf.cell(0, 16, "CERTIFICADO", align="C", new_x="LMARGIN", new_y="NEXT")

    pdf.set_text_color(60, 60, 60)
    pdf.set_font("Helvetica", "", 15)
    pdf.ln(12)
    pdf.cell(0, 9, "Certificamos que", align="C", new_x="LMARGIN", new_y="NEXT")

    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Helvetica", "B", 26)
    pdf.ln(4)
    pdf.cell(0, 14, _latin1(nome), align="C", new_x="LMARGIN", new_y="NEXT")

    pdf.set_text_color(60, 60, 60)
    pdf.set_font("Helvetica", "", 15)
    pdf.ln(6)
    pdf.set_x(35)
    pdf.multi_cell(
        227, 9,
        _latin1(
            f"participou do evento {evento}, "
            f"com carga horária total de {carga_horaria} horas."
        ),
        align="C",
    )

    pdf.set_y(150)
    pdf.set_font("Helvetica", "", 12)
    pdf.cell(
        0, 8,
        _latin1(f"{data.day} de {MESES[data.month - 1]} de {data.year}"),
        align="C", new_x="LMARGIN", new_y="NEXT",
    )

    pdf.set_y(182)
    pdf.set_font("Courier", "", 9)
    pdf.set_text_color(120, 120, 120)
    pdf.cell(0, 6, _latin1(f"Código de verificação: {codigo}"), align="C")

    return bytes(pdf.output())
