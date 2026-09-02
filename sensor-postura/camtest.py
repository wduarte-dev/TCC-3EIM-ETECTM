import cv2
import time

camera = cv2.VideoCapture(0)

inicio = time.time()
frames = 0

while True:
    sucesso, frame = camera.read()

    if not sucesso:
        print("Erro ao capturar imagem")
        break

    frames += 1

    tempo = time.time() - inicio

    if tempo >= 1:
        print("FPS:", frames)
        frames = 0
        inicio = time.time()

    cv2.imshow("Camera", frame)

    if cv2.waitKey(1) == ord("q"):
        break

camera.release()
cv2.destroyAllWindows()