"""
Decisão da postura. Lógica PURA: não sabe de câmera, MoveNet, tela, socket nem
relógio. Recebe os 3 pontos (orelha esquerda, ombro esquerdo, ombro direito, em
pixels) e a baseline, e devolve o estado e os valores. Por isso dá pra testar
com pontos sintéticos, sem o Pi (ver test_postura_logica.py).

Os limiares, a média móvel e a regra de um quadro são os mesmos do código
antigo (T1, provado por teste). O contador de ALERTA mudou de propósito no T3:
as perdas de detecção no meio de uma sequência ruim passam a contar como indício.
E em 20/11: o ALERTA só sai depois de QUADROS_PARA_SAIR_ALERTA quadros bons seguidos.
"""
import math
from collections import deque, namedtuple

from postura_config import (
    LIMIAR_DESVIO_ANGULO, LIMIAR_QUEDA_RAZAO, HISTORICO_TAMANHO, FRAMES_PARA_ALERTA,
    PERDAS_TOLERADAS, MINIMO_RUINS_MEDIDOS, QUADROS_PARA_SAIR_ALERTA,
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


def calcular_razao_cb(x_orelha_esq, y_orelha_esq, x_orelha_dir, y_orelha_dir,
                      x_ombro_esq, y_ombro_esq, x_ombro_dir, y_ombro_dir):
    """
    T4: c/b = distância orelha-orelha ÷ largura dos ombros. Só ARMAZENADA no CSV: não
    entra na decisão até os dados do estudo mostrarem que ela separa postura boa de ruim.
    Hipótese (não medida): cabeça pra frente com ombros parados → rosto mais perto → c/b sobe.
    """
    dist_ombros = math.hypot(x_ombro_dir - x_ombro_esq, y_ombro_dir - y_ombro_esq)
    if dist_ombros < 1e-6:
        return None
    return math.hypot(x_orelha_dir - x_orelha_esq, y_orelha_dir - y_orelha_esq) / dist_ombros


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


# --- Enquadramento: quais dos 3 pontos o MoveNet está vendo (T2') ---
# Nomes sem esquerda/direita: a imagem é espelhada e o "esquerdo" do MoveNet não é
# garantido como o esquerdo da pessoa; pro usuário só importa qual ponto falta.
PONTOS = ("orelha", "ombro_orelha", "outro_ombro")
NOME_PONTO = {"orelha": "orelha", "ombro_orelha": "ombro do lado da orelha", "outro_ombro": "outro ombro"}


def pontos_visiveis(confiancas, limiar):
    """confiancas = (orelha, ombro do lado da orelha, outro ombro) → {nome: bool}.
    Visível = confiança ACIMA do limiar (mesma regra que decide se o quadro vale)."""
    return {nome: c > limiar for nome, c in zip(PONTOS, confiancas)}


def descrever_falta(faltas, total):
    """
    faltas = {nome: nº de quadros em que o ponto não apareceu} durante a calibração.
    Devolve o texto do ponto que mais faltou (empates: todos), ou None se nada faltou.
    """
    if total <= 0 or not faltas or max(faltas.values()) == 0:
        return None
    pior = max(faltas.values())
    nomes = [NOME_PONTO[n] for n in PONTOS if faltas.get(n, 0) == pior]
    return f"{' e '.join(nomes)} fora da imagem ({pior} de {total} quadros)"


Avaliacao = namedtuple("Avaliacao",
                       "status angulo razao desvio_angulo queda_razao status_exibido")
"""
Resultado de um quadro.
  status          o que o QUADRO mostrou (SEM_USUARIO quando perdeu os pontos): vai pro CSV
  status_exibido  a decisão que vai pra tela (numa perda tolerada continua ATENCAO/ALERTA)
  angulo/razao    já suavizados (média móvel); None quando o quadro não tem pontos
"""


class AvaliadorPostura:
    """
    Estado entre quadros (média móvel + contador de postura ruim). Uma instância
    por baseline: calibrou de novo, cria outra (ou chama zerar()).

    Contador (T3; c = contador, K = FRAMES_PARA_ALERTA, N = PERDAS_TOLERADAS,
    M = MINIMO_RUINS_MEDIDOS):
        ruim medido → c += 1, perdidos = 0, medidos += 1
        correta     → c -= 1 (mínimo 0), perdidos = 0; c chegou a 0 → medidos = 0
                      (o desconto de 1 é o comportamento antigo, mantido)
        sem pontos  → limpa a média móvel e:
                      - sem sequência ruim (c = 0): SEM_USUARIO, nada muda
                      - com sequência ruim: perdidos += 1; se perdidos <= N, c += 1
                        (indício: encurvado no limite da captação) e a tela continua na
                        decisão; se perdidos > N, zera tudo e mostra SEM_USUARIO
                        (saiu do enquadramento)
        ALERTA quando c > K E medidos >= M (trava: o alerta não pode vir
        majoritariamente de quadros perdidos). Senão, ruim = ATENCAO.

    Saída do ALERTA (S = QUADROS_PARA_SAIR_ALERTA; 0 desliga):
        depois que entrou em ALERTA, a tela fica em ALERTA até S quadros CORRETOS
        seguidos. Ruim ou perda no meio reinicia a contagem. No S-ésimo, zera tudo
        (fim do episódio) e mostra CORRETA. Na janela de saída o `status` do quadro
        é CORRETA (dado honesto, CSV) e o `status_exibido` é ALERTA.
    """

    def __init__(self, baseline_angulo, baseline_razao,
                 limiar_angulo=LIMIAR_DESVIO_ANGULO, limiar_queda=LIMIAR_QUEDA_RAZAO,
                 historico=HISTORICO_TAMANHO, frames_para_alerta=FRAMES_PARA_ALERTA,
                 perdas_toleradas=PERDAS_TOLERADAS, minimo_medidos=MINIMO_RUINS_MEDIDOS,
                 quadros_para_sair=QUADROS_PARA_SAIR_ALERTA):
        self.baseline_angulo = baseline_angulo
        self.baseline_razao = baseline_razao
        self.limiar_angulo = limiar_angulo
        self.limiar_queda = limiar_queda
        self.frames_para_alerta = frames_para_alerta
        self.perdas_toleradas = perdas_toleradas
        self.minimo_medidos = minimo_medidos
        self.quadros_para_sair = quadros_para_sair
        self._angulos = deque(maxlen=historico)
        self._razoes = deque(maxlen=historico)
        self.contador = 0
        self.perdidos = 0      # perdas seguidas dentro da sequência ruim
        self.medidos = 0       # quadros ruins MEDIDOS na sequência atual
        self.em_alerta = False # entrou em ALERTA e ainda não saiu (só com a saída ligada)
        self.bons_seguidos = 0 # quadros corretos seguidos na janela de saída

    def zerar(self):
        self._angulos.clear()
        self._razoes.clear()
        self._zerar_contador()

    def _zerar_contador(self):
        self.contador = self.perdidos = self.medidos = self.bons_seguidos = 0
        self.em_alerta = False

    def _decisao_ruim(self):
        if self.em_alerta or (self.contador > self.frames_para_alerta
                              and self.medidos >= self.minimo_medidos):
            self.em_alerta = self.quadros_para_sair > 0
            return ALERTA
        return ATENCAO

    def avaliar(self, pontos):
        """pontos: os 6 valores em pixels, ou None quando o MoveNet não achou os 3 pontos."""
        angulo_bruto, razao_bruta = metricas(pontos)
        if angulo_bruto is None:
            self._angulos.clear()
            self._razoes.clear()
            exibido = SEM_USUARIO
            if self.contador > 0 or self.em_alerta:
                self.perdidos += 1
                self.bons_seguidos = 0
                if self.perdidos <= self.perdas_toleradas:
                    self.contador += 1
                    exibido = self._decisao_ruim()
                else:
                    self._zerar_contador()
            return Avaliacao(SEM_USUARIO, None, None, None, None, exibido)

        self._angulos.append(angulo_bruto)
        self._razoes.append(razao_bruta)
        angulo = sum(self._angulos) / len(self._angulos)
        razao = sum(self._razoes) / len(self._razoes)

        desvio_angulo = abs(angulo - self.baseline_angulo)
        queda_razao = (self.baseline_razao - razao) / self.baseline_razao  # só interessa quando DIMINUI

        self.perdidos = 0
        exibido = None
        if postura_ruim(desvio_angulo, queda_razao, self.limiar_angulo, self.limiar_queda):
            self.bons_seguidos = 0
            self.contador += 1
            self.medidos += 1
            status = self._decisao_ruim()
        else:
            self.contador = max(0, self.contador - 1)
            if self.contador == 0:
                self.medidos = 0
            status = CORRETA
            if self.em_alerta:
                self.bons_seguidos += 1
                if self.bons_seguidos >= self.quadros_para_sair:
                    self._zerar_contador()   # fim do episódio: contador vazio
                else:
                    exibido = ALERTA         # janela de saída: tela segue em ALERTA
        return Avaliacao(status, angulo, razao, desvio_angulo, queda_razao, exibido or status)
