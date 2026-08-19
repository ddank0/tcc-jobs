"""Backtesting e métricas de erro. Núcleo funcional.

Aqui mora o teste mais importante do projeto: a garantia de que nenhuma
janela de treino contém competência posterior à prevista. Um vazamento é
silencioso e melhora todas as métricas - por isso a geração de janelas é
pura e testada por mutação.
"""
