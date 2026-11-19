"""
B3 = desligar o Raspberry Pi (`sudo poweroff`). Lógica separada da tela e do GPIO.

Regra: só o aperto MUITO LONGO (≥ LIMITE_MUITO_LONGO_S = 3 s, classificado ao soltar)
desliga. Curto e longo são ignorados, e soltar antes dos 3 s cancela: com botão
instável, um toque sem querer não derruba o sistema. Enquanto segura, a linha de
baixo da tela mostra a contagem.

O `poweroff` NÃO corta a energia do Pi 3B (ele não tem botão de power): depois dele,
só religando a fonte. Espere o LED verde (ACT) parar de piscar antes de tirar da tomada.
"""
import math
import os
import subprocess
import time

from pomodoro_config import (
    COMANDO_DESLIGAR, B3_DICA_APOS_S, LIMITE_MUITO_LONGO_S, MENSAGEM_FALHA_DESLIGAR_S,
)
from pomodoro_logica import MUITO_LONGO

TEXTO_DESLIGANDO = "DESLIGANDO, AGUARDE"
TEXTO_FALHOU = "FALHOU DESLIGAR"
TEXTO_SOLTE = "SOLTE: DESLIGAR PI"


def montar_comando(root=None):
    """Como root não precisa de sudo."""
    if root is None:
        root = hasattr(os, "geteuid") and os.geteuid() == 0
    comando = list(COMANDO_DESLIGAR)
    if root and comando[:1] == ["sudo"]:
        comando = [c for c in comando[1:] if c != "-n"]
    return comando


def rodar_comando(comando):
    """True se o comando saiu com código 0. Qualquer falha (sudo pedindo senha, comando
    ausente, travou) vira False pra tela avisar, em vez de derrubar o programa."""
    try:
        return subprocess.run(comando, capture_output=True, timeout=10).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


class Desligamento:
    def __init__(self, executar=rodar_comando, relogio=time.monotonic, root=None):
        self._executar = executar
        self._relogio = relogio
        self._root = root
        self.em_andamento = False   # comando aceito: o sistema vai desligar
        self._falha_ate = 0.0

    def botao(self, tipo):
        """Evento do B3. Devolve True se pediu o desligamento (e o comando foi aceito)."""
        if tipo != MUITO_LONGO or self.em_andamento:
            return False
        if self._executar(montar_comando(self._root)):
            self.em_andamento = True
            return True
        self._falha_ate = self._relogio() + MENSAGEM_FALHA_DESLIGAR_S
        return False

    def texto(self, segurando_s):
        """Texto da linha de baixo (ou None se o B3 não tem nada a dizer agora)."""
        if self.em_andamento:
            return TEXTO_DESLIGANDO
        if self._relogio() < self._falha_ate:
            return TEXTO_FALHOU
        if segurando_s >= LIMITE_MUITO_LONGO_S:
            return TEXTO_SOLTE
        if segurando_s >= B3_DICA_APOS_S:
            return f"SEGURE {math.ceil(LIMITE_MUITO_LONGO_S - segurando_s)}s: DESLIGAR"
        return None
