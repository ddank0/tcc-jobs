"""O .importlinter cobre todos os módulos que existem?

Os contratos só valem para o que está escrito neles. Um módulo novo do núcleo
que ninguém lembra de listar fica livre para importar a casca, e o
`lint-imports` segue verde - foi o que aconteceu com `etl/agregacao.py` na
T10, que entrou em `nucleo-etl-e-puro` mas ficou fora das camadas.

Este teste é o que torna a regra "cada módulo novo entra no .importlinter na
mesma tarefa que o cria" verificável em vez de combinada.
"""

import configparser
import tomllib
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
PACOTE = RAIZ / "src" / "tcc_jobs"


def _contratos() -> configparser.ConfigParser:
    cfg = configparser.ConfigParser()
    cfg.read(RAIZ / ".importlinter", encoding="utf-8")
    return cfg


def _modulos_do_pacote() -> set[str]:
    """Todo módulo importável de tcc_jobs, exceto migrations e __init__."""
    encontrados: set[str] = set()
    for arquivo in PACOTE.rglob("*.py"):
        relativo = arquivo.relative_to(PACOTE.parent)
        if "migrations" in relativo.parts or arquivo.name == "__init__.py":
            continue
        encontrados.add(".".join(relativo.with_suffix("").parts))
    return encontrados


def _texto_dos_contratos() -> str:
    cfg = _contratos()
    return " ".join(cfg[secao][chave] for secao in cfg.sections() for chave in cfg[secao])


def test_todo_modulo_esta_em_algum_contrato() -> None:
    texto = _texto_dos_contratos()

    descobertos = sorted(
        m for m in _modulos_do_pacote() if m not in texto and m.rsplit(".", 1)[0] not in texto
    )

    assert descobertos == [], (
        "módulos fora de qualquer contrato do .importlinter: "
        f"{descobertos}. Todo módulo novo entra nos contratos na mesma tarefa que o cria."
    )


def test_nucleo_esta_ranqueado_nas_camadas() -> None:
    """Estar em `nucleo-etl-e-puro` não basta.

    Aquele contrato só proíbe importar db, portal e cli. Quem impede o núcleo
    de importar a casca de disco - `etl/armazenamento.py` - é o ranqueamento
    em `camadas`.
    """
    camadas = _contratos()["importlinter:contract:camadas"]["layers"]

    for modulo in ("tcc_jobs.etl.parsers", "tcc_jobs.etl.agregacao"):
        assert modulo in camadas, f"{modulo} é núcleo e precisa estar ranqueado em `camadas`"


def test_pyproject_e_importlinter_apontam_para_o_mesmo_pacote() -> None:
    with (RAIZ / "pyproject.toml").open("rb") as f:
        pyproject = tomllib.load(f)

    assert pyproject["project"]["name"] == "tcc-jobs"
    secao = _contratos()["importlinter"]
    chave = "root_packages" if "root_packages" in secao else "root_package"
    assert "tcc_jobs" in secao[chave]
