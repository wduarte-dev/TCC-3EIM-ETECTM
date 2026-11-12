#!/usr/bin/env python3
"""
SERVIÇO DE MONITORAMENTO DE POSTURA — TCC (versão headless, Raspberry Pi 3B)

O que mudou em relação ao main-otimizado.py:
- Roda SEM TELA: o status sai no terminal (ou no journal do systemd) pela
  função mostrar_status(). Quando o display OLED estiver pronto, é só essa
  função que muda.
- Calibração SOB DEMANDA: ao ligar (e ao voltar pra câmera ao vivo), fica em
  "aguardando calibração" sem analisar nada, até o usuário rodar
  `postura recalibrar`. Aí vem uma contagem de 10 s e a coleta.
  Exceção: se o programa reiniciar no mesmo boot (travou e o systemd religou),
  reaproveita a última baseline salva.
- NUNCA encerra sozinho: se a câmera cair, tenta reabrir; se um vídeo acabar,
  volta pra câmera ao vivo.
- Recebe ordens do comando `postura` (status, live, video, recalibrar, gravar)
  por um socket Unix, sem precisar reiniciar o programa.
- Grava vídeos de teste com a própria webcam (`postura gravar N`).
- Grava um log CSV por dia na pasta logs/.
- Janela com o vídeo é OPCIONAL (--preview), pra debug via `ssh -X`.

Os cálculos (ângulo, razão pescoço/ombros, limiares, média móvel e contador de
alerta) e as otimizações do Pi 3B são os MESMOS do main-otimizado.py.

Uso manual:
    python3 postura_servico.py                 # headless, câmera ao vivo
    python3 postura_servico.py --preview       # com janela (precisa de ssh -X)
    python3 postura_servico.py --video ruim.mp4
"""
import os
import sys
import csv
import math
import json
import time
import queue
import signal
import socket
import argparse
import threading
from collections import deque
from datetime import datetime

import cv2
import numpy as np

from postura_config import (
    CAMINHO_MODELO, DIR_VIDEOS, DIR_LOGS, CAMINHO_SOCKET, ARQUIVO_BASELINE,
    INDICE_CAMERA, LARGURA, ALTURA,
    LIMIAR_CONFIANCA, LIMIAR_DESVIO_ANGULO, LIMIAR_QUEDA_RAZAO,
    DURACAO_CALIBRACAO, HISTORICO_TAMANHO, FRAMES_PARA_ALERTA,
    CONTAGEM_CALIBRACAO, CONTAGEM_GRAVACAO, GRAVACAO_MAX_S,
    INTERVALO_PRINT_S, MAX_FALHAS_LEITURA, ESPERA_CAMERA_S,
    listar_videos,
)

# Índices das articulações no MoveNet (COCO format)
ORELHA_ESQ = 3
OMBRO_ESQ, OMBRO_DIR = 5, 6

NOME_JANELA = "Monitoramento de Postura - TCC"


# =====================================================================
# CÁLCULOS — idênticos ao main-otimizado.py
# =====================================================================

def calcular_angulo_vertical(x_orelha, y_orelha, x_ombro, y_ombro):
    """
    Calcula o DESVIO EM DIREÇÃO (graus) da linha orelha-ombro em relação à
    vertical. Sozinho, isso só pega inclinação LATERAL da cabeça — não pega
    "queda" de cabeça pra frente/baixo sem deslocamento lateral, porque
    atan2 é invariante à magnitude do vetor. Por isso combinamos com
    calcular_razao_pescoco() abaixo.
    """
    dx = x_orelha - x_ombro
    dy = y_orelha - y_ombro  # No OpenCV, Y cresce para baixo, então orelha está acima (y menor)

    if dy == 0:
        return 0.0

    angulo_rad = math.atan2(dx, -dy)
    return abs(math.degrees(angulo_rad))


def calcular_razao_pescoco(x_orelha, y_orelha, x_ombro_esq, y_ombro_esq, x_ombro_dir, y_ombro_dir):
    """
    Mede o comprimento aparente do "pescoço" (distância orelha-ombro),
    normalizado pela largura dos ombros (que serve de referência de escala
    e cancela o efeito de aproximar/afastar da câmera).

    Esse é o componente que capta postura ruim SUTIL: quando a cabeça cai
    pra frente/baixo (cervical flexion, "text neck"), essa razão diminui,
    mesmo quando o ângulo lateral (função acima) quase não muda.
    """
    dist_orelha_ombro = math.hypot(x_orelha - x_ombro_esq, y_orelha - y_ombro_esq)
    dist_ombros = math.hypot(x_ombro_dir - x_ombro_esq, y_ombro_dir - y_ombro_esq)

    if dist_ombros < 1e-6:
        return None

    return dist_orelha_ombro / dist_ombros


def preprocessar_letterbox(frame, tamanho):
    """
    Redimensiona o frame para um quadrado 'tamanho x tamanho' SEM distorcer a
    proporção original (letterbox), preenchendo o espaço sobrando com preto.
    Retorna a imagem processada + os parâmetros necessários para mapear os
    keypoints de volta às coordenadas do frame original.
    """
    h, w = frame.shape[:2]
    escala = tamanho / max(h, w)
    novo_w, novo_h = int(round(w * escala)), int(round(h * escala))

    # INTER_LINEAR (padrão) mantido para não degradar os keypoints.
    redimensionado = cv2.resize(frame, (novo_w, novo_h))

    pad_w = tamanho - novo_w
    pad_h = tamanho - novo_h
    topo, base = pad_h // 2, pad_h - pad_h // 2
    esquerda, direita = pad_w // 2, pad_w - pad_w // 2

    padronizado = cv2.copyMakeBorder(
        redimensionado, topo, base, esquerda, direita,
        cv2.BORDER_CONSTANT, value=(0, 0, 0)
    )
    padronizado = cv2.cvtColor(padronizado, cv2.COLOR_BGR2RGB)

    return padronizado, escala, esquerda, topo


def desnormalizar_keypoint(kp_x_norm, kp_y_norm, tamanho, escala, offset_x, offset_y):
    """
    Converte a coordenada normalizada (0-1) retornada pelo modelo, que está
    relativa ao quadrado com letterbox, de volta para pixels no frame original.
    """
    x_no_quadrado = kp_x_norm * tamanho
    y_no_quadrado = kp_y_norm * tamanho
    x_original = (x_no_quadrado - offset_x) / escala
    y_original = (y_no_quadrado - offset_y) / escala
    return int(x_original), int(y_original)


def carregar_classe_interpretador():
    """Aceita tflite_runtime, ai_edge_litert (sucessor do tflite_runtime) ou TensorFlow completo."""
    try:
        from tflite_runtime.interpreter import Interpreter
    except ImportError:
        try:
            from ai_edge_litert.interpreter import Interpreter
        except ImportError:
            from tensorflow.lite.python.interpreter import Interpreter
    return Interpreter


class DetectorPostura:
    """Encapsula o MoveNet. A inferência é a mesma do main-otimizado.py."""

    def __init__(self):
        # OTIMIZAÇÃO 1: OpenCV em 1 thread, sobrando núcleos pro TFLite.
        cv2.setNumThreads(1)

        # OTIMIZAÇÃO 2: TFLite usando (núcleos - 1) threads → 3 no Pi 3B.
        num_threads = max(1, (os.cpu_count() or 4) - 1)
        Interpreter = carregar_classe_interpretador()
        self.interpretador = Interpreter(model_path=CAMINHO_MODELO, num_threads=num_threads)
        self.interpretador.allocate_tensors()

        detalhes_entrada = self.interpretador.get_input_details()
        detalhes_saida = self.interpretador.get_output_details()
        self.indice_entrada = detalhes_entrada[0]['index']
        self.indice_saida = detalhes_saida[0]['index']
        self.dtype_esperado = detalhes_entrada[0]['dtype']
        self.tamanho_entrada = detalhes_entrada[0]['shape'][1]  # normalmente 192 no Lightning

    def detectar_metricas_postura(self, frame, limiar_confianca):
        """
        Retorna (angulo_bruto, razao_pescoco, pontos) ou (None, None, None).
        Requer orelha esquerda + os DOIS ombros com confiança suficiente.
        """
        tamanho = self.tamanho_entrada
        entrada_img, escala, offset_x, offset_y = preprocessar_letterbox(frame, tamanho)

        # OTIMIZAÇÃO 4: sem cópia extra quando o dtype já bate.
        entrada_tensor = entrada_img[np.newaxis, ...].astype(self.dtype_esperado, copy=False)
        self.interpretador.set_tensor(self.indice_entrada, entrada_tensor)

        self.interpretador.invoke()
        keypoints = self.interpretador.get_tensor(self.indice_saida)[0][0]

        orelha_y, orelha_x, conf_orelha = keypoints[ORELHA_ESQ]
        ombro_esq_y, ombro_esq_x, conf_ombro_esq = keypoints[OMBRO_ESQ]
        ombro_dir_y, ombro_dir_x, conf_ombro_dir = keypoints[OMBRO_DIR]

        if (conf_orelha <= limiar_confianca or conf_ombro_esq <= limiar_confianca
                or conf_ombro_dir <= limiar_confianca):
            return None, None, None

        x_orelha, y_orelha = desnormalizar_keypoint(orelha_x, orelha_y, tamanho, escala, offset_x, offset_y)
        x_ombro_esq, y_ombro_esq = desnormalizar_keypoint(ombro_esq_x, ombro_esq_y, tamanho, escala, offset_x, offset_y)
        x_ombro_dir, y_ombro_dir = desnormalizar_keypoint(ombro_dir_x, ombro_dir_y, tamanho, escala, offset_x, offset_y)

        angulo_bruto = calcular_angulo_vertical(x_orelha, y_orelha, x_ombro_esq, y_ombro_esq)
        razao_pescoco = calcular_razao_pescoco(
            x_orelha, y_orelha, x_ombro_esq, y_ombro_esq, x_ombro_dir, y_ombro_dir
        )

        pontos = (x_orelha, y_orelha, x_ombro_esq, y_ombro_esq, x_ombro_dir, y_ombro_dir)
        return angulo_bruto, razao_pescoco, pontos


def desenhar_pontos(frame, pontos):
    x_orelha, y_orelha, x_ombro_esq, y_ombro_esq, x_ombro_dir, y_ombro_dir = pontos
    cv2.circle(frame, (x_orelha, y_orelha), 6, (255, 0, 0), -1)
    cv2.circle(frame, (x_ombro_esq, y_ombro_esq), 6, (0, 255, 255), -1)
    cv2.circle(frame, (x_ombro_dir, y_ombro_dir), 6, (0, 255, 255), -1)
    cv2.line(frame, (x_orelha, y_orelha), (x_ombro_esq, y_ombro_esq), (255, 255, 255), 2)
    cv2.line(frame, (x_ombro_esq, y_ombro_esq), (x_ombro_dir, y_ombro_dir), (255, 255, 255), 1)


def abrir_camera():
    """Abre a webcam com as otimizações do Pi 3B. Retorna None se não abrir."""
    # OTIMIZAÇÃO 5: backend V4L2 nativo.
    cap = cv2.VideoCapture(INDICE_CAMERA, cv2.CAP_V4L2)
    if not cap.isOpened():
        cap.release()
        return None
    # OTIMIZAÇÃO 6: MJPG (a câmera comprime; sem efeito se não suportar).
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, LARGURA)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, ALTURA)
    # OTIMIZAÇÃO 7: buffer de 1 frame, sempre o mais recente.
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    return cap


# =====================================================================
# LOG EM CSV — um arquivo por dia em logs/
# =====================================================================

class LogCSV:
    CABECALHO = [
        "data_hora", "fonte", "video", "status",
        "angulo", "razao_pescoco", "desvio_angulo", "queda_razao_pct",
        "baseline_angulo", "baseline_razao", "fps",
    ]

    def __init__(self, pasta):
        self.pasta = pasta
        os.makedirs(pasta, exist_ok=True)
        self.data_atual = None
        self.arquivo = None
        self.escritor = None
        self.ultimo_flush = 0.0

    def _garantir_arquivo(self):
        hoje = datetime.now().strftime("%Y-%m-%d")
        if hoje == self.data_atual:
            return
        self.fechar()
        caminho = os.path.join(self.pasta, f"postura_{hoje}.csv")
        novo = not os.path.exists(caminho)
        self.arquivo = open(caminho, "a", newline="", encoding="utf-8")
        self.escritor = csv.writer(self.arquivo)
        if novo:
            self.escritor.writerow(self.CABECALHO)
        self.data_atual = hoje

    def registrar(self, **campos):
        try:
            self._garantir_arquivo()
            linha = []
            for coluna in self.CABECALHO:
                valor = campos.get(coluna, "")
                if isinstance(valor, float):
                    valor = f"{valor:.3f}"
                linha.append("" if valor is None else valor)
            self.escritor.writerow(linha)
            agora = time.time()
            if agora - self.ultimo_flush > 2.0:  # grava no cartão a cada 2s, não a cada frame
                self.arquivo.flush()
                self.ultimo_flush = agora
        except OSError as erro:
            print(f"[LOG] Falha ao gravar CSV: {erro}", flush=True)

    def fechar(self):
        if self.arquivo:
            self.arquivo.flush()
            self.arquivo.close()
        self.arquivo = None
        self.escritor = None
        self.data_atual = None


# =====================================================================
# BASELINE SALVA — só vale dentro do mesmo boot
# =====================================================================

def horario_do_boot():
    """Momento (epoch) em que o Pi ligou, lido do kernel. None se não der pra saber."""
    try:
        with open("/proc/stat", encoding="utf-8") as f:
            for linha in f:
                if linha.startswith("btime"):
                    return float(linha.split()[1])
    except OSError:
        pass
    return None


def salvar_baseline(baseline_angulo, baseline_razao):
    dados = {
        "baseline_angulo": baseline_angulo,
        "baseline_razao": baseline_razao,
        "salvo_em": time.time(),
    }
    temporario = ARQUIVO_BASELINE + ".tmp"
    try:
        with open(temporario, "w", encoding="utf-8") as f:
            json.dump(dados, f, indent=2)
        os.replace(temporario, ARQUIVO_BASELINE)  # troca atômica: nunca fica meio escrito
    except OSError as erro:
        print(f"Aviso: não consegui salvar a baseline: {erro}", flush=True)


def carregar_baseline_do_mesmo_boot():
    """
    Devolve (angulo, razao) se a baseline salva for de DEPOIS do último boot,
    ou seja, o programa só reiniciou (travou, `postura reiniciar`...).
    Se o Pi acabou de ligar, devolve None: o usuário tem que recalibrar.
    """
    boot = horario_do_boot()
    if boot is None or not os.path.isfile(ARQUIVO_BASELINE):
        return None
    try:
        with open(ARQUIVO_BASELINE, encoding="utf-8") as f:
            dados = json.load(f)
        if dados["salvo_em"] > boot:
            return float(dados["baseline_angulo"]), float(dados["baseline_razao"])
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


# =====================================================================
# MONITOR — o "motor" que nunca para
# =====================================================================

TEXTO_AGUARDANDO = "AGUARDANDO CALIBRAÇÃO (digite: postura recalibrar)"


class MonitorPostura:

    def __init__(self, preview=False, video_inicial=None):
        self.detector = DetectorPostura()
        self.log = LogCSV(DIR_LOGS)
        self.comandos = queue.Queue()
        self.lock = threading.Lock()
        self.rodando = True
        self.preview = preview
        self.video_inicial = video_inicial

        # Baseline guardada pra próxima sessão AO VIVO, sem recalibrar.
        # Vem de: reinício no mesmo boot, ou queda/reconexão da câmera.
        self._baseline_guardada = None if video_inicial else carregar_baseline_do_mesmo_boot()
        if self._baseline_guardada:
            print("Reinício no mesmo boot: reaproveitando a última baseline.", flush=True)
        self._recalibrar_pendente = False

        self.estado = {
            "fonte": "-", "video": None, "status": "INICIANDO", "texto": "Iniciando...",
            "desvio_angulo": None, "queda_razao_pct": None,
            "baseline_angulo": None, "baseline_razao": None,
            "fps": 0.0, "atualizado": None,
            "inicio": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            # contadores que o `postura` acompanha pra saber quando terminou
            "calibracao": {"id": 0, "ok": None, "msg": ""},
            "gravacao": {"id": 0, "ok": None, "msg": "", "arquivo": None},
        }
        self._status_impresso = None
        self._texto_impresso = None
        self._ultimo_print = 0.0

    # ---------------- saída ----------------

    def mostrar_status(self, status, texto, forcar=False, **extras):
        """
        ÚNICO ponto de saída do status pro usuário.
        Hoje: imprime no terminal / journal (sem inundar: só quando muda ou a
        cada INTERVALO_PRINT_S). Futuro: desenhar no display OLED aqui
        (ex: status AGUARDANDO_CALIBRACAO → "Aguardando recalibração...").
        """
        agora = time.time()
        with self.lock:
            self.estado.update(extras)
            self.estado["status"] = status
            self.estado["texto"] = texto
            self.estado["atualizado"] = datetime.now().strftime("%H:%M:%S")
            fonte, video = self.estado["fonte"], self.estado["video"]

        imprimir = (
            status != self._status_impresso
            or (forcar and texto != self._texto_impresso)
            or agora - self._ultimo_print >= INTERVALO_PRINT_S
        )
        if imprimir:
            if fonte == "live":
                rotulo = "AO VIVO"
            elif fonte == "video":
                rotulo = f"VIDEO {os.path.basename(video or '')}"
            else:
                rotulo = "-"
            print(f"[{datetime.now():%H:%M:%S}] [{rotulo}] {texto}", flush=True)
            self._status_impresso = status
            self._texto_impresso = texto
            self._ultimo_print = agora

        # >>> DISPLAY OLED: quando estiver pronto, desenhar o status aqui. <<<

    def _mostrar_preview(self, frame, linhas):
        """Janela opcional (--preview). linhas = [(texto, cor_bgr), ...]"""
        if not self.preview:
            return
        y = 40
        for texto, cor in linhas:
            cv2.putText(frame, texto, (20, y), cv2.FONT_HERSHEY_SIMPLEX, 0.7, cor, 2, cv2.LINE_AA)
            y += 35
        cv2.imshow(NOME_JANELA, frame)
        tecla = cv2.waitKey(1) & 0xFF
        if tecla == ord('q'):
            print("Encerrado pela tecla 'q' na janela.", flush=True)
            self.rodando = False
        elif tecla == ord('r'):
            self.comandos.put(("recalibrar", None))

    def _registrar_fim(self, chave, **campos):
        """Marca o fim de uma calibração/gravação (o `postura` espera por isso)."""
        with self.lock:
            anterior = self.estado[chave]
            self.estado[chave] = dict(anterior, id=anterior["id"] + 1, **campos)

    # ---------------- utilidades ----------------

    def _pegar_comando(self):
        try:
            return self.comandos.get_nowait()
        except queue.Empty:
            return None

    def _dormir(self, segundos):
        fim = time.time() + segundos
        # sai antes se chegar um comando, pra reagir na hora
        while self.rodando and time.time() < fim and self.comandos.empty():
            time.sleep(0.1)

    @staticmethod
    def _ler_frame(cap):
        retorno, frame = cap.read()
        if not retorno or frame is None:
            return None
        return cv2.flip(frame, 1)  # espelho, igual ao original

    @staticmethod
    def _caminho_video(arquivo):
        return arquivo if os.path.isabs(arquivo) else os.path.join(DIR_VIDEOS, arquivo)

    # ---------------- laço principal ----------------

    def executar(self):
        threading.Thread(target=self._servidor_comandos, daemon=True).start()
        proxima = ("video", self.video_inicial) if self.video_inicial else ("live", None)
        try:
            while self.rodando:
                proxima = self._sessao(*proxima)
        finally:
            self.log.fechar()
            if self.preview:
                cv2.destroyAllWindows()
            try:
                os.remove(CAMINHO_SOCKET)
            except OSError:
                pass
            print("Serviço de postura encerrado.", flush=True)

    def _sessao(self, tipo, arquivo):
        """Abre uma fonte (câmera ou vídeo), monitora e devolve a próxima fonte."""
        with self.lock:  # fonte nova: descarta medidas da anterior
            self.estado.update(baseline_angulo=None, baseline_razao=None,
                               desvio_angulo=None, queda_razao_pct=None, fps=0.0)
        if tipo == "live":
            resultado = self._esperar_camera()
            if isinstance(resultado, tuple):
                return resultado  # chegou um pedido de vídeo enquanto esperava a câmera
            cap, fps_video = resultado, None
        else:
            self._baseline_guardada = None  # vídeo novo: a baseline ao vivo não vale mais
            cap = cv2.VideoCapture(self._caminho_video(arquivo))
            if not cap.isOpened():
                cap.release()
                print(f"Não consegui abrir o vídeo '{arquivo}'. Voltando pra câmera ao vivo.", flush=True)
                return ("live", None)
            fps_video = cap.get(cv2.CAP_PROP_FPS)
            if not fps_video or fps_video <= 1 or fps_video > 240:
                fps_video = 30.0

        with self.lock:
            self.estado["fonte"] = tipo
            self.estado["video"] = arquivo
        try:
            return self._monitorar(cap, tipo, fps_video)
        finally:
            cap.release()

    def _esperar_camera(self):
        """Tenta abrir a webcam até conseguir. Nunca desiste."""
        tentativa = 0
        while self.rodando:
            comando = self._pegar_comando()
            if comando:
                if comando[0] == "video":
                    return comando
                if comando[0] == "recalibrar":
                    self._recalibrar_pendente = True  # calibra assim que a câmera voltar
            cap = abrir_camera()
            if cap is not None:
                if cap.read()[0]:
                    return cap
                cap.release()
            tentativa += 1
            with self.lock:
                self.estado["fonte"] = "live"
                self.estado["video"] = None
            self.mostrar_status(
                "SEM_CAMERA",
                f"Câmera não encontrada (tentativa {tentativa}). Tentando de novo em {ESPERA_CAMERA_S}s...",
                forcar=True,
            )
            self._dormir(ESPERA_CAMERA_S)
        return ("live", None)

    def _calibrar(self, cap, tipo, fps_video):
        """
        Ao vivo: contagem regressiva de CONTAGEM_CALIBRACAO s + DURACAO_CALIBRACAO s de coleta.
        Vídeo: usa os primeiros DURACAO_CALIBRACAO segundos DO VÍDEO (contados
        em frames, porque o Pi processa mais devagar que o tempo real).
        Retorna ("ok", (b_ang, b_razao)) | ("falhou",) | ("fim",) | ("trocar", comando)
        """
        falhas = 0

        # --- Passo 1: contagem regressiva (só ao vivo) ---
        if tipo == "live":
            fim_contagem = time.time() + CONTAGEM_CALIBRACAO
            while self.rodando:
                restante = fim_contagem - time.time()
                if restante <= 0:
                    break
                comando = self._pegar_comando()
                if comando and comando[0] in ("live", "video"):
                    return ("trocar", comando)
                frame = self._ler_frame(cap)
                if frame is None:
                    falhas += 1
                    if falhas >= MAX_FALHAS_LEITURA:
                        return ("fim",)
                    time.sleep(0.05)
                    continue
                falhas = 0
                segundos = math.ceil(restante)
                self.mostrar_status("CONTAGEM", f"Fique na postura CORRETA. Calibrando em {segundos}s...", forcar=True)
                self._mostrar_preview(frame, [
                    ("Fique na postura CORRETA", (0, 255, 255)),
                    (f"Calibrando em {segundos}s", (0, 255, 255)),
                ])

        # --- Passo 2: coleta de amostras ---
        amostras_angulo, amostras_razao = [], []
        inicio = time.time()
        frames_lidos = 0
        frames_alvo = int(DURACAO_CALIBRACAO * fps_video) if tipo == "video" else None

        while self.rodando:
            if tipo == "live" and time.time() - inicio >= DURACAO_CALIBRACAO:
                break
            if tipo == "video" and frames_lidos >= frames_alvo:
                break

            comando = self._pegar_comando()
            if comando and comando[0] in ("live", "video"):
                return ("trocar", comando)

            frame = self._ler_frame(cap)
            if frame is None:
                if tipo == "video":
                    break  # vídeo acabou durante a calibração: usa o que tiver
                falhas += 1
                if falhas >= MAX_FALHAS_LEITURA:
                    return ("fim",)
                time.sleep(0.05)
                continue
            falhas = 0
            frames_lidos += 1

            angulo_bruto, razao_pescoco, pontos = self.detector.detectar_metricas_postura(frame, LIMIAR_CONFIANCA)
            if angulo_bruto is not None and razao_pescoco is not None:
                amostras_angulo.append(angulo_bruto)
                amostras_razao.append(razao_pescoco)
                if self.preview:
                    desenhar_pontos(frame, pontos)

            if tipo == "live":
                restante = max(0.0, DURACAO_CALIBRACAO - (time.time() - inicio))
            else:
                restante = max(0.0, (frames_alvo - frames_lidos) / fps_video)
            self.mostrar_status(
                "CALIBRANDO",
                f"Calibrando... fique parado ({math.ceil(restante)}s)",
                forcar=True,
            )
            self._mostrar_preview(frame, [(f"Calibrando... {restante:0.1f}s", (0, 255, 0))])

        if not self.rodando:
            return ("fim",)

        if len(amostras_angulo) < 5:
            msg = "Calibração falhou (poucas detecções válidas). Confira se você aparece na câmera."
            self.mostrar_status("CALIBRACAO_FALHOU", msg, forcar=True)
            self._registrar_fim("calibracao", ok=False, msg=msg)
            return ("falhou",)

        baseline_angulo = sum(amostras_angulo) / len(amostras_angulo)
        baseline_razao = sum(amostras_razao) / len(amostras_razao)

        if tipo == "live":
            salvar_baseline(baseline_angulo, baseline_razao)

        msg = f"Baseline calibrada: ângulo={baseline_angulo:.1f}°  razão_pescoço={baseline_razao:.3f}"
        with self.lock:
            fonte, video = self.estado["fonte"], self.estado["video"]
        self.mostrar_status(
            "CALIBRADO", msg, forcar=True,
            baseline_angulo=round(baseline_angulo, 2),
            baseline_razao=round(baseline_razao, 4),
        )
        self._registrar_fim("calibracao", ok=True, msg=msg)
        self.log.registrar(
            data_hora=datetime.now().isoformat(timespec="milliseconds"),
            fonte=fonte, video=video or "", status="CALIBRADO",
            baseline_angulo=baseline_angulo, baseline_razao=baseline_razao,
        )
        return ("ok", (baseline_angulo, baseline_razao))

    def _gravar(self, cap, segundos):
        """
        Grava um vídeo de teste da webcam em videos/. Durante a gravação a
        análise de postura fica pausada (sobra CPU pro Pi gravar liso).
        Grava a imagem crua (sem espelhar): quando o vídeo for analisado, ele
        é espelhado igual à câmera ao vivo.
        """
        nome_base = datetime.now().strftime("gravacao_%Y%m%d_%H%M%S")

        # --- contagem: dá tempo de se ajeitar E mede o FPS real da câmera ---
        inicio_contagem = time.time()
        fim_contagem = inicio_contagem + CONTAGEM_GRAVACAO
        frames_contagem, ultimo_frame = 0, None
        while self.rodando and time.time() < fim_contagem:
            retorno, frame = cap.read()
            if retorno and frame is not None:
                frames_contagem += 1
                ultimo_frame = frame
                if self.preview:
                    self._mostrar_preview(cv2.flip(frame, 1), [("Gravacao comeca em breve", (0, 255, 255))])
            segundos_contagem = math.ceil(fim_contagem - time.time())
            self.mostrar_status(
                "GRAVACAO_CONTAGEM",
                f"Gravação começa em {max(segundos_contagem, 1)}s. "
                f"Fique na postura CORRETA nos primeiros {DURACAO_CALIBRACAO}s!",
                forcar=True,
            )

        if not self.rodando:
            return
        if ultimo_frame is None:
            msg = "Gravação falhou: a câmera não entregou imagem."
            self.mostrar_status("GRAVACAO_FALHOU", msg, forcar=True)
            self._registrar_fim("gravacao", ok=False, msg=msg, arquivo=None)
            return

        # FPS medido de verdade, pra o vídeo não sair acelerado nem em câmera lenta
        fps = frames_contagem / max(time.time() - inicio_contagem, 1e-6)
        fps = min(max(fps, 5.0), 60.0)
        altura, largura = ultimo_frame.shape[:2]

        nome = nome_base + ".mp4"
        caminho = os.path.join(DIR_VIDEOS, nome)
        escritor = cv2.VideoWriter(caminho, cv2.VideoWriter_fourcc(*"mp4v"), fps, (largura, altura))
        if not escritor.isOpened():  # sem codec mp4 nesse OpenCV: cai pro AVI/MJPG
            escritor.release()
            nome = nome_base + ".avi"
            caminho = os.path.join(DIR_VIDEOS, nome)
            escritor = cv2.VideoWriter(caminho, cv2.VideoWriter_fourcc(*"MJPG"), fps, (largura, altura))

        # --- gravação ---
        inicio = time.time()
        frames = 0
        while self.rodando and time.time() - inicio < segundos:
            retorno, frame = cap.read()
            if not retorno or frame is None:
                time.sleep(0.02)
                continue
            escritor.write(frame)
            frames += 1
            restante = math.ceil(segundos - (time.time() - inicio))
            self.mostrar_status("GRAVANDO", f"Gravando... {max(restante, 0)}s", forcar=True)
            if self.preview:
                self._mostrar_preview(cv2.flip(frame, 1), [(f"REC {max(restante, 0)}s", (0, 0, 255))])
        escritor.release()

        if frames == 0:
            try:
                os.remove(caminho)
            except OSError:
                pass
            msg = "Gravação falhou: nenhum frame gravado."
            self.mostrar_status("GRAVACAO_FALHOU", msg, forcar=True)
            self._registrar_fim("gravacao", ok=False, msg=msg, arquivo=None)
            return

        msg = f"Vídeo salvo: videos/{nome} ({frames} frames, {fps:.0f} fps)"
        self.mostrar_status("GRAVACAO_OK", msg, forcar=True)
        self._registrar_fim("gravacao", ok=True, msg=msg, arquivo=nome)

    def _monitorar(self, cap, tipo, fps_video):
        """
        Laço de uma sessão. Estados:
          - sem baseline e sem pedido de calibrar → AGUARDANDO (não analisa nada)
          - calibrando
          - com baseline → monitorando a postura
        Devolve a próxima fonte quando chega um comando de troca ou a fonte acaba.
        """
        baseline = None
        if tipo == "live" and self._baseline_guardada:
            baseline = self._baseline_guardada
            with self.lock:
                self.estado["baseline_angulo"] = round(baseline[0], 2)
                self.estado["baseline_razao"] = round(baseline[1], 4)
        self._baseline_guardada = None

        # vídeo calibra sozinho (com os primeiros segundos dele); ao vivo, só sob pedido
        precisa_calibrar = (tipo == "video") or self._recalibrar_pendente
        self._recalibrar_pendente = False

        contador_ma_postura = 0
        historico_angulos = deque(maxlen=HISTORICO_TAMANHO)
        historico_razoes = deque(maxlen=HISTORICO_TAMANHO)
        falhas = 0
        fps = 0.0
        ultimo_frame_t = None

        while self.rodando:
            # --- calibração pedida ---
            if precisa_calibrar:
                precisa_calibrar = False
                resultado = self._calibrar(cap, tipo, fps_video)
                if resultado[0] == "trocar":
                    return resultado[1]
                if resultado[0] == "fim":
                    return ("live", None)
                if resultado[0] == "falhou":
                    if tipo == "video":
                        return ("live", None)
                    baseline = None  # ao vivo: volta a aguardar outro `postura recalibrar`
                    continue
                baseline = resultado[1]
                contador_ma_postura = 0
                historico_angulos.clear()
                historico_razoes.clear()
                ultimo_frame_t = None
                continue

            # --- comandos vindos do `postura` ---
            comando = self._pegar_comando()
            if comando:
                if comando[0] == "recalibrar":
                    precisa_calibrar = True
                    continue
                if comando[0] == "gravar":
                    self._gravar(cap, comando[1])
                    ultimo_frame_t = None
                    continue
                return comando  # ("live", None) ou ("video", arquivo): a próxima sessão aguarda

            # --- AGUARDANDO: câmera ligada, mas sem analisar nada ---
            if baseline is None:
                frame = self._ler_frame(cap)
                if frame is None:
                    falhas += 1
                    if falhas >= MAX_FALHAS_LEITURA:
                        print("Câmera parou de responder. Reabrindo...", flush=True)
                        return ("live", None)
                    time.sleep(0.05)
                    continue
                falhas = 0
                self.mostrar_status("AGUARDANDO_CALIBRACAO", TEXTO_AGUARDANDO)
                self._mostrar_preview(frame, [("Aguardando calibracao", (255, 255, 255)),
                                              ("postura recalibrar  /  tecla r", (255, 255, 255))])
                time.sleep(0.1)  # sem inferência aqui: alivia a CPU enquanto espera
                continue

            baseline_angulo, baseline_razao = baseline

            frame = self._ler_frame(cap)
            if frame is None:
                if tipo == "video":
                    print("Vídeo terminou. Voltando pra câmera ao vivo.", flush=True)
                    return ("live", None)
                falhas += 1
                if falhas >= MAX_FALHAS_LEITURA:
                    print("Câmera parou de responder. Reabrindo (mantendo a baseline)...", flush=True)
                    self._baseline_guardada = baseline  # mesma câmera, mesma pessoa
                    return ("live", None)
                time.sleep(0.05)
                continue
            falhas = 0

            # FPS (média exponencial, só informativo)
            agora = time.time()
            if ultimo_frame_t is not None and agora > ultimo_frame_t:
                fps_inst = 1.0 / (agora - ultimo_frame_t)
                fps = fps_inst if fps == 0 else 0.9 * fps + 0.1 * fps_inst
            ultimo_frame_t = agora

            angulo_bruto, razao_pescoco, pontos = self.detector.detectar_metricas_postura(frame, LIMIAR_CONFIANCA)

            status = "SEM_USUARIO"
            status_texto = "Procurando usuario..."
            cor_alerta = (255, 255, 255)
            angulo = razao = desvio_angulo = queda_razao = None

            if angulo_bruto is not None and razao_pescoco is not None:
                if self.preview:
                    desenhar_pontos(frame, pontos)

                # Suavização temporal (média móvel)
                historico_angulos.append(angulo_bruto)
                historico_razoes.append(razao_pescoco)
                angulo = sum(historico_angulos) / len(historico_angulos)
                razao = sum(historico_razoes) / len(historico_razoes)

                # Componente lateral: desvio do ângulo em relação à baseline
                desvio_angulo = abs(angulo - baseline_angulo)

                # Componente de "queda de cabeça" (só interessa quando DIMINUI)
                queda_razao = (baseline_razao - razao) / baseline_razao

                postura_ruim = desvio_angulo > LIMIAR_DESVIO_ANGULO or queda_razao > LIMIAR_QUEDA_RAZAO
                medidas = f"(ang {int(desvio_angulo)}° / queda {queda_razao * 100:.0f}%)"

                if postura_ruim:
                    contador_ma_postura += 1
                    if contador_ma_postura > FRAMES_PARA_ALERTA:
                        status, status_texto, cor_alerta = "ALERTA", f"ALERTA: POSTURA INCORRETA {medidas}", (0, 0, 255)
                    else:
                        status, status_texto, cor_alerta = "ATENCAO", f"ATENCAO... {medidas}", (0, 255, 255)
                else:
                    contador_ma_postura = max(0, contador_ma_postura - 1)
                    status, status_texto, cor_alerta = "CORRETA", f"POSTURA CORRETA {medidas}", (0, 255, 0)
            else:
                # Sem detecção confiável: zera os históricos
                historico_angulos.clear()
                historico_razoes.clear()

            queda_pct = queda_razao * 100 if queda_razao is not None else None
            self.mostrar_status(
                status, f"{status_texto} | {fps:.1f} fps",
                desvio_angulo=round(desvio_angulo, 1) if desvio_angulo is not None else None,
                queda_razao_pct=round(queda_pct, 1) if queda_pct is not None else None,
                fps=round(fps, 1),
            )

            with self.lock:
                fonte, video = self.estado["fonte"], self.estado["video"]
            self.log.registrar(
                data_hora=datetime.now().isoformat(timespec="milliseconds"),
                fonte=fonte, video=video or "", status=status,
                angulo=angulo, razao_pescoco=razao,
                desvio_angulo=desvio_angulo, queda_razao_pct=queda_pct,
                baseline_angulo=baseline_angulo, baseline_razao=baseline_razao,
                fps=fps,
            )

            self._mostrar_preview(frame, [(status_texto, cor_alerta)])

        return ("live", None)

    # ---------------- comandos (socket) ----------------

    def _servidor_comandos(self):
        try:
            os.remove(CAMINHO_SOCKET)
        except OSError:
            pass
        servidor = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        servidor.bind(CAMINHO_SOCKET)
        os.chmod(CAMINHO_SOCKET, 0o600)  # só o próprio usuário manda comandos
        servidor.listen(4)
        servidor.settimeout(1.0)

        while self.rodando:
            try:
                conexao, _ = servidor.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            with conexao:
                try:
                    conexao.settimeout(2.0)
                    dados = b""
                    while not dados.endswith(b"\n") and len(dados) < 4096:
                        pedaco = conexao.recv(1024)
                        if not pedaco:
                            break
                        dados += pedaco
                    pedido = json.loads(dados.decode("utf-8") or "{}")
                    resposta = self._tratar_comando(pedido)
                except (OSError, ValueError) as erro:
                    resposta = {"ok": False, "erro": f"pedido inválido: {erro}"}
                try:
                    conexao.sendall((json.dumps(resposta, ensure_ascii=False) + "\n").encode("utf-8"))
                except OSError:
                    pass
        servidor.close()

    def _tratar_comando(self, pedido):
        acao = pedido.get("acao")
        with self.lock:
            status_atual = self.estado["status"]
            fonte_atual = self.estado["fonte"]
        ocupado = status_atual in ("CONTAGEM", "CALIBRANDO", "GRAVACAO_CONTAGEM", "GRAVANDO")

        if acao == "status":
            with self.lock:
                return {"ok": True, "estado": json.loads(json.dumps(self.estado))}
        if acao == "live":
            self.comandos.put(("live", None))
            return {"ok": True, "msg": "Voltando pra câmera ao vivo. Depois rode: postura recalibrar"}
        if acao == "recalibrar":
            if ocupado:
                return {"ok": False, "erro": "Já tem uma calibração ou gravação em andamento. Espera terminar."}
            self.comandos.put(("recalibrar", None))
            if fonte_atual == "video":
                return {"ok": True, "msg": f"Recalibrando com os próximos {DURACAO_CALIBRACAO}s do vídeo."}
            return {"ok": True, "msg": f"Se ajeita! Contagem de {CONTAGEM_CALIBRACAO}s e depois {DURACAO_CALIBRACAO}s parado."}
        if acao == "video":
            nome = os.path.basename(str(pedido.get("arquivo", "")))
            if nome not in listar_videos():
                return {"ok": False, "erro": f"Vídeo '{nome}' não encontrado na pasta videos/."}
            self.comandos.put(("video", nome))
            return {"ok": True, "msg": f"Trocando pro vídeo '{nome}' (calibra com os primeiros {DURACAO_CALIBRACAO}s dele)."}
        if acao == "gravar":
            try:
                segundos = int(pedido.get("segundos"))
            except (TypeError, ValueError):
                return {"ok": False, "erro": "Informe a duração em segundos. Ex: postura gravar 30"}
            if not DURACAO_CALIBRACAO < segundos <= GRAVACAO_MAX_S:
                return {"ok": False, "erro": f"A duração tem que ser maior que {DURACAO_CALIBRACAO}s "
                                             f"(os primeiros {DURACAO_CALIBRACAO}s são a calibração) "
                                             f"e no máximo {GRAVACAO_MAX_S}s."}
            if fonte_atual != "live" or status_atual == "SEM_CAMERA":
                return {"ok": False, "erro": "Só dá pra gravar com a câmera ao vivo funcionando (use: postura live)."}
            if ocupado:
                return {"ok": False, "erro": "Já tem uma calibração ou gravação em andamento. Espera terminar."}
            self.comandos.put(("gravar", segundos))
            return {"ok": True, "msg": f"Gravação de {segundos}s: contagem de {CONTAGEM_GRAVACAO}s pra se ajeitar."}
        return {"ok": False, "erro": f"comando desconhecido: {acao}"}


# =====================================================================

def outra_instancia_rodando():
    if not os.path.exists(CAMINHO_SOCKET):
        return False
    teste = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    teste.settimeout(1.0)
    try:
        teste.connect(CAMINHO_SOCKET)
        return True
    except OSError:
        return False  # socket velho de uma execução que caiu
    finally:
        teste.close()


def main():
    parser = argparse.ArgumentParser(description="Monitoramento de postura (TCC) - headless")
    parser.add_argument("--preview", action="store_true",
                        help="mostra a janela com o vídeo (precisa de tela ou ssh -X)")
    parser.add_argument("--video", metavar="ARQUIVO",
                        help="começa por um vídeo (nome em videos/ ou caminho) em vez da câmera")
    args = parser.parse_args()

    if outra_instancia_rodando():
        sys.exit("O monitor de postura já está rodando (provavelmente o serviço).\n"
                 "Pra rodar manual, pare ele antes com:  postura parar")

    video_inicial = None
    if args.video:
        if os.path.isfile(args.video):
            video_inicial = os.path.abspath(args.video)
        elif os.path.isfile(os.path.join(DIR_VIDEOS, args.video)):
            video_inicial = args.video
        else:
            sys.exit(f"Vídeo não encontrado: {args.video}")

    preview = args.preview
    if preview and not os.environ.get("DISPLAY"):
        print("Aviso: --preview pedido, mas não há tela (DISPLAY vazio). Entre com `ssh -X`. "
              "Seguindo sem janela.", flush=True)
        preview = False

    os.makedirs(DIR_VIDEOS, exist_ok=True)
    print("\n=== MONITORAMENTO DE POSTURA (HEADLESS) ===", flush=True)
    print(f"Logs em: {DIR_LOGS}", flush=True)
    if preview:
        print("Janela: 'q' encerra, 'r' recalibra.", flush=True)

    monitor = MonitorPostura(preview=preview, video_inicial=video_inicial)

    def parar(_sinal, _quadro):
        monitor.rodando = False

    signal.signal(signal.SIGTERM, parar)  # systemctl stop
    signal.signal(signal.SIGINT, parar)   # Ctrl+C

    monitor.executar()


if __name__ == "__main__":
    main()
