import cv2
import numpy as np
import math
import tflite_runtime.interpreter as tflite

# 1. Carregar Modelo
interpretador = tflite.Interpreter(model_path="movenet_lightning.tflite")
interpretador.allocate_tensors()
detalhes_entrada = interpretador.get_input_details()
detalhes_saida = interpretador.get_output_details()

# Índices das articulações no MoveNet / COCO
# 3: Orelha Esquerda | 5: Ombro Esquerdo
ORELHA_ESQ, OMBRO_ESQ = 3, 5

def calcular_angulo_vertical(p_orelha, p_ombro):
    """Calcula o ângulo em graus entre a linha da orelha-ombro e a linha vertical"""
    dx = p_orelha[0] - p_ombro[0]
    dy = p_orelha[1] - p_ombro[1]
    # atan2 calcula o ângulo em radianos, convertemos para graus
    angulo_rad = math.atan2(abs(dx), abs(dy))
    return math.degrees(angulo_rad)

# Conecta na Câmera
captura = cv2.VideoCapture(0)
captura.set(cv2.CAP_PROP_FRAME_WIDTH, 320)
captura.set(cv2.CAP_PROP_FRAME_HEIGHT, 240)

print("\n=== SISTEMA DE MONITORAMENTO DE POSTURA INICIADO ===")
print("Pressione Ctrl+C no terminal para encerrar.\n")

try:
    while True:
        retorno, frame = captura.read()
        if not retorno or frame is None:
            continue

        # Pré-processamento
        frame_192 = cv2.resize(frame, (192, 192))
        dados_entrada = np.expand_dims(frame_192, axis=0).astype(np.float32)

        # Inferência
        interpretador.set_tensor(detalhes_entrada[0]['index'], dados_entrada)
        interpretador.invoke()
        keypoints = interpretador.get_tensor(detalhes_saida[0]['index'])[0][0]

        # Extrai coordenadas da Orelha e Ombro (normalizadas 0.0 a 1.0)
        orelha_y, orelha_x, conf_orelha = keypoints[ORELHA_ESQ]
        ombro_y, ombro_x, conf_ombro = keypoints[OMBRO_ESQ]

        # Só calcula se a confiança da IA for maior que 20%
        if conf_orelha > 0.2 and conf_ombro > 0.2:
            # Converte porcentagem para pixels (320x240)
            p_orelha = (int(orelha_x * 320), int(orelha_y * 240))
            p_ombro = (int(ombro_x * 320), int(ombro_y * 240))

            # Calcula a inclinação da cabeça em relação ao ombro
            angulo = calcular_angulo_vertical(p_orelha, p_ombro)

            # Define o limiar de má postura
            if angulo > 25.0:
                print(f"🚨 [ALERTA] MÁ POSTURA DETECTADA! Ângulo: {int(angulo)}° (Inclinado para frente)")
            else:
                print(f"✅ [OK] Postura Correta. Ângulo: {int(angulo)}°")

except KeyboardInterrupt:
    print("\nEncerrando sistema...")

captura.release()
