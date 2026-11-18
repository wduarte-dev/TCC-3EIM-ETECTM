# Pomodoro (display OLED + 2 botões)

Timer de foco/pausa que roda no Raspberry Pi e mostra tudo no display OLED
128x64. Também mostra, na linha de baixo, o status do monitor de postura
(`sensor-postura/`) e deixa o usuário recalibrar a **postura** ou a **voz** (`sensor-voz/`)
pelo botão B1.

> **Estado:** a lógica, a tela e a ligação com a postura foram testadas no
> notebook (testes automáticos + simulação). **Ainda não foi testado no Pi com o
> OLED e os botões de verdade.**

## Botões

| Botão | Ligação | O que faz |
|---|---|---|
| **B1** | GPIO17 (pino 11) ↔ GND (pino 9) | **Recalibração** (postura ou voz; tabela abaixo). **Não mexe no pomodoro** |
| **B2** | GPIO27 (pino 13) ↔ GND (pino 14) | Pomodoro (tabela abaixo) |

Sem resistor externo: o Pi usa o pull-up interno. Não usar os pinos 3 e 5 (I2C do display).

Os dois botões são classificados **ao soltar**: **curto** < 1 s, **longo** de 1 a 3 s, **muito longo** ≥ 3 s
(`LIMITE_LONGO_S` e `LIMITE_MUITO_LONGO_S` no `pomodoro_config.py`). Enquanto o botão está
segurado, a tela mostra o que vai acontecer ao soltar (`SOLTE: PAUSAR`, `SOLTE: REINICIAR`...).

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

### B2: pomodoro

| Estado | B2 curto | B2 longo | B2 muito longo |
|---|---|---|---|
| Escolhendo o tempo | troca o preset | **inicia** o foco | nada |
| Rodando (foco ou descanso) | ignora | **pausa** | **reinicia** (volta pra escolha) |
| Pausado | ignora | **retoma** | **reinicia** |

Curto fora da escolha é ignorado de propósito: um toque sem querer não atrapalha o timer.

## Como o ciclo funciona

Foco → pausa → foco → ... sozinho, sem apertar nada. A cada 4 focos
(`CICLOS_ATE_PAUSA_LONGA`) a pausa é a longa. Não há buzzer (decisão de projeto, ver
`claude/00-visao-geral.md`): quando a fase troca, **a tela pisca por 3 s**.

Presets (em `pomodoro_config.py`, é só editar a lista):

| Preset | Foco | Pausa | Pausa longa |
|---|---|---|---|
| 25/5 | 25 min | 5 min | 15 min |
| 50/10 | 50 min | 10 min | 20 min |
| 90/20 | 90 min | 20 min | 30 min |

O 25/5 é o padrão da técnica Pomodoro; os outros são variações populares e os
tempos de pausa longa são escolha do projeto, **sem validação própria**.

## Arquivos

| Arquivo | Função |
|---|---|
| `main.py` | Laço principal: junta botões, timer, postura e tela |
| `pomodoro_logica.py` | Máquina de estados (pura: não sabe de GPIO nem de tela) |
| `botoes.py` | Classificação curto/longo/muito longo + botões reais (gpiozero) e simulados (teclado) |
| `display.py` | Desenho da tela + backends (OLED, emulador pygame, PNG) |
| `postura_cliente.py` | Consulta o `postura_servico.py` pelo socket Unix (sem mexer na câmera) |
| `recalibracao.py` | Menu do B1 (postura ↔ voz; lógica pura) |
| `voz_cliente.py` | Recalibração da voz em thread, reaproveitando `sensor-voz/main.py` |
| `pomodoro_config.py` | **Presets, pinos, limites de aperto, endereço do OLED** |
| `test_pomodoro.py` | Testes automáticos |
| `instalar.sh` | Instala como serviço do systemd (inicia no boot) |

## Testar sem hardware (notebook)

```bash
pip install pillow           # só isso pra testar a lógica e gerar PNG
python -m unittest -v        # testes (de dentro da pasta pomodoro/)

# Tela vira um PNG (/tmp/pomodoro_tela.png) e os botões viram teclado:
python main.py --display png --botoes teclado
#   digite:  1c = B1 curto | 1l = B1 longo | 2c = B2 curto | 2l = B2 longo | 2m = B2 muito longo | q = sair
# Pra testar o B1 da voz sem mic nem Praat, acrescente --voz simulada

# Demo acelerada (1 s real = 1 min): bom pra ver a troca de fase e a pausa longa
python main.py --display png --botoes teclado --velocidade 60
```

Janela do emulador em vez de PNG: `pip install luma.emulator pygame` e `--display pygame`.
Sem o serviço de postura rodando, a linha de baixo mostra `POSTURA OFFLINE`.

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

**Teste de bancada dos botões sem comprar o módulo:** com o jumper, encoste o
GPIO17 (pino 11) no GND (pino 9) = B1 (curto = alterna, ≥ 1 s = recalibra). Encostar o GPIO27 (pino 13) no GND (pino 14)
pelo tempo desejado = B2 (1 s = longo, 3 s = muito longo).

## Limitações

- Não foi testado no hardware real (OLED, botões, fonte de energia do Pi).
- A fonte padrão do Pillow não tem acentos; os textos da tela são sem acento de propósito.
- O aspecto da tela no OLED depende da fonte instalada no Pi (usa DejaVu Sans Bold se existir,
  senão a fonte padrão do Pillow).
- Se o serviço de postura já estiver calibrando, ele recusa o pedido do B1 (não faz nada).
- A calibração da voz grava `sensor-voz/baseline_voz.json`, que **não é versionado** (`.gitignore`): cada máquina/mic tem a sua. Sem ele o menu do B1 mostra `CALIBRAR: VOZ`. Se o Pi já tinha o arquivo vindo do repo, o `git pull` apaga a cópia (aí é só calibrar de novo).
- Menu do B1 com fechamento em 5 s e o limiar de 1 s do "longo" são escolhas do projeto, sem validação própria.
- A recalibração da voz pelo B1 foi testada só com a voz simulada e testes automáticos; mic e Praat reais ainda não.
