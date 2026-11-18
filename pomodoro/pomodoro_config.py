"""
Configurações do pomodoro (display OLED + 2 botões).

Ajuste os valores AQUI: os outros arquivos leem deste mesmo lugar.
"""
import os

# --- Presets (nome, foco, pausa, pausa longa), tudo em MINUTOS ---
# 25/5 é o padrão da técnica Pomodoro. 50/10 e 90/20 são variações populares;
# os tempos da pausa longa são escolha do projeto (sem validação própria).
PRESETS = [
    {"nome": "25/5",  "foco": 25, "pausa": 5,  "pausa_longa": 15},
    {"nome": "50/10", "foco": 50, "pausa": 10, "pausa_longa": 20},
    {"nome": "90/20", "foco": 90, "pausa": 20, "pausa_longa": 30},
]

CICLOS_ATE_PAUSA_LONGA = 4   # a cada N focos concluídos, a pausa é a longa

# --- Botões (GPIO no numeração BCM; ligação: pino do GPIO ↔ GND, sem resistor) ---
GPIO_B1 = 17   # pino 11 (GND no pino 9)  → recalibrar (postura ou voz)
GPIO_B2 = 27   # pino 13 (GND no pino 14) → pomodoro
DEBOUNCE_S = 0.05

# Classificação do aperto (B1 e B2), medida ao SOLTAR o botão.
# No B1 só importa curto × longo; "muito longo" conta como longo.
LIMITE_LONGO_S = 1.0         # até aqui = curto; daqui até o próximo limite = longo
LIMITE_MUITO_LONGO_S = 3.0   # a partir daqui = muito longo

# --- Display OLED SSD1306 128x64 (I2C) ---
OLED_I2C_PORTA = 1
OLED_I2C_ENDERECO = 0x3C
LARGURA, ALTURA = 128, 64
ATUALIZACAO_TELA_S = 0.25    # a cada quanto tempo redesenha a tela
PISCAR_MUDANCA_FASE_S = 3.0  # tela pisca (invertida) quando troca de fase: não há buzzer

# --- Ligação com o serviço de postura (socket Unix do postura_servico.py) ---
CAMINHO_SOCKET_POSTURA = f"/tmp/postura-{os.getuid()}.sock"
INTERVALO_CONSULTA_POSTURA_S = 1.0
TIMEOUT_POSTURA_S = 1.5

# --- B1: menu de recalibração (postura/voz) ---
MENU_B1_TIMEOUT_S = 5.0      # sem clique por esse tempo, o menu fecha sozinho

# --- Recalibração da voz pelo B1 (reaproveita o sensor-voz/main.py) ---
CAMINHO_SENSOR_VOZ = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                  "..", "sensor-voz", "main.py")
PREPARO_VOZ_S = 2.0          # "PREPARE-SE" antes de cada gravação de 3 s
MENSAGEM_FINAL_VOZ_S = 3.0   # quanto tempo "VOZ CALIBRADA/FALHOU" fica na tela
