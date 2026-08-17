"""Estrutura do ZIP da fonte: integridade e recuperação parcial.

Os parsers de cada CSV têm arquivos próprios - aqui fica só o que envolve o
contêiner, que é onde a fonte falha.
"""

import io
import zipfile


def test_zip_integro_aceita_arquivo_valido(zip_amostra: bytes) -> None:
    from tcc_jobs.etl.parsers import zip_integro

    assert zip_integro(zip_amostra) is True


def test_zip_integro_recusa_truncado(zip_amostra: bytes) -> None:
    """Um download interrompido ainda começa com a assinatura PK - foi assim
    que a competência 201812 entrou em bronze com exatos 8 MiB e ficou lá.
    """
    from tcc_jobs.etl.parsers import zip_integro

    assert zip_integro(zip_amostra[: len(zip_amostra) // 2]) is False


def test_zip_integro_recusa_conteudo_que_nao_e_zip() -> None:
    from tcc_jobs.etl.parsers import zip_integro

    assert zip_integro(b"<html>erro do portal</html>") is False


def test_zip_integro_recusa_vazio() -> None:
    from tcc_jobs.etl.parsers import zip_integro

    assert zip_integro(b"") is False


def _zip_de(membros: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zip_:
        for nome, dados in membros.items():
            zip_.writestr(nome, dados)
    return buffer.getvalue()


def test_extrair_recuperavel_devolve_membros_intactos_de_zip_truncado() -> None:
    """A competência 201812 é publicada corrompida na origem: o ZIP termina em
    exatos 8 MiB, no meio do último membro. Os anteriores estão íntegros, e
    descartá-los abriria um buraco na série temporal por causa de um arquivo
    que nem chegamos a precisar inteiro.
    """
    from tcc_jobs.etl.parsers import extrair_recuperavel

    inteiro = _zip_de(
        {
            "201812_Licitação.csv": b"a;b\n1;2\n" * 500,
            "201812_ParticipantesLicitação.csv": b"c;d\n3;4\n" * 5000,
        }
    )
    truncado = inteiro[: len(inteiro) // 2]

    recuperados = extrair_recuperavel(truncado)

    assert "Licitação" in recuperados
    assert recuperados["Licitação"] == b"a;b\n1;2\n" * 500


def test_extrair_recuperavel_descarta_membro_incompleto() -> None:
    """Metade de um CSV de participantes é pior que nenhum: enviesaria as
    features de competitividade para baixo, sem sinal de que faltou dado.
    """
    from tcc_jobs.etl.parsers import extrair_recuperavel

    inteiro = _zip_de(
        {
            "201812_Licitação.csv": b"a;b\n1;2\n" * 500,
            "201812_ParticipantesLicitação.csv": b"c;d\n3;4\n" * 5000,
        }
    )

    recuperados = extrair_recuperavel(inteiro[: len(inteiro) // 2])

    assert "ParticipantesLicitação" not in recuperados


def test_extrair_recuperavel_de_zip_integro_devolve_tudo(zip_amostra: bytes) -> None:
    from tcc_jobs.etl.parsers import extrair_do_zip, extrair_recuperavel

    assert extrair_recuperavel(zip_amostra).keys() == extrair_do_zip(zip_amostra).keys()


def test_extrair_recuperavel_de_lixo_devolve_vazio() -> None:
    from tcc_jobs.etl.parsers import extrair_recuperavel

    assert extrair_recuperavel(b"<html>erro</html>") == {}
