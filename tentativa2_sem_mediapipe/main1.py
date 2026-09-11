import cv2
import numpy as np
import tflite_runtime.interpreter as tflite
from flask import Flask, Response

app = Flask(__name__)

# --- CARREGAR MODELO ---
interpretador = tflite.Interpreter(model_path="movenet_lightning.tflite")
interpretador.allocate_tensors()
detalhes_entrada = interpretador.get_input_details()
detalhes_saida = interpretador.get_output_details()

# --- CONFIGURAR CÂMERA ---
url = 'http://192.168.15.6:8080/video'
cmd = input("0 (via ip) ou 1 (via usb) ")
if cmd == '0':
	captura = cv2.VideoCapture(url)
else:
	captura = cv2.VideoCapture(0)

captura.set(cv2.CAP_PROP_FRAME_WIDTH, 320)
captura.set(cv2.CAP_PROP_FRAME_HEIGHT, 240)

def gerar_frames():
    while True:
        retorno, frame = captura.read()
        if not retorno:
            break

        # 1. Pré-processamento
        frame_192 = cv2.resize(frame, (192, 192))
        dados_entrada = np.expand_dims(frame_192, axis=0).astype(np.float32)

        # 2. Inferência MoveNet
        interpretador.set_tensor(detalhes_entrada[0]['index'], dados_entrada)
        interpretador.invoke()
        pontos_chaves = interpretador.get_tensor(detalhes_saida[0]['index'])[0][0]

        # 3. Desenhar os 17 pontos no frame original
        h, w, _ = frame.shape
        for kp in pontos_chaves:
            y, x, conf = kp
            if conf > 0.2:
                cv2.circle(frame, (int(x * w), int(y * h)), 3, (0, 255, 0), -1)

        # 4. Codifica o frame para JPG
        _, buffer = cv2.imencode('.jpg', frame)
        frame_bytes = buffer.tobytes()

        # Transmite o frame em loop via HTTP
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')

@app.route('/')
def video_feed():
    return Response(gerar_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

if __name__ == '__main__':
    # Roda o servidor na porta 5000 acessível pela rede
    app.run(host='0.0.0.0', port=5000, threaded=True)

@app.route('/')
def index():
    # Renderiza uma página HTML simples que consome o vídeo
    return """
    <html>
      <head>
        <title>TCC Postura - Raspberry Pi 3B</title>
        <style>
          body { background-color: #121212; color: white; text-align: center; font-family: sans-serif; }
          img { border: 2px solid #00ff00; margin-top: 20px; max-width: 90%; }
        </style>
      </head>
      <body>
        <h2>TCC Monitoramento de Postura - RPi 3B</h2>
        <img src="/video_feed" />
      </body>
    </html>
    """

@app.route('/video_feed')
def video_feed():
    return Response(gerar_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, threaded=True)
