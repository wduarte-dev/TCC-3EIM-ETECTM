# Pomodoro (display LCD 16x2 ou OLED + 3 botões)

Timer de foco/pausa que roda no Raspberry Pi e mostra tudo no display: desde 23/11/2026 o
padrão é o **LCD 16x2** (HD44780, por GPIO); o OLED 128x64 continua funcionando com
`--display oled` (ou `DISPLAY_PADRAO = "oled"` no `pomodoro_config.py`). Também mostra, na linha de baixo, o status do monitor de postura
(`sensor-postura/`) e deixa o usuário recalibrar a **postura** ou **conectar o Wi-Fi**
pelo botão B1. O B3 desliga o Pi.

> **Estado:** a lógica, a tela, a ligação com a postura e a leitura dos botões (com pinos
> simulados) foram testadas no notebook (testes automáticos + simulação). **Ainda não foi
> testado no Pi com o OLED e os módulos de botão de verdade.**

## Botões

Os botões são **3 módulos de 3 pinos (VCC, OUT, GND)**. Ligar **pelo nome impresso** na placa.

| Fio | Liga no Pi |
|---|---|
| VCC dos 3 (emendados) | pino 17 (**3,3 V**, nunca 5 V; o pino 1 é do OLED) |
| GND dos 3 (emendados) | pino 9 |
| OUT do **B1** | pino 11 (GPIO17): **menu** (recalibrar a postura ou conectar o Wi-Fi; tabela abaixo). Não mexe no pomodoro |
| OUT do **B2** | pino 13 (GPIO27): pomodoro (tabela abaixo) |
| OUT do **B3** | pino 15 (GPIO22): **desligar o Pi** (seção abaixo) |

Não usar os pinos 3 e 5 (I2C do OLED) nem os do LCD (abaixo).

## Display LCD 16x2 (padrão desde 23/11)

LCD HD44780 em **modo 4 bits** (6 GPIO). Pi desligado ao ligar os fios; 5 V e GND emendados numa
linha de protoboard.

| LCD | Liga em | Pi |
|---|---|---|
| 1 VSS | GND | pino 39 |
| 2 VDD | 5 V | pino 4 |
| 3 V0 | cursor de um trimpot de 10 kΩ (pontas em 5 V e GND): contraste | |
| 4 RS | GPIO5 | pino 29 |
| 5 RW | **GND** (só escrita: o LCD nunca devolve 5 V pro GPIO) | pino 39 |
| 6 E | GPIO6 | pino 31 |
| 7–10 D0–D3 | soltos | |
| 11 D4 | GPIO13 | pino 33 |
| 12 D5 | GPIO19 | pino 35 |
| 13 D6 | GPIO26 | pino 37 |
| 14 D7 | GPIO16 | pino 36 |
| 15 A | 5 V **com resistor de 220 Ω** (backlight) | pino 4 |
| 16 K | GND | pino 39 |

- **3,3 V no GPIO serve:** com o LCD em 5 V, o datasheet do HD44780U dá entrada alta mínima de 2,2 V.
  Alguns clones pedem 0,7·VCC (3,5 V): se o LCD não responder de jeito nenhum, é uma suspeita.
- **Driver próprio** (`lcd_hd44780.py`, sobre o gpiozero que os botões já usam): sem dependência nova.
- **Teste de bancada:** `python ../teste_lcd.py` (na raiz do repo; `--contraste` pra regular o V0,
  `--telas` pras telas reais do pomodoro). Precisa de `pip install gpiozero lgpio` (o gpiozero cai num
  backend próprio se o `lgpio` não compilar; pra compilar o `lgpio` precisa de `swig` e `python3-dev`).
  Pare o serviço antes: `sudo systemctl stop pomodoro`.
- **Primeiro teste:** só com alimentação + trimpot, a linha de cima mostra 16 blocos escuros
  (ajuste o trimpot até aparecerem). Blocos sem texto depois de rodar o programa = RS/E ou
  D4–D7 trocados.

**Telas no LCD** (`display_lcd.py`; a lógica é a mesma, só o desenho muda). Cada parte tem
**uma linha inteira**: linha 1 = pomodoro, linha 2 = postura (no OLED a postura era uma faixa de 9 px).

| Tela | Linha 1 | Linha 2 |
|---|---|---|
| Escolha | `TEMPO       25/5` (B2 segurado: `SOLTE: INICIAR`) | postura/menu |
| Rodando | `FOCO 1/4   24:59`; pausado: ícone `‖` antes da fase; o preset aparece no lugar da fase por 2 s a cada 8 s (não cabem os dois) | `POSTURA: BOA`, `POSTURA: ATENÇÃO`... |
| Postura ruim | igual | `POSTURA: RUIM` alternando com a linha cheia de blocos (o "invertido" do OLED) |
| Enquadramento | igual | texto à esquerda + os **3 pontos** nas 2 últimas colunas (cheio = visto, anel = não visto) |
| Troca de fase | tela inteira pisca com blocos (3 s) | |
| Wi-Fi conectando | primeiros 6 s: `REDE:` e `SENHA:` juntas (rolam se forem longas; `LCD_WIFI_CREDENCIAIS_S`); depois ícone + `CONECTANDO...` | `BANDA: 2.4 GHZ` e `CLIQUE: CANCELAR` alternando (volta às credenciais a cada ~11 s) |
| Wi-Fi resultado | ícone + `WIFI CONECTADO`/`WIFI FALHOU` | ✓/✗ + nome da rede |

- **Textos que não cabem em 16 colunas** ganham forma curta (só no LCD; tabela `FORMAS_CURTAS`):
  `POSTURA: SEM SERVIÇO` → `POSTURA: OFFLINE`, `APERTE B1: CALIBRAR` → `B1 P/ CALIBRAR`,
  `COMEÇANDO EM: 7s` → `COMEÇA EM 7s`, `SEGURE 3s: DESLIGAR` → `SEG.3s: DESLIGAR` etc. O que ainda não
  couber rola na horizontal.
- **Ícones e acentos** (Ç, Ã...) são caracteres desenhados em 5x8 na CGRAM, que só guarda **8 por
  tela**; se faltar vaga, a letra perde o acento. A ROM japonesa do LCD troca `\` por ¥ e `~` por →:
  esses dois também ganham desenho próprio (podem aparecer na senha do Wi-Fi).
- **Desligar pelo B3:** o aviso `DESLIGANDO...` fica 3 s (`LCD_APAGAR_APOS_S`) e o texto é apagado (display desligado).
  **A luz azul continua acesa**: o Pi desligado ainda manda 5 V pro pino e o backlight está direto nele
  (inferência; confirmar que o SSH caiu). Só apaga tirando da tomada ou com um transistor no backlight
  (não feito). **Só tire da tomada depois que o LED verde do Pi parar de piscar.**
- **Limitação:** o backlight é ligado direto no 5 V (sem GPIO), então não dá pra piscar a luz;
  o alerta pisca o conteúdo. Conferido só em prévia PNG, **não no LCD real**.

**Como o código lê o módulo** (pinos em `pomodoro_config.py`):
- O módulo tem resistor próprio, então o pino do Pi fica **sem pull interno** (`PULL_INTERNO_BOTOES = None`). A versão
  anterior usava o pull-up interno e `bounce_time` do gpiozero, pensada pro botão solto no GND; com o módulo isso
  brigava com o resistor dele (hipótese, não medida; o sintoma observado em 19/11 foi clique curto lido como longo e
  médio como curto).
- **Polaridade automática** (`POLARIDADE_BOTOES = "auto"`): ao iniciar, lê o nível parado de cada pino por 0,6 s e assume que
  o contrário é "apertado". **Não aperte nenhum botão ao iniciar.** Serve pro módulo que sobe e pro que desce ao apertar.
  A linha de log mostra o que foi descoberto (`journalctl -u pomodoro`). Pra forçar: `--polaridade alto|baixo`.
- **Filtro de repique próprio:** lê cada pino a cada 10 ms e só aceita uma mudança depois de 4 leituras seguidas iguais
  (40 ms), ao apertar e ao soltar. Repique e picos curtos são ignorados, e falhas de contato menores que 40 ms no meio de
  um aperto não o quebram. Valores do projeto (`AMOSTRA_S`, `AMOSTRAS_ESTAVEIS`), sem validação própria.
- Se o pino ocioso vier **instável** (mais de 10% das leituras diferentes), o log avisa `LINHA INSTAVEL`: aí o problema é
  fio, emenda ou pino flutuando, e software não conserta.
- **Diagnóstico:** `python diagnostico_botoes.py` (com o serviço parado) mostra as bordas cruas de cada pino e diz se o
  problema é repique, ruído com o botão solto ou polaridade. Tente `--pull baixo` e `--pull cima` se o módulo não
  tiver resistor próprio (OUT flutuando).

Os botões são classificados **ao soltar**: **curto** < 1 s, **longo** de 1 a 3 s, **muito longo** ≥ 3 s
(`LIMITE_LONGO_S` e `LIMITE_MUITO_LONGO_S` no `pomodoro_config.py`). Enquanto o botão está
segurado, a tela mostra o que vai acontecer ao soltar (`SOLTE: INICIAR`, `SOLTE: VOLTAR`...). Não há
dica fixa de "curto/longo" na tela (decisão de 19/11: ocupa espaço e não informa nada concreto); o mapa
dos botões vai num adesivo na caixa.

### B1: recalibrar a postura ou conectar o Wi-Fi

| B1 | O que acontece |
|---|---|
| **curto** | abre o menu na linha de baixo (`RECALIBRAR: POSTURA`); cada novo clique alterna **POSTURA → WIFI CONECTAR**. Antes da primeira calibração da postura aparece `CALIBRAR: POSTURA` |
| **longo** (≥ 1 s) | **executa a opção mostrada** (enquanto segura: `SOLTE: RECAL POSTURA` / `SOLTE: WIFI CONECTAR`); o menu fecha |
| sem clique por 5 s | o menu fecha sozinho (`MENU_B1_TIMEOUT_S`) e a linha de baixo volta a mostrar a postura |
| longo com o menu fechado | ignorado (aperto longo sem querer não faz nada); a partir de 1 s a linha mostra `SEGURE 5s: PAUSAR` |
| **segurar ≥ 5 s e soltar** (20/11) | **pausa a medição de postura** (o serviço fecha a câmera e para a análise; a tela mostra `POSTURA: PAUSADA`). De novo: **retoma e recalibra** (contagem de 10 s). Enquanto segura, aos 5 s: `SOLTE: PAUSAR` / `SOLTE: RETOMAR`. Vale com o menu aberto ou fechado. Pausa e retomada vão pros eventos (`b1_pausar_postura` aqui; `medicao_pausada`/`medicao_retomada` no serviço) |
| **curto na tela de espera do Wi-Fi** | cancela e volta à tela inicial |

- **Postura:** o pedido vai pro serviço (`postura recalibrar`) e a própria linha de baixo mostra as mensagens do serviço (`COMEÇANDO EM: 7s`, `CALIBRANDO...`...), com os 3 pontos do enquadramento.
- **Wi-Fi:** ver a seção abaixo.
- A **voz** saiu do menu em 19/11 (fora do escopo do TCC).

### Wi-Fi (T7)

O Pi entra numa rede **que o usuário cria** (ex.: hotspot do celular). Rede padrão: **`DIHMO`**,
senha **`admin1234`** (fraca de propósito, pra ser fácil). Pra trocar, por SSH ou no terminal do Pi:

```bash
wifi                                   # mostra a rede configurada
wifi --ssid MinhaRede --senha 12345678 # troca (grava e atualiza o perfil do NetworkManager)
```

No Pi: **B1 curto** até `WIFI CONECTAR` e **segure**. A tela cheia mostra:

- **Espera** (não fecha sozinha): `CONECTANDO...` animado, `REDE:`, `SENHA:` e `BANDA: 2.4 GHZ`
  (o Pi 3B só tem Wi-Fi 2.4 GHz: no iPhone 12+ ligue "Maximizar Compatibilidade"; no Android fixe 2.4 GHz).
  Enquanto isso o Pi repete `nmcli device wifi rescan` + `nmcli connection up tcc-wifi` a cada
  10 s, por até 120 s (o hotspot costuma ser criado **depois** de ler a senha). `CLIQUE: CANCELAR`.
- **Resultado** (3 s, depois volta à tela inicial): ícone com ✓ `WIFI CONECTADO` ou ✗ `WIFI FALHOU`, e o
  nome da rede. Conectado = perfil ativo no `wlan0` com endereço IPv4.
- **Já conectado na rede configurada:** mostra `WIFI CONECTADO` direto, **sem desconectar**.
- **Com SSH ativo e o Wi-Fi noutra rede:** trocar de rede derruba o SSH, então a primeira vez só mostra
  `SSH ATIVO: REPITA` e reabre o menu em `WIFI CONECTAR`; segurar de novo em até 5 s confirma.
- Durante as telas cheias o B2 não age (o pomodoro continua contando por baixo); o B3 aparece por cima.

Detalhes:
- **Fonte da verdade:** `~/.config/pomodoro/wifi.json` (permissão 600; outro caminho por `POMODORO_WIFI`). Sem ele,
  vale a padrão. O perfil no NetworkManager se chama `tcc-wifi` (WPA2-PSK, `autoconnect-priority -10`, abaixo
  das redes que você já usa pra desenvolver). O `instalar.sh` cria o perfil.
- **Validação do comando:** SSID de 1 a 32 caracteres, senha de 8 a 63 (ASCII) e, além disso, **rede e senha
  têm que caber na tela** (`REDE:  ` + nome ≤ 127 px na fonte da tela). Em vez de cortar com `~`, o comando
  recusa e diz quantos caracteres cabem (texto comum: ~14 na rede e ~13 na senha; só `W`: 9 e 8).
- **Permissão:** o serviço roda como usuário normal. Se o NetworkManager negar (`nmcli general permissions`), o
  código tenta `sudo -n nmcli` (igual ao `sudo -n poweroff` do B3).

### B3: desligar o Pi

| B3 | O que acontece |
|---|---|
| **clique curto** | só mostra `SEGURE 3s: DESLIGAR` na linha de baixo por 2 s (`B3_DICA_CLIQUE_S`), pra lembrar como desliga |
| segurar | a partir de 0,5 s a linha de baixo mostra `SEGURE 3s: DESLIGAR` (contagem); aos 3 s, `SOLTE: DESLIGAR PI` |
| **soltar depois de 3 s** (muito longo) | roda `sudo -n poweroff`; a tela mostra `DESLIGANDO, AGUARDE` e fica assim até o fim |
| soltar entre 1 e 3 s (longo) | **cancela**, não faz nada |
| comando falhou | `FALHOU DESLIGAR` por 3 s (quase sempre: o sudo pediu senha) |

- 3 s com soltar é de propósito: com botão que já deu leitura instável, um toque sem querer não derruba o sistema.
- **Pré-requisito:** o usuário precisa rodar `sudo poweroff` sem senha. No Raspberry Pi OS padrão isso costuma já valer;
  confira com `sudo -n true && echo ok`. Se o serviço rodar como root, não precisa de sudo.
- **O `poweroff` não corta a energia do Pi 3B** (ele não tem botão de power): depois dele só religando a fonte.
  Espere o **LED verde parar de piscar** antes de tirar da tomada. A tela mantém o último aviso até a energia cair.
- No notebook (`--botoes teclado`) o `3m` **não desliga a máquina**: só imprime o comando que rodaria.

### B2: pomodoro

| Estado | B2 curto | B2 longo (≥ 1 s) |
|---|---|---|
| Escolhendo o tempo | troca o preset | **inicia** o foco (`SOLTE: INICIAR`) |
| Rodando (foco ou descanso) | **pausa** | **volta** pra escolha e zera o bloco (`SOLTE: VOLTAR`) |
| Pausado | **retoma** | **volta** pra escolha |

No B2 o "muito longo" vale como longo (só o B3 usa os 3 s). Troca de 19/11: antes o curto era
ignorado fora da escolha; agora um toque sem querer **pausa** o timer, em troca de pausar com um
clique (usabilidade × segurança contra toque acidental; não testado no Pi).

## Telas (aprovadas em 19/11)

- **Escolha:** título `TEMPO`, o preset grande no meio e, só enquanto o B2 está segurado, `SOLTE: ...`.
- **Rodando:** canto esquerdo do topo = preset (`25/5`); canto direito = fase e ciclo (`FOCO 1/4`,
  `PAUSA 1/4`, `P.LONGA 4/4`; `P.LONGA` porque o nome inteiro encosta no preset). **Pausado:** ícone
  de pausa (duas barras) à esquerda da fase.
- **Linha de baixo (postura):** `POSTURA: BOA`, `POSTURA: ATENÇÃO`, `POSTURA: RUIM` (linha invertida),
  `POSTURA: SEM SERVIÇO` (serviço de postura fora), `COMEÇANDO EM: 7s` (contagem da calibração). Os
  outros avisos (`APERTE B1: CALIBRAR`, `CALIBRANDO...`, `SEM CAMERA`...) seguem como eram.
  `POSTURA: PAUSADA` quando a medição foi pausada pelo B1 (20/11).
- **Descanso do pomodoro (pausa curta e longa, 20/11):** a linha mostra `POSTURA: DESCANSO` no lugar
  de `BOA`/`ATENÇÃO`/`RUIM`/`SEM USUARIO` (a pessoa deve levantar: "sem usuário" é esperado). Falhas
  (`SEM SERVIÇO`, `SEM CAMERA`), calibração e `PAUSADA` aparecem normalmente. O serviço de postura
  continua gravando tudo no log; cruzar descanso × `SEM_USUARIO` é inferência, não prova de que a
  pessoa saiu.

## Enquadramento: os 3 pontos na tela

O produto não tem SSH: quem usa só vê o display. Por isso, enquanto a pessoa se ajeita pra
calibrar (`AJEITE-SE!`), durante a calibração, quando ela falha e quando o sistema não acha o
usuário (`SEM USUARIO`), o canto direito da linha de baixo mostra uma **mini-figura com os 3
pontos que a postura usa**: a orelha (em cima) e os dois ombros (embaixo). **Cheio** = a
câmera está vendo o ponto; **vazado** = não está. A instrução pro usuário é uma só: **deixe os
três pontos cheios** (ajuste a câmera, a cadeira ou a distância).

- A informação vem do serviço de postura (`pontos_visiveis` no status, confiança acima de 0,4).
- A orelha aparece sobre o ombro da **direita** de quem olha, porque a imagem é espelhada. Isso é
  inferência pela convenção do MoveNet: **conferir no Pi** (se sair trocado, inverter
  `X_OMBRO_ORELHA` e `X_OUTRO_OMBRO` no `display.py`).

## Como o ciclo funciona

Foco → pausa → foco → ... sozinho, sem apertar nada. A cada 4 focos
(`CICLOS_ATE_PAUSA_LONGA`) a pausa é a longa. Não há buzzer (decisão de projeto, ver
`claude/00-visao-geral.md`): quando a fase troca, **a tela pisca por 3 s**.

### Presets (T6)

Vem **um** pré-configurado: **25/5** (foco 25 min, pausa 5 min, pausa longa 15 min a cada 4 focos).
O 25/5 é o padrão da técnica Pomodoro; os 15 min da pausa longa são escolha do projeto, **sem
validação própria**. O usuário adiciona os dele pelo comando `pomodoro` (instalado pelo `instalar.sh`):

```bash
pomodoro listar                       # o 1º (com *) é o pré-configurado
pomodoro adicionar --preset 50/10     # FOCO/PAUSA em minutos: sem pausa longa
pomodoro adicionar --preset 50/10/20  # o 3º número é a pausa longa
pomodoro remover --preset 50/10       # o pré-configurado não sai
```

- Regras: minutos inteiros de **1 a 180**; pausa longa **≥ pausa**; sem duplicata (nem do
  pré-configurado). Se algo não vale, o comando diz o porquê e **nada é gravado**.
- **Sem o 3º número não há pausa longa:** foco e pausa se alternam sem fim e o topo mostra só a
  fase (`FOCO`, sem o `1/4`).
- Ficam em `~/.config/pomodoro/presets.json` (fora do repositório, o `git pull` não apaga; outro
  caminho pela variável `POMODORO_PRESETS`). O serviço **recarrega sozinho** quando a tela de escolha
  (`TEMPO`) está aberta, sem reiniciar.
- Na escolha, nomes compridos (`50/10/20`) usam uma fonte menor pra caber.
- No Windows: `python pomodoro_ctl.py listar` (não há o atalho `pomodoro`).
- A faixa de 1 a 180 min é escolha do projeto, sem fonte.

## Arquivos

| Arquivo | Função |
|---|---|
| `main.py` | Laço principal: junta botões, timer, postura e tela |
| `pomodoro_logica.py` | Máquina de estados (pura: não sabe de GPIO nem de tela) |
| `botoes.py` | Filtro de repique, polaridade automática, classificação curto/longo/muito longo + botões reais (gpiozero, por amostragem) e simulados (teclado) |
| `energia.py` | B3: desligar o Pi (`sudo poweroff`), contagem na tela e aviso de falha |
| `registro_pomodoro.py` | **Log do pomodoro** no arquivo de eventos do Pi: grava só as transições (lógica pura) |
| `diagnostico_botoes.py` | Mostra as bordas cruas dos pinos no Pi (repique × ruído × polaridade) |
| `display.py` | Desenho da tela 128x64 + backends (OLED, emulador pygame, PNG); escolhe entre OLED e LCD |
| `display_lcd.py` | Telas no LCD 16x2 (mesmas funções do `display.py`) + backend real e prévia PNG |
| `lcd_hd44780.py` | Driver do LCD HD44780 em 4 bits (gpiozero) |
| `postura_cliente.py` | Consulta o `postura_servico.py` pelo socket Unix (sem mexer na câmera) |
| `recalibracao.py` | Menu do B1 (postura → Wi-Fi; lógica pura) |
| `wifi.py` | Wi-Fi: rede configurada, validação (WPA2 + cabe na tela), `nmcli` e a conexão em thread |
| `wifi_ctl.py` | O comando `wifi` (`wifi --ssid X --senha Y`) |
| `presets.py` | Presets: o pré-configurado + os do usuário (JSON), validação de `MM/MM[/MM]` |
| `pomodoro_ctl.py` | O comando `pomodoro` (`listar`, `adicionar --preset`, `remover --preset`) |
| `pomodoro_config.py` | **Preset de fábrica, pinos, polaridade e filtro dos botões, limites de aperto, endereço do OLED** |
| `test_pomodoro.py`, `test_display_lcd.py` | Testes automáticos |
| `instalar.sh` | Instala como serviço do systemd (inicia no boot) |

## Testar sem hardware (notebook)

```bash
pip install pillow           # só isso pra testar a lógica e gerar PNG
python -m unittest -v        # testes (de dentro da pasta pomodoro/)

# Tela vira um PNG (/tmp/pomodoro_tela.png) e os botões viram teclado:
python main.py --display lcd-png --botoes teclado     # prévia do LCD 16x2 (--display png = OLED)
#   digite:  1c = B1 curto | 1l = B1 longo | 2c = B2 curto | 2l = B2 longo | 2m = B2 muito longo | 3m = B3 (só simula o desligar) | q = sair
# No notebook sem NetworkManager, o WIFI CONECTAR mostra WIFI FALHOU (sem nmcli)

# Demo acelerada (1 s real = 1 min): bom pra ver a troca de fase e a pausa longa
python main.py --display png --botoes teclado --velocidade 60
```

Janela do emulador em vez de PNG: `pip install luma.emulator pygame` e `--display pygame`.
Sem o serviço de postura rodando, a linha de baixo mostra `POSTURA: SEM SERVIÇO`.

## No Raspberry Pi

```bash
source ~/venv-tcc/bin/activate
pip install -r req.txt
sudo raspi-config            # Interface Options → I2C (já ativado se o i2cdetect mostrou 3c)
python main.py               # LCD + botões de verdade (OLED: --display oled)
```

Se o `pip install` do `gpiozero`/`lgpio` falhar nesse venv (Python 3.11 compilado),
anote a mensagem de erro: ainda não foi testado nesse ambiente.

Pra iniciar no boot: `bash instalar.sh` (sem `sudo` na frente). Depois:
`sudo journalctl -u pomodoro -f` acompanha o log e `sudo systemctl restart pomodoro` reinicia.

**Teste de bancada dos botões (Pi desligado da câmera/serviço):** `sudo systemctl stop pomodoro` e
`python diagnostico_botoes.py` (5 s sem tocar; depois 5 cliques curtos em cada botão e um aperto de ~2 s; Ctrl+C mostra o resumo).
Depois `python main.py` e confira no log a polaridade descoberta de cada botão.

## Log (`~/tcc-logs/eventos_AAAA-MM-DD.csv`)

O pomodoro grava cada transição no arquivo de eventos do Pi (ver `registro/README.md`): troca de
preset, início e fim de foco/pausa/pausa longa (com preset e ciclo), pausar/retomar, voltar pra
seleção, o pedido de desligar pelo B3 e `servico_iniciou`/`servico_parou` com a versão do código.
Serve pra cruzar com a postura e com a saúde do Pi pelo horário.

## Limitações

- O log de eventos não rodou no Pi ainda (testado no notebook).
- Não foi testado no hardware real (OLED, módulos de botão, `sudo poweroff` pelo B3, fonte de energia do Pi). A leitura dos
  botões foi testada com pinos simulados (`MockFactory` do gpiozero) e sequências sintéticas de repique, não com o módulo real.
- A polaridade automática falha se um botão estiver apertado ao iniciar (inverte a lógica daquele botão até reiniciar).
- A tela usa **DejaVu Sans Bold** (tem acentos: `ATENÇÃO`, `SERVIÇO`, `COMEÇANDO`). Sem ela o Pillow
  cai na fonte padrão, os acentos somem e o layout muda; o `instalar.sh` avisa
  (`sudo apt install fonts-dejavu-core`). Alguns textos antigos seguem sem acento (`CALIBRACAO FALHOU`).
- Se o serviço de postura já estiver calibrando, ele recusa o pedido do B1 (não faz nada).
- Menu do B1 com fechamento em 5 s, o limiar de 1 s do "longo", o de 3 s do desligar e o filtro de 40 ms são escolhas do projeto, sem validação própria.
- **Wi-Fi: nada testado no Pi** (só com `nmcli` falso nos testes). A testar: permissão do usuário do serviço
  (`nmcli general permissions`), tempo até conectar após o botão e após o boot, se o `rescan` + `up` repetido
  ajuda de fato, senha errada sem tela, `raspberrypi.local` no hotspot do celular, power save do Wi-Fi.
- Timeout de 120 s, intervalo de 10 s, prioridade -10 e resultado por 3 s: escolhas do projeto, sem validação.
- Senha padrão fraca de propósito: enquanto o usuário não troca com `wifi --ssid X --senha Y`, qualquer rede
  `DIHMO` com essa senha atrai o Pi. A senha digitada no comando fica no histórico do shell.
- O pedido do Wi-Fi confere a rede atual e o SSH na hora do aperto (chamadas rápidas ao `nmcli`/`ss`; se
  travarem, a tela congela até o timeout delas: até 8 s no pior caso).
