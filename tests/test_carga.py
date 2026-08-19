from pathlib import Path

import polars as pl
from sqlalchemy import Engine, event, text
from sqlalchemy.orm import Session

from tcc_jobs.core.competencia import Competencia
from tcc_jobs.db.carga import carregar
from tcc_jobs.etl.armazenamento import Armazenamento
from tcc_jobs.etl.pipeline import ingerir
from tests.conftest import CriarCliente

C = Competencia.de_str("202401")


def _zerar(engine: Engine) -> None:
    """Limpa o banco sem manter transação aberta.

    A fixture `sessao` não serve para os testes de carga inicial: a transação
    dela conflita com o lock exclusivo do DROP CONSTRAINT. Mas a garantia de
    esquema precisa ser a mesma - sem ela, estes testes dependem de outro
    arquivo ter rodado antes, e a ordem de execução vira acoplamento.
    """
    from sqlalchemy import inspect

    from tcc_jobs.db.base import Base

    esperadas = set(Base.metadata.tables)
    if not esperadas <= set(inspect(engine).get_table_names()):
        with engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
        Base.metadata.create_all(engine)

    with engine.begin() as conn:
        nomes = ", ".join(f'"{t}"' for t in Base.metadata.tables)
        conn.execute(text(f"TRUNCATE {nomes} RESTART IDENTITY CASCADE"))


def _silver_pronto(tmp_path: Path, criar_cliente: CriarCliente) -> Armazenamento:
    arm = Armazenamento(tmp_path)
    ingerir([C], criar_cliente(), arm)
    return arm


def test_carrega_dimensoes_e_fatos(
    sessao: Session, engine: Engine, tmp_path: Path, criar_cliente: CriarCliente
) -> None:
    arm = _silver_pronto(tmp_path, criar_cliente)

    carregar([C], arm, engine)

    # Contagens exatas, e as tabelas filhas incluídas. Com `> 0` e sem item e
    # participante na lista, uma carga que nunca inserisse item passava - o
    # teste seguinte comparava 0 com 0 e também não via.
    esperado = {
        "modalidade": 5,
        "orgao": 24,
        "unidade_gestora": 30,
        "licitacao": 30,
        "item_licitacao": 30,
        "participante_licitacao": 30,
    }
    obtido = {t: sessao.execute(text(f"SELECT count(*) FROM {t}")).scalar() for t in esperado}
    assert obtido == esperado


def test_reprocessar_nao_duplica(
    sessao: Session, engine: Engine, tmp_path: Path, criar_cliente: CriarCliente
) -> None:
    """O requisito central da ingestão."""
    arm = _silver_pronto(tmp_path, criar_cliente)

    carregar([C], arm, engine)
    antes = {
        t: sessao.execute(text(f"SELECT count(*) FROM {t}")).scalar()
        for t in ("licitacao", "item_licitacao", "participante_licitacao", "orgao")
    }

    carregar([C], arm, engine)
    depois = {
        t: sessao.execute(text(f"SELECT count(*) FROM {t}")).scalar()
        for t in ("licitacao", "item_licitacao", "participante_licitacao", "orgao")
    }

    assert antes == depois


def test_chave_natural_impede_duplicata(
    sessao: Session, engine: Engine, tmp_path: Path, criar_cliente: CriarCliente
) -> None:
    """Licitação aberta em dezembro reaparece na competência de janeiro."""
    arm = _silver_pronto(tmp_path, criar_cliente)
    carregar([C], arm, engine)

    duplicatas = sessao.execute(
        text("""
        SELECT count(*) FROM (
            SELECT numero_licitacao, codigo_ug, codigo_modalidade
            FROM licitacao GROUP BY 1, 2, 3 HAVING count(*) > 1
        ) d
        """)
    ).scalar()

    assert duplicatas == 0


def test_filhos_referenciam_licitacao_existente(
    sessao: Session, engine: Engine, tmp_path: Path, criar_cliente: CriarCliente
) -> None:
    arm = _silver_pronto(tmp_path, criar_cliente)

    carregar([C], arm, engine)

    orfaos = sessao.execute(
        text("""
        SELECT count(*) FROM participante_licitacao p
        LEFT JOIN licitacao l ON l.id = p.licitacao_id
        WHERE l.id IS NULL
        """)
    ).scalar()
    assert orfaos == 0


def test_hierarquia_de_orgaos_carrega_com_fk_diferida(
    sessao: Session, engine: Engine, tmp_path: Path, criar_cliente: CriarCliente
) -> None:
    """Os órgãos superiores entram como órgãos próprios, e a ordem de inserção
    não importa porque a FK é diferida."""
    arm = _silver_pronto(tmp_path, criar_cliente)

    carregar([C], arm, engine)

    com_superior = sessao.execute(
        text("SELECT count(*) FROM orgao WHERE codigo_orgao_superior IS NOT NULL")
    ).scalar()
    assert com_superior is not None and com_superior > 0

    quebradas = sessao.execute(
        text("""
        SELECT count(*) FROM orgao o
        LEFT JOIN orgao s ON s.codigo_orgao = o.codigo_orgao_superior
        WHERE o.codigo_orgao_superior IS NOT NULL AND s.codigo_orgao IS NULL
        """)
    ).scalar()
    assert quebradas == 0


def test_localizacao_vai_para_unidade_gestora(
    sessao: Session, engine: Engine, tmp_path: Path, criar_cliente: CriarCliente
) -> None:
    """uf e municipio pertencem à UG, não à licitação."""
    arm = _silver_pronto(tmp_path, criar_cliente)

    carregar([C], arm, engine)

    com_uf = sessao.execute(
        text("SELECT count(*) FROM unidade_gestora WHERE uf IS NOT NULL")
    ).scalar()
    assert com_uf is not None and com_uf > 0


def test_relata_linhas_inseridas(
    sessao: Session, engine: Engine, tmp_path: Path, criar_cliente: CriarCliente
) -> None:
    arm = _silver_pronto(tmp_path, criar_cliente)

    resultado = carregar([C], arm, engine)[0]

    assert resultado.erro is None
    assert resultado.inseridas["licitacao"] == 30
    assert resultado.inseridas["item"] == 30
    assert resultado.inseridas["participante"] == 30


def test_silver_ausente_relata_erro(sessao: Session, engine: Engine, tmp_path: Path) -> None:
    """Rodar load sem ingest antes não deve estourar exceção."""
    resultado = carregar([C], Armazenamento(tmp_path), engine)[0]

    assert resultado.erro is not None
    assert "silver" in resultado.erro


def test_carga_inicial_produz_o_mesmo_resultado(
    engine: Engine, tmp_path: Path, criar_cliente: CriarCliente
) -> None:
    """O modo rápido remove as FKs durante o INSERT, mas o resultado precisa
    ser idêntico - e as constraints têm de voltar ao final.

    Não usa a fixture `sessao`: ela mantém uma transação aberta, e o
    DROP CONSTRAINT precisa de ACCESS EXCLUSIVE - os dois juntos travam. Essa
    incompatibilidade é a razão de o modo depender de flag explícita.
    """
    _zerar(engine)
    arm = _silver_pronto(tmp_path, criar_cliente)

    carregar([C], arm, engine, carga_inicial=True)

    with engine.connect() as conn:
        participantes = conn.execute(text("SELECT count(*) FROM participante_licitacao")).scalar()
        fks = conn.execute(
            text("""
            SELECT count(*) FROM pg_constraint
            WHERE conrelid = CAST('participante_licitacao' AS regclass) AND contype = 'f'
            """)
        ).scalar()

    assert participantes is not None and participantes > 0
    assert fks == 2, "as chaves estrangeiras precisam ser recriadas"


def test_carga_inicial_tambem_e_idempotente(
    engine: Engine, tmp_path: Path, criar_cliente: CriarCliente
) -> None:
    _zerar(engine)
    arm = _silver_pronto(tmp_path, criar_cliente)

    carregar([C], arm, engine, carga_inicial=True)
    with engine.connect() as conn:
        antes = conn.execute(text("SELECT count(*) FROM participante_licitacao")).scalar()

    carregar([C], arm, engine, carga_inicial=True)
    with engine.connect() as conn:
        depois = conn.execute(text("SELECT count(*) FROM participante_licitacao")).scalar()

    assert antes == depois


def _contar_ddl_de_constraint(engine: Engine) -> list[str]:
    """Registra os ALTER TABLE ... CONSTRAINT emitidos."""
    emitidos: list[str] = []

    def espiao(conn: object, cursor: object, sql: str, *_: object) -> None:
        if "CONSTRAINT" in sql.upper() and "ALTER TABLE" in sql.upper():
            emitidos.append(sql)

    event.listen(engine, "before_cursor_execute", espiao)
    return emitidos


def test_carga_inicial_recria_as_fks_uma_vez_por_lote(
    engine: Engine, tmp_path: Path, criar_cliente: CriarCliente
) -> None:
    """O ADD CONSTRAINT revalida a tabela filha inteira.

    Medido na base cheia: 15,9 s para uma única FK de participante_licitacao.
    Fazer isso por competência torna a carga O(N x M) - as 136 competências
    revalidariam uma tabela que cresce até 74,8 milhões de linhas. O contexto
    precisa envolver o lote, não cada competência.
    """
    _zerar(engine)
    outra = Competencia.de_str("202402")
    arm = Armazenamento(tmp_path)
    ingerir([C, outra], criar_cliente(), arm)  # as duas com silver de verdade
    emitidos = _contar_ddl_de_constraint(engine)

    carregar([C, outra], arm, engine, carga_inicial=True)

    adicionados = [s for s in emitidos if "ADD CONSTRAINT" in s.upper()]
    assert len(adicionados) == 4, (
        f"esperado 4 ADD CONSTRAINT (2 tabelas x 2 FKs), uma vez para o lote "
        f"inteiro; foram {len(adicionados)}: {adicionados}"
    )


def test_carga_inicial_recria_as_fks_mesmo_se_uma_competencia_falha(
    engine: Engine, tmp_path: Path, criar_cliente: CriarCliente
) -> None:
    """O finally roda em conexão nova.

    Se ele reaproveitasse a conexão da falha, o ADD CONSTRAINT esbarraria em
    "current transaction is aborted" e o banco ficaria sem chave estrangeira.
    """
    _zerar(engine)
    arm = _silver_pronto(tmp_path, criar_cliente)

    # a segunda competência não tem silver: falha no meio do lote
    carregar([C, Competencia.de_str("209912")], arm, engine, carga_inicial=True)

    with engine.connect() as conn:
        fks = conn.execute(
            text("""
            SELECT count(*) FROM pg_constraint
            WHERE conrelid IN (
                CAST('participante_licitacao' AS regclass),
                CAST('item_licitacao' AS regclass))
              AND contype = 'f'
            """)
        ).scalar()

    assert fks == 4, "as chaves estrangeiras precisam voltar mesmo após falha"


def test_falha_de_carga_vai_para_o_ingestao_log(
    sessao: Session, engine: Engine, tmp_path: Path
) -> None:
    """O RF10 existe para o caminho de falha.

    Antes o early-exit de silver ausente usava `return` de dentro do `try`,
    saindo da função antes de _registrar. A competência que falhava não
    deixava rastro nenhum - exatamente o caso em que o log importa.
    """
    carregar([C], Armazenamento(tmp_path), engine)

    linha = sessao.execute(
        text("SELECT status, mensagem_erro FROM ingestao_log WHERE competencia = :c"),
        {"c": str(C)},
    ).one_or_none()

    assert linha is not None, "competência que falhou precisa aparecer no log"
    assert linha[0] == "erro"
    assert "silver" in linha[1]


def test_log_registra_lidas_e_rejeitadas_de_verdade(
    sessao: Session, engine: Engine, tmp_path: Path, criar_cliente: CriarCliente
) -> None:
    """Os quatro números do RF10 precisam medir algo.

    `lidas` já foi a soma das linhas *escritas*, e `rejeitadas` era zero fixo -
    três dos quatro campos não mediam nada, e foi essa cegueira que deixou a
    competência 201812 registrar sucesso tendo perdido os participantes.
    """
    arm = _silver_pronto(tmp_path, criar_cliente)
    carregar([C], arm, engine)

    lidas, inseridas = sessao.execute(
        text("SELECT linhas_lidas, linhas_inseridas FROM ingestao_log WHERE competencia = :c"),
        {"c": str(C)},
    ).one()

    esperado = sum(
        pl.read_parquet(arm.caminho_silver(C, t)).height
        for t in ("licitacao", "item", "participante")
    )
    assert lidas == esperado, "linhas_lidas deve contar o que veio do silver"
    assert inseridas > 0
