"""
Telas do pomodoro no LCD de caracteres 16x2 (HD44780). Porte das telas do OLED
(display.py, aprovadas em 19/11) SEM mexer na lógica: as funções têm a mesma
assinatura de desenhar(), desenhar_wifi_espera() e desenhar_wifi_resultado(), mas
devolvem um Quadro (2 linhas de 16 células) em vez de uma imagem 128x64.

Divisão do espaço (pedido do Wellington, 23/11): no OLED o timer ocupava quase tudo e
a postura ficava numa faixa de 9 px. Aqui cada um tem UMA LINHA INTEIRA:
    linha 1 = pomodoro (fase/preset + tempo)   linha 2 = postura (ou menu/avisos)

O que mudou por causa do hardware (o resto segue o OLED):
- Sem gráfico livre: ícones (pausa, Wi-Fi, ✓/✗, os 3 pontos) e letras acentuadas
  viram caracteres próprios, desenhados em 5x8 na CGRAM, que só tem 8 vagas por tela.
  Se uma tela pedir mais de 8, as letras acentuadas viram a letra sem acento.
- Sem vídeo invertido: o "ALERTA invertido" vira a linha piscando com blocos cheios, e
  o "piscar ao trocar de fase" vira a tela inteira alternando com blocos cheios.
- 16 colunas: textos maiores ganham uma forma curta (tabela abaixo) e, em último caso,
  rolam na horizontal.
"""
import math
import re
import time
import unicodedata
from dataclasses import dataclass

from display import formatar_tempo, _texto_fase
from energia import TEXTO_DESLIGANDO
from pomodoro_config import (
    LCD_COLUNAS, LCD_LINHAS, LCD_PRESET_CICLO_S, LCD_PRESET_MOSTRA_S,
    LCD_ROLAGEM_CPS, LCD_ALERTA_PISCA_HZ, LCD_WIFI_CREDENCIAIS_S,
    LCD_GPIO_RS, LCD_GPIO_E, LCD_GPIO_D4, LCD_GPIO_D5, LCD_GPIO_D6, LCD_GPIO_D7,
)
from pomodoro_logica import SELECAO, PAUSADO

COLS = LCD_COLUNAS
BLOCO = "\xff"          # bloco cheio: existe na ROM do HD44780 (código 0xFF)
VAGAS_CGRAM = 8


# ------------------------------------------------------------ caracteres próprios --
@dataclass(frozen=True)
class Glifo:
    """Desenho 5x8 (8 linhas de 5 bits). `reserva` = o que mostrar se faltar vaga na CGRAM
    (None = ícone, sempre tem prioridade)."""
    bits: tuple
    reserva: str = None


def _g(*linhas, reserva=None):
    return Glifo(tuple(int(l, 2) for l in linhas), reserva)


ICONE_PAUSA = _g("00000", "11011", "11011", "11011", "11011", "11011", "11011", "00000")
ICONE_WIFI = _g("01110", "10001", "00000", "01110", "10001", "00000", "00100", "00000")
ICONE_OK = _g("00000", "00001", "00011", "10110", "11100", "01000", "00000", "00000")
ICONE_FALHA = _g("00000", "10001", "01010", "00100", "01010", "10001", "00000", "00000")

# Letras que a ROM japonesa (A00) do HD44780 não tem. '\' e '~' também: nesses códigos
# a ROM desenha ¥ e →, então ganham desenho próprio (podem aparecer na senha do Wi-Fi).
LETRAS = {
    "Ç": _g("01110", "10001", "10000", "10000", "10001", "01110", "00100", "01100", reserva="C"),
    "Ã": _g("01101", "10010", "01110", "10001", "10001", "11111", "10001", "10001", reserva="A"),
    "Õ": _g("01101", "10010", "01110", "10001", "10001", "10001", "10001", "01110", reserva="O"),
    "Á": _g("00010", "00100", "01110", "10001", "10001", "11111", "10001", "10001", reserva="A"),
    "À": _g("01000", "00100", "01110", "10001", "10001", "11111", "10001", "10001", reserva="A"),
    "Â": _g("00100", "01010", "01110", "10001", "10001", "11111", "10001", "10001", reserva="A"),
    "É": _g("00010", "00100", "11111", "10000", "11110", "10000", "10000", "11111", reserva="E"),
    "Ê": _g("00100", "01010", "11111", "10000", "11110", "10000", "10000", "11111", reserva="E"),
    "Í": _g("00010", "00100", "01110", "00100", "00100", "00100", "00100", "01110", reserva="I"),
    "Ó": _g("00010", "00100", "01110", "10001", "10001", "10001", "10001", "01110", reserva="O"),
    "Ô": _g("00100", "01010", "01110", "10001", "10001", "10001", "10001", "01110", reserva="O"),
    "Ú": _g("00010", "00100", "10001", "10001", "10001", "10001", "10001", "01110", reserva="U"),
    "ç": _g("00000", "01110", "10000", "10000", "10001", "01110", "00100", "01100", reserva="c"),
    "ã": _g("01101", "10010", "01110", "00001", "01111", "10001", "01111", "00000", reserva="a"),
    "\\": _g("00000", "10000", "01000", "00100", "00010", "00001", "00000", "00000", reserva="/"),
    "~": _g("00000", "00000", "01000", "10101", "00010", "00000", "00000", "00000", reserva="-"),
}

# Os 3 pontos do enquadramento (T2') em 2 células, como a mini-figura do OLED:
# célula da esquerda = o outro ombro (embaixo); da direita = orelha (em cima) sobre o
# ombro do lado dela (embaixo). Ponto 3x3: cheio = visto; anel = não visto.
_CHEIO = ("01110", "01110", "01110")
_ANEL = ("01110", "01010", "01110")
_VAZIO = ("00000",) * 3


def figura_pontos(pontos):
    orelha, ombro_orelha, outro_ombro = pontos
    esq = _g(*_VAZIO, "00000", "00000", *(_CHEIO if outro_ombro else _ANEL))
    dir_ = _g(*(_CHEIO if orelha else _ANEL), "00000", "00000", *(_CHEIO if ombro_orelha else _ANEL))
    return [esq, dir_]


# --------------------------------------------------------------- textos curtos --
# Só entram quando o texto do OLED não cabe na linha. Mesma mensagem, menos letras.
FORMAS_CURTAS = {
    "POSTURA: SEM SERVIÇO": "POSTURA: OFFLINE",
    "APERTE B1: CALIBRAR": "B1 P/ CALIBRAR",
    "CALIBRACAO FALHOU": "CALIB. FALHOU",
    "DESLIGANDO, AGUARDE": "DESLIGANDO...",
    "SOLTE: DESLIGAR PI": "SOLTE: DESLIGAR",
    "SOLTE: WIFI CONECTAR": "SOLTE:CONEC.WIFI",
    "SOLTE: RECAL POSTURA": "SOLTE:RECALIBRAR",
    "SOLTE: CALIB POSTURA": "SOLTE: CALIBRAR",
    "RECALIBRAR: POSTURA": "RECALIB. POSTURA",
    "CALIBRAR: POSTURA": "CALIBRAR POSTURA",
}
_CONTAGEM = re.compile(r"^COMEÇANDO EM: (\d+)s$")


def compactar(texto, largura=COLS):
    """Texto do OLED → forma que cabe em `largura` colunas (se ainda não couber, rola)."""
    if len(texto) <= largura:
        return texto
    m = _CONTAGEM.match(texto)
    if m:
        texto = f"COMEÇA EM {m.group(1)}s"
    texto = FORMAS_CURTAS.get(texto, texto)
    if len(texto) > largura:
        texto = texto.replace("SEGURE ", "SEG.")        # SEG.3s: DESLIGAR, SEG.5s: RETOMAR
    if len(texto) > largura:
        texto = texto.replace(": ", ":")                # POSTURA:DESCANSO
    return texto


def rolar(texto, largura=COLS, t=None):
    """Janela de `largura` que anda pelo texto (pausa no começo e no fim). Curto = igual."""
    if len(texto) <= largura:
        return texto
    t = time.monotonic() if t is None else t
    passos = len(texto) - largura
    pausa = 1.5
    ciclo = 2 * pausa + passos / LCD_ROLAGEM_CPS
    dentro = t % ciclo - pausa
    deslocamento = min(passos, max(0, int(dentro * LCD_ROLAGEM_CPS)))
    return texto[deslocamento:deslocamento + largura]


# --------------------------------------------------------------------- quadro --
def _celulas(texto):
    """Texto → células: caractere da ROM (str) ou Glifo."""
    saida = []
    for c in texto:
        if c in LETRAS:
            saida.append(LETRAS[c])
        elif c == BLOCO or 32 <= ord(c) <= 125:
            saida.append(c)
        else:                                            # outro acento: letra base
            base = unicodedata.normalize("NFKD", c).encode("ascii", "ignore").decode()
            saida.append(base[:1] if base and 32 <= ord(base[0]) <= 125 and base[0] not in "\\~" else "?")
    return saida


def _encaixar(celulas, alinhamento="esquerda", largura=COLS):
    celulas = celulas[:largura]
    falta = largura - len(celulas)
    if alinhamento == "centro":
        esq = falta // 2
        return [" "] * esq + celulas + [" "] * (falta - esq)
    if alinhamento == "direita":
        return [" "] * falta + celulas
    return celulas + [" "] * falta


@dataclass
class Quadro:
    linhas: list            # LCD_LINHAS listas de COLS células (str ou Glifo)

    def glifos(self):
        vistos = []
        for linha in self.linhas:
            for c in linha:
                if isinstance(c, Glifo) and c not in vistos:
                    vistos.append(c)
        return vistos

    def texto(self):
        """Pra teste/log: ícones viram '#', letras próprias viram a letra."""
        inverso = {g: k for k, g in LETRAS.items()}
        return ["".join(inverso.get(c, "#") if isinstance(c, Glifo) else c for c in linha)
                for linha in self.linhas]


def _fechar_quadro(linhas):
    """Garante no máximo 8 desenhos próprios: troca letras acentuadas pela reserva."""
    q = Quadro([_encaixar(l) for l in linhas])
    if len(q.glifos()) > VAGAS_CGRAM:
        q.linhas = [[c.reserva if isinstance(c, Glifo) and c.reserva else c for c in l] for l in q.linhas]
    return q


def _linha_cheia():
    return [BLOCO] * COLS


# ------------------------------------------------------------------- telas --
def _topo_rodando(pomo, agora):
    tempo = formatar_tempo(pomo.restante_s)               # MM:SS (ou MMM:SS acima de 99 min)
    mostra_preset = (LCD_PRESET_CICLO_S > 0
                     and agora % LCD_PRESET_CICLO_S >= LCD_PRESET_CICLO_S - LCD_PRESET_MOSTRA_S)
    texto = pomo.preset["nome"] if mostra_preset else _texto_fase(pomo)
    prefixo = [ICONE_PAUSA] if pomo.estado == PAUSADO else []   # como no OLED: ícone antes da fase
    cabe = COLS - len(tempo) - 1 - len(prefixo)
    if len(texto) > cabe:
        texto = texto.replace(" ", "")                    # P.LONGA4/4
    return prefixo + _encaixar(_celulas(texto[:cabe]), largura=cabe) + [" "] + _celulas(tempo)


def desenhar(pomo, texto_postura, status_postura=None, segurando_tipo=None, piscando=False,
             pontos=None):
    """Mesma assinatura do display.desenhar(); devolve um Quadro 16x2."""
    if texto_postura == TEXTO_DESLIGANDO:                 # B3 executado: DESLIGADO ocupa a tela toda
        return _fechar_quadro([_encaixar(_celulas("DESLIGADO"), "centro")] * 2)
    if piscando:
        return _fechar_quadro([_linha_cheia(), _linha_cheia()])
    agora = time.monotonic()

    # Linha 1: pomodoro
    dica = pomo.rotulo_aperto(segurando_tipo) if segurando_tipo else ""
    if dica:
        topo = _encaixar(_celulas(f"SOLTE: {dica}"), "centro")
    elif pomo.estado == SELECAO:
        nome = pomo.preset["nome"]
        espaco = COLS - len("TEMPO") - 1
        if len(nome) <= espaco:
            topo = _celulas("TEMPO") + _encaixar(_celulas(nome), "direita", COLS - len("TEMPO"))
        else:
            topo = _encaixar(_celulas(rolar(nome, COLS, agora)), "centro")
    else:
        topo = _topo_rodando(pomo, agora)

    # Linha 2: postura (linha inteira só dela)
    if status_postura == "ALERTA":
        if int(agora * LCD_ALERTA_PISCA_HZ * 2) % 2:
            baixo = _linha_cheia()
        else:
            baixo = _encaixar(_celulas(rolar(compactar(texto_postura))), "centro")
    elif pontos is not None:
        largura = COLS - 3                                # texto | espaço | 2 células da figura
        texto = rolar(compactar(texto_postura, largura), largura, agora)
        baixo = _encaixar(_celulas(texto), largura=largura) + [" "] + figura_pontos(pontos)
    else:
        baixo = _encaixar(_celulas(rolar(compactar(texto_postura), COLS, agora)), "centro")

    return _fechar_quadro([topo, baixo])


# ------------------------------------------------------ telas cheias do Wi-Fi --
_PAGINA_S = 2.5
_espera = {"inicio": None, "ultima": 0.0}      # pra a 1ª página (rede e senha) valer desde o começo da espera


def _linha_wifi(prefixo, valor):
    texto = prefixo + valor
    return texto if len(texto) <= COLS else prefixo.strip() + valor     # REDE:xxxx


def _rolar_desde(texto, t, atraso=1.0):
    """Mostra o começo por `atraso` s e depois rola até o fim (texto curto = igual)."""
    if len(texto) <= COLS:
        return texto
    desloc = min(len(texto) - COLS, max(0, int((t - atraso) * LCD_ROLAGEM_CPS)))
    return texto[desloc:desloc + COLS]


def _paginas_wifi(ssid, senha):
    """[(duração_s, linha1, linha2)]. A 1ª página mostra REDE e SENHA JUNTAS pelo tempo que o
    Wellington pediu (LCD_WIFI_CREDENCIAIS_S); depois alternam o CONECTANDO... e os avisos."""
    rede, chave = _linha_wifi("REDE: ", ssid), _linha_wifi("SENHA: ", senha)
    sobra = max(len(rede), len(chave)) - COLS
    credenciais = max(LCD_WIFI_CREDENCIAIS_S, 2.0 + max(0, sobra) / LCD_ROLAGEM_CPS)   # dá tempo de rolar
    return [
        (credenciais, rede, chave),
        (_PAGINA_S, None, "BANDA: 2.4 GHZ"),               # o Pi 3B só tem Wi-Fi 2.4 GHz
        (_PAGINA_S, None, "CLIQUE: CANCELAR"),
    ]


def desenhar_wifi_espera(ssid, senha, pontos=3):
    """1ª página: REDE e SENHA nas 2 linhas. Depois: ícone + CONECTANDO... em cima e, embaixo,
    a banda e como cancelar. Recomeça pela 1ª página quando a tela volta (nova tentativa)."""
    agora = time.monotonic()
    if _espera["inicio"] is None or agora - _espera["ultima"] > 1.5:
        _espera["inicio"] = agora                          # a tela não estava sendo desenhada: nova espera
    _espera["ultima"] = agora
    paginas = _paginas_wifi(ssid, senha)
    t = (agora - _espera["inicio"]) % sum(d for d, _, _ in paginas)
    for dur, l1, l2 in paginas:
        if t < dur:
            break
        t -= dur
    if l1 is not None:                                     # página das credenciais
        return _fechar_quadro([_encaixar(_celulas(_rolar_desde(l1, t))),
                               _encaixar(_celulas(_rolar_desde(l2, t)))])
    topo = [ICONE_WIFI, " "] + _celulas("CONECTANDO" + "." * pontos)
    return _fechar_quadro([topo, _encaixar(_celulas(l2), "centro")])


def desenhar_wifi_resultado(ok, ssid):
    """Linha 1: ícone + WIFI CONECTADO/FALHOU ; linha 2: ✓/✗ + nome da rede."""
    titulo = "WIFI CONECTADO" if ok else "WIFI FALHOU"
    topo = _encaixar([ICONE_WIFI, " "] + _celulas(titulo), "centro")
    marca = ICONE_OK if ok else ICONE_FALHA
    nome = rolar(ssid, COLS - 2)
    baixo = _encaixar([marca, " "] + _celulas(nome), "centro")
    return _fechar_quadro([topo, baixo])


# ------------------------------------------------------------------ backends --
def _codigo(celula, slots):
    if isinstance(celula, Glifo):
        return slots[celula]
    return ord(celula)


class DisplayLCD:
    """LCD 16x2 real. Só reescreve o que mudou (CGRAM e linhas) pra não piscar."""

    def __init__(self):
        from lcd_hd44780 import LCD4Bits
        self._lcd = LCD4Bits(LCD_GPIO_RS, LCD_GPIO_E, LCD_GPIO_D4, LCD_GPIO_D5,
                             LCD_GPIO_D6, LCD_GPIO_D7, COLS, LCD_LINHAS)
        self._cgram = [None] * VAGAS_CGRAM               # o que está gravado em cada vaga
        self._ultimas = [None] * LCD_LINHAS

    def _vagas(self, glifos):
        """Glifo → vaga 0..7. Reaproveita o que já está gravado; grava só o novo."""
        mapa = {g: i for i, g in enumerate(self._cgram) if g in glifos}
        livres = [i for i, g in enumerate(self._cgram) if g not in mapa]
        for g in glifos:
            if g not in mapa:
                i = livres.pop(0)
                self._lcd.criar_caractere(i, g.bits)
                self._cgram[i] = g
                mapa[g] = i
        return mapa

    def mostrar(self, quadro):
        slots = self._vagas(quadro.glifos())
        for n, linha in enumerate(quadro.linhas):
            codigos = bytes(_codigo(c, slots) for c in linha)
            if codigos != self._ultimas[n]:
                self._lcd.posicao(n, 0)
                self._lcd.escrever(codigos)
                self._ultimas[n] = codigos

    def fechar(self):
        self._lcd.limpar()
        self._lcd.fechar()


class DisplayLCDPNG:
    """Prévia do LCD num PNG (notebook/SSH). Aproximada: as letras usam a fonte do PC,
    não a da ROM do LCD; os ícones e acentos próprios saem pixel a pixel, como no LCD."""

    PIXEL, GAP, MARGEM = 6, 6, 18

    def __init__(self, caminho="/tmp/pomodoro_tela.png"):
        self.caminho = caminho

    def _imagem(self, quadro):
        from PIL import Image, ImageDraw
        from display import _fonte
        p, gap, m = self.PIXEL, self.GAP, self.MARGEM
        cw, ch = 5 * p, 8 * p
        largura = 2 * m + COLS * cw + (COLS - 1) * gap
        altura = 2 * m + LCD_LINHAS * ch + (LCD_LINHAS - 1) * gap
        fundo, apagado, aceso = (20, 40, 200), (35, 60, 215), (235, 240, 255)
        img = Image.new("RGB", (largura, altura), fundo)
        d = ImageDraw.Draw(img)
        fonte = _fonte(int(ch * 0.8))
        for li, linha in enumerate(quadro.linhas):
            for co, c in enumerate(linha):
                x0, y0 = m + co * (cw + gap), m + li * (ch + gap)
                d.rectangle((x0, y0, x0 + cw - 1, y0 + ch - 1), fill=apagado)
                if isinstance(c, Glifo) or c == BLOCO:
                    bits = c.bits if isinstance(c, Glifo) else (0x1F,) * 8
                    for r, valor in enumerate(bits):
                        for b in range(5):
                            if valor >> (4 - b) & 1:
                                d.rectangle((x0 + b * p, y0 + r * p, x0 + (b + 1) * p - 2,
                                             y0 + (r + 1) * p - 2), fill=aceso)
                elif c != " ":
                    d.text((x0 + cw / 2, y0 + ch * 0.45), c, font=fonte, fill=aceso, anchor="mm")
        return img

    def mostrar(self, quadro):
        self._imagem(quadro).save(self.caminho)

    def fechar(self):
        pass
