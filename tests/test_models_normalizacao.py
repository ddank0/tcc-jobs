"""Testes das correções de 3FN.

Ver [[Licitações - Decisões de Modelagem]] para as dependências funcionais
medidas que motivaram cada uma.
"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from tcc_jobs.db.models import (
    Licitacao,
    Modalidade,
    Orgao,
    UnidadeGestora,
)


def test_modalidade_e_tabela_propria(sessao: Session) -> None:
    """codigo_modalidade -> modalidade é funcional perfeita (0/6 violações).
    Guardar o nome em licitacao era dependência transitiva."""
    sessao.add(Modalidade(codigo=5, nome="Pregão"))
    sessao.commit()

    m = sessao.get(Modalidade, 5)
    assert m is not None
    assert m.nome == "Pregão"


def test_licitacao_nao_guarda_o_nome_da_modalidade(sessao: Session) -> None:
    assert "modalidade" not in Licitacao.__table__.columns


def test_licitacao_referencia_modalidade(sessao: Session) -> None:
    sessao.add(Orgao(codigo_orgao="22000", nome="Agricultura"))
    sessao.add(UnidadeGestora(codigo_ug="130094", nome="SFA/PA", codigo_orgao="22000"))
    sessao.add(Modalidade(codigo=5, nome="Pregão"))
    sessao.commit()

    sessao.add(
        Licitacao(
            numero_licitacao="000012023",
            codigo_ug="130094",
            codigo_modalidade=5,
            competencia="202401",
            valor=Decimal("170612.0000"),
            data_abertura=date(2023, 12, 26),
        )
    )
    sessao.commit()

    lic = sessao.query(Licitacao).one()
    assert lic.codigo_modalidade == 5


def test_modalidade_inexistente_falha(sessao: Session) -> None:
    sessao.add(Orgao(codigo_orgao="22000", nome="Agricultura"))
    sessao.add(UnidadeGestora(codigo_ug="130094", nome="SFA/PA", codigo_orgao="22000"))
    sessao.commit()

    sessao.add(
        Licitacao(
            numero_licitacao="000012023",
            codigo_ug="130094",
            codigo_modalidade=99,
            competencia="202401",
        )
    )
    with pytest.raises(IntegrityError):
        sessao.commit()


def test_localizacao_pertence_a_unidade_gestora(sessao: Session) -> None:
    """codigo_ug -> uf e municipio são funcionais perfeitas (0/772)."""
    sessao.add(Orgao(codigo_orgao="22000", nome="Agricultura"))
    sessao.add(
        UnidadeGestora(
            codigo_ug="130094",
            nome="SFA/PA",
            uf="PA",
            municipio="BELEM",
            codigo_orgao="22000",
        )
    )
    sessao.commit()

    ug = sessao.get(UnidadeGestora, "130094")
    assert ug is not None
    assert ug.uf == "PA"
    assert ug.municipio == "BELEM"


def test_licitacao_nao_guarda_localizacao(sessao: Session) -> None:
    for coluna in ("uf", "municipio"):
        assert coluna not in Licitacao.__table__.columns


def test_orgao_nao_guarda_nome_do_superior(sessao: Session) -> None:
    """nome_orgao_superior dependia de codigo_orgao_superior, não da PK."""
    assert "nome_orgao_superior" not in Orgao.__table__.columns


def test_orgao_superior_e_auto_relacionamento(sessao: Session) -> None:
    sessao.add(Orgao(codigo_orgao="22000", nome="Ministério da Agricultura"))
    sessao.add(
        Orgao(codigo_orgao="22101", nome="Secretaria Executiva", codigo_orgao_superior="22000")
    )
    sessao.commit()

    subordinado = sessao.get(Orgao, "22101")
    assert subordinado is not None
    superior = sessao.get(Orgao, subordinado.codigo_orgao_superior or "")
    assert superior is not None
    assert superior.nome == "Ministério da Agricultura"


def test_orgao_sem_superior_e_valido(sessao: Session) -> None:
    """Órgão de topo não tem superior."""
    sessao.add(Orgao(codigo_orgao="22000", nome="Ministério da Agricultura"))
    sessao.commit()

    orgao = sessao.get(Orgao, "22000")
    assert orgao is not None
    assert orgao.codigo_orgao_superior is None


def test_fk_do_superior_e_deferrable(sessao: Session) -> None:
    """A carga insere órgãos em lote, sem garantir que o superior venha antes.
    Com a FK diferida, a verificação acontece no commit."""
    # Subordinado antes do superior: só funciona com a FK diferida.
    sessao.add(Orgao(codigo_orgao="22101", nome="Secretaria", codigo_orgao_superior="22000"))
    sessao.add(Orgao(codigo_orgao="22000", nome="Ministério"))
    sessao.commit()

    assert sessao.query(Orgao).count() == 2
