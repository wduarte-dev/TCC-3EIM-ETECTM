"""
Configurações do pomodoro (display OLED + 3 botões).

Ajuste os valores AQUI: os outros arquivos leem deste mesmo lugar.
"""
import os

# --- Presets (T6), tudo em MINUTOS ---
# Um só vem de fábrica: 25/5 com pausa longa de 15. O 25/5 é o padrão da técnica
# Pomodoro; os 15 min da pausa longa são escolha do projeto (sem validação própria).
# O usuário adiciona os dele com o comando `pomodoro adicionar --preset MM/MM[/MM]`
# (ver presets.py); ficam num JSON fora do repositório.
PRESET_PADRAO = {"nome": "25/5", "foco": 25, "pausa": 5, "pausa_longa": 15}
PRESETS = [PRESET_PADRAO]      # só o de fábrica (o main.py junta os do usuário)
CAMINHO_PRESETS = os.environ.get("POMODORO_PRESETS") or os.path.join(
    os.path.expanduser("~"), ".config", "pomodoro", "presets.json")
MINUTOS_MIN, MINUTOS_MAX = 1, 180   # faixa aceita no comando (escolha do projeto, sem fonte)

CICLOS_ATE_PAUSA_LONGA = 4   # a cada N focos concluídos, a pausa é a longa

# --- Botões: 3 MÓDULOS de 3 pinos (VCC, OUT, GND), BCM ---
# VCC dos 3 no pino 17 (3,3 V) e GND dos 3 no pino 9 (ver claude/hardware.md).
GPIO_B1 = 17   # pino 11 → menu: recalibrar postura / conectar Wi-Fi
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
LIMITE_PAUSA_POSTURA_S = 5.0 # só no B1: soltar depois disso pausa/retoma a medição de postura

# --- B3: desligar o Pi ---
# "sudo -n": não pede senha (falha na hora se precisar de uma). Como root, sem sudo.
COMANDO_DESLIGAR = ["sudo", "-n", "poweroff"]
B3_DICA_APOS_S = 0.5         # segurando: a contagem "SEGURE Ns" aparece depois disso
B3_DICA_CLIQUE_S = 2.0       # clique curto no B3: mostra "SEGURE 3s: DESLIGAR" por esse tempo
MENSAGEM_FALHA_DESLIGAR_S = 3.0

# --- Display OLED SSD1306 128x64 (I2C) ---
OLED_I2C_PORTA = 1
OLED_I2C_ENDERECO = 0x3C
LARGURA, ALTURA = 128, 64

# --- Qual display usar (23/11/2026: troca pro LCD 16x2) ---
#   "lcd"  LCD 16x2 HD44780 por GPIO (4 bits) | "oled"  OLED SSD1306 128x64 (I2C)
#   No notebook: "lcd-png" (prévia do LCD num PNG) ou "png"/"pygame" (do OLED).
DISPLAY_PADRAO = "lcd"

# --- LCD 16x2 HD44780, modo 4 bits (BCM; ligação em claude/hardware.md) ---
# RW do LCD vai FIXO no GND: o LCD só recebe e nunca devolve 5 V pro GPIO do Pi.
LCD_GPIO_RS = 5     # pino 29
LCD_GPIO_E = 6      # pino 31
LCD_GPIO_D4 = 13    # pino 33
LCD_GPIO_D5 = 19    # pino 35
LCD_GPIO_D6 = 26    # pino 37
LCD_GPIO_D7 = 16    # pino 36
LCD_COLUNAS, LCD_LINHAS = 16, 2
# Topo do pomodoro rodando: a fase fica fixa e o preset aparece no lugar dela por
# LCD_PRESET_MOSTRA_S a cada LCD_PRESET_CICLO_S (não cabem os dois em 16 colunas).
# LCD_PRESET_CICLO_S = 0 desliga (só a fase). Escolha do projeto, sem validação.
LCD_PRESET_CICLO_S = 8.0
LCD_PRESET_MOSTRA_S = 2.0
LCD_ROLAGEM_CPS = 3.0        # texto maior que a linha rola a 3 caracteres/s (raro)
LCD_WIFI_CREDENCIAIS_S = 6.0  # espera do Wi-Fi: REDE e SENHA ficam juntas na tela por esse tempo (a espera dura até ~10 s)
LCD_APAGAR_APOS_S = 3.0      # B3 desligando: o aviso fica esse tempo e o texto some (a luz azul continua: o 5 V do Pi segue ligado)
LCD_ALERTA_PISCA_HZ = 1.0    # POSTURA: RUIM alterna com a linha cheia (o "invertido" do OLED)

ATUALIZACAO_TELA_S = 0.25    # a cada quanto tempo redesenha a tela
PISCAR_MUDANCA_FASE_S = 3.0  # tela pisca (invertida) quando troca de fase: não há buzzer

# --- Ligação com o serviço de postura (socket Unix do postura_servico.py) ---
CAMINHO_SOCKET_POSTURA = f"/tmp/postura-{os.getuid()}.sock"
INTERVALO_CONSULTA_POSTURA_S = 1.0
TIMEOUT_POSTURA_S = 1.5

# --- B1: menu (postura / Wi-Fi) ---
MENU_B1_TIMEOUT_S = 5.0      # sem clique por esse tempo, o menu fecha sozinho

# --- Wi-Fi (T7; ver wifi.py) ---
# Rede padrão: fraca DE PROPÓSITO (fácil de criar no hotspot do celular). Enquanto o usuário
# não troca com `wifi --ssid X --senha Y`, qualquer rede DIHMO com essa senha atrai o Pi.
WIFI_SSID_PADRAO = "DIHMO"
WIFI_SENHA_PADRAO = "admin1234"
CAMINHO_WIFI = os.environ.get("POMODORO_WIFI") or os.path.join(
    os.path.expanduser("~"), ".config", "pomodoro", "wifi.json")
WIFI_PERFIL_NM = "tcc-wifi"  # nome do perfil no NetworkManager
WIFI_INTERFACE = "wlan0"
WIFI_PRIORIDADE = -10        # autoconnect um pouco abaixo das redes de desenvolvimento (padrão 0)
WIFI_TIMEOUT_S = 120         # desiste depois disso (escolha do projeto, sem validação)
WIFI_INTERVALO_S = 10        # repete rescan + connection up a cada X s (escolha do projeto)
WIFI_RESULTADO_S = 3.0       # quanto tempo WIFI CONECTADO/FALHOU fica na tela
WIFI_CONFIRMA_SSH_S = 5.0    # com SSH ativo, repetir o longo dentro desse tempo pra confirmar
