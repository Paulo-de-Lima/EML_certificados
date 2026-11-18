"""Gera o participantes.csv com dados fictícios.

Uso:  python scripts/gerar_participantes.py [quantidade] [arquivo]

Inclui de propósito algumas linhas com problema (e-mail inválido, nome vazio,
e-mail repetido) para a lista de falhas do painel ter o que mostrar.
A semente é fixa: o arquivo gerado é sempre o mesmo.
"""
import csv
import random
import sys
import unicodedata

NOMES = [
    "Ana", "Bruno", "Carla", "Daniel", "Eduarda", "Felipe", "Gabriela", "Henrique",
    "Isabela", "João", "Karina", "Lucas", "Mariana", "Nicolas", "Olívia", "Paulo",
    "Rafaela", "Samuel", "Tatiana", "Vinícius", "Yasmin", "André", "Beatriz", "Caio",
    "Débora", "Érico", "Fernanda", "Gustavo", "Helena", "Ígor", "Júlia", "Leonardo",
    "Letícia", "Marcelo", "Natália", "Otávio", "Priscila", "Rodrigo", "Sofia", "Thiago",
]
SOBRENOMES = [
    "Silva", "Santos", "Oliveira", "Souza", "Rodrigues", "Ferreira", "Alves", "Pereira",
    "Lima", "Gomes", "Costa", "Ribeiro", "Martins", "Carvalho", "Almeida", "Lopes",
    "Soares", "Fernandes", "Vieira", "Barbosa", "Rocha", "Dias", "Nascimento", "Andrade",
    "Moreira", "Nunes", "Marques", "Machado", "Mendes", "Freitas", "Cardoso", "Araújo",
    "Conceição", "Gonçalves", "Assunção", "Brandão",
]


def sem_acento(texto: str) -> str:
    return unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode().lower()


def main() -> None:
    quantidade = int(sys.argv[1]) if len(sys.argv) > 1 else 5000
    arquivo = sys.argv[2] if len(sys.argv) > 2 else "participantes.csv"
    rnd = random.Random(2026)

    linhas = []
    for i in range(1, quantidade + 1):
        nome = f"{rnd.choice(NOMES)} {rnd.choice(SOBRENOMES)} {rnd.choice(SOBRENOMES)}"
        primeiro, *_, ultimo = nome.split()
        email = f"{sem_acento(primeiro)}.{sem_acento(ultimo)}{i}@exemplo.com"
        linhas.append([nome, email])

    # Linhas com problema, espalhadas pelo arquivo (só se o arquivo for grande o bastante).
    if quantidade >= 100:
        passo = quantidade // 10
        for n, i in enumerate(range(passo // 2, quantidade, passo)):
            if n % 3 == 0:
                linhas[i][1] = linhas[i][1].replace("@", "")  # e-mail sem @
            elif n % 3 == 1:
                linhas[i][1] = linhas[i - 1][1]  # e-mail repetido
            else:
                linhas[i][0] = ""  # nome vazio

    with open(arquivo, "w", newline="", encoding="utf-8") as f:
        escritor = csv.writer(f)
        escritor.writerow(["nome", "email"])
        escritor.writerows(linhas)
    print(f"{arquivo}: {len(linhas)} participantes")


if __name__ == "__main__":
    main()
