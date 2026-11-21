"""
Configurações compartilhadas entre o serviço (postura_servico.py) e o
comando de controle (postura_ctl.py).

Ajuste os limiares AQUI — os dois arquivos leem deste mesmo lugar.
"""
import os
import socket
import sys

EH_WINDOWS = sys.platform == "win32"

# Caminhos sempre relativos à pasta deste arquivo (e não à pasta de onde o
# programa foi chamado). Isso é o que permite o systemd rodar o serviço de
# qualquer diretório e ainda achar o modelo, os vídeos e os logs.
DIR_BASE = os.path.dirname(os.path.realpath(__file__))
CAMINHO_MODELO = os.path.join(DIR_BASE, "movenet_lightning.tflite")
DIR_VIDEOS = os.path.join(DIR_BASE, "videos")
DIR_LOGS = os.path.join(DIR_BASE, "logs")
DIR_FOTOS = os.path.join(DIR_BASE, "fotos")   # `postura foto` (T5); não vai pro Git
FOTO_LARGURA = 320                             # JPEG reduzido: leve pra baixar por scp

# Última baseline calibrada ao vivo. Só é reaproveitada se o programa
# reiniciar no MESMO boot (ex: travou e o systemd religou). Depois de um
# boot novo, o sistema sempre aguarda `postura recalibrar`.
ARQUIVO_BASELINE = os.path.join(DIR_BASE, "baseline.json")

# Canal de comunicação entre o comando `postura` e o serviço.
# Linux/macOS: socket Unix; leva o UID no nome pra cada usuário ter o seu.
# Windows: o Python não expõe AF_UNIX, então usa TCP só na máquina local
# (127.0.0.1, porta fixa). Quem usa o socket só precisa de FAMILIA_SOCKET e
# CAMINHO_SOCKET; o formato do endereço muda sozinho conforme o sistema.
if EH_WINDOWS:
    FAMILIA_SOCKET = socket.AF_INET
    CAMINHO_SOCKET = ("127.0.0.1", 47831)
else:
    FAMILIA_SOCKET = socket.AF_UNIX
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
# ALERTA quando o contador de postura ruim PASSA disso (61º quadro). VALOR PROVISÓRIO (20/11):
# mirado em 10 a 20 s de má postura antes do ALERTA. Conta com o fps medido no Pi em 18–20/11
# (~4,1 fps, com throttling): 61 ÷ 4,1 ≈ 15 s. O fps varia com a carga, então o tempo real é
# uma FAIXA, não um valor fixo. Nenhuma fonte da literatura pra este valor (escolha do projeto).
# Antes: 15 (16º quadro, ≈ 3,7 s a 4,1 fps).
FRAMES_PARA_ALERTA = 60

# --- Contador de ALERTA que usa as perdas de detecção (T3, "informative missingness") ---
# Perder os pontos (SEM_USUARIO) no meio de uma sequência ruim é indício de que a pessoa
# está encurvada no limite do que o MoveNet capta. Inferência por regras, não IA.
# VALORES PROVISÓRIOS, escolha do projeto, a definir com os dados do estudo (rajadas de
# SEM_USUARIO dentro de postura ruim). Origem:
#   PERDAS_TOLERADAS: no simulador aprovado eram 2 com escala de 6 quadros (1/3); 1/3 de 15 = 5.
#   MINIMO_RUINS_MEDIDOS: o ALERTA (16 quadros) não pode vir majoritariamente de quadros
#   perdidos → pelo menos metade medida = 8.
#   ATENÇÃO (20/11): N e M foram derivados do limiar ANTIGO (15/16 quadros) e foram mantidos
#   sem mudança quando o FRAMES_PARA_ALERTA passou pra 60; a "metade medida" não vale mais.
PERDAS_TOLERADAS = 5          # N: perdas SEGUIDAS que ainda contam como indício (em quadros)
MINIMO_RUINS_MEDIDOS = 8      # M: quadros ruins MEDIDOS exigidos pra afirmar ALERTA

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
