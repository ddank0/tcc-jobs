from pathlib import Path

from sqlalchemy import Engine, text
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
    dela conflita com o lock exclusivo do DROP CONSTRAINT.
    """
    from tcc_jobs.db.base import Base

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

    for tabela in ("modalidade", "orgao", "unidade_gestora", "fornecedor", "licitacao"):
        total = sessao.execute(text(f"SELECT count(*) FROM {tabela}")).scalar()
        assert total is not None and total > 0, f"{tabela} vazia"


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
    assert resultado.inseridas["licitacao"] > 0


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
