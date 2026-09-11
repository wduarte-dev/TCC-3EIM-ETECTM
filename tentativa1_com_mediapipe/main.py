import cv2
import mediapipe as mp
import time
import winsound

from frame import capturar_frame
from coordenadas_landmarks import pegar_landmarks, options
from calibrar import adicionar_dado, calcular_referencia
from verificar_postura import verificar_postura

from analise_postura import (
    calcular_meio_ombros,
    calcular_posicao_cabeca
)


camera = cv2.VideoCapture(0)

with mp.tasks.vision.PoseLandmarker.create_from_options(options) as landmarker:

    timestamp = 0

    dados_calibracao = []
    inicio_calibracao = time.time()
    calibrado = False

    while True:

        # Captura o frame
        frame = capturar_frame(camera)

        if frame is None:
            print("Erro ao capturar imagem")
            break

        # Pega os 3 landmarks
        pontos = pegar_landmarks(
            frame,
            landmarker,
            timestamp
        )

        timestamp += 1

        if pontos:

            nariz, ombro_esq, ombro_dir = pontos

            # Calcula a posição atual da cabeça
            meio_ombros = calcular_meio_ombros(
                ombro_esq,
                ombro_dir
            )

            posicao_cabeca = calcular_posicao_cabeca(
                nariz,
                meio_ombros
            )

            # Enquanto não estiver calibrado, coleta os dados
            if not calibrado:

                adicionar_dado(
                    dados_calibracao,
                    nariz,
                    ombro_esq,
                    ombro_dir
                )

                tempo_passado = time.time() - inicio_calibracao

                print(
                    "Tempo:",
                    round(tempo_passado, 1),
                    "| Dados:",
                    len(dados_calibracao)
                )

                if tempo_passado >= 10:

                    referencia = calcular_referencia(
                        dados_calibracao
                    )

                    print("Calibração concluída!")
                    print("Referência:", referencia)

                    calibrado = True

            # Depois da calibração, verifica a postura
            else:

                postura_normal = verificar_postura(
                    posicao_cabeca,
                    referencia
                )

                if postura_normal:

                    print("Postura normal")

                else:

                    print("Postura desviada")

                    # Som a cada frame enquanto estiver desviada
                    winsound.Beep(1000, 1000)
                    time.sleep(1)

        # Mostra a câmera
        cv2.imshow("Camera", frame)

        if cv2.waitKey(1) == ord("q"):
            break


camera.release()
cv2.destroyAllWindows()