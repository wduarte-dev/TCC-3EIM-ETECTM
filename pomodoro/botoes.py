"""
Botões. Duas partes:

1. ClassificadorAperto: lógica PURA que transforma "apertou em t0, soltou em t1"
   em curto / longo / muito_longo. Testável sem GPIO.
2. Backends que geram os eventos de verdade:
     - BotoesGPIO:    gpiozero, no Pi (B1 = GPIO17, B2 = GPIO27)
     - BotoesTeclado: digitar no terminal, pra testar no notebook
         1  → B1 (recalibrar)      2c → B2 curto
         2l → B2 longo             2m → B2 muito longo

Todos mandam os eventos pra uma fila (queue.Queue): ("B1", None) ou ("B2", tipo).
Assim o laço principal consome na própria thread, sem corrida.
"""
import sys
import threading
import time

from pomodoro_config import (
    GPIO_B1, GPIO_B2, DEBOUNCE_S, LIMITE_LONGO_S, LIMITE_MUITO_LONGO_S,
)
from pomodoro_logica import CURTO, LONGO, MUITO_LONGO


def classificar(duracao_s, limite_longo=LIMITE_LONGO_S, limite_muito_longo=LIMITE_MUITO_LONGO_S):
    """Duração do aperto (s) → curto | longo | muito_longo."""
    if duracao_s >= limite_muito_longo:
        return MUITO_LONGO
    if duracao_s >= limite_longo:
        return LONGO
    return CURTO


class ClassificadorAperto:
    """Guarda o instante em que o botão foi apertado e classifica ao soltar."""

    def __init__(self, relogio=time.monotonic):
        self._relogio = relogio
        self._inicio = None

    def apertou(self):
        if self._inicio is None:      # ignora repique de "apertou" sem ter soltado
            self._inicio = self._relogio()

    def soltou(self):
        """Devolve o tipo do aperto, ou None se o 'soltou' veio sem 'apertou'."""
        if self._inicio is None:
            return None
        duracao = self._relogio() - self._inicio
        self._inicio = None
        return classificar(duracao)

    def segurando_ha(self):
        """Segundos desde que apertou (0 se solto). A tela usa pra mostrar a dica."""
        if self._inicio is None:
            return 0.0
        return self._relogio() - self._inicio

    def tipo_se_soltar_agora(self):
        """Pra tela avisar 'continue segurando...' antes de soltar."""
        if self._inicio is None:
            return None
        return classificar(self.segurando_ha())


class BotoesGPIO:
    """B1 age ao APERTAR; B2 age ao SOLTAR (porque depende da duração)."""

    def __init__(self, fila):
        from gpiozero import Button   # import tardio: só existe/funciona no Pi
        self.fila = fila
        self.aperto_b2 = ClassificadorAperto()
        self._b1 = Button(GPIO_B1, pull_up=True, bounce_time=DEBOUNCE_S)
        self._b2 = Button(GPIO_B2, pull_up=True, bounce_time=DEBOUNCE_S)
        self._b1.when_pressed = lambda: self.fila.put(("B1", None))
        self._b2.when_pressed = self.aperto_b2.apertou
        self._b2.when_released = self._b2_soltou

    def _b2_soltou(self):
        tipo = self.aperto_b2.soltou()
        if tipo:
            self.fila.put(("B2", tipo))

    def fechar(self):
        self._b1.close()
        self._b2.close()


class BotoesTeclado:
    """Simula os botões digitando no terminal (uma linha + Enter por aperto)."""

    COMANDOS = {"1": ("B1", None), "2c": ("B2", CURTO),
                "2l": ("B2", LONGO), "2m": ("B2", MUITO_LONGO)}

    def __init__(self, fila):
        self.fila = fila
        self.aperto_b2 = ClassificadorAperto()   # sem uso aqui; mantém a mesma interface
        self._ativo = True
        threading.Thread(target=self._ler, daemon=True).start()

    def _ler(self):
        print("Botões simulados:  1 = B1 recalibrar | 2c = B2 curto | 2l = B2 longo | "
              "2m = B2 muito longo | q = sair", flush=True)
        while self._ativo:
            linha = sys.stdin.readline()
            if linha == "":          # stdin fechou
                return
            linha = linha.strip().lower()
            if linha == "q":
                self.fila.put(("SAIR", None))
                return
            if linha in self.COMANDOS:
                self.fila.put(self.COMANDOS[linha])

    def fechar(self):
        self._ativo = False
