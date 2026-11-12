# Sensor de postura

Monitora a postura pela webcam usando o MoveNet (TFLite). Roda **sem tela** no
Raspberry Pi 3B como serviço do systemd, inicia sozinho no boot e é controlado
pelo comando `postura`.

## Arquivos

| Arquivo | Função |
|---|---|
| `postura_servico.py` | O monitor em si: câmera/vídeo → MoveNet → cálculo de postura → status + log |
| `postura_ctl.py` | O comando `postura` (status, recalibrar, gravar, janela...) |
| `postura_config.py` | Limiares, tempos e caminhos. **Ajuste os valores aqui.** |
| `instalar.sh` | Instala o serviço do systemd e o comando `postura` |
| `movenet_lightning.tflite` | Modelo de detecção de pose |
| `main-otimizado-rpi3b.py` | Versão anterior (com janela, ENTER pra calibrar). Mantida como referência |
| `videos/` | Vídeos de teste (não vão pro Git) |
| `logs/` | Um CSV por dia com todas as medições (não vai pro Git) |
| `baseline.json` | Última calibração ao vivo (gerado sozinho, não vai pro Git) |

## Como funciona

1. **Ao ligar, o sistema fica AGUARDANDO CALIBRAÇÃO.** A câmera fica ligada, mas
   nada é analisado e nenhum alerta é dado. Isso evita calibrar com a cadeira
   vazia ou com a pessoa ainda se ajeitando.
2. **`postura recalibrar`** inicia uma contagem de **10 s** pra pessoa se ajeitar e
   depois coleta **5 s** de amostras. A média vira a **baseline**, a referência de
   postura correta daquela pessoa e daquela câmera.
3. **Duas medidas**, a partir da orelha e dos dois ombros:
   - **Ângulo θ** entre a reta orelha–ombro e a vertical da imagem → detecta a
     cabeça tombando pro lado. Alerta se o desvio passar de **12°** em relação à baseline.
   - **Razão a/b** (distância orelha–ombro ÷ largura dos ombros) → detecta a
     cabeça caindo pra frente/baixo. Dividir pelos ombros cancela a distância da
     câmera. Alerta se a razão **cair** mais de **12%** em relação à baseline. Aumentar
     a razão não gera alerta.
4. **Média móvel** de 5 leituras (tira a tremedeira) + **contador**: só vira
   ALERTA depois de 15 frames seguidos de postura ruim.
5. **Nunca para sozinho:** se a câmera cair, reabre e mantém a baseline; se um vídeo
   acabar, volta pra câmera ao vivo (aguardando calibração).
6. **Reinício no mesmo boot** (travou e o systemd religou, ou `postura reiniciar`):
   reaproveita a última baseline. **Boot novo:** sempre aguarda calibração.

## Instalação no Raspberry Pi

O `tflite-runtime` só tem pacote até o **Python 3.11**, por isso ele foi compilado
no Pi. As bibliotecas ficam num ambiente virtual **fora** da pasta do repositório
(pra não sumir se a pasta for apagada):

```bash
python3.11 -m venv ~/venv-tcc
source ~/venv-tcc/bin/activate
pip install --upgrade pip
pip install "numpy<2" "opencv-python<4.12" tflite-runtime
```

- `numpy<2`: o tflite-runtime 2.14 foi compilado com o NumPy 1.x.
- `opencv-python<4.12`: as versões novas do OpenCV exigem NumPy 2.

Depois:

```bash
git clone https://github.com/wduarte-dev/tcc-3eim-etectm.git ~/tcc-3eim-etectm
cd ~/tcc-3eim-etectm/sensor-postura
```

**1. Teste manual primeiro** (entre no Pi com `ssh -X` pra ver a janela, com o venv ativado):

```bash
python postura_servico.py --preview
```

Na janela: `r` calibra, `q` encerra.

**2. Se funcionou, instale o serviço** (sem `sudo` na frente, ele pede a senha quando precisa):

```bash
bash instalar.sh
```

Ele acha o `~/venv-tcc` sozinho. Se o venv estiver em outro lugar:
`bash instalar.sh /caminho/do/venv/bin/python`

**Atualizar depois:** `git pull && postura reiniciar`

## Comandos

```bash
postura status        # o que está rodando agora (fonte, status, baseline, FPS)
postura recalibrar    # contagem de 10s (mostrada no terminal) + 5s de coleta
postura gravar 30     # grava 30s da webcam em videos/ (precisa ser mais que 5s)
postura janela        # abre o monitor com a janela da câmera (precisa de ssh -X)
postura live          # volta pra câmera ao vivo (fica aguardando calibração)
postura video         # lista os vídeos de videos/ e você escolhe pelo número
postura video 2       # troca direto pro vídeo nº 2
postura log           # acompanha a saída do serviço ao vivo (Ctrl+C sai)
postura parar         # para o serviço
postura iniciar       # liga o serviço
postura reiniciar     # reinicia o serviço
```

### `postura janela`

O serviço roda escondido pelo systemd e não tem tela. O `postura janela` pausa o
serviço, abre o monitor com a janela **no seu terminal** e, quando você fecha
(`q` na janela ou Ctrl+C) ou se der erro, **religa o serviço sozinho**. A baseline
é reaproveitada nos dois sentidos, então não precisa recalibrar.

## Testando com vídeo

1. `postura gravar 30` grava 30 s com a própria webcam do Pi (na mesma posição
   do uso real). Há uma contagem de 5 s pra se ajeitar antes de começar.
2. **Os primeiros 5 s do vídeo têm que ser na postura correta**, porque é com
   eles que o sistema calibra quando analisa o vídeo. Depois disso, faça as
   posturas que quer testar.
3. `postura video` → escolhe o vídeo. Quando ele acaba, o sistema volta pra
   câmera ao vivo e aguarda calibração.

Dica: um vídeo por situação (cabeça pro lado, cabeça baixa, postura correta)
facilita a análise no CSV.

Também dá pra rodar manual: `python postura_servico.py --video nome.mp4`

## Log (dados pro TCC)

`logs/postura_AAAA-MM-DD.csv`, uma linha por frame analisado:

`data_hora, fonte, video, status, angulo, razao_pescoco, desvio_angulo, queda_razao_pct, baseline_angulo, baseline_razao, fps`

O `status` pode ser `CALIBRADO`, `CORRETA`, `ATENCAO`, `ALERTA` ou `SEM_USUARIO`.

## Display (próximo passo)

Toda a saída de status passa pela função `mostrar_status()` em
`postura_servico.py`. Quando o display OLED estiver pronto, é só ela que muda
(ex.: status `AGUARDANDO_CALIBRACAO` → "Aguardando recalibração...").
