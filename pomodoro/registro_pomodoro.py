"""
Log do pomodoro no arquivo de eventos (~/tcc-logs/eventos_AAAA-MM-DD.csv, ver registro/).

Em vez de espalhar chamadas de log pelo main.py, compara o estado do pomodoro antes e depois
de cada volta do laço e grava só as TRANSIÇÕES (lógica pura em `transicoes`, testável):

    preset          troca de preset na seleção (detalhe: o nome)
    foco_inicio     começou um foco (da seleção ou depois de uma pausa)
    foco_fim, pausa_inicio, pausa_fim, pausa_longa_inicio, pausa_longa_fim
    pausou          timer congelado (detalhe: a fase)
    retomou         timer voltou a correr
    voltou_selecao  longo no B2 no meio de uma fase (detalhe: a fase interrompida)

Limitação: na demo acelerada (--velocidade alta) um tick pode atravessar mais de uma fase e
o log mostra só a primeira e a última. No uso normal (velocidade 1) isso não acontece.
"""
import os
import sys
from collections import namedtuple

sys.path.insert(0, os.path.realpath(os.path.join(os.path.dirname(os.path.realpath(__file__)),
                                                 os.pardir, "registro")))
from registro_comum import RegistroEventos, ORIGEM_POMODORO, ORIGEM_SISTEMA  # noqa: E402

from pomodoro_logica import SELECAO, PAUSADO, FOCO, PAUSA, PAUSA_LONGA, FASES_RODANDO  # noqa: E402

NOME_FASE = {FOCO: "foco", PAUSA: "pausa", PAUSA_LONGA: "pausa_longa"}

Foto = namedtuple("Foto", "estado fase preset ciclo ciclos")


def foto(pomo):
    return Foto(pomo.estado, pomo.fase_atual, pomo.preset["nome"], pomo.ciclo_atual,
                pomo.ciclos_ate_longa)


def _detalhe(f):
    return f"preset={f.preset} ciclo={f.ciclo}/{f.ciclos}"


def transicoes(antes, depois):
    """Lista de (evento, detalhe) que levou de `antes` a `depois` (duas Foto)."""
    if antes is None or antes == depois:
        return []
    a_rodando, d_rodando = antes.estado in FASES_RODANDO, depois.estado in FASES_RODANDO
    if antes.estado == SELECAO and depois.estado == SELECAO:
        return [("preset", depois.preset)] if antes.preset != depois.preset else []
    if antes.estado == SELECAO and d_rodando:
        return [(f"{NOME_FASE[depois.estado]}_inicio", _detalhe(depois))]
    if depois.estado == SELECAO:
        return [("voltou_selecao", f"interrompeu {NOME_FASE.get(antes.fase, antes.fase)} "
                                   f"{_detalhe(antes)}")]
    if a_rodando and depois.estado == PAUSADO:
        return [("pausou", f"{NOME_FASE[antes.estado]} {_detalhe(antes)}")]
    if antes.estado == PAUSADO and d_rodando:
        return [("retomou", f"{NOME_FASE[depois.estado]} {_detalhe(depois)}")]
    if a_rodando and d_rodando and antes.estado != depois.estado:
        return [(f"{NOME_FASE[antes.estado]}_fim", _detalhe(antes)),
                (f"{NOME_FASE[depois.estado]}_inicio", _detalhe(depois))]
    return []


class LogPomodoro:
    def __init__(self, eventos=None):
        self.eventos = eventos or RegistroEventos("pomodoro")
        self._ultima = None

    def observar(self, pomo):
        """Chamar a cada volta do laço: grava o que mudou desde a última chamada."""
        atual = foto(pomo)
        for evento, detalhe in transicoes(self._ultima, atual):
            self.eventos.registrar(ORIGEM_POMODORO, evento, detalhe)
        self._ultima = atual

    def pausa_postura_b1(self, acao):
        """B1 segurado ≥ 5 s pediu pausar/retomar a postura (o serviço grava se aconteceu)."""
        self.eventos.registrar(ORIGEM_POMODORO, f"b1_{acao}_postura", "")

    def desligar_b3(self):
        """O B3 pediu o poweroff (vai com fsync: separa desligamento pedido de queda)."""
        self.eventos.registrar(ORIGEM_SISTEMA, "desligar_b3", "poweroff pedido pelo B3")
