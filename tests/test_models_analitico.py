from datetime import datetime
from decimal import Decimal

from tcc_jobs.db.models import ExecucaoModelo, IngestaoLog, Previsao, SerieMensal


def test_registra_log_de_ingestao(sessao):
    sessao.add(
        IngestaoLog(
            competencia="202401",
            arquivo="202401_Licitação.csv",
            linhas_lidas=2537,
            linhas_inseridas=2500,
            linhas_atualizadas=37,
            linhas_rejeitadas=0,
            iniciado_em=datetime(2026, 8, 2, 10, 0),
            finalizado_em=datetime(2026, 8, 2, 10, 2),
            status="sucesso",
        )
    )
    sessao.commit()

    log = sessao.query(IngestaoLog).one()
    assert log.linhas_lidas == 2537
    assert log.status == "sucesso"


def test_serie_mensal_agrega_por_orgao_e_modalidade(sessao):
    sessao.add(
        SerieMensal(
            competencia="202401",
            codigo_orgao="22000",
            codigo_modalidade=5,
            quantidade_licitacoes=120,
            valor_total=Decimal("4500000.0000"),
            valor_mediano=Decimal("32000.0000"),
        )
    )
    sessao.commit()

    assert sessao.query(SerieMensal).one().quantidade_licitacoes == 120


def test_previsao_referencia_execucao_e_guarda_intervalo(sessao):
    execucao = ExecucaoModelo(
        tipo="forecast",
        algoritmo="AutoARIMA",
        parametros_json={"season_length": 12},
        metricas_json={"mae": 12.5, "mae_baseline": 18.1},
        janela_treino_inicio="201301",
        janela_treino_fim="202312",
        executado_em=datetime(2026, 8, 2, 12, 0),
    )
    sessao.add(execucao)
    sessao.commit()

    sessao.add(
        Previsao(
            execucao_id=execucao.id,
            serie_chave="orgao:22000",
            competencia_alvo="202401",
            alvo="quantidade",
            valor_previsto=Decimal("118.0000"),
            ic_inferior=Decimal("101.0000"),
            ic_superior=Decimal("135.0000"),
        )
    )
    sessao.commit()

    prev = sessao.query(Previsao).one()
    assert prev.serie_chave == "orgao:22000"
    assert prev.ic_inferior < prev.valor_previsto < prev.ic_superior
    assert sessao.get(ExecucaoModelo, prev.execucao_id).metricas_json["mae"] == 12.5
