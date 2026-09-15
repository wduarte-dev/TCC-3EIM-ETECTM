import cv2
import numpy as np
import math

# importa o tflite-runtime (para sistemas mais modestos / arm ou o tensorflow para windows etc)
try:
    import tflite_runtime.interpreter as tflite
except ImportError:
    from tensorflow.lite.python import interpreter as tflite

# carrega o modelo de detecção de pontos
interpretador = tflite.Interpreter(model_path="movenet_lightning.tflite")
interpretador.allocate_tensors()
detalhes_entrada = interpretador.get_input_details()
detalhes_saida = interpretador.get_output_details()

# Índices das articulações no MoveNet / COCO
ORELHA_ESQ, OMBRO_ESQ = 3, 5

def calcular_angulo_vertical(x1, y1, x2, y2):
    """Calcula o ângulo em graus entre a linha orelha-ombro e a linha vertical"""
    dx = x1 - x2
    dy = y1 - y2
    # atan2 calcula o ângulo em radianos, convertemos para graus
    angulo_rad = math.atan2(abs(dx), abs(dy))
    return math.degrees(angulo_rad)

# Conecta na Câmera
LARGURA, ALTURA = 640, 480  # Aumentado para 640x480 para melhor visualização na tela
captura = cv2.VideoCapture(0)
captura.set(cv2.CAP_PROP_FRAME_WIDTH, LARGURA)
captura.set(cv2.CAP_PROP_FRAME_HEIGHT, ALTURA)

print("\n=== SISTEMA DE MONITORAMENTO DE POSTURA INICIADO ===")
print("Pressione a tecla 'q' na janela da imagem para encerrar.\n")

while True:
    retorno, frame = captura.read()
    if not retorno or frame is None:
        continue

    # Espelha a imagem para agir como um espelho (opcional, melhora a experiência)
    frame = cv2.flip(frame, 1)

    # Pré-processamento para a IA (O MoveNet exige entrada 192x192)
    frame_192 = cv2.resize(frame, (192, 192))
    try:
        dados_entrada = np.expand_dims(frame_192, axis=0).astype(np.float32)
    except ValueError:
        dados_entrada = np.expand_dims(frame_192, axis=0).astype(np.uint8)


    # Inferência
    interpretador.set_tensor(detalhes_entrada[0]['index'], dados_entrada)
    interpretador.invoke()
    keypoints = interpretador.get_tensor(detalhes_saida[0]['index'])[0][0]

    # Extrai coordenadas
    orelha_y, orelha_x, conf_orelha = keypoints[ORELHA_ESQ]
    ombro_y, ombro_x, conf_ombro = keypoints[OMBRO_ESQ]

    # Só calcula se a confiança da IA for maior que 20%
    if conf_orelha > 0.2 and conf_ombro > 0.2:
        # Como espelhamos o frame com cv2.flip, precisamos inverter a coordenada X da IA
        x_orelha = int((1.0 - orelha_x) * LARGURA)
        y_orelha = int(orelha_y * ALTURA)
        
        x_ombro = int((1.0 - ombro_x) * LARGURA)
        y_ombro = int(ombro_y * ALTURA)

        # Calcula a inclinação passando os parâmetros exatos
        angulo = calcular_angulo_vertical(x_orelha, y_orelha, x_ombro, y_ombro)

        # Desenha os pontos e a linha conectando a orelha ao ombro
        cv2.circle(frame, (x_orelha, y_orelha), 6, (255, 0, 0), -1)  # Ponto Azul na Orelha
        cv2.circle(frame, (x_ombro, y_ombro), 6, (0, 255, 255), -1)  # Ponto Amarelo no Ombro
        cv2.line(frame, (x_orelha, y_orelha), (x_ombro, y_ombro), (255, 255, 255), 2)  # Linha Branca

        # Define o limiar de má postura (25 graus)
        if angulo > 25.0:
            status_texto = f"ALERTA: POSTURA INCORRETA ({int(angulo)} deg)"
            cor_alerta = (0, 0, 255)  # Vermelho BGR
        else:
            status_texto = f"POSTURA CORRETA ({int(angulo)} deg)"
            cor_alerta = (0, 255, 0)  # Verde BGR

        # Exibe o texto de aviso na tela da imagem
        cv2.putText(frame, status_texto, (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.8, cor_alerta, 2, cv2.LINE_AA)
    else:
        # Caso a pessoa saia do enquadramento ou a IA não ache os pontos
        cv2.putText(frame, "Procurando usuario...", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2, cv2.LINE_AA)

    # Abre a janela visual com o vídeo modificado
    cv2.imshow("Monitoramento de Postura - TCC", frame)
    
    # Sai do programa se apertar a tecla 'q'
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

captura.release()
cv2.destroyAllWindows()
