"""
Botões. Duas partes:

1. Lógica PURA (testável sem GPIO):
     - Debouncer / detectar_ocioso / EntradaBotao: filtram o ruído do módulo e
       descobrem a polaridade;
     - ClassificadorAperto: transforma "apertou em t0, soltou em t1" em
       curto / longo / muito_longo.
2. Backends que geram os eventos de verdade:
     - BotoesGPIO:    gpiozero, no Pi (B1 = GPIO17, B2 = GPIO27, B3 = GPIO22).
                      Lê os pinos por AMOSTRAGEM (não por callback) e filtra o repique
                      na própria lógica; o módulo VCC/OUT/GND tem resistor próprio,
                      então o pino do Pi fica sem pull interno (ver pomodoro_config.py)
     - BotoesTeclado: digitar no terminal, pra testar no notebook
         1c → B1 curto             2c → B2 curto           3m → B3 muito longo
         1l → B1 longo             2l → B2 longo           (3c e 3l existem, mas o B3 ignora)
         1p → B1 segurado ≥ 5 s (pausa/retoma a postura)
                                   2m → B2 muito longo

Todos mandam os eventos pra uma fila (queue.Queue): ("B1" | "B2" | "B3", tipo).
Assim o laço principal consome na própria thread, sem corrida.
"""
import sys
import threading
import time

from pomodoro_config import (
    GPIO_B1, GPIO_B2, GPIO_B3, LIMITE_LONGO_S, LIMITE_MUITO_LONGO_S, LIMITE_PAUSA_POSTURA_S,
    POLARIDADE_BOTOES, PULL_INTERNO_BOTOES, AUTO_OCIOSO_S, AMOSTRA_S, AMOSTRAS_ESTAVEIS,
)
from pomodoro_logica import CURTO, LONGO, MUITO_LONGO

PAUSA_POSTURA = "pausa_postura"   # só no B1: soltou com ≥ LIMITE_PAUSA_POSTURA_S


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
        self.ultima_duracao = 0.0     # duração do último aperto (s), pra o B1 saber se foi ≥ 5 s

    def apertou(self):
        if self._inicio is None:      # ignora repique de "apertou" sem ter soltado
            self._inicio = self._relogio()

    def soltou(self):
        """Devolve o tipo do aperto, ou None se o 'soltou' veio sem 'apertou'."""
        if self._inicio is None:
            return None
        duracao = self._relogio() - self._inicio
        self._inicio = None
        self.ultima_duracao = duracao
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


class Debouncer:
    """
    Filtro de repique por contagem: o estado só muda depois de `n` leituras SEGUIDAS
    diferentes dele. Uma leitura igual ao estado atual zera a contagem, então
    repique (0,1,0,1...) e picos curtos não passam, nem ao apertar nem ao soltar.
    """

    def __init__(self, inicial, n=AMOSTRAS_ESTAVEIS):
        self.estado = bool(inicial)
        self._n = max(1, n)
        self._contra = 0

    def alimentar(self, leitura):
        leitura = bool(leitura)
        if leitura == self.estado:
            self._contra = 0
        else:
            self._contra += 1
            if self._contra >= self._n:
                self.estado = leitura
                self._contra = 0
        return self.estado


def detectar_ocioso(leituras):
    """
    Nível parado do pino = a maioria das leituras (True = alto).
    Devolve (nivel_ocioso, fracao_minoria). Fração perto de 0 = linha firme;
    acima de ~0,1 = linha instável (fio solto, emenda ruim, pino flutuando).
    """
    leituras = [bool(x) for x in leituras]
    if not leituras:
        raise ValueError("sem leituras")
    altos = sum(leituras)
    ocioso = altos * 2 > len(leituras)
    minoria = (len(leituras) - altos) if ocioso else altos
    return ocioso, minoria / len(leituras)


class EntradaBotao:
    """
    Um botão: leituras brutas do pino (True = nível alto) → tipo do aperto ao soltar.
    `nivel_ocioso` é o nível do pino com o botão solto (False = módulo que sobe ao
    apertar; True = módulo que desce ao apertar). Pura: o relógio é injetável.
    """

    def __init__(self, nivel_ocioso, n_estavel=AMOSTRAS_ESTAVEIS, relogio=time.monotonic):
        self.nivel_ocioso = bool(nivel_ocioso)
        self._filtro = Debouncer(self.nivel_ocioso, n_estavel)
        self.aperto = ClassificadorAperto(relogio)
        self._apertado = False

    def amostrar(self, nivel_alto):
        """Uma leitura do pino. Devolve curto/longo/muito_longo no instante em que soltou."""
        apertado = self._filtro.alimentar(nivel_alto) != self.nivel_ocioso
        tipo = None
        if apertado and not self._apertado:
            self.aperto.apertou()
        elif not apertado and self._apertado:
            tipo = self.aperto.soltou()
        self._apertado = apertado
        return tipo


class BotoesGPIO:
    """
    B1, B2 e B3 no Pi. Agem ao SOLTAR (dependem da duração do aperto).

    Uma thread lê os 3 pinos a cada AMOSTRA_S e passa cada leitura pelo EntradaBotao.
    Polaridade "auto": lê o nível parado por AUTO_OCIOSO_S no início (sem apertar nada).
    """

    PINOS = (("B1", GPIO_B1), ("B2", GPIO_B2), ("B3", GPIO_B3))
    PULLS = {None: (None, True), "baixo": (False, None), "cima": (True, None)}

    def __init__(self, fila, polaridade=POLARIDADE_BOTOES, pull=PULL_INTERNO_BOTOES,
                 fabrica_pinos=None, log=None):
        if polaridade not in ("auto", "alto", "baixo"):
            raise ValueError(f"polaridade inválida: {polaridade!r}")
        if pull not in self.PULLS:
            raise ValueError(f"pull inválido: {pull!r}")
        from gpiozero import DigitalInputDevice   # import tardio: só existe/funciona no Pi
        self.fila = fila
        self._log = log or (lambda msg: print(msg, file=sys.stderr, flush=True))
        pull_up, ativo = self.PULLS[pull]
        self._dispositivos = {}
        for nome, pino in self.PINOS:
            argumentos = {"pull_up": pull_up, "pin_factory": fabrica_pinos}
            if ativo is not None:
                argumentos["active_state"] = ativo   # só é aceito com pino flutuando (pull_up=None)
            self._dispositivos[nome] = DigitalInputDevice(pino, **argumentos)

        ociosos, self.info = self._descobrir_ociosos(polaridade)
        self._entradas = {nome: EntradaBotao(ociosos[nome]) for nome, _ in self.PINOS}
        self.aperto_b1 = self._entradas["B1"].aperto
        self.aperto_b2 = self._entradas["B2"].aperto
        self.aperto_b3 = self._entradas["B3"].aperto

        self._ativo = True
        self._thread = threading.Thread(target=self._laco, daemon=True)
        self._thread.start()

    @staticmethod
    def _nivel(dispositivo):
        """Nível bruto do pino (True = alto), sem depender de active_state."""
        return bool(dispositivo.pin.state)

    def _descobrir_ociosos(self, polaridade):
        pinos = dict(self.PINOS)
        if polaridade == "auto":
            n = max(1, round(AUTO_OCIOSO_S / AMOSTRA_S))
            leituras = {nome: [] for nome in pinos}
            for _ in range(n):
                for nome, disp in self._dispositivos.items():
                    leituras[nome].append(self._nivel(disp))
                time.sleep(AMOSTRA_S)
            resultado = {nome: detectar_ocioso(l) for nome, l in leituras.items()}
        else:
            fixo = polaridade == "baixo"   # "baixo" = desce ao apertar = parado em alto
            resultado = {nome: (fixo, 0.0) for nome in pinos}

        ociosos, info = {}, {}
        for nome, (ocioso, minoria) in resultado.items():
            ociosos[nome] = ocioso
            info[nome] = {"gpio": pinos[nome], "parado_em": "alto" if ocioso else "baixo",
                          "minoria": minoria}
            msg = (f"botao {nome} (GPIO{pinos[nome]}): parado em {info[nome]['parado_em']}"
                   f" ({'sobe' if not ocioso else 'desce'} ao apertar), polaridade={polaridade}")
            if polaridade == "auto" and minoria > 0.1:
                msg += (f"  ** LINHA INSTAVEL ({minoria:.0%} das leituras diferentes): confira fio,"
                        " emenda e se algum botao estava apertado ao iniciar")
            self._log(msg)
        return ociosos, info

    def _laco(self):
        while self._ativo:
            try:
                for nome, entrada in self._entradas.items():
                    tipo = entrada.amostrar(self._nivel(self._dispositivos[nome]))
                    if tipo:
                        self.fila.put((nome, tipo_do_aperto(nome, tipo, entrada.aperto.ultima_duracao)))
            except Exception as erro:   # um erro de leitura não pode matar os botões em silêncio
                if self._ativo:
                    self._log(f"erro lendo botoes: {erro!r}")
            time.sleep(AMOSTRA_S)

    def fechar(self):
        self._ativo = False
        self._thread.join(timeout=1.0)
        for disp in self._dispositivos.values():
            disp.close()


def tipo_do_aperto(nome, tipo, duracao, limite_pausa=LIMITE_PAUSA_POSTURA_S):
    """O B1 ganha um 4º tipo: soltar com ≥ 5 s pausa/retoma a postura. Os outros, iguais."""
    if nome == "B1" and duracao >= limite_pausa:
        return PAUSA_POSTURA
    return tipo


class BotoesTeclado:
    """Simula os botões digitando no terminal (uma linha + Enter por aperto)."""

    COMANDOS = {"1c": ("B1", CURTO), "1l": ("B1", LONGO), "1p": ("B1", PAUSA_POSTURA),
                "2c": ("B2", CURTO), "2l": ("B2", LONGO), "2m": ("B2", MUITO_LONGO),
                "3c": ("B3", CURTO), "3l": ("B3", LONGO), "3m": ("B3", MUITO_LONGO)}

    def __init__(self, fila):
        self.fila = fila
        self.aperto_b1 = ClassificadorAperto()   # sem uso aqui; mantém a mesma interface
        self.aperto_b2 = ClassificadorAperto()
        self.aperto_b3 = ClassificadorAperto()
        self._ativo = True
        threading.Thread(target=self._ler, daemon=True).start()

    def _ler(self):
        print("Botões simulados:  1c = B1 curto | 1l = B1 longo | 1p = B1 5 s (pausa postura) | 2c = B2 curto | "
              "2l = B2 longo | 2m = B2 muito longo | 3m = B3 muito longo (desliga) | q = sair", flush=True)
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
