import re
from dataclasses import dataclass
from typing import Self

PADRAO = re.compile(r"^(\d{4})(0[1-9]|1[0-2])$")


@dataclass(frozen=True, order=True)
class Competencia:
    """Mês de referência dos dados, no formato AAAAMM.

    Tipo de valor imutável e ordenável: comparação e intervalo saem de graça,
    e o formato é validado uma única vez, na fronteira - em vez de passar str
    solto por dez funções.
    """

    ano: int
    mes: int

    @classmethod
    def de_str(cls, valor: str) -> Self:
        casamento = PADRAO.match(valor)
        if casamento is None:
            raise ValueError(f"competência inválida: {valor!r}. Use o formato AAAAMM, ex: 202401")
        return cls(ano=int(casamento.group(1)), mes=int(casamento.group(2)))

    def __str__(self) -> str:
        return f"{self.ano:04d}{self.mes:02d}"

    def proxima(self) -> Competencia:
        if self.mes == 12:
            return Competencia(self.ano + 1, 1)
        return Competencia(self.ano, self.mes + 1)

    @staticmethod
    def intervalo(de: Competencia, ate: Competencia) -> list[Competencia]:
        if de > ate:
            raise ValueError(f"intervalo invertido: {de} é posterior a {ate}")
        janela = [de]
        while janela[-1] < ate:
            janela.append(janela[-1].proxima())
        return janela
