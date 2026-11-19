"""
Configurações do pomodoro (display OLED + 3 botões).

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

# --- Botões: 3 MÓDULOS de 3 pinos (VCC, OUT, GND), BCM ---
# VCC dos 3 no pino 17 (3,3 V) e GND dos 3 no pino 9 (ver claude/hardware.md).
GPIO_B1 = 17   # pino 11 → recalibrar (postura ou voz)
GPIO_B2 = 27   # pino 13 → pomodoro
GPIO_B3 = 22   # pino 15 → desligar o Pi (aperto de 3 s; ver energia.py)

# Polaridade do OUT do módulo:
#   "auto"  descobre sozinha lendo o nível parado por AUTO_OCIOSO_S no início
#           (NÃO segure nenhum botão ao iniciar); funciona com módulo que sobe
#           ou que desce ao apertar
#   "alto"  OUT sobe ao apertar    |   "baixo"  OUT desce ao apertar
POLARIDADE_BOTOES = "auto"
AUTO_OCIOSO_S = 0.6
# Resistor interno do Pi no pino do OUT. O módulo já tem o resistor dele, então o
# padrão é nenhum (None): o pull-up interno brigava com o do módulo.
#   None = sem resistor interno | "cima" = pull-up | "baixo" = pull-down
PULL_INTERNO_BOTOES = None
# Leitura por amostragem (em vez de eventos): a cada AMOSTRA_S lê o pino e só aceita
# uma mudança de estado depois de AMOSTRAS_ESTAVEIS leituras seguidas iguais
# (4 × 10 ms = 40 ms). Repique e picos mais curtos que isso são ignorados, tanto
# ao apertar quanto ao soltar. Valores do projeto, ajustar com o diagnostico_botoes.py.
AMOSTRA_S = 0.01
AMOSTRAS_ESTAVEIS = 4

# Classificação do aperto (B1, B2 e B3), medida ao SOLTAR o botão.
# No B1 só importa curto × longo; "muito longo" conta como longo.
LIMITE_LONGO_S = 1.0         # até aqui = curto; daqui até o próximo limite = longo
LIMITE_MUITO_LONGO_S = 3.0   # a partir daqui = muito longo (no B3, desliga o Pi)

# --- B3: desligar o Pi ---
# "sudo -n": não pede senha (falha na hora se precisar de uma). Como root, sem sudo.
COMANDO_DESLIGAR = ["sudo", "-n", "poweroff"]
B3_DICA_APOS_S = 0.5         # só mostra a dica de "segure" depois disso (toque rápido não pisca)
MENSAGEM_FALHA_DESLIGAR_S = 3.0

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
CAMINHO_BASELINE_VOZ = os.path.join(os.path.dirname(CAMINHO_SENSOR_VOZ), "baseline_voz.json")
PREPARO_VOZ_S = 2.0          # "PREPARE-SE" antes de cada gravação de 3 s
MENSAGEM_FINAL_VOZ_S = 3.0   # quanto tempo "VOZ CALIBRADA/FALHOU" fica na tela
