"""
Máquina de estados do pomodoro. Lógica PURA: não sabe de GPIO, tela nem relógio
do sistema. Quem chama avisa o tempo passado (`tick(dt)`) e os apertos de botão
(`botao(tipo)`). Por isso dá pra testar tudo no notebook, sem o Pi.

Estados:
    SELECAO      escolhendo o preset (nada rodando)
    FOCO         contagem regressiva do foco
    PAUSA        contagem regressiva do descanso curto
    PAUSA_LONGA  contagem regressiva do descanso longo
    PAUSADO      timer congelado (guarda a fase que estava rodando)

Botão (tipo do aperto, ver botoes.py):
    SELECAO : curto → próximo preset | longo → inicia o foco | muito longo → nada
    rodando : longo → pausa          | muito longo → reinicia (volta pra SELECAO)
    PAUSADO : longo → retoma         | muito longo → reinicia
    (curto não faz nada fora da SELECAO, pra um toque sem querer não atrapalhar)
"""
from pomodoro_config import PRESETS, CICLOS_ATE_PAUSA_LONGA

SELECAO = "SELECAO"
FOCO = "FOCO"
PAUSA = "PAUSA"
PAUSA_LONGA = "PAUSA_LONGA"
PAUSADO = "PAUSADO"

FASES_RODANDO = (FOCO, PAUSA, PAUSA_LONGA)

CURTO = "curto"
LONGO = "longo"
MUITO_LONGO = "muito_longo"

# Eventos que tick()/botao() devolvem (a tela usa pra piscar, por exemplo)
EV_FASE_MUDOU = "FASE_MUDOU"
EV_INICIOU = "INICIOU"
EV_PAUSOU = "PAUSOU"
EV_RETOMOU = "RETOMOU"
EV_REINICIOU = "REINICIOU"
EV_PRESET_MUDOU = "PRESET_MUDOU"


class Pomodoro:
    def __init__(self, presets=None, ciclos_ate_longa=CICLOS_ATE_PAUSA_LONGA):
        self.presets = presets or PRESETS
        self.ciclos_ate_longa = ciclos_ate_longa
        self.indice_preset = 0
        self.estado = SELECAO
        self._fase_antes_da_pausa = None
        self.restante_s = 0.0
        self.focos_concluidos = 0

    # ---------- leitura ----------
    @property
    def preset(self):
        return self.presets[self.indice_preset]

    @property
    def rodando(self):
        return self.estado in FASES_RODANDO

    @property
    def fase_atual(self):
        """Fase que está valendo (mesmo com o timer pausado)."""
        return self._fase_antes_da_pausa if self.estado == PAUSADO else self.estado

    @property
    def ciclo_atual(self):
        """Número do foco em andamento dentro do bloco (1..N)."""
        if self.estado == SELECAO:
            return 0
        n = self.ciclos_ate_longa
        if self.fase_atual == FOCO:
            return (self.focos_concluidos % n) + 1
        # Na pausa, o foco que acabou de terminar é o último concluído
        return ((self.focos_concluidos - 1) % n) + 1

    def duracao_fase_s(self, fase):
        minutos = {
            FOCO: self.preset["foco"],
            PAUSA: self.preset["pausa"],
            PAUSA_LONGA: self.preset["pausa_longa"],
        }[fase]
        return minutos * 60.0

    def rotulo_aperto(self, tipo):
        """
        O que vai acontecer se o B2 for solto agora com esse tipo de aperto
        (a tela mostra enquanto o botão está segurado). "" = nada.
        """
        if tipo == LONGO:
            if self.estado == SELECAO:
                return "INICIAR"
            return "RETOMAR" if self.estado == PAUSADO else "PAUSAR"
        if tipo == MUITO_LONGO and self.estado != SELECAO:
            return "REINICIAR"
        return ""

    # ---------- entrada ----------
    def botao(self, tipo):
        """Trata um aperto do B2. Devolve a lista de eventos."""
        if self.estado == SELECAO:
            if tipo == CURTO:
                self.indice_preset = (self.indice_preset + 1) % len(self.presets)
                return [EV_PRESET_MUDOU]
            if tipo == LONGO:
                self.focos_concluidos = 0
                self._entrar(FOCO)
                return [EV_INICIOU]
            return []

        if tipo == MUITO_LONGO:
            self._reiniciar()
            return [EV_REINICIOU]

        if tipo == LONGO:
            if self.rodando:
                self._fase_antes_da_pausa = self.estado
                self.estado = PAUSADO
                return [EV_PAUSOU]
            if self.estado == PAUSADO:
                self.estado = self._fase_antes_da_pausa
                self._fase_antes_da_pausa = None
                return [EV_RETOMOU]
        return []

    def tick(self, dt):
        """Avança `dt` segundos. Só desconta tempo quando está rodando."""
        eventos = []
        if not self.rodando:
            return eventos
        self.restante_s -= dt
        # while: um dt grande (ex.: demo acelerada) pode atravessar mais de uma fase
        while self.restante_s <= 0 and self.rodando:
            sobra = -self.restante_s
            self._entrar(self._proxima_fase())
            self.restante_s -= sobra
            eventos.append(EV_FASE_MUDOU)
        return eventos

    # ---------- internos ----------
    def _proxima_fase(self):
        """Fase depois da atual. Foco e pausa se encadeiam sozinhos."""
        if self.estado == FOCO:
            self.focos_concluidos += 1
            if self.focos_concluidos % self.ciclos_ate_longa == 0:
                return PAUSA_LONGA
            return PAUSA
        return FOCO

    def _entrar(self, fase):
        self.estado = fase
        self.restante_s = self.duracao_fase_s(fase)

    def _reiniciar(self):
        """Muito longo: volta pra seleção de presets e zera o bloco."""
        self._fase_antes_da_pausa = None
        self.estado = SELECAO
        self.restante_s = 0.0
        self.focos_concluidos = 0
