# Sensor de postura

Monitora a postura pela webcam usando o MoveNet (TFLite). Roda **sem tela** no
Raspberry Pi 3B como serviço do systemd, inicia sozinho no boot e é controlado
pelo comando `postura`.

## Arquivos

| Arquivo | Função |
|---|---|
| `postura_servico.py` | O monitor em si: câmera/vídeo → MoveNet → `postura_logica` → status + log |
| `postura_logica.py` | **Decisão da postura, lógica pura** (ângulo, razão, média móvel, contador): recebe os 3 pontos + a baseline e devolve o estado. Não usa câmera nem OpenCV |
| `test_postura_logica.py` | Testes com pontos sintéticos + prova de que a decisão é igual à do código antigo |
| `postura_ctl.py` | O comando `postura` (status, recalibrar, gravar, janela...) |
| `postura_config.py` | Limiares, tempos e caminhos. **Ajuste os valores aqui.** |
| `instalar.sh` | Instala o serviço do systemd e o comando `postura` |
| `movenet_lightning.tflite` | Modelo de detecção de pose |
| `main-otimizado-rpi3b.py` | Versão anterior (com janela, ENTER pra calibrar). Mantida como referência |
| `videos/` | Vídeos de teste (não vão pro Git) |
| `logs/` | Um CSV por dia com todas as medições (não vai pro Git) |
| `fotos/` | Última `postura foto` (não vai pro Git) |
| `baseline.json` | Última calibração ao vivo (gerado sozinho, não vai pro Git) |

O programa de coleta do estudo ([`../coleta/`](../coleta/)) importa `DetectorPostura` daqui e
lê `ultimos_keypoints`/`ultimo_letterbox` (os 17 pontos do último quadro). Esses atributos só
são guardados; a decisão do serviço não usa.

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
4. **Média móvel** de 5 leituras (tira a tremedeira) + **contador**: cada quadro ruim
   soma 1, cada quadro correto desconta 1, e vira ALERTA quando o contador passa de 15.
   **Perder os pontos também é informação (T3):** se o MoveNet perde a pessoa no meio de
   uma sequência ruim (`RUIM → SEM → RUIM → SEM`), é provável que ela esteja encurvada no
   limite do que a câmera capta. Até `PERDAS_TOLERADAS` (5) perdas **seguidas** contam como
   indício (o contador sobe e a tela continua em ATENÇÃO/ALERTA); passou disso, conclui que a
   pessoa saiu do enquadramento, zera e mostra `SEM_USUARIO`. Uma perda sem sequência ruim
   antes não inicia nada. **Trava:** o ALERTA exige pelo menos `MINIMO_RUINS_MEDIDOS` (8)
   quadros ruins **medidos**, pra não sair majoritariamente de quadros perdidos. É
   **inferência por regras (máquina de estados), não IA**. Os valores 5 e 8 são
   **provisórios**, escolha do projeto, a definir com os dados do estudo.
5. **Enquadramento (quais pontos a câmera vê):** na contagem da calibração o MoveNet já roda,
   e o status (`pontos_visiveis`) diz se a orelha, o ombro do lado dela e o outro ombro estão
   visíveis (confiança > 0,4). O pomodoro desenha isso no OLED como 3 pontos (cheio/vazado), e o
   `postura status` mostra `● orelha ○ outro ombro`... Se a calibração falhar, a mensagem diz
   **qual ponto mais faltou** (ex.: `outro ombro fora da imagem (40 de 50 quadros)`). A baseline
   já não usava quadros sem os 3 pontos; continua falhando com menos de 5 quadros válidos.
6. **Nunca para sozinho:** se a câmera cair, reabre e mantém a baseline; se um vídeo
   acabar, volta pra câmera ao vivo (aguardando calibração).
7. **Reinício no mesmo boot** (travou e o systemd religou, ou `postura reiniciar`):
   reaproveita a última baseline. **Boot novo:** sempre aguarda calibração.

## Testes (sem câmera)

```bash
python -m unittest -v        # de dentro de sensor-postura/; só precisa do Python
```

`test_postura_logica.py` testa ângulo, razão, limiares, média móvel e contador com pontos
inventados (ex.: orelha girada 30°, pescoço 30% mais curto). O teste
`TesteIgualAoCodigoAntigo` roda 300 sequências aleatórias de 300 quadros (com quadros sem
detecção no meio) na lógica nova e numa cópia literal do trecho antigo do serviço e exige
**resultado idêntico quadro a quadro**: é a prova de que a refatoração não mudou o comportamento.
Os arquivos antigos `main.py` e `main-otimizado-rpi3b.py` continuam com a cópia própria dos
cálculos (referência histórica, não são usados pelo serviço).

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

## Rodando no Windows (desenvolvimento/demo)

O mesmo código roda no Windows; o Raspberry Pi continua igual. Não há serviço
(systemd): roda-se o monitor direto.

```powershell
py -3.11 -m venv venv-tcc
venv-tcc\Scripts\activate
pip install "numpy<2" opencv-python ai-edge-litert
python postura_servico.py --preview
```

- **Modelo:** não existe `tflite-runtime` pra Windows; o código usa o `ai-edge-litert`
  (ou o TensorFlow completo) sozinho, nessa ordem.
- **Câmera:** usa o backend DirectShow (`CAP_DSHOW`) em vez do V4L2.
- **Comandos:** em outro terminal, `python postura_ctl.py status|recalibrar|gravar N|live|video`.
  Eles falam com o monitor por TCP em `127.0.0.1:47831` (no Linux é socket Unix).
  `iniciar`, `parar`, `reiniciar`, `log` e `janela` dependem do systemd e não existem no Windows.
- **Limite:** FPS e baseline do Windows não valem pro Pi (outra câmera, outra CPU).
  Serve pra desenvolver e demonstrar, não como dado de desempenho do TCC.

## Comandos

```bash
postura status        # o que está rodando agora (fonte, status, baseline, FPS)
postura recalibrar    # contagem de 10s (mostrada no terminal) + 5s de coleta
postura gravar 30     # grava 30s da webcam em videos/ (precisa ser mais que 5s)
postura janela        # abre o monitor com a janela da câmera (precisa de ssh -X)
postura foto          # JPEG do último quadro com os 3 pontos e o status (baixe com scp)
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

### `postura foto` (ferramenta de desenvolvimento, T5)

Salva `fotos/postura_foto.jpg` (320 px de largura) com o **último quadro** da câmera, os 3 pontos,
as linhas orelha–ombro e ombro–ombro e o status/desvio/queda. Serve pra conferir enquadramento e
calibração por SSH sem `ssh -X` nem parar o serviço. O comando imprime o `scp` pra baixar:

```bash
postura foto
scp usuario@raspberrypi.local:/caminho/impresso/postura_foto.jpg .
```

O serviço só guarda a referência do último quadro (sem cópia) e só desenha/comprime o JPEG quando o
comando é pedido; o custo no Pi 3B não foi medido. Na banca, quem mostra a câmera ao vivo é o
`postura janela`. Não é recurso do produto final (que não tem SSH).

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

`data_hora, fonte, video, status, angulo, razao_pescoco, desvio_angulo, queda_razao_pct, baseline_angulo, baseline_razao, fps, status_exibido, contador, perdidos_seguidos, ruins_medidos, razao_cb`

- `status`: o que **o quadro** mostrou: `CALIBRADO`, `CORRETA`, `ATENCAO`, `ALERTA` ou `SEM_USUARIO`
  (quadro sem os 3 pontos fica `SEM_USUARIO` mesmo quando conta como indício: dado honesto).
- `status_exibido`: a decisão que foi pra tela (numa perda tolerada, continua `ATENCAO`/`ALERTA`).
- `contador`, `perdidos_seguidos`, `ruins_medidos`: estado do contador de alerta (servem pra ajustar N e M).
- `razao_cb` (T4): distância orelha-orelha ÷ largura dos ombros. **Só armazenada**, não decide
  nada; vazia se a outra orelha não apareceu.
- Se o arquivo do dia já existia com as colunas antigas, o serviço começa `postura_AAAA-MM-DD_v2.csv`
  em vez de misturar formatos.

## Display (próximo passo)

Toda a saída de status passa pela função `mostrar_status()` em
`postura_servico.py`. Quando o display OLED estiver pronto, é só ela que muda
(ex.: status `AGUARDANDO_CALIBRACAO` → "Aguardando recalibração...").
