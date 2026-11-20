"""
Tela de 128x64. Duas partes:

1. desenhar(): monta a imagem (PIL, 1 bit) a partir do estado. NÃO sabe qual
   display é; por isso o mesmo desenho vai pro OLED, pro emulador ou pra um PNG.
2. Backends: OLED (luma.oled/SSD1306 via I2C), emulador pygame (notebook) e PNG
   (grava um arquivo; funciona até por SSH).

Sem acentos nos textos: a fonte padrão do display não tem.
"""
import math

from PIL import Image, ImageChops, ImageDraw, ImageFont

from pomodoro_config import (
    LARGURA, ALTURA, OLED_I2C_PORTA, OLED_I2C_ENDERECO,
)
from pomodoro_logica import (
    SELECAO, FOCO, PAUSA, PAUSA_LONGA, PAUSADO,
)

CAMINHOS_FONTE = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    "DejaVuSans-Bold.ttf",
)

_cache_fontes = {}


def _fonte(tamanho):
    """Fonte TrueType se existir; senão a padrão do Pillow (None = bitmap fixa)."""
    if tamanho in _cache_fontes:
        return _cache_fontes[tamanho]
    fonte = None
    for caminho in CAMINHOS_FONTE:
        try:
            fonte = ImageFont.truetype(caminho, tamanho)
            break
        except OSError:
            continue
    if fonte is None:
        try:
            fonte = ImageFont.load_default(size=tamanho)   # Pillow >= 10.1
        except TypeError:
            fonte = None
    _cache_fontes[tamanho] = fonte
    return fonte


def _texto(draw, xy, texto, tamanho=10, preenchimento=1, ancora="la"):
    fonte = _fonte(tamanho)
    if fonte is None:
        fonte = ImageFont.load_default()
    draw.text(xy, texto, font=fonte, fill=preenchimento, anchor=ancora)


def formatar_tempo(segundos):
    """Segundos → 'MM:SS' (arredonda pra cima: começa em 25:00 e o 00:00 só no fim)."""
    total = max(0, math.ceil(segundos))
    return f"{total // 60:02d}:{total % 60:02d}"


def _texto_fase(pomo):
    return {
        FOCO: "FOCO",
        PAUSA: "PAUSA",
        PAUSA_LONGA: "PAUSA LONGA",
        PAUSADO: "|| " + {FOCO: "FOCO", PAUSA: "PAUSA", PAUSA_LONGA: "P.LONGA"}.get(pomo.fase_atual, ""),
    }.get(pomo.estado, "")


# Enquadramento (T2'): mini-figura com os 3 pontos que a postura usa, no canto direito
# da linha de baixo. Cheio = o MoveNet está vendo o ponto; vazado = não está.
# A imagem da câmera é espelhada, então a orelha usada aparece sobre o ombro da DIREITA
# de quem olha (inferência pela convenção do MoveNet, conferir no Pi; se sair trocado,
# é só inverter X_OMBRO_ORELHA e X_OUTRO_OMBRO).
X_OMBRO_ORELHA, X_OUTRO_OMBRO = 125, 117
Y_ORELHA, Y_OMBROS, RAIO_PONTO = 54, 60, 2
X_FIM_TEXTO_COM_PONTOS = 110       # texto da linha de baixo vai até aqui quando há figura


def _ponto(d, x, y, cheio, cor=1):
    caixa = (x - RAIO_PONTO, y - RAIO_PONTO, x + RAIO_PONTO, y + RAIO_PONTO)
    d.ellipse(caixa, fill=cor if cheio else None, outline=cor)


def _figura_pontos(d, pontos, cor=1):
    """pontos = (orelha, ombro do lado da orelha, outro ombro) → bools."""
    orelha, ombro_orelha, outro_ombro = pontos
    _ponto(d, X_OMBRO_ORELHA, Y_ORELHA, orelha, cor)
    _ponto(d, X_OMBRO_ORELHA, Y_OMBROS, ombro_orelha, cor)
    _ponto(d, X_OUTRO_OMBRO, Y_OMBROS, outro_ombro, cor)


def desenhar(pomo, texto_postura, status_postura=None, segurando_tipo=None, piscando=False,
             pontos=None):
    """
    Devolve a imagem (modo '1', 128x64).
      pomo            instância de Pomodoro
      texto_postura   linha curta de baixo (ver postura_cliente.texto_curto)
      status_postura  status bruto do serviço; "ALERTA" inverte a linha de baixo
      segurando_tipo  'longo'/'muito_longo' enquanto o B2 está segurado (mostra dica)
      piscando        True durante alguns segundos após trocar de fase (sem buzzer)
      pontos          (orelha, ombro, outro ombro) visíveis? Desenha a mini-figura do
                      enquadramento à direita da linha de baixo (None = sem figura)
    """
    img = Image.new("1", (LARGURA, ALTURA), 0)
    d = ImageDraw.Draw(img)

    dica = pomo.rotulo_aperto(segurando_tipo) if segurando_tipo else ""

    if pomo.estado == SELECAO:
        _texto(d, (LARGURA // 2, 0), "ESCOLHA O TEMPO", 9, ancora="ma")
        _texto(d, (LARGURA // 2, 26), pomo.preset["nome"], 26, ancora="mm")
        linha = f"SOLTE: {dica}" if dica else "curto=troca longo=ok"
        _texto(d, (LARGURA // 2, 41), linha, 9, ancora="ma")
    else:
        topo_esq = f"{pomo.preset['nome']}  C{pomo.ciclo_atual}/{pomo.ciclos_ate_longa}"
        _texto(d, (0, 0), topo_esq, 9)
        _texto(d, (LARGURA - 1, 0), _texto_fase(pomo), 9, ancora="ra")
        _texto(d, (LARGURA // 2, 28), formatar_tempo(pomo.restante_s), 26, ancora="mm")
        if dica:
            _texto(d, (LARGURA // 2, 41), f"SOLTE: {dica}", 9, ancora="ma")

    # Linha de baixo: postura (invertida quando é ALERTA, pra chamar atenção)
    if status_postura == "ALERTA":
        d.rectangle((0, 52, LARGURA - 1, ALTURA - 1), fill=1)
        _texto(d, (LARGURA // 2, 53), texto_postura, 9, preenchimento=0, ancora="ma")
    else:
        d.line((0, 51, LARGURA - 1, 51), fill=1)
        if pontos is not None:
            _texto(d, (0, 53), texto_postura, 9)        # à esquerda, abrindo espaço pra figura
            _figura_pontos(d, pontos)
        else:
            _texto(d, (LARGURA // 2, 53), texto_postura, 9, ancora="ma")

    if piscando:
        # via "L": o invert direto no modo "1" dá tela toda branca em algumas versões do Pillow
        img = ImageChops.invert(img.convert("L")).convert("1")
    return img


# ---------------------------------------------------------------- backends ----

class DisplayOLED:
    """OLED SSD1306 128x64 por I2C (no Pi: SDA = pino 3, SCL = pino 5)."""

    def __init__(self):
        from luma.core.interface.serial import i2c
        from luma.oled.device import ssd1306
        serial = i2c(port=OLED_I2C_PORTA, address=OLED_I2C_ENDERECO)
        self._dev = ssd1306(serial, width=LARGURA, height=ALTURA)

    def mostrar(self, imagem):
        self._dev.display(imagem)

    def fechar(self):
        self._dev.clear()


class DisplayPygame:
    """Janela do emulador do luma (notebook). Precisa de: pip install luma.emulator pygame"""

    def __init__(self):
        from luma.emulator.device import pygame as emulador
        self._dev = emulador(width=LARGURA, height=ALTURA, mode="1", scale=4, transform="scale2x")

    def mostrar(self, imagem):
        self._dev.display(imagem)

    def fechar(self):
        self._dev.cleanup()


class DisplayPNG:
    """Grava a tela ampliada num PNG (abre no visualizador de imagens; funciona por SSH)."""

    def __init__(self, caminho="/tmp/pomodoro_tela.png", escala=4):
        self.caminho = caminho
        self.escala = escala

    def mostrar(self, imagem):
        grande = imagem.convert("L").resize((LARGURA * self.escala, ALTURA * self.escala), Image.NEAREST)
        grande.save(self.caminho)

    def fechar(self):
        pass


def criar_display(nome):
    if nome == "oled":
        return DisplayOLED()
    if nome == "pygame":
        return DisplayPygame()
    if nome == "png":
        return DisplayPNG()
    raise ValueError(f"display desconhecido: {nome}")
