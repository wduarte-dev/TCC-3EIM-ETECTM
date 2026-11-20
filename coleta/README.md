# Coleta do estudo de validação dos limiares

Programa que roda **no notebook** (fora do Pi) pra medir ~30 pessoas em 7 posturas e
descobrir, com dados, se os limiares do sensor de postura (12° e 12%, hoje escolhidos
sem medição) separam postura boa de ruim. Nome do método: **validação empírica dos limiares**.

- Usa o **mesmo modelo** (`sensor-postura/movenet_lightning.tflite`) e o **mesmo
  pré-processamento** do serviço: importa `DetectorPostura` de `postura_servico.py` e as
  métricas de `postura_logica.py` (não copia nada).
- **Não salva imagem nenhuma.** Só os 17 pontos do MoveNet + confiança, as métricas e os
  metadados, em CSV, com ID anônimo (P01, P02…).

## Arquivos

| Arquivo | Função |
|---|---|
| `coleta.py` | Câmera, janela do OpenCV, perguntas no terminal e gravação dos CSV |
| `coleta_logica.py` | **Lógica pura**: etapas, análise de cada quadro, resumo e a sequência (máquina de estados). Sem câmera |
| `test_coleta.py` | Testes sem câmera (pontos sintéticos, relógio falso) + 1 teste com o MoveNet de verdade |
| `dados/` | Os CSV da coleta (**não vão pro Git**) |

## Instalar (Windows, notebook da escola)

O `tflite-runtime` não existe pra Windows; o código tenta, nessa ordem, `tflite_runtime`,
`ai_edge_litert` e o TensorFlow completo.

```powershell
py -m venv venv-coleta
venv-coleta\Scripts\activate
pip install tensorflow opencv-python
```

Baixe o repositório inteiro (o programa precisa da pasta `sensor-postura/` ao lado).

## Rodar

```powershell
cd coleta
python coleta.py --camera 1          # no notebook a 0 costuma ser a webcam embutida
```

1. **No terminal:** ID (enter aceita o próximo livre), termo aceito, óculos, cabelo cobrindo a
   orelha, cadeira, distância e altura da câmera, notebook, observações.
2. **Na janela:**
   - **Enquadramento:** ajuste a câmera até os 3 pontos (orelha, ombro do lado da orelha, outro
     ombro) ficarem **verdes**, com folga pra pessoa se encurvar. `C` troca de câmera.
   - **Cada etapa:** o texto aparece → `ESPAÇO` → 2 s pra assumir a pose → **grava 5 s** →
     resultado. `ESPAÇO` aceita, `R` repete.
   - `ESC` sai a qualquer momento; o que já foi gravado fica salvo (a pessoa fica como incompleta).

Opções: `--duracao 5` (segundos gravados), `--contagem 2`, `--dados PASTA`, `--video ARQ`
(testar sem câmera), `--mjpg` (a Bresser **não** tem MJPG, por isso não é o padrão).

## As 7 etapas

| # | Chave | O que a pessoa faz |
|---|---|---|
| 1 | `correta` | Postura correta (texto da OSHA, abaixo). **Vira a baseline** (média, igual ao `postura recalibrar`) |
| 2 | `incl_esquerda` | Cabeça inclinada pro ombro esquerdo dela, no máximo |
| 3 | `incl_direita` | Cabeça inclinada pro ombro direito dela, no máximo |
| 4 | `relaxada` | Jeito normal dela no computador, sem corrigir |
| 5 | `ma_postura` | Encurvada: ombros pra frente e cabeça levemente caída |
| 6 | `cabeca_baixa` | Olhando pro colo |
| 7 | `projecao` | Só a cabeça pra frente, ombros parados (T4: testa a razão `c/b`) |

**Texto da postura correta:** OSHA, *Computer Workstations eTool*, "Good Working Positions"
(cabeça nivelada, olhando pra frente e alinhada com o tronco; ombros relaxados com os braços
soltos ao lado do corpo; tronco e pescoço mais ou menos na vertical; pés apoiados).

**Só a etapa 1 obriga repetir** quando vêm menos de 5 quadros válidos (sem baseline não dá pra
comparar nada). Nas outras, perder os pontos é **dado do estudo** (hipótese do T3: perde-se mais
com postura ruim), então a etapa é aceita mesmo com perdas.

## O que é gravado (`dados/`)

| Arquivo | Uma linha por | Conteúdo |
|---|---|---|
| `quadros_<ID>_<data>.csv` | quadro gravado (todas as tentativas) | etapa, tentativa, tempo, `valido`, ângulo, razão, `c/b`, distâncias `a`/`b`/`c` em pixels, desvio e queda em relação à baseline, `ruim_quadro`, e os **17 pontos** (`x`, `y`, `conf`) |
| `etapas.csv` | tentativa de etapa | `aceita` (1/0), nº de quadros, **% sem usuário**, fps, mediana e desvio-padrão de cada métrica, baseline (na etapa 1) |
| `participantes.csv` | pessoa | metadados, baseline (ângulo, razão, largura dos ombros `b0`, `c/b`), etapas aceitas, fonte, sistema, versões, interpretador, hash do modelo, limiares em uso |

Definições (as mesmas do serviço):
- **válido** = orelha + os dois ombros com confiança **acima** de 0,4 (`LIMIAR_CONFIANCA`);
- `a` = orelha–ombro do mesmo lado, `b` = largura dos ombros, `c` = orelha–orelha;
  `razao` = `a/b`, `razao_cb` = `c/b` (só quando a outra orelha aparece);
- `desvio_angulo`, `queda_razao_pct` e `ruim_quadro` são **por quadro**, sem a média móvel de 5
  do serviço (a análise offline pode refazer qualquer suavização a partir dos dados crus);
- "esq"/"dir" nos nomes dos pontos são os rótulos do MoveNet na imagem **espelhada** (como no
  serviço), não necessariamente o lado da pessoa.

## Testes (sem câmera)

```bash
python -m unittest -v        # de dentro de coleta/
```

Testa a análise de cada quadro (métricas iguais às de `postura_logica`; em 2000 quadros
aleatórios, "válido" aqui = o serviço não dar `SEM_USUARIO`), o resumo, a sequência inteira
(contagem não grava, baseline ruim obriga repetir, perdas aceitas nas etapas ruins, sair no meio)
e os CSV. Um teste roda o MoveNet de verdade e confere que os 17 pontos da coleta dão a mesma
validade e as mesmas métricas que o serviço (pula se não houver interpretador instalado).

## Limitações (declarar na banca)

- **Não testado no Windows nem com a Bresser** (desenvolvido e testado no Linux, com câmera
  falsa e MoveNet em quadros sintéticos). Antes da coleta: teste de 5 min na escola (a Bresser
  abre? os pontos aparecem?).
- Postura errada **encenada** (instruída), não espontânea.
- Câmera frontal: a literatura define cabeça pra frente na vista **lateral** (plano sagital).
- Distância e altura da câmera são anotadas à mão, aproximadas.
- O fps do notebook não vale como fps do Pi: por isso as métricas são guardadas por quadro e
  sem suavização.
