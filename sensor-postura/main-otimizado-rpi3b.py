import os
import cv2
import numpy as np
import math
import time
from collections import deque

try:
    import tflite_runtime.interpreter as tflite
except ImportError:
    from tensorflow.lite.python import interpreter as tflite

# =====================================================================
# OTIMIZAÇÕES PARA RASPBERRY PI 3B (Cortex-A53 quad-core @ 1.2GHz, 1GB RAM)
# Nenhuma mudança nesta seção altera os cálculos de postura (ângulo,
# razão pescoço/ombros) nem a lógica de decisão do sistema — apenas
# reduz o custo de CPU por frame. Comentários "OTIMIZAÇÃO N" marcam
# cada mudança em relação ao script original.
# =====================================================================

# OTIMIZAÇÃO 1: o OpenCV, por padrão, cria seu próprio pool de threads
# para operações como resize/cvtColor. Em um Pi 3B (só 4 núcleos), isso
# compete com as threads do TFLite abaixo e gera overhead de
# criação/destruição de threads a cada frame. Como as operações do
# OpenCV aqui são leves comparadas à inferência, é mais eficiente
# deixar o OpenCV rodar em 1 thread e reservar os núcleos para o
# TFLite.
cv2.setNumThreads(1)

# Carrega o modelo MoveNet
# OTIMIZAÇÃO 2: por padrão o interpretador do TFLite roda em 1 thread.
# Isso é, de longe, a maior fonte de lentidão/travamento em um Pi 3B,
# já que a inferência fica presa a um único núcleo (1.2GHz). Usamos
# NUM_THREADS_TFLITE núcleos para a inferência e deixamos 1 núcleo
# livre para captura de câmera + exibição (cv2.imshow), evitando que a
# thread principal trave/engasgue enquanto o modelo roda.
NUM_THREADS_TFLITE = max(1, (os.cpu_count() or 4) - 1)  # 3 núcleos em um Pi 3B (4 núcleos)

interpretador = tflite.Interpreter(
    model_path="movenet_lightning.tflite",
    num_threads=NUM_THREADS_TFLITE,
)
interpretador.allocate_tensors()
detalhes_entrada = interpretador.get_input_details()
detalhes_saida = interpretador.get_output_details()
DTYPE_ESPERADO = detalhes_entrada[0]['dtype']
TAMANHO_ENTRADA = detalhes_entrada[0]['shape'][1]  # normalmente 192 para o Lightning

# Índices das articulações no MoveNet (COCO format)
ORELHA_ESQ = 3
OMBRO_ESQ, OMBRO_DIR = 5, 6


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

    # OTIMIZAÇÃO 3: INTER_LINEAR (padrão do cv2.resize) é mantido — trocar
    # por INTER_NEAREST economizaria um pouco de CPU, mas pode degradar a
    # qualidade dos keypoints detectados, o que afetaria o cálculo. Como o
    # pedido foi não prejudicar os cálculos, a interpolação original foi
    # preservada.
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


def detectar_metricas_postura(frame, limiar_confianca):
    """
    Roda a inferência do MoveNet em um frame e retorna:
    - angulo_bruto (float) ou None
    - razao_pescoco (float) ou None
    - pontos (x_orelha, y_orelha, x_ombro_esq, y_ombro_esq, x_ombro_dir, y_ombro_dir) ou None
    Requer orelha esquerda + os DOIS ombros com confiança suficiente
    (o ombro direito agora é necessário como referência de escala).
    """
    entrada_img, escala, offset_x, offset_y = preprocessar_letterbox(frame, TAMANHO_ENTRADA)

    # OTIMIZAÇÃO 4: np.expand_dims + .astype(dtype) sempre alocava um novo
    # array e SEMPRE copiava os dados, mesmo quando entrada_img já estava
    # no dtype esperado pelo modelo (comum em modelos quantizados uint8).
    # Trocamos para indexação com newaxis (equivalente, sem cópia extra) e
    # passamos copy=False no astype, para só copiar quando o dtype
    # realmente muda. O valor numérico produzido é idêntico ao original.
    entrada_tensor = entrada_img[np.newaxis, ...].astype(DTYPE_ESPERADO, copy=False)
    interpretador.set_tensor(detalhes_entrada[0]['index'], entrada_tensor)

    interpretador.invoke()
    keypoints = interpretador.get_tensor(detalhes_saida[0]['index'])[0][0]

    orelha_y, orelha_x, conf_orelha = keypoints[ORELHA_ESQ]
    ombro_esq_y, ombro_esq_x, conf_ombro_esq = keypoints[OMBRO_ESQ]
    ombro_dir_y, ombro_dir_x, conf_ombro_dir = keypoints[OMBRO_DIR]

    if (conf_orelha <= limiar_confianca or conf_ombro_esq <= limiar_confianca
            or conf_ombro_dir <= limiar_confianca):
        return None, None, None

    x_orelha, y_orelha = desnormalizar_keypoint(
        orelha_x, orelha_y, TAMANHO_ENTRADA, escala, offset_x, offset_y
    )
    x_ombro_esq, y_ombro_esq = desnormalizar_keypoint(
        ombro_esq_x, ombro_esq_y, TAMANHO_ENTRADA, escala, offset_x, offset_y
    )
    x_ombro_dir, y_ombro_dir = desnormalizar_keypoint(
        ombro_dir_x, ombro_dir_y, TAMANHO_ENTRADA, escala, offset_x, offset_y
    )

    angulo_bruto = calcular_angulo_vertical(x_orelha, y_orelha, x_ombro_esq, y_ombro_esq)
    razao_pescoco = calcular_razao_pescoco(
        x_orelha, y_orelha, x_ombro_esq, y_ombro_esq, x_ombro_dir, y_ombro_dir
    )

    pontos = (x_orelha, y_orelha, x_ombro_esq, y_ombro_esq, x_ombro_dir, y_ombro_dir)
    return angulo_bruto, razao_pescoco, pontos


def calibrar_postura(captura, duracao_segundos=5):
    """
    Tela de calibração: o usuário fica na postura correta e pressiona ENTER
    para começar a coleta. Durante 'duracao_segundos', os ângulos detectados
    são registrados e a média vira o ângulo de referência (baseline) da
    postura correta desse usuário/câmera/dia.
    """
    # --- Passo 1: aguarda o ENTER com o usuário já na postura correta ---
    while True:
        retorno, frame = captura.read()
        if not retorno or frame is None:
            continue
        frame = cv2.flip(frame, 1)

        cv2.putText(frame, "Fique na postura CORRETA", (20, 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2, cv2.LINE_AA)
        cv2.putText(frame, "Pressione ENTER para calibrar (5s)", (20, 75),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2, cv2.LINE_AA)
        cv2.imshow("Monitoramento de Postura - TCC", frame)

        tecla = cv2.waitKey(1) & 0xFF
        if tecla == 13:  # ENTER
            break
        if tecla == ord('q'):
            return None, None

    # --- Passo 2: coleta amostras por 'duracao_segundos' ---
    amostras_angulo = []
    amostras_razao = []
    inicio = time.time()
    while time.time() - inicio < duracao_segundos:
        retorno, frame = captura.read()
        if not retorno or frame is None:
            continue
        frame = cv2.flip(frame, 1)

        angulo_bruto, razao_pescoco, pontos = detectar_metricas_postura(frame, LIMIAR_CONFIANCA)
        segundos_restantes = duracao_segundos - (time.time() - inicio)

        if angulo_bruto is not None and razao_pescoco is not None:
            amostras_angulo.append(angulo_bruto)
            amostras_razao.append(razao_pescoco)
            x_orelha, y_orelha, x_ombro_esq, y_ombro_esq, x_ombro_dir, y_ombro_dir = pontos
            cv2.circle(frame, (x_orelha, y_orelha), 6, (255, 0, 0), -1)
            cv2.circle(frame, (x_ombro_esq, y_ombro_esq), 6, (0, 255, 255), -1)
            cv2.circle(frame, (x_ombro_dir, y_ombro_dir), 6, (0, 255, 255), -1)
            cv2.line(frame, (x_orelha, y_orelha), (x_ombro_esq, y_ombro_esq), (255, 255, 255), 2)
            cv2.line(frame, (x_ombro_esq, y_ombro_esq), (x_ombro_dir, y_ombro_dir), (255, 255, 255), 1)

        cv2.putText(frame, f"Calibrando... {segundos_restantes:0.1f}s", (20, 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2, cv2.LINE_AA)
        cv2.imshow("Monitoramento de Postura - TCC", frame)
        cv2.waitKey(1)

    if len(amostras_angulo) < 5:
        # Poucas amostras válidas (ex: usuário fora do quadro) -> não dá pra confiar na calibração
        return None, None

    baseline_angulo = sum(amostras_angulo) / len(amostras_angulo)
    baseline_razao = sum(amostras_razao) / len(amostras_razao)
    return baseline_angulo, baseline_razao


# Conecta na Câmera
LARGURA, ALTURA = 640, 480

# OTIMIZAÇÃO 5: forçamos o backend V4L2 explicitamente. No Linux/Raspberry
# Pi, o OpenCV às vezes cai em um backend genérico (ex: GStreamer) mais
# pesado; V4L2 é o caminho nativo e mais leve para webcams USB no Pi.
captura = cv2.VideoCapture(0, cv2.CAP_V4L2)

# OTIMIZAÇÃO 6: solicita captura em MJPG. Muitas webcams USB, por padrão,
# transmitem em YUYV bruto, que é muito mais pesado de transportar via USB
# e de converter na CPU. Em MJPG, a própria câmera já comprime o frame, e a
# decodificação de MJPG é mais rápida que processar o YUYV bruto na CPU
# fraca do Pi 3B. Se a câmera não suportar, esta chamada simplesmente não
# tem efeito (não quebra o restante do código).
captura.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))

captura.set(cv2.CAP_PROP_FRAME_WIDTH, LARGURA)
captura.set(cv2.CAP_PROP_FRAME_HEIGHT, ALTURA)

# OTIMIZAÇÃO 7: reduz o buffer interno de frames para 1. Sem isso, se o
# processamento (inferência) for mais lento que a captura, a fila de
# frames pendentes cresce e o vídeo exibido passa a mostrar frames
# "atrasados" (lag crescente) em vez de travar a taxa de captura no ritmo
# do processamento. Com buffer=1, sempre pegamos o frame mais recente.
captura.set(cv2.CAP_PROP_BUFFERSIZE, 1)

print("\n=== SISTEMA DE MONITORAMENTO DE POSTURA (OTIMIZADO) ===")
print("Pressione a tecla 'q' na janela da imagem para encerrar.\n")

LIMIAR_CONFIANCA = 0.4          # Confiança mínima dos keypoints para considerar válidos
LIMIAR_DESVIO_ANGULO = 12.0     # Graus de desvio lateral tolerados em relação à baseline
LIMIAR_QUEDA_RAZAO = 0.12       # Queda tolerada na razão pescoço/ombros (fração, ex: 0.12 = 12%)
DURACAO_CALIBRACAO = 5          # segundos

# --- Calibração: usuário fica na postura correta e define as baselines ---
baseline_angulo, baseline_razao = None, None
while baseline_angulo is None or baseline_razao is None:
    baseline_angulo, baseline_razao = calibrar_postura(captura, DURACAO_CALIBRACAO)
    if baseline_angulo is None or baseline_razao is None:
        print("Calibração falhou (poucas detecções válidas). Tentando novamente...")
        retorno, frame_teste = captura.read()
        if not retorno:
            captura.release()
            cv2.destroyAllWindows()
            raise SystemExit("Não foi possível acessar a câmera para recalibrar.")

print(f"Baseline calibrada: angulo={baseline_angulo:.1f}°  razao_pescoco={baseline_razao:.3f}")

contador_ma_postura = 0

# Suavização temporal: média móvel dos últimos N valores, reduz o "tremor" da leitura
HISTORICO_TAMANHO = 5
historico_angulos = deque(maxlen=HISTORICO_TAMANHO)
historico_razoes = deque(maxlen=HISTORICO_TAMANHO)

while True:
    retorno, frame = captura.read()
    if not retorno or frame is None:
        continue

    # Espelha o frame para efeito de espelho
    frame = cv2.flip(frame, 1)

    angulo_bruto, razao_pescoco, pontos = detectar_metricas_postura(frame, LIMIAR_CONFIANCA)

    status_texto = "Procurando usuario..."
    cor_alerta = (255, 255, 255)

    if angulo_bruto is not None and razao_pescoco is not None:
        x_orelha, y_orelha, x_ombro_esq, y_ombro_esq, x_ombro_dir, y_ombro_dir = pontos

        # Desenha os pontos e as linhas de referência no corpo
        cv2.circle(frame, (x_orelha, y_orelha), 6, (255, 0, 0), -1)
        cv2.circle(frame, (x_ombro_esq, y_ombro_esq), 6, (0, 255, 255), -1)
        cv2.circle(frame, (x_ombro_dir, y_ombro_dir), 6, (0, 255, 255), -1)
        cv2.line(frame, (x_orelha, y_orelha), (x_ombro_esq, y_ombro_esq), (255, 255, 255), 2)
        cv2.line(frame, (x_ombro_esq, y_ombro_esq), (x_ombro_dir, y_ombro_dir), (255, 255, 255), 1)

        # Suavização temporal (média móvel)
        historico_angulos.append(angulo_bruto)
        historico_razoes.append(razao_pescoco)
        angulo = sum(historico_angulos) / len(historico_angulos)
        razao = sum(historico_razoes) / len(historico_razoes)

        # Componente lateral: desvio do ângulo em relação à baseline
        desvio_angulo = abs(angulo - baseline_angulo)

        # Componente de "queda de cabeça": quanto a razão pescoço/ombros
        # encolheu em relação à baseline (só interessa quando DIMINUI)
        queda_razao = (baseline_razao - razao) / baseline_razao

        postura_ruim = desvio_angulo > LIMIAR_DESVIO_ANGULO or queda_razao > LIMIAR_QUEDA_RAZAO

        if postura_ruim:
            contador_ma_postura += 1
            if contador_ma_postura > 15:  # ~ meio segundo a 30fps
                status_texto = f"ALERTA: POSTURA INCORRETA (ang {int(desvio_angulo)}° / queda {queda_razao*100:.0f}%)"
                cor_alerta = (0, 0, 255)  # Vermelho
            else:
                status_texto = f"ATENCAO... (ang {int(desvio_angulo)}° / queda {queda_razao*100:.0f}%)"
                cor_alerta = (0, 255, 255)  # Amarelo
        else:
            contador_ma_postura = max(0, contador_ma_postura - 1)
            status_texto = f"POSTURA CORRETA (ang {int(desvio_angulo)}° / queda {queda_razao*100:.0f}%)"
            cor_alerta = (0, 255, 0)  # Verde
    else:
        # Sem detecção confiável: zera os históricos para não misturar leituras antigas
        historico_angulos.clear()
        historico_razoes.clear()

    # Exibe o status na tela
    cv2.putText(frame, status_texto, (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.8, cor_alerta, 2, cv2.LINE_AA)

    cv2.imshow("Monitoramento de Postura - TCC", frame)

    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

captura.release()
cv2.destroyAllWindows()