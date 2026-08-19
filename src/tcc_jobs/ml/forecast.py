"""Modelos de previsão. Núcleo funcional: recebem dados, devolvem dados.

Não importa db/ nem portal/ - a casca que lê serie_mensal e grava previsao
fica em runner.py. E não importa etl/: as camadas se comunicam por tabelas.
"""
