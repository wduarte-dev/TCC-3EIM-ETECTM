# Pomodoro (display OLED + 3 botões)

Timer de foco/pausa que roda no Raspberry Pi e mostra tudo no display OLED
128x64. Também mostra, na linha de baixo, o status do monitor de postura
(`sensor-postura/`) e deixa o usuário recalibrar a **postura** ou a **voz** (`sensor-voz/`)
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
| OUT do **B1** | pino 11 (GPIO17): **recalibração** (postura ou voz; tabela abaixo). Não mexe no pomodoro |
| OUT do **B2** | pino 13 (GPIO27): pomodoro (tabela abaixo) |
| OUT do **B3** | pino 15 (GPIO22): **desligar o Pi** (seção abaixo) |

Não usar os pinos 3 e 5 (I2C do display).

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

### B1: recalibrar postura ou voz

| B1 | O que acontece |
|---|---|
| **curto** | abre o menu na linha de baixo (`RECALIBRAR: POSTURA`); cada novo clique alterna **POSTURA ↔ VOZ**. Quem ainda não foi calibrada (postura `AGUARDANDO_CALIBRACAO`; voz sem `baseline_voz.json`) aparece como `CALIBRAR: ...`; depois da primeira vez vira `RECALIBRAR: ...` |
| **longo** (≥ 1 s) | **recalibra a opção mostrada** (enquanto segura aparece `SOLTE: RECAL ...`); o menu fecha |
| sem clique por 5 s | o menu fecha sozinho (`MENU_B1_TIMEOUT_S`) e a linha de baixo volta a mostrar a postura |
| longo com o menu fechado | ignorado (aperto longo sem querer não recalibra nada) |
| qualquer aperto durante a recalibração da voz | ignorado |

- **Postura:** o pedido vai pro serviço (`postura recalibrar`) e a própria linha de baixo mostra as mensagens do serviço (`AJEITE-SE! 7s`, `CALIBRANDO...`...).
- **Voz:** grava 2 vezes 3 s de "AAAA" e salva a baseline (reaproveita o `sensor-voz/main.py`). Mensagens: `VOZ 1/2: PREPARE-SE` (2 s) → `VOZ 1/2: FALE AAAA` → `VOZ 1/2: ANALISANDO` → idem 2/2 → `VOZ CALIBRADA` (ou `VOZ FALHOU` / `SEM MIC/PRAAT`, que somem após 3 s). Deixa o ambiente silencioso e a mesma posição do mic de sempre: baseline de um ambiente não vale pra outro.
- Isso só **recalibra** a voz. Como a **medição** normal da voz é disparada ainda está em aberto.

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
| `diagnostico_botoes.py` | Mostra as bordas cruas dos pinos no Pi (repique × ruído × polaridade) |
| `display.py` | Desenho da tela + backends (OLED, emulador pygame, PNG) |
| `postura_cliente.py` | Consulta o `postura_servico.py` pelo socket Unix (sem mexer na câmera) |
| `recalibracao.py` | Menu do B1 (postura ↔ voz; lógica pura) |
| `voz_cliente.py` | Recalibração da voz em thread, reaproveitando `sensor-voz/main.py` |
| `presets.py` | Presets: o pré-configurado + os do usuário (JSON), validação de `MM/MM[/MM]` |
| `pomodoro_ctl.py` | O comando `pomodoro` (`listar`, `adicionar --preset`, `remover --preset`) |
| `pomodoro_config.py` | **Preset de fábrica, pinos, polaridade e filtro dos botões, limites de aperto, endereço do OLED** |
| `test_pomodoro.py` | Testes automáticos |
| `instalar.sh` | Instala como serviço do systemd (inicia no boot) |

## Testar sem hardware (notebook)

```bash
pip install pillow           # só isso pra testar a lógica e gerar PNG
python -m unittest -v        # testes (de dentro da pasta pomodoro/)

# Tela vira um PNG (/tmp/pomodoro_tela.png) e os botões viram teclado:
python main.py --display png --botoes teclado
#   digite:  1c = B1 curto | 1l = B1 longo | 2c = B2 curto | 2l = B2 longo | 2m = B2 muito longo | 3m = B3 (só simula o desligar) | q = sair
# Pra testar o B1 da voz sem mic nem Praat, acrescente --voz simulada

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
python main.py               # OLED + botões de verdade
```

Pra recalibrar a **voz** pelo B1 o venv também precisa das dependências do `sensor-voz`
(`pip install -r ../sensor-voz/req.txt`), mais `sudo apt install praat libportaudio2` (o
`sounddevice` não importa sem a PortAudio). Sem isso a tela mostra `SEM MIC/PRAAT`.

Se o `pip install` do `gpiozero`/`lgpio` falhar nesse venv (Python 3.11 compilado),
anote a mensagem de erro: ainda não foi testado nesse ambiente.

Pra iniciar no boot: `bash instalar.sh` (sem `sudo` na frente). Depois:
`sudo journalctl -u pomodoro -f` acompanha o log e `sudo systemctl restart pomodoro` reinicia.

**Teste de bancada dos botões (Pi desligado da câmera/serviço):** `sudo systemctl stop pomodoro` e
`python diagnostico_botoes.py` (5 s sem tocar; depois 5 cliques curtos em cada botão e um aperto de ~2 s; Ctrl+C mostra o resumo).
Depois `python main.py` e confira no log a polaridade descoberta de cada botão.

## Limitações

- Não foi testado no hardware real (OLED, módulos de botão, `sudo poweroff` pelo B3, fonte de energia do Pi). A leitura dos
  botões foi testada com pinos simulados (`MockFactory` do gpiozero) e sequências sintéticas de repique, não com o módulo real.
- A polaridade automática falha se um botão estiver apertado ao iniciar (inverte a lógica daquele botão até reiniciar).
- A tela usa **DejaVu Sans Bold** (tem acentos: `ATENÇÃO`, `SERVIÇO`, `COMEÇANDO`). Sem ela o Pillow
  cai na fonte padrão, os acentos somem e o layout muda; o `instalar.sh` avisa
  (`sudo apt install fonts-dejavu-core`). Alguns textos antigos seguem sem acento (`CALIBRACAO FALHOU`).
- Se o serviço de postura já estiver calibrando, ele recusa o pedido do B1 (não faz nada).
- A calibração da voz grava `sensor-voz/baseline_voz.json`, que **não é versionado** (`.gitignore`): cada máquina/mic tem a sua. Sem ele o menu do B1 mostra `CALIBRAR: VOZ`. Se o Pi já tinha o arquivo vindo do repo, o `git pull` apaga a cópia (aí é só calibrar de novo).
- Menu do B1 com fechamento em 5 s, o limiar de 1 s do "longo", o de 3 s do desligar e o filtro de 40 ms são escolhas do projeto, sem validação própria.
- A recalibração da voz pelo B1 foi testada só com a voz simulada e testes automáticos; mic e Praat reais ainda não.
