"""
Menu do B1: recalibrar a postura ou conectar o Wi-Fi.

Lógica PURA (não sabe de GPIO, tela nem relógio): recebe `botao(tipo)` e `tick(dt)`.
O B1 NÃO mexe no pomodoro; o pomodoro é só do B2.

    B1 curto  → abre o menu (POSTURA) e, a cada novo clique, alterna POSTURA → WIFI CONECTAR
    B1 longo  → executa a opção escolhida e o menu fecha
    sem clique por MENU_TIMEOUT_S → o menu fecha sozinho (a linha de baixo volta
                                    a mostrar a postura)
    B1 longo com o menu fechado é ignorado (aperto longo sem querer não faz nada).

A voz saiu do menu em 19/11 (voz fora do escopo do TCC).
"""
from pomodoro_config import MENU_B1_TIMEOUT_S
from pomodoro_logica import CURTO

POSTURA = "postura"
WIFI = "wifi"
OPCOES = (POSTURA, WIFI)
ACAO_RECALIBRAR = "recalibrar"   # nome mantido: a ação devolvida é (ACAO_RECALIBRAR, opcao)


class MenuB1:
    def __init__(self, timeout_s=MENU_B1_TIMEOUT_S):
        self.timeout_s = timeout_s
        self.opcao = None          # None = menu fechado
        self.ocupado = False       # True enquanto uma ação está rodando (ignora o B1)
        self._restante_s = 0.0

    @property
    def aberto(self):
        return self.opcao is not None

    def botao(self, tipo):
        """Devolve (ACAO_RECALIBRAR, opcao) quando é pra executar; senão None."""
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

    def abrir_em(self, opcao):
        """Reabre o menu já na opção (ex.: confirmar o Wi-Fi com SSH ativo)."""
        self.opcao = opcao
        self._restante_s = self.timeout_s

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
        Linha de baixo da tela (≤ 128 px) ou None se o menu está fechado.
        calibrado = {POSTURA: bool}: postura ainda não calibrada aparece como CALIBRAR;
        depois da primeira vez, vira RECALIBRAR. (None = calibrada.)
        """
        if not self.aberto:
            return None
        if self.opcao == WIFI:
            return "SOLTE: WIFI CONECTAR" if segurando_longo else "WIFI CONECTAR"
        ja = True if calibrado is None else calibrado.get(POSTURA, True)
        if segurando_longo:
            return f"SOLTE: {'RECAL' if ja else 'CALIB'} POSTURA"
        return f"{'RECALIBRAR' if ja else 'CALIBRAR'}: POSTURA"
