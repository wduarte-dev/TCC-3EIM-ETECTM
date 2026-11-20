"""
Lógica PURA do programa de coleta do estudo (T1b + etapa 7 do T4).

Não sabe de câmera, janela, MoveNet nem arquivo: recebe os 17 pontos já em pixels
e o horário, e decide o que gravar. Por isso dá pra testar sem câmera
(ver test_coleta.py). A parte de câmera/janela/CSV fica em coleta.py.

As métricas (ângulo, razão, c/b, regra de um quadro) vêm IMPORTADAS de
sensor-postura/postura_logica.py, não copiadas: o estudo mede exatamente o que o
sistema mede.
"""
import math
import os
import statistics
import sys
from collections import namedtuple

DIR_POSTURA = os.path.join(os.path.dirname(os.path.realpath(__file__)), os.pardir, "sensor-postura")
sys.path.insert(0, os.path.realpath(DIR_POSTURA))

from postura_config import LIMIAR_CONFIANCA  # noqa: E402
from postura_logica import (  # noqa: E402
    metricas, calcular_razao_cb, calcular_baseline, postura_ruim, MINIMO_AMOSTRAS_CALIBRACAO,
)

# Ordem de saída do MoveNet (formato COCO). "esq"/"dir" são os rótulos do MoveNet na
# imagem ESPELHADA (igual ao serviço), não necessariamente o lado da pessoa.
NOMES_PONTOS = (
    "nariz", "olho_esq", "olho_dir", "orelha_esq", "orelha_dir",
    "ombro_esq", "ombro_dir", "cotovelo_esq", "cotovelo_dir",
    "punho_esq", "punho_dir", "quadril_esq", "quadril_dir",
    "joelho_esq", "joelho_dir", "tornozelo_esq", "tornozelo_dir",
)
I_ORELHA, I_OUTRA_ORELHA, I_OMBRO_ORELHA, I_OUTRO_OMBRO = 3, 4, 5, 6   # os mesmos do serviço

Etapa = namedtuple("Etapa", "num chave titulo instrucoes")

# Texto da etapa 1: OSHA, Computer Workstations eTool, "Good Working Positions"
# (cabeça nivelada, olhando pra frente e alinhada com o tronco; ombros relaxados e braços
# soltos ao lado do corpo; tronco e pescoço aproximadamente verticais; pés apoiados).
# Sem acento: o texto da janela do OpenCV só aceita ASCII.
ETAPAS = (
    Etapa(1, "correta", "POSTURA CORRETA (baseline)", (
        "Sente com as costas apoiadas no encosto.",
        "Tronco e pescoco retos, mais ou menos na vertical.",
        "Cabeca nivelada, olhando pra frente,",
        "alinhada com o tronco.",
        "Ombros relaxados, bracos soltos ao lado do corpo.",
        "Pes apoiados no chao.",
        "(Referencia: OSHA, Computer Workstations eTool)",
    )),
    Etapa(2, "incl_esquerda", "CABECA INCLINADA PRA ESQUERDA", (
        "Incline a cabeca pro lado do SEU ombro esquerdo,",
        "o maximo que conseguir sem dor.",
        "Ombros parados.",
    )),
    Etapa(3, "incl_direita", "CABECA INCLINADA PRA DIREITA", (
        "Incline a cabeca pro lado do SEU ombro direito,",
        "o maximo que conseguir sem dor.",
        "Ombros parados.",
    )),
    Etapa(4, "relaxada", "SEU JEITO NORMAL", (
        "Sente do jeito que voce costuma ficar",
        "no computador, relaxado.",
        "Nao tente corrigir a postura.",
    )),
    Etapa(5, "ma_postura", "MA POSTURA (ENCURVADO)", (
        "Ombros projetados pra frente e",
        "cabeca levemente caida pra frente,",
        "como quem esta cansado no fim do dia.",
    )),
    Etapa(6, "cabeca_baixa", "CABECA BAIXA", (
        "Olhe pro seu colo,",
        "como quem le o celular apoiado nas pernas.",
    )),
    Etapa(7, "projecao", "SO A CABECA PRA FRENTE", (
        "Empurre so a cabeca (o queixo) pra frente.",
        "Ombros parados, sem encurvar.",
    )),
)

# Métricas resumidas por etapa (mediana e desvio-padrão de cada uma)
METRICAS = ("angulo", "razao", "razao_cb", "a_px", "b_px", "c_px", "desvio_angulo", "queda_razao_pct")


def analisar_quadro(kps, baseline=None, limiar=LIMIAR_CONFIANCA):
    """
    kps: 17 tuplas (x_px, y_px, confiança) ou None (quadro sem leitura).
    baseline: (angulo, razao) da etapa 1, ou None (ainda não calibrou).

    Regra de "quadro válido" = a do serviço: orelha + os dois ombros com confiança
    ACIMA do limiar. Ângulo e razão vêm de postura_logica.metricas().
    desvio/queda/ruim_quadro são POR QUADRO (sem a média móvel de 5 do serviço), pra
    análise offline poder refazer qualquer suavização.
    """
    r = dict(valido=False, angulo=None, razao=None, razao_cb=None,
             a_px=None, b_px=None, c_px=None,
             desvio_angulo=None, queda_razao_pct=None, ruim_quadro=None,
             conf_orelha=0.0, conf_ombro_orelha=0.0, conf_outro_ombro=0.0)
    if kps is None:
        return r
    xo, yo, co = kps[I_ORELHA]
    xe, ye, ce = kps[I_OMBRO_ORELHA]
    xd, yd, cd = kps[I_OUTRO_OMBRO]
    r.update(conf_orelha=float(co), conf_ombro_orelha=float(ce), conf_outro_ombro=float(cd))
    if co <= limiar or ce <= limiar or cd <= limiar:
        return r
    angulo, razao = metricas((xo, yo, xe, ye, xd, yd))
    if angulo is None:          # ombros coincidentes: o serviço também descarta
        return r
    r.update(valido=True, angulo=angulo, razao=razao,
             a_px=math.hypot(xo - xe, yo - ye), b_px=math.hypot(xd - xe, yd - ye))
    xo2, yo2, co2 = kps[I_OUTRA_ORELHA]
    if co2 > limiar:
        r["razao_cb"] = calcular_razao_cb(xo, yo, xo2, yo2, xe, ye, xd, yd)
        r["c_px"] = math.hypot(xo2 - xo, yo2 - yo)
    if baseline is not None:
        desvio = abs(angulo - baseline[0])
        queda = (baseline[1] - razao) / baseline[1]
        r.update(desvio_angulo=desvio, queda_razao_pct=queda * 100.0,
                 ruim_quadro=postura_ruim(desvio, queda))
    return r


def _mediana_dp(valores):
    if not valores:
        return None, None
    dp = statistics.stdev(valores) if len(valores) >= 2 else None
    return statistics.median(valores), dp


def resumir_etapa(analises, duracao_s):
    """Resumo de uma tentativa: contagens, % sem usuário, mediana e desvio de cada métrica."""
    validas = [a for a in analises if a["valido"]]
    n_total, n_validos = len(analises), len(validas)
    resumo = dict(
        n_total=n_total, n_validos=n_validos,
        pct_sem_usuario=(100.0 * (n_total - n_validos) / n_total) if n_total else None,
        fps_medio=(n_total / duracao_s) if duracao_s > 0 else None,
        n_cb=sum(1 for a in validas if a["razao_cb"] is not None),
    )
    for m in METRICAS:
        resumo[f"{m}_mediana"], resumo[f"{m}_dp"] = _mediana_dp(
            [a[m] for a in validas if a[m] is not None])
    julgados = [a["ruim_quadro"] for a in validas if a["ruim_quadro"] is not None]
    resumo["pct_ruim_quadro"] = (100.0 * sum(julgados) / len(julgados)) if julgados else None
    # baseline igual à do serviço: MÉDIA das amostras válidas, mínimo de 5
    resumo["baseline"] = calcular_baseline([a["angulo"] for a in validas],
                                           [a["razao"] for a in validas])
    return resumo


# --- Máquina de estados de uma pessoa ---
ENQUADRAR, INSTRUCAO, CONTAGEM, GRAVANDO, REVISAO, FIM = (
    "ENQUADRAR", "INSTRUCAO", "CONTAGEM", "GRAVANDO", "REVISAO", "FIM")


class Sessao:
    """
    Sequência de uma pessoa (o operador aperta as teclas, a pessoa só faz a pose):
        ENQUADRAR  ajustar a câmera até os 3 pontos aparecerem → ESPAÇO
        INSTRUCAO  mostra o texto da etapa → ESPAÇO
        CONTAGEM   alguns segundos pra pessoa assumir a pose (não grava)
        GRAVANDO   grava todos os quadros por `duracao_s`
        REVISAO    mostra o resumo → ESPAÇO aceita, R repete a etapa
        FIM        acabou as 7 etapas (ou o operador saiu)

    Só a etapa 1 EXIGE repetir quando não deu (sem baseline não dá pra comparar nada).
    Nas outras, perder os pontos é DADO (hipótese do T3), então aceita mesmo com perdas.

    `registro` recebe tudo que deve ir pro disco:
        registro.quadro(sessao, t_s, analise, kps)
        registro.etapa(sessao, resumo, aceita)
    """

    def __init__(self, registro, duracao_s=5.0, contagem_s=2.0, etapas=ETAPAS):
        self.registro = registro
        self.duracao_s = duracao_s
        self.contagem_s = contagem_s
        self.etapas = etapas
        self.estado = ENQUADRAR
        self.indice = 0
        self.tentativa = 1
        self.baseline = None        # (angulo, razao) da etapa 1 aceita
        self.baseline_b_px = None   # mediana da largura dos ombros na etapa 1 (pra b/b0 offline)
        self.baseline_cb = None     # mediana de c/b na etapa 1
        self.aceitas = []           # chaves das etapas aceitas
        self.resumo = None          # resumo da última tentativa (tela de revisão)
        self.completa = False
        self._t0 = None
        self._analises = []

    @property
    def etapa(self):
        return self.etapas[self.indice] if self.indice < len(self.etapas) else None

    def restante_s(self, agora):
        """Segundos restantes da contagem ou da gravação (pra tela)."""
        if self.estado == CONTAGEM:
            return max(0.0, self.contagem_s - (agora - self._t0))
        if self.estado == GRAVANDO:
            return max(0.0, self.duracao_s - (agora - self._t0))
        return None

    @property
    def gravados(self):
        return len(self._analises)

    @property
    def gravados_validos(self):
        return sum(1 for a in self._analises if a["valido"])

    def pode_aceitar(self):
        if self.estado != REVISAO or self.resumo is None:
            return False
        if self.indice == 0:
            return self.resumo["baseline"] is not None
        return True

    def aviso_revisao(self):
        """Texto curto pro operador na revisão (None = nada a avisar)."""
        if self.resumo is None:
            return None
        if self.indice == 0 and self.resumo["baseline"] is None:
            return (f"Menos de {MINIMO_AMOSTRAS_CALIBRACAO} quadros validos: "
                    "sem baseline, repita (R)")
        pct = self.resumo["pct_sem_usuario"] or 0.0
        if self.indice == 0 and pct > 50:
            return "Muitas perdas na baseline: ajuste a camera e repita (R)"
        if self.indice >= 4 and pct > 0:
            return "Perdas aqui sao dado do estudo: pode aceitar"
        return None

    # --- entradas ---
    def tecla(self, tecla, agora):
        """tecla: 'espaco', 'r' ou 'sair'."""
        if tecla == "sair":
            self._sair(agora)
        elif tecla == "espaco":
            if self.estado == ENQUADRAR:
                self.estado = INSTRUCAO
            elif self.estado == INSTRUCAO:
                self.estado, self._t0, self._analises = CONTAGEM, agora, []
            elif self.estado == REVISAO and self.pode_aceitar():
                self._aceitar()
        elif tecla == "r" and self.estado == REVISAO:
            self.registro.etapa(self, self.resumo, False)
            self.tentativa += 1
            self.estado = INSTRUCAO

    def quadro(self, kps, agora):
        """Um quadro da câmera (kps = 17 pontos em pixels ou None). Devolve a análise."""
        analise = analisar_quadro(kps, self.baseline)
        if self.estado == CONTAGEM and agora - self._t0 >= self.contagem_s:
            self.estado, self._t0 = GRAVANDO, agora
        if self.estado == GRAVANDO:
            t = agora - self._t0
            if t >= self.duracao_s:
                self._fechar_gravacao(t)
            else:
                self._analises.append(analise)
                self.registro.quadro(self, t, analise, kps)
        return analise

    # --- internos ---
    def _fechar_gravacao(self, duracao_real):
        self.resumo = resumir_etapa(self._analises, duracao_real)
        self.estado = REVISAO

    def _aceitar(self):
        self.registro.etapa(self, self.resumo, True)
        if self.indice == 0:
            self.baseline = self.resumo["baseline"]
            self.baseline_b_px = self.resumo["b_px_mediana"]
            self.baseline_cb = self.resumo["razao_cb_mediana"]
        self.aceitas.append(self.etapa.chave)
        self.indice += 1
        self.tentativa = 1
        self.resumo = None
        if self.indice >= len(self.etapas):
            self.completa = True
            self.estado = FIM
        else:
            self.estado = INSTRUCAO

    def _sair(self, agora):
        if self.estado == GRAVANDO and self._analises:
            # gravação interrompida: registra a tentativa como não aceita
            self.registro.etapa(self, resumir_etapa(self._analises, agora - self._t0), False)
        elif self.estado == REVISAO and self.resumo is not None:
            self.registro.etapa(self, self.resumo, False)
        self.estado = FIM
