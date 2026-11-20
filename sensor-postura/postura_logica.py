"""
Decisão da postura. Lógica PURA: não sabe de câmera, MoveNet, tela, socket nem
relógio. Recebe os 3 pontos (orelha esquerda, ombro esquerdo, ombro direito, em
pixels) e a baseline, e devolve o estado e os valores. Por isso dá pra testar
com pontos sintéticos, sem o Pi (ver test_postura_logica.py).

O comportamento é o MESMO que estava dentro do laço do postura_servico.py
(mesmos limiares, média móvel e contador); os testes comparam quadro a quadro
com uma cópia do código antigo.
"""
import math
from collections import deque, namedtuple

from postura_config import (
    LIMIAR_DESVIO_ANGULO, LIMIAR_QUEDA_RAZAO, HISTORICO_TAMANHO, FRAMES_PARA_ALERTA,
)

CORRETA = "CORRETA"
ATENCAO = "ATENCAO"
ALERTA = "ALERTA"
SEM_USUARIO = "SEM_USUARIO"

MINIMO_AMOSTRAS_CALIBRACAO = 5   # menos detecções válidas que isso = calibração falha


def calcular_angulo_vertical(x_orelha, y_orelha, x_ombro, y_ombro):
    """
    DESVIO EM DIREÇÃO (graus) da linha orelha-ombro em relação à vertical.
    Sozinho, só pega inclinação LATERAL da cabeça: não pega "queda" de cabeça
    pra frente/baixo sem deslocamento lateral, porque atan2 é invariante à
    magnitude do vetor. Por isso combinamos com calcular_razao_pescoco().
    """
    dx = x_orelha - x_ombro
    dy = y_orelha - y_ombro  # Y cresce pra baixo: a orelha está acima (y menor)
    if dy == 0:
        return 0.0
    return abs(math.degrees(math.atan2(dx, -dy)))


def calcular_razao_pescoco(x_orelha, y_orelha, x_ombro_esq, y_ombro_esq, x_ombro_dir, y_ombro_dir):
    """
    Comprimento aparente do "pescoço" (distância orelha-ombro) dividido pela
    largura dos ombros (referência de escala: cancela aproximar/afastar da câmera).
    Quando a cabeça cai pra frente/baixo, essa razão diminui. None se os ombros
    coincidem (largura zero).
    """
    dist_orelha_ombro = math.hypot(x_orelha - x_ombro_esq, y_orelha - y_ombro_esq)
    dist_ombros = math.hypot(x_ombro_dir - x_ombro_esq, y_ombro_dir - y_ombro_esq)
    if dist_ombros < 1e-6:
        return None
    return dist_orelha_ombro / dist_ombros


def metricas(pontos):
    """pontos = (x_orelha, y_orelha, x_ombro_esq, y_ombro_esq, x_ombro_dir, y_ombro_dir)
    → (angulo_bruto, razao_pescoco); (None, None) sem pontos ou com ombros coincidentes."""
    if pontos is None:
        return None, None
    xo, yo, xe, ye, xd, yd = pontos
    razao = calcular_razao_pescoco(xo, yo, xe, ye, xd, yd)
    if razao is None:
        return None, None
    return calcular_angulo_vertical(xo, yo, xe, ye), razao


def postura_ruim(desvio_angulo, queda_razao,
                 limiar_angulo=LIMIAR_DESVIO_ANGULO, limiar_queda=LIMIAR_QUEDA_RAZAO):
    """Regra de um quadro: desvio lateral acima do limiar OU queda da razão acima do limiar."""
    return desvio_angulo > limiar_angulo or queda_razao > limiar_queda


def calcular_baseline(amostras_angulo, amostras_razao, minimo=MINIMO_AMOSTRAS_CALIBRACAO):
    """Média das amostras da calibração → (angulo, razao), ou None se vieram poucas."""
    if len(amostras_angulo) < minimo:
        return None
    return (sum(amostras_angulo) / len(amostras_angulo),
            sum(amostras_razao) / len(amostras_razao))


Avaliacao = namedtuple("Avaliacao", "status angulo razao desvio_angulo queda_razao")
"""Resultado de um quadro. angulo/razao já suavizados (média móvel); None em SEM_USUARIO."""


class AvaliadorPostura:
    """
    Estado entre quadros (média móvel + contador de postura ruim). Uma instância
    por baseline: calibrou de novo, cria outra (ou chama zerar()).

        ruim       → contador += 1; ALERTA quando passa de FRAMES_PARA_ALERTA, senão ATENCAO
        correta    → contador -= 1 (mínimo 0) → CORRETA
        sem pontos → SEM_USUARIO; limpa a média móvel e NÃO mexe no contador
    """

    def __init__(self, baseline_angulo, baseline_razao,
                 limiar_angulo=LIMIAR_DESVIO_ANGULO, limiar_queda=LIMIAR_QUEDA_RAZAO,
                 historico=HISTORICO_TAMANHO, frames_para_alerta=FRAMES_PARA_ALERTA):
        self.baseline_angulo = baseline_angulo
        self.baseline_razao = baseline_razao
        self.limiar_angulo = limiar_angulo
        self.limiar_queda = limiar_queda
        self.frames_para_alerta = frames_para_alerta
        self._angulos = deque(maxlen=historico)
        self._razoes = deque(maxlen=historico)
        self.contador = 0

    def zerar(self):
        self._angulos.clear()
        self._razoes.clear()
        self.contador = 0

    def avaliar(self, pontos):
        """pontos: os 6 valores em pixels, ou None quando o MoveNet não achou os 3 pontos."""
        angulo_bruto, razao_bruta = metricas(pontos)
        if angulo_bruto is None:
            self._angulos.clear()
            self._razoes.clear()
            return Avaliacao(SEM_USUARIO, None, None, None, None)

        self._angulos.append(angulo_bruto)
        self._razoes.append(razao_bruta)
        angulo = sum(self._angulos) / len(self._angulos)
        razao = sum(self._razoes) / len(self._razoes)

        desvio_angulo = abs(angulo - self.baseline_angulo)
        queda_razao = (self.baseline_razao - razao) / self.baseline_razao  # só interessa quando DIMINUI

        if postura_ruim(desvio_angulo, queda_razao, self.limiar_angulo, self.limiar_queda):
            self.contador += 1
            status = ALERTA if self.contador > self.frames_para_alerta else ATENCAO
        else:
            self.contador = max(0, self.contador - 1)
            status = CORRETA
        return Avaliacao(status, angulo, razao, desvio_angulo, queda_razao)
