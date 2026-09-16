import cv2
import numpy as np
import math
import time

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

# Variáveis de controle criadas para o temporizador de 3 segundos
INTERVALO_DETECÇÃO = 3.0  
contador = 0
ultima_execucao_ia = 0.0
status_texto = "Procurando usuario..."
cor_alerta = (255, 255, 255)
pontos_desenho = None  

while True:
    retorno, frame = captura.read()
    if not retorno or frame is None:
        continue

    # Espelha a imagem para agir como um espelho (opcional, melhora a experiência)
    frame = cv2.flip(frame, 1)

    tempo_atual = time.time()

    # Só entra no bloco da IA se passarem 3 segundos
    if tempo_atual - ultima_execucao_ia >= INTERVALO_DETECÇÃO:
        ultima_execucao_ia = tempo_atual

        # Pré-processamento para a IA (O MoveNet exige entrada 192x192)
        frame_192 = cv2.resize(frame, (192, 192))
        dados_entrada = np.expand_dims(frame_192, axis=0).astype(np.float32)

        # Inferência (Mantido exatamente igual)
        try:
            interpretador.set_tensor(detalhes_entrada[0]['index'], dados_entrada)
        except ValueError:
            dados_entrada = np.expand_dims(frame_192, axis=0).astype(np.uint8)
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

            # Salva os pontos atuais para o desenho persistir durante os 3 segundos
            pontos_desenho = (x_orelha, y_orelha, x_ombro, y_ombro)

            # Calcula a inclinação passando os parâmetros exatos
            angulo = calcular_angulo_vertical(x_orelha, y_orelha, x_ombro, y_ombro)

            # Define o limiar de má postura (25 graus)
            if angulo > 25.0:
                # A IA captura a cada 3 segundos e aciona um contador que, se for >= 3, acionará má postura, totalizando
                # 9 segundos em postura inadequada para detecção.
                contador += 1
                if contador < 3:
                    status_texto = f"ATENÇÃO: POSTURA SUSPEITA...  ({int(angulo)}°)"
                    cor_alerta = (0, 255, 255)  # Amarelo BGR
                if contador >= 3:
                    status_texto = f"ALERTA: POSTURA INCORRETA ({int(angulo)}°)"
                    cor_alerta = (0, 0, 255)  # Vermelho BGR
            else:
                contador = 0
                status_texto = f"POSTURA CORRETA ({int(angulo)}°)"
                cor_alerta = (0, 255, 0)  # Verde BGR
        else:
            status_texto = "Procurando usuario..."
            pontos_desenho = None

    # Desenha os pontos salvos e o texto em todos os frames para manter a fluidez visual
    if pontos_desenho is not None:
        xo, yo, xm, ym = pontos_desenho
        cv2.circle(frame, (xo, yo), 6, (255, 0, 0), -1)  # Ponto Azul na Orelha
        cv2.circle(frame, (xm, ym), 6, (0, 255, 255), -1)  # Ponto Amarelo no Ombro
        cv2.line(frame, (xo, yo), (xm, ym), (255, 255, 255), 2)  # Linha Branca

    # Exibe o texto de aviso na tela da imagem
    cv2.putText(frame, status_texto, (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.8, cor_alerta, 2, cv2.LINE_AA)

    # Abre a janela visual com o vídeo modificado
    cv2.imshow("Monitoramento de Postura - TCC", frame)
    
    # Sai do programa se apertar a tecla 'q'
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

captura.release()
cv2.destroyAllWindows()
