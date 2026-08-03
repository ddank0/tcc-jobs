from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from tcc_jobs.db.models import (
    Fornecedor,
    ItemLicitacao,
    Licitacao,
    Modalidade,
    Orgao,
    ParticipanteLicitacao,
    UnidadeGestora,
)


@pytest.fixture
def base_minima(sessao: Session) -> Session:
    sessao.add(Orgao(codigo_orgao="22000", nome="Ministério da Agricultura e Pecuária"))
    sessao.add(
        UnidadeGestora(
            codigo_ug="130094", nome="SFA/PA", uf="PA", municipio="BELEM", codigo_orgao="22000"
        )
    )
    sessao.add(Modalidade(codigo=5, nome="Pregão"))
    sessao.add(Modalidade(codigo=8, nome="Dispensa"))
    sessao.add(Fornecedor(cnpj="14986916000177", nome="CORDEL AUTOMACAO & SERVICOS LTDA"))
    sessao.commit()
    return sessao


def nova_licitacao(**kwargs: Any) -> Licitacao:
    padrao = dict(
        numero_licitacao="000012023",
        codigo_ug="130094",
        codigo_modalidade=5,
        numero_processo="21030.002858/2023",
        objeto="Contratação de empresa de engenharia",
        situacao="Evento de Adiamento Publicado",
        data_abertura=date(2023, 12, 26),
        data_resultado=date(2024, 1, 17),
        valor=Decimal("170612.0000"),
        competencia="202401",
    )
    return Licitacao(**{**padrao, **kwargs})


def test_persiste_licitacao(base_minima: Session) -> None:
    base_minima.add(nova_licitacao())
    base_minima.commit()

    lic = base_minima.query(Licitacao).one()
    assert lic.id is not None
    assert lic.valor == Decimal("170612.0000")
    assert lic.data_abertura == date(2023, 12, 26)


def test_chave_natural_impede_duplicata(base_minima: Session) -> None:
    base_minima.add(nova_licitacao())
    base_minima.commit()

    base_minima.add(nova_licitacao(competencia="202402", objeto="outro texto"))
    with pytest.raises(IntegrityError):
        base_minima.commit()


def test_mesma_ug_e_numero_com_modalidade_diferente_coexistem(base_minima: Session) -> None:
    base_minima.add(nova_licitacao())
    base_minima.add(nova_licitacao(codigo_modalidade=8))
    base_minima.commit()

    assert base_minima.query(Licitacao).count() == 2


def test_item_e_participante_referenciam_licitacao(base_minima: Session) -> None:
    lic = nova_licitacao()
    base_minima.add(lic)
    base_minima.commit()

    base_minima.add(
        ItemLicitacao(
            licitacao_id=lic.id,
            codigo_item_compra="1300940500001202300001",
            descricao="SERVICO ENGENHARIA",
            quantidade=Decimal("1"),
            valor_item=Decimal("99500.0000"),
            cnpj_vencedor="14986916000177",
        )
    )
    base_minima.add(
        ParticipanteLicitacao(
            licitacao_id=lic.id,
            codigo_item_compra="1300940500001202300001",
            cnpj_participante="14986916000177",
            flag_vencedor=False,
        )
    )
    base_minima.commit()

    assert base_minima.query(ItemLicitacao).one().valor_item == Decimal("99500.0000")
    assert base_minima.query(ParticipanteLicitacao).one().flag_vencedor is False
