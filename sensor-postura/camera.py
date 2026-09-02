# Importação da biblioteca base de visão computacional (captura da câmera do usuário)
import cv2 

# Seleciona a câmera principal do usuário. Se ele possuir mais de uma, por exemplo, elas serão representadas como:
# Câmera 1 = 0
# Câmera 2 = 1
# Câmera 3 = 2 
# ...
# Camera n = n-1
camera = cv2.VideoCapture(0)

# Loop principal de captura de frame e processamento
while True:
    # camera.read retorna uma tupla contendo um bool (indicando que a captura deu certo) e o frame, que é uma matriz de pixels que a câmera capturou naquele instante
    sucesso, frame = camera.read()
    
    if not sucesso:
        print("Erro ao capturar imagem")
        break
    # Mostra o frame capturado na tela
    cv2.imshow("Camera", frame)
    # Se o usuário pressionar "q", o programa fecha.
    if cv2.waitKey(1) == ord("q"):
        break

camera.release()
cv2.destroyAllWindows()