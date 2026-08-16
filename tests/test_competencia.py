import pytest

from tcc_jobs.core.competencia import Competencia


def test_cria_de_string() -> None:
    c = Competencia.de_str("202401")
    assert c.ano == 2024
    assert c.mes == 1
    assert str(c) == "202401"


@pytest.mark.parametrize("valor", ["2013", "20130", "2013-01", "201313", "201300", "abcdef", ""])
def test_rejeita_formato_invalido(valor: str) -> None:
    with pytest.raises(ValueError, match="competência"):
        Competencia.de_str(valor)


def test_ordenacao_permite_comparar() -> None:
    assert Competencia.de_str("201312") < Competencia.de_str("201401")
    assert Competencia.de_str("202404") > Competencia.de_str("201301")


def test_intervalo_atravessa_o_ano() -> None:
    janela = Competencia.intervalo(Competencia.de_str("201311"), Competencia.de_str("201402"))
    assert [str(c) for c in janela] == ["201311", "201312", "201401", "201402"]


def test_intervalo_de_um_mes() -> None:
    c = Competencia.de_str("202401")
    assert Competencia.intervalo(c, c) == [c]


def test_intervalo_invertido_falha() -> None:
    with pytest.raises(ValueError, match="invertido"):
        Competencia.intervalo(Competencia.de_str("202404"), Competencia.de_str("201301"))


def test_janela_completa_tem_136_competencias() -> None:
    """201301 a 202404 é a janela disponível na fonte: 11 anos completos mais
    janeiro a abril de 2024."""
    janela = Competencia.intervalo(Competencia.de_str("201301"), Competencia.de_str("202404"))
    assert len(janela) == 136
