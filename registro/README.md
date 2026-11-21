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

## Rotação

Um arquivo por dia. Ao abrir o do dia (e a cada 10 min), apaga os **mais antigos que 7 dias**;
se o grupo passou do **teto**, apaga o mais antigo antes dos 7 dias (o de hoje nunca).

| Grupo | Teto |
|---|---|
| `saude_*` + `eventos_*` | 100 MB |

Arquivos antigos **não** são guardados pro TCC: pra guardar um período, copie antes.

**Tamanho estimado (conta, não medido):** saúde ~1 MB/dia (~60 bytes × 17 mil amostras).

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
quebra de linha nos valores, falha de disco sem derrubar), versão (hash, `+alterado`, sem `.git`)
e a amostra de saúde com leituras falsas.

## Limitações (declarar na banca)

- **Nada disto rodou no Pi ainda** (testado no Linux do notebook, com leituras falsas).
- `fsync` a cada 5 s gasta um pouco o cartão SD (escolha consciente: o registro de antes de uma
  queda vale mais). Não medido.
- Um `servico_iniciou` sem `servico_parou` antes **sugere** queda de energia ou travamento, mas
  não prova a causa.
- Os tamanhos por dia são estimativas por conta, não medidas.
