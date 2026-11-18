"""
Menu do B1: escolher e disparar uma recalibração (postura ou voz).

Lógica PURA (não sabe de GPIO, tela nem relógio): recebe `botao(tipo)` e `tick(dt)`.
O B1 NÃO mexe no pomodoro; o pomodoro é só do B2.

    B1 curto  → abre o menu (POSTURA) e, a cada novo clique, alterna POSTURA ↔ VOZ
    B1 longo  → executa a recalibração da opção escolhida e o menu fecha
    sem clique por MENU_TIMEOUT_S → o menu fecha sozinho (a linha de baixo volta
                                    a mostrar a postura)
    B1 longo com o menu fechado é ignorado (aperto longo sem querer não recalibra).
"""
from pomodoro_config import MENU_B1_TIMEOUT_S
from pomodoro_logica import CURTO

POSTURA = "postura"
VOZ = "voz"
OPCOES = (POSTURA, VOZ)
ACAO_RECALIBRAR = "recalibrar"

_NOME = {POSTURA: "POSTURA", VOZ: "VOZ"}


class MenuB1:
    def __init__(self, timeout_s=MENU_B1_TIMEOUT_S):
        self.timeout_s = timeout_s
        self.opcao = None          # None = menu fechado
        self.ocupado = False       # True enquanto uma recalibração está rodando (ignora o B1)
        self._restante_s = 0.0

    @property
    def aberto(self):
        return self.opcao is not None

    def botao(self, tipo):
        """Devolve (ACAO_RECALIBRAR, opcao) quando é pra recalibrar; senão None."""
        if self.ocupado:
            return None
        if tipo == CURTO:
            if not self.aberto:
                self.opcao = OPCOES[0]
            else:
                self.opcao = OPCOES[(OPCOES.index(self.opcao) + 1) % len(OPCOES)]
            self._restante_s = self.timeout_s
            return None
        if not self.aberto:        # longo/muito longo com o menu fechado
            return None
        escolhida = self.opcao
        self.fechar()
        return (ACAO_RECALIBRAR, escolhida)

    def tick(self, dt):
        """Tempo REAL passado (s). Fecha o menu quando ninguém clica por um tempo."""
        if self.aberto and not self.ocupado:
            self._restante_s -= dt
            if self._restante_s <= 0:
                self.fechar()

    def fechar(self):
        self.opcao = None
        self._restante_s = 0.0

    def texto(self, segurando_longo=False, calibrado=None):
        """
        Linha de baixo da tela (≤ 128 px, sem acento) ou None se o menu está fechado.
        calibrado = {POSTURA: bool, VOZ: bool}: quem ainda não foi calibrada aparece
        como CALIBRAR; depois da primeira vez, vira RECALIBRAR. (None = todas calibradas.)
        """
        if not self.aberto:
            return None
        ja = True if calibrado is None else calibrado.get(self.opcao, True)
        if segurando_longo:
            return f"SOLTE: {'RECAL' if ja else 'CALIB'} {_NOME[self.opcao]}"
        return f"{'RECALIBRAR' if ja else 'CALIBRAR'}: {_NOME[self.opcao]}"
