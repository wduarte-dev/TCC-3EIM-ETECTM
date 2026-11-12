# Sensor de postura

Monitora a postura pela webcam usando o MoveNet (TFLite). Roda **sem tela** no
Raspberry Pi 3B como serviço do systemd, inicia sozinho no boot e é controlado
pelo comando `postura`.

## Arquivos

| Arquivo | Função |
|---|---|
| `postura_servico.py` | O monitor em si: câmera/vídeo → MoveNet → cálculo de postura → status + log |
| `postura_ctl.py` | O comando `postura` (status, troca de fonte, recalibrar...) |
| `postura_config.py` | Limiares e caminhos. **Ajuste os valores aqui.** |
| `instalar.sh` | Instala o serviço do systemd e o comando `postura` |
| `movenet_lightning.tflite` | Modelo de detecção de pose |
| `main-otimizado-rpi3b.py` | Versão anterior (com janela, ENTER pra calibrar). Mantida como referência |
| `videos/` | Vídeos de teste (não vão pro Git) |
| `logs/` | Um CSV por dia com todas as medições (não vai pro Git) |

## Como funciona

1. **Calibração automática:** ao iniciar, faz uma contagem regressiva de 5 s
   (fique na postura correta) e coleta 5 s de amostras. A média vira a
   **baseline**, ou seja, a referência de postura correta daquela pessoa e daquela câmera.
2. **Duas medidas**, a partir da orelha e dos dois ombros:
   - **Ângulo θ** entre a reta orelha–ombro e a vertical da imagem → detecta a
     cabeça tombando pro lado. Alerta se o desvio passar de **12°** em relação à baseline.
   - **Razão a/b** (distância orelha–ombro ÷ largura dos ombros) → detecta a
     cabeça caindo pra frente/baixo. Dividir pelos ombros cancela a distância da
     câmera. Alerta se a razão **cair** mais de **12%** em relação à baseline. Aumentar
     a razão não gera alerta.
3. **Média móvel** de 5 leituras (tira a tremedeira) + **contador**: só vira
   ALERTA depois de 15 frames seguidos de postura ruim.
4. Nunca para sozinho: se a câmera cair, tenta reabrir; se um vídeo acabar, volta
   pra câmera ao vivo.

## Instalação no Raspberry Pi

```bash
git clone https://github.com/wduarte-dev/tcc-3eim-etectm.git ~/tcc-3eim-etectm
cd ~/tcc-3eim-etectm/sensor-postura
```

**1. Teste manual primeiro** (entre no Pi com `ssh -X` pra ver a janela):

```bash
python3.11 postura_servico.py --preview
```

Na janela: `q` encerra e `r` recalibra.

**2. Se funcionou, instale o serviço** (sem `sudo` na frente, ele pede a senha quando precisa):

```bash
bash instalar.sh
```

Se ele não achar o Python certo sozinho: `bash instalar.sh /caminho/do/python3.11`

**Atualizar depois:** `git pull && postura reiniciar`

## Comandos

```bash
postura status        # o que está rodando agora (fonte, status, baseline, FPS)
postura live          # volta pra câmera ao vivo (recalibra)
postura video         # lista os vídeos de videos/ e você escolhe pelo número
postura video 2       # troca direto pro vídeo nº 2
postura recalibrar    # refaz a baseline
postura log           # acompanha a saída do serviço ao vivo (Ctrl+C sai)
postura parar         # para o serviço
postura iniciar       # liga o serviço
postura reiniciar     # reinicia o serviço
```

> Pra rodar manual com `--preview`, faça `postura parar` antes: os dois disputam a câmera.

## Testando com vídeo

Coloque vídeos (`.mp4`, `.avi`, `.mkv`, `.mov`, `.webm`) em `videos/` e use
`postura video`. Os **primeiros 5 s do vídeo** precisam mostrar a pessoa na
postura correta, porque é com eles que o sistema calibra. Quando o vídeo acaba, o
sistema volta sozinho pra câmera ao vivo.

Também dá pra rodar manual: `python3.11 postura_servico.py --video nome.mp4`

## Log (dados pro TCC)

`logs/postura_AAAA-MM-DD.csv`, uma linha por frame analisado:

`data_hora, fonte, video, status, angulo, razao_pescoco, desvio_angulo, queda_razao_pct, baseline_angulo, baseline_razao, fps`

O `status` pode ser `CALIBRADO`, `CORRETA`, `ATENCAO`, `ALERTA` ou `SEM_USUARIO`.

## Display (próximo passo)

Toda a saída de status passa pela função `mostrar_status()` em
`postura_servico.py`. Quando o display OLED estiver pronto, é só ela que muda.
