import cv2
import numpy as np

# importação com compatibilidade tensorflow / tensorflow lite
import tflite_runtime.interpreter as tflite

# carregamento do modelo
interpretador = tflite.Interpreter(model_path="movenet_lightning.tflite")
interpretador.allocate_tensors()
detalhes_entrada = interpretador.get_input_details()
detalhes_saida = interpretador.get_output_details()

# captura da câmera     
captura = cv2.VideoCapture(0)
captura.set(cv2.CAP_PROP_FRAME_WIDTH,  640)
captura.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

if not captura.isOpened():
    print("Erro ao acessar a câmera.")
    exit()
print("Câmera inicializada, q para sair")

# main loop (exibição da câmera)
while True:
    retorno, frame = captura.read()
    if not retorno:
        print("Frame perdido.")
        break
    
    # pré-processamento do frame antes da exibição
    frame_redimensionado = cv2.resize(frame, (192, 192))
    dados_entrada = np.expand_dims(frame_redimensionado, axis=0).astype(np.float32)
    interpretador.set_tensor(detalhes_entrada[0]['index'], dados_entrada)
    interpretador.invoke()
        # matriz com os 17 pontos
    pontos_chaves = interpretador.get_tensor(detalhes_saida[0]['index'])[0][0]
    
    cv2.imshow("Câmera", frame)
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

captura.release()
cv2.destroyAllWindows()
