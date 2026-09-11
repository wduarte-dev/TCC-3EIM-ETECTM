import cv2
import mediapipe as mp

from coordenadas_landmarks import pegar_landmarks, options


camera = cv2.VideoCapture(0)

with mp.tasks.vision.PoseLandmarker.create_from_options(options) as landmarker:

    timestamp = 0

    while True:

        sucesso, frame = camera.read()

        if not sucesso:
            print("Erro ao capturar imagem")
            break

        pontos = pegar_landmarks(
            frame,
            landmarker,
            timestamp
        )

        timestamp += 1

        if pontos:

            nariz, ombro_esq, ombro_dir = pontos

            altura, largura, _ = frame.shape

            pontos_plot = [
                nariz,
                ombro_esq,
                ombro_dir
            ]

            for ponto in pontos_plot:

                x = int(ponto.x * largura)
                y = int(ponto.y * altura)

                cv2.circle(
                    frame,
                    (x, y),
                    8,
                    (0, 255, 0),
                    -1
                )

        cv2.imshow("Postura", frame)

        if cv2.waitKey(1) == ord("q"):
            break


camera.release()
cv2.destroyAllWindows()