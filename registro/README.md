# Registro do Pi (saúde, eventos e rotação)

Logs pra **explorar e cruzar informações** e pra ter registrado **o motivo quando algo der
errado**, sem esperar o problema repetir (ex.: o reboot de 20/11/2026 ficou sem explicação
porque não havia log do que veio antes). Decidido em 20/11/2026.

| Arquivo | Função |
|---|---|
| `registro_comum.py` | Arquivo por dia, rotação, horário com fuso e versão do código. Usado pela saúde, pela postura e pelo pomodoro |
| `saude.py` | **Log de saúde**: serviço próprio (`tcc-saude`), ligado desde o boot |
| `instalar.sh` | Instala o `tcc-saude` no systemd |
| `test_registro.py` | Testes sem o Pi |

## Onde ficam os arquivos

`~/tcc-logs/` (na home: o serviço roda como o usuário, sem sudo, e é fácil de copiar por `scp`).
A variável `TCC_LOGS` troca a pasta.

| Arquivo | Uma linha por | Quem grava |
|---|---|---|
| `saude_AAAA-MM-DD.csv` | amostra (~5 s) | `tcc-saude` |
| `eventos_AAAA-MM-DD.csv` | mudança (só quando algo muda) | pomodoro, postura e o próprio `tcc-saude` |

**Mesmo relógio:** todos os arquivos usam horário ISO **com fuso** (`2026-11-20T21:39:05.123-03:00`),
pra juntar por horário no pandas.

**Versão do código:** cada vez que um processo abre o arquivo do dia, ele escreve uma linha
`# versao_codigo=<hash> processo=<nome> aberto=<horário>`. O hash vem do `.git` do Pi (o código
chega por `git pull`); `+alterado` quando há mudança não commitada em arquivo versionado (senão o
hash "mentiria" num teste); `desconhecida` sem `.git`. Ler no pandas com:

```python
import pandas as pd
saude = pd.read_csv("saude_2026-11-21.csv", comment="#", parse_dates=["data_hora"])
```

Por causa do `comment="#"`, nenhum valor gravado leva `#` (vira `n.`).

## Eventos (`eventos_AAAA-MM-DD.csv`)

Colunas `data_hora, origem, evento, detalhe`. Dois processos (pomodoro e postura) escrevem no
mesmo arquivo: cada linha sai numa única escrita com `O_APPEND`, e só quem cria o arquivo escreve
o cabeçalho.

| Origem | Evento | Detalhe |
|---|---|---|
| `pomodoro` | `preset` | nome do preset escolhido na seleção |
| `pomodoro` | `foco_inicio`, `foco_fim`, `pausa_inicio`, `pausa_fim`, `pausa_longa_inicio`, `pausa_longa_fim` | `preset=25/5 ciclo=2/4` |
| `pomodoro` | `pausou`, `retomou` | a fase + preset e ciclo |
| `pomodoro` | `voltou_selecao` | a fase interrompida (longo no B2) |
| `postura` | `estado` | status do serviço a cada **mudança** (`CORRETA`, `ATENCAO`, `ALERTA`, `SEM_USUARIO`, `AGUARDANDO_CALIBRACAO`, `CALIBRANDO`, `SEM_CAMERA`...), com o fps quando está analisando. No OLED: `CORRETA` = BOA, `ATENCAO` = ATENÇÃO, `ALERTA` = RUIM |
| `postura` | `calibracao_ok` | ao vivo/vídeo, ângulo e razão da baseline, quadros válidos |
| `postura` | `calibracao_falhou` | o ponto que mais faltou (orelha/ombro) e quadros válidos |
| `sistema` | `servico_iniciou` | serviço (`postura`, `pomodoro`, `saude`), versão do código e pid |
| `sistema` | `servico_parou` | serviço; **só em parada limpa** (`systemctl stop`, `poweroff`) |
| `sistema` | `desligar_b3` | o B3 pediu o `poweroff` |

Eventos de `sistema` vão com `fsync`; os outros não (a postura pode mudar de estado várias vezes
por minuto e o `fsync` gasta o cartão): numa queda de energia os últimos segundos deles podem se
perder.

**Cruzar pomodoro × postura** (ex.: `SEM_USUARIO` durante a pausa): o log só registra. `SEM_USUARIO`
na pausa **não prova** que a pessoa saiu do PC (pode estar vendo um vídeo na frente da câmera):
qualquer leitura disso é inferência e deve ser declarada assim na banca.

```python
ev = pd.read_csv("eventos_2026-11-21.csv", comment="#", parse_dates=["data_hora"])
junto = pd.merge_asof(saude.sort_values("data_hora"), ev.sort_values("data_hora"),
                      on="data_hora", direction="backward")   # o último evento antes de cada amostra
```

## Rotação

Um arquivo por dia. Ao abrir o do dia (e a cada 10 min), apaga os **mais antigos que 7 dias**;
se o grupo passou do **teto**, apaga o mais antigo antes dos 7 dias (o de hoje nunca).

| Grupo | Teto |
|---|---|
| `saude_*` + `eventos_*` | 100 MB |

Arquivos antigos **não** são guardados pro TCC: pra guardar um período, copie antes.

**Tamanho estimado (conta, não medido):** saúde ~1 MB/dia (~60 bytes × 17 mil amostras); eventos
dependem de quanto a postura oscila (cada linha ~70 bytes).

## Log de saúde (`saude.py`, serviço `tcc-saude`)

Sempre ligado desde o boot, **independente do serviço de postura**. Uma amostra a cada ~5 s,
**gravada no cartão a cada amostra** (`fsync`): se a energia cair, o que estava só na memória se
perde, e é justamente o registro que mais interessa.

| Coluna | O que é |
|---|---|
| `data_hora` | ISO com fuso |
| `throttled` | `vcgencmd get_throttled` em hex |
| `subtensao_agora` | bit 0: subtensão **neste instante** (1/0) |
| `throttling_agora` | bit 2: CPU limitada **neste instante** (1/0) |
| `temp_c` | temperatura da CPU (`/sys/class/thermal/thermal_zone0/temp`) |
| `carga_1min` | carga média de 1 min (4 núcleos: 4,0 = tudo ocupado) |
| `ram_disponivel_mb` | `MemAvailable` do `/proc/meminfo` |
| `uptime_s` | segundos desde o boot |

Os bits 16 a 19 do `get_throttled` ("já aconteceu") ficam marcados até o próximo reboot; só os
bits 0 a 3 ("agora") dizem **quando** aconteceu, por isso a amostragem. O fps **não** entra aqui
(só existe com a postura rodando).

**Como achar um reboot:** `uptime_s` pequeno logo depois de um grande. Olhar as últimas amostras
antes dele (`subtensao_agora`, `temp_c`) e, nos eventos, se houve `servico_parou` (parada limpa)
ou não (queda de energia ou travamento: **indício, não prova**).

### Instalar no Pi

```bash
cd ~/tcc-3eim-etectm/registro
bash instalar.sh          # sem sudo na frente; mostra uma amostra de teste
tail -f ~/tcc-logs/saude_$(date +%F).csv
```

Usa só a biblioteca padrão: roda com o `python3` do sistema, sem o venv. Teste rápido sem
instalar: `python3 saude.py --uma`.

## Testes

```bash
python -m unittest -v        # de dentro de registro/
```

Rotação (7 dias, teto do grupo, nunca o de hoje, sufixo `_v2`), arquivo do dia (cabeçalho,
linha de versão, dois processos no mesmo arquivo com um cabeçalho só, virada do dia, `#` e
quebra de linha nos valores, falha de disco sem derrubar), eventos, versão (hash, `+alterado`,
sem `.git`) e a amostra de saúde com leituras falsas. Os eventos do pomodoro são testados em
`pomodoro/test_pomodoro.py` e os da postura em `sensor-postura/test_servico_registro.py`.

## Limitações (declarar na banca)

- **Nada disto rodou no Pi ainda** (testado no Linux do notebook, com leituras falsas).
- `fsync` a cada 5 s gasta um pouco o cartão SD (escolha consciente: o registro de antes de uma
  queda vale mais). Não medido.
- Um `servico_iniciou` sem `servico_parou` antes **sugere** queda de energia ou travamento, mas
  não prova a causa.
- Eventos que não são de `sistema` vão sem `fsync`: numa queda, os últimos segundos podem faltar.
- Na demo acelerada do pomodoro (`--velocidade` alta) um passo pode atravessar mais de uma fase e
  o log mostra só a primeira e a última.
- Os tamanhos por dia são estimativas por conta, não medidas.
