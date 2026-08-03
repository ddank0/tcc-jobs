import pytest
from sqlalchemy.exc import IntegrityError

from tcc_jobs.db.models import Fornecedor, Orgao, UnidadeGestora


def test_persiste_orgao(sessao):
    sessao.add(Orgao(codigo_orgao="22000", nome="Ministério da Agricultura e Pecuária"))
    sessao.commit()

    orgao = sessao.get(Orgao, "22000")
    assert orgao is not None
    assert orgao.nome == "Ministério da Agricultura e Pecuária"


def test_unidade_gestora_referencia_orgao(sessao):
    sessao.add(Orgao(codigo_orgao="22000", nome="Ministério da Agricultura e Pecuária"))
    sessao.add(
        UnidadeGestora(
            codigo_ug="130094",
            nome="SUPERINT.DE AGRICULTURA E PECUARIA - SFA/PA",
            codigo_orgao="22000",
        )
    )
    sessao.commit()

    ug = sessao.get(UnidadeGestora, "130094")
    assert ug is not None
    assert ug.codigo_orgao == "22000"


def test_unidade_gestora_sem_orgao_falha(sessao):
    sessao.add(UnidadeGestora(codigo_ug="130094", nome="SFA/PA", codigo_orgao="99999"))
    with pytest.raises(IntegrityError):
        sessao.commit()


def test_fornecedor_usa_cnpj_como_chave(sessao):
    sessao.add(Fornecedor(cnpj="14986916000177", nome="CORDEL AUTOMACAO & SERVICOS LTDA"))
    sessao.commit()

    assert sessao.get(Fornecedor, "14986916000177").nome == "CORDEL AUTOMACAO & SERVICOS LTDA"
