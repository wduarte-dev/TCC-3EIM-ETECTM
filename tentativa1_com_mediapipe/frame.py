import cv2
def capturar_frame(camera):

    sucesso, frame = camera.read()

    if not sucesso:
        return None

    return frame