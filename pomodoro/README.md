# Pomodoro (display OLED + 2 botões)

Timer de foco/pausa que roda no Raspberry Pi e mostra tudo no display OLED
128x64. Também mostra, na linha de baixo, o status do monitor de postura
(`sensor-postura/`) e deixa o usuário recalibrar a postura por um botão.

> **Estado:** a lógica, a tela e a ligação com a postura foram testadas no
> notebook (testes automáticos + simulação). **Ainda não foi testado no Pi com o
> OLED e os botões de verdade.**

## Botões

| Botão | Ligação | O que faz |
|---|---|---|
| **B1** | GPIO17 (pino 11) ↔ GND (pino 9) | Qualquer aperto: **recalibrar a postura** (equivale a `postura recalibrar`) |
| **B2** | GPIO27 (pino 13) ↔ GND (pino 14) | Pomodoro (tabela abaixo) |

Sem resistor externo: o Pi usa o pull-up interno. Não usar os pinos 3 e 5 (I2C do display).

O B2 é classificado **ao soltar**: **curto** < 1 s, **longo** de 1 a 3 s, **muito longo** ≥ 3 s
(`LIMITE_LONGO_S` e `LIMITE_MUITO_LONGO_S` no `pomodoro_config.py`). Enquanto o botão está
segurado, a tela mostra o que vai acontecer ao soltar (`SOLTE: PAUSAR`, `SOLTE: REINICIAR`...).

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
| `pomodoro_config.py` | **Presets, pinos, limites de aperto, endereço do OLED** |
| `test_pomodoro.py` | Testes automáticos |
| `instalar.sh` | Instala como serviço do systemd (inicia no boot) |

## Testar sem hardware (notebook)

```bash
pip install pillow           # só isso pra testar a lógica e gerar PNG
python -m unittest -v        # testes (de dentro da pasta pomodoro/)

# Tela vira um PNG (/tmp/pomodoro_tela.png) e os botões viram teclado:
python main.py --display png --botoes teclado
#   digite:  1 = B1 | 2c = B2 curto | 2l = B2 longo | 2m = B2 muito longo | q = sair

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

Se o `pip install` do `gpiozero`/`lgpio` falhar nesse venv (Python 3.11 compilado),
anote a mensagem de erro: ainda não foi testado nesse ambiente.

Pra iniciar no boot: `bash instalar.sh` (sem `sudo` na frente). Depois:
`sudo journalctl -u pomodoro -f` acompanha o log e `sudo systemctl restart pomodoro` reinicia.

**Teste de bancada dos botões sem comprar o módulo:** com o jumper, encoste o
GPIO17 (pino 11) no GND (pino 9) = B1. Encostar o GPIO27 (pino 13) no GND (pino 14)
pelo tempo desejado = B2 (1 s = longo, 3 s = muito longo).

## Limitações

- Não foi testado no hardware real (OLED, botões, fonte de energia do Pi).
- A fonte padrão do Pillow não tem acentos; os textos da tela são sem acento de propósito.
- O aspecto da tela no OLED depende da fonte instalada no Pi (usa DejaVu Sans Bold se existir,
  senão a fonte padrão do Pillow).
- O B1 age ao apertar; se o serviço de postura estiver calibrando, ele recusa o pedido (não faz nada).
