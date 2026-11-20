"""
Testes da lógica pura da postura (não precisa de câmera, OpenCV nem MoveNet).

    python -m unittest -v        (de dentro da pasta sensor-postura/)

Pontos sintéticos em pixels: (x_orelha, y_orelha, x_ombro_esq, y_ombro_esq, x_ombro_dir, y_ombro_dir).
"""
import math
import random
import unittest
from collections import deque

import postura_logica as pl
from postura_config import (
    LIMIAR_DESVIO_ANGULO, LIMIAR_QUEDA_RAZAO, HISTORICO_TAMANHO, FRAMES_PARA_ALERTA,
)

# Postura de referência: orelha 100 px acima do ombro esquerdo, ombros a 200 px
RETO = (300, 100, 300, 200, 100, 200)          # ângulo 0°, razão 0,5
BASE = (0.0, 0.5)


def tombado(graus, raio=100):
    """Orelha girada `graus` pro lado, mesmo comprimento de pescoço."""
    r = math.radians(graus)
    return (300 + raio * math.sin(r), 200 - raio * math.cos(r), 300, 200, 100, 200)


def caido(fator):
    """Pescoço aparente encurtado (cabeça caindo pra frente): razão = 0,5 × fator."""
    return (300, 200 - 100 * fator, 300, 200, 100, 200)


# ---------------------------------------------------------------------------
# Cópia LITERAL do trecho antigo do postura_servico.py (commit 142d8e5, dentro de
# _monitorar), só trocando os cálculos que vinham do detector pelas mesmas funções.
# Serve de "antes": a lógica nova tem que dar o mesmo resultado quadro a quadro.
# ---------------------------------------------------------------------------
class ReferenciaAntiga:
    def __init__(self, baseline_angulo, baseline_razao):
        self.baseline_angulo, self.baseline_razao = baseline_angulo, baseline_razao
        self.contador_ma_postura = 0
        self.historico_angulos = deque(maxlen=HISTORICO_TAMANHO)
        self.historico_razoes = deque(maxlen=HISTORICO_TAMANHO)

    def passo(self, pontos):
        if pontos is None:
            angulo_bruto = razao_pescoco = None
        else:
            xo, yo, xe, ye, xd, yd = pontos
            angulo_bruto = pl.calcular_angulo_vertical(xo, yo, xe, ye)
            razao_pescoco = pl.calcular_razao_pescoco(xo, yo, xe, ye, xd, yd)
            if razao_pescoco is None:     # o detector antigo devolvia a razão None nesse caso
                angulo_bruto = None
        status = "SEM_USUARIO"
        angulo = razao = desvio_angulo = queda_razao = None
        if angulo_bruto is not None and razao_pescoco is not None:
            self.historico_angulos.append(angulo_bruto)
            self.historico_razoes.append(razao_pescoco)
            angulo = sum(self.historico_angulos) / len(self.historico_angulos)
            razao = sum(self.historico_razoes) / len(self.historico_razoes)
            desvio_angulo = abs(angulo - self.baseline_angulo)
            queda_razao = (self.baseline_razao - razao) / self.baseline_razao
            postura_ruim = desvio_angulo > LIMIAR_DESVIO_ANGULO or queda_razao > LIMIAR_QUEDA_RAZAO
            if postura_ruim:
                self.contador_ma_postura += 1
                if self.contador_ma_postura > FRAMES_PARA_ALERTA:
                    status = "ALERTA"
                else:
                    status = "ATENCAO"
            else:
                self.contador_ma_postura = max(0, self.contador_ma_postura - 1)
                status = "CORRETA"
        else:
            self.historico_angulos.clear()
            self.historico_razoes.clear()
        return (status, angulo, razao, desvio_angulo, queda_razao)


class TesteCalculos(unittest.TestCase):
    def test_angulo_reto_e_tombado(self):
        self.assertAlmostEqual(pl.calcular_angulo_vertical(300, 100, 300, 200), 0.0)
        xo, yo, *_ = tombado(30)
        self.assertAlmostEqual(pl.calcular_angulo_vertical(xo, yo, 300, 200), 30.0, places=6)
        xo, yo, *_ = tombado(-30)
        self.assertAlmostEqual(pl.calcular_angulo_vertical(xo, yo, 300, 200), 30.0, places=6)  # abs

    def test_angulo_com_dy_zero_e_zero(self):
        self.assertEqual(pl.calcular_angulo_vertical(400, 200, 300, 200), 0.0)

    def test_razao(self):
        self.assertAlmostEqual(pl.calcular_razao_pescoco(*RETO), 0.5)
        self.assertAlmostEqual(pl.calcular_razao_pescoco(*caido(0.8)), 0.4)

    def test_razao_nao_muda_com_a_distancia_da_camera(self):
        dobro = tuple(v * 2 for v in RETO)
        self.assertAlmostEqual(pl.calcular_razao_pescoco(*dobro), pl.calcular_razao_pescoco(*RETO))

    def test_ombros_coincidentes_sem_metrica(self):
        self.assertIsNone(pl.calcular_razao_pescoco(300, 100, 300, 200, 300, 200))
        self.assertEqual(pl.metricas((300, 100, 300, 200, 300, 200)), (None, None))
        self.assertEqual(pl.metricas(None), (None, None))

    def test_baseline(self):
        self.assertIsNone(pl.calcular_baseline([1, 2, 3, 4], [0.5] * 4))
        self.assertEqual(pl.calcular_baseline([1, 2, 3, 4, 5], [0.4, 0.5, 0.6, 0.5, 0.5]), (3.0, 0.5))


class TesteDecisao(unittest.TestCase):
    def test_limiares_sao_estritos(self):
        self.assertFalse(pl.postura_ruim(LIMIAR_DESVIO_ANGULO, 0.0))
        self.assertTrue(pl.postura_ruim(LIMIAR_DESVIO_ANGULO + 0.01, 0.0))
        self.assertFalse(pl.postura_ruim(0.0, LIMIAR_QUEDA_RAZAO))
        self.assertTrue(pl.postura_ruim(0.0, LIMIAR_QUEDA_RAZAO + 0.001))

    def test_razao_aumentando_nao_e_postura_ruim(self):
        self.assertFalse(pl.postura_ruim(0.0, -0.5))

    def test_postura_reta_e_correta(self):
        av = pl.AvaliadorPostura(*BASE)
        r = av.avaliar(RETO)
        self.assertEqual(r.status, pl.CORRETA)
        self.assertAlmostEqual(r.desvio_angulo, 0.0)
        self.assertAlmostEqual(r.queda_razao, 0.0)

    def test_sem_pontos_e_sem_usuario(self):
        self.assertEqual(pl.AvaliadorPostura(*BASE).avaliar(None).status, pl.SEM_USUARIO)

    def test_alerta_so_depois_de_15_quadros_ruins(self):
        av = pl.AvaliadorPostura(*BASE)
        estados = [av.avaliar(tombado(40)).status for _ in range(FRAMES_PARA_ALERTA + 1)]
        self.assertEqual(estados[:FRAMES_PARA_ALERTA], [pl.ATENCAO] * FRAMES_PARA_ALERTA)
        self.assertEqual(estados[-1], pl.ALERTA)       # 16º quadro (contador > 15)

    def test_queda_da_cabeca_tambem_alerta(self):
        av = pl.AvaliadorPostura(*BASE)
        for _ in range(FRAMES_PARA_ALERTA + 1):
            r = av.avaliar(caido(0.7))
        self.assertEqual(r.status, pl.ALERTA)
        self.assertAlmostEqual(r.queda_razao, 0.3)

    def test_correta_desconta_um_por_quadro(self):
        av = pl.AvaliadorPostura(*BASE, historico=1)
        for _ in range(10):
            av.avaliar(tombado(40))
        av.avaliar(RETO)
        self.assertEqual(av.contador, 9)

    def test_sem_usuario_nao_mexe_no_contador_e_limpa_a_media(self):
        av = pl.AvaliadorPostura(*BASE)
        for _ in range(10):
            av.avaliar(tombado(40))
        av.avaliar(None)
        self.assertEqual(av.contador, 10)
        r = av.avaliar(RETO)      # média recomeça do zero: só o quadro reto conta
        self.assertAlmostEqual(r.angulo, 0.0)

    def test_media_movel_de_5(self):
        av = pl.AvaliadorPostura(*BASE)
        for g in (10, 20, 30, 40, 50, 60):
            r = av.avaliar(tombado(g))
        self.assertAlmostEqual(r.angulo, 40.0, places=6)   # média de 20..60


class TesteEnquadramento(unittest.TestCase):
    def test_visivel_e_acima_do_limiar(self):
        v = pl.pontos_visiveis((0.9, 0.4, 0.1), 0.4)
        self.assertEqual(v, {"orelha": True, "ombro_orelha": False, "outro_ombro": False})

    def test_descreve_o_ponto_que_mais_faltou(self):
        texto = pl.descrever_falta({"orelha": 2, "ombro_orelha": 0, "outro_ombro": 40}, 50)
        self.assertEqual(texto, "outro ombro fora da imagem (40 de 50 quadros)")

    def test_empate_lista_os_dois(self):
        texto = pl.descrever_falta({"orelha": 30, "ombro_orelha": 30, "outro_ombro": 0}, 50)
        self.assertTrue(texto.startswith("orelha e ombro do lado da orelha"))

    def test_nada_faltou(self):
        self.assertIsNone(pl.descrever_falta({"orelha": 0, "ombro_orelha": 0, "outro_ombro": 0}, 50))
        self.assertIsNone(pl.descrever_falta({}, 0))


class TesteIgualAoCodigoAntigo(unittest.TestCase):
    """Prova do T1: mesma saída do código antigo em sequências aleatórias longas."""

    def _comparar(self, sequencia, baseline):
        antiga = ReferenciaAntiga(*baseline)
        nova = pl.AvaliadorPostura(*baseline)
        for i, pontos in enumerate(sequencia):
            esperado = antiga.passo(pontos)
            obtido = tuple(nova.avaliar(pontos))
            self.assertEqual(obtido, esperado, f"quadro {i}: {pontos}")
            self.assertEqual(nova.contador, antiga.contador_ma_postura, f"contador no quadro {i}")

    def test_sequencias_aleatorias(self):
        sorteio = random.Random(20261119)   # semente fixa: o teste é reproduzível
        for _ in range(200):
            baseline = (sorteio.uniform(0, 20), sorteio.uniform(0.3, 0.8))
            sequencia = []
            for _ in range(300):
                tipo = sorteio.random()
                if tipo < 0.15:
                    sequencia.append(None)
                elif tipo < 0.18:
                    sequencia.append((300, 100, 300, 200, 300, 200))     # ombros coincidentes
                else:
                    # pixels inteiros, como o detector entrega
                    sequencia.append(tuple(int(sorteio.uniform(0, 640)) for _ in range(6)))
            self._comparar(sequencia, baseline)

    def test_sequencias_proximas_do_limiar(self):
        sorteio = random.Random(7)
        for _ in range(100):
            sequencia = [None if sorteio.random() < 0.1 else
                         (tombado(sorteio.uniform(0, 25)) if sorteio.random() < 0.5 else caido(sorteio.uniform(0.75, 1.0)))
                         for _ in range(300)]
            self._comparar(sequencia, BASE)


if __name__ == "__main__":
    unittest.main()
