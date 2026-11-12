"""
Configurações compartilhadas entre o serviço (postura_servico.py) e o
comando de controle (postura_ctl.py).

Ajuste os limiares AQUI — os dois arquivos leem deste mesmo lugar.
"""
import os

# Caminhos sempre relativos à pasta deste arquivo (e não à pasta de onde o
# programa foi chamado). Isso é o que permite o systemd rodar o serviço de
# qualquer diretório e ainda achar o modelo, os vídeos e os logs.
DIR_BASE = os.path.dirname(os.path.realpath(__file__))
CAMINHO_MODELO = os.path.join(DIR_BASE, "movenet_lightning.tflite")
DIR_VIDEOS = os.path.join(DIR_BASE, "videos")
DIR_LOGS = os.path.join(DIR_BASE, "logs")

# Última baseline calibrada ao vivo. Só é reaproveitada se o programa
# reiniciar no MESMO boot (ex: travou e o systemd religou). Depois de um
# boot novo, o sistema sempre aguarda `postura recalibrar`.
ARQUIVO_BASELINE = os.path.join(DIR_BASE, "baseline.json")

# Canal de comunicação entre o comando `postura` e o serviço (socket Unix).
# Leva o UID no nome pra cada usuário ter o seu.
CAMINHO_SOCKET = f"/tmp/postura-{os.getuid()}.sock"

# --- Câmera ---
INDICE_CAMERA = 0
LARGURA, ALTURA = 640, 480

# --- Lógica de postura (mesmos valores do main-otimizado.py) ---
LIMIAR_CONFIANCA = 0.4        # Confiança mínima dos keypoints para considerar válidos
LIMIAR_DESVIO_ANGULO = 12.0   # Graus de desvio lateral tolerados em relação à baseline
LIMIAR_QUEDA_RAZAO = 0.12     # Queda tolerada na razão pescoço/ombros (0.12 = 12%)
DURACAO_CALIBRACAO = 5        # segundos coletando amostras da postura correta
HISTORICO_TAMANHO = 5         # tamanho da média móvel
FRAMES_PARA_ALERTA = 15       # frames seguidos de postura ruim até virar ALERTA

# --- Comportamento headless ---
CONTAGEM_CALIBRACAO = 10      # segundos pra se ajeitar depois do `postura recalibrar` (ao vivo)
CONTAGEM_GRAVACAO = 5         # segundos pra se ajeitar depois do `postura gravar N`
GRAVACAO_MAX_S = 600          # duração máxima de uma gravação (10 min)
INTERVALO_PRINT_S = 5.0       # repete o status no terminal a cada X s, mesmo sem mudança
MAX_FALHAS_LEITURA = 30       # leituras falhas seguidas da câmera antes de reabrir ela
ESPERA_CAMERA_S = 3           # intervalo entre tentativas de abrir a câmera

EXTENSOES_VIDEO = (".mp4", ".avi", ".mkv", ".mov", ".webm")


def listar_videos():
    """Lista (em ordem alfabética) os vídeos disponíveis na pasta videos/."""
    if not os.path.isdir(DIR_VIDEOS):
        return []
    return sorted(
        nome for nome in os.listdir(DIR_VIDEOS)
        if nome.lower().endswith(EXTENSOES_VIDEO)
        and os.path.isfile(os.path.join(DIR_VIDEOS, nome))
    )
