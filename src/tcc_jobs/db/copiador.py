"""Carga em massa via COPY do PostgreSQL.

É o ponto de desempenho mais crítico do projeto: são 21,8 milhões de linhas em
participante_licitacao, e inserção por ORM instanciaria um objeto Python para
cada uma - diferença entre minutos e horas.
"""

import polars as pl
from sqlalchemy import Connection


def copiar_para_tabela(
    conn: Connection,
    tabela: str,
    df: pl.DataFrame,
    colunas: list[str],
) -> int:
    """Copia o DataFrame para a tabela, devolvendo o número de linhas.

    Usa o COPY do psycopg3 com write_row, que preserva tipos - inclusive
    Decimal, sem passar por float e perder precisão.

    iter_rows percorre o DataFrame em Rust e entrega tuplas prontas: não é
    laço Python sobre dados brutos, e é a interface que write_row exige. A
    alternativa, to_dicts(), materializaria milhões de dicionários.
    """
    if df.height == 0:
        return 0

    lista_colunas = ", ".join(f'"{c}"' for c in colunas)
    sql = f'COPY "{tabela}" ({lista_colunas}) FROM STDIN'

    cursor = conn.connection.cursor()
    with cursor.copy(sql) as copy:
        for linha in df.select(colunas).iter_rows():
            copy.write_row(linha)

    return df.height
