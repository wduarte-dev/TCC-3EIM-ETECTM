# Coleta do estudo de validação dos limiares

Programa que roda **no notebook** (fora do Pi) pra medir ~30 pessoas em 7 posturas e
descobrir, com dados, se os limiares do sensor de postura (12° e 12%, hoje escolhidos
sem medição) separam postura boa de ruim. Nome do método: **validação empírica dos limiares**.

- Usa o **mesmo modelo** (`sensor-postura/movenet_lightning.tflite`) e o **mesmo
  pré-processamento** do serviço: importa `DetectorPostura` de `postura_servico.py` e as
  métricas de `postura_logica.py` (não copia nada).
- **Não salva imagem nenhuma.** Só os 17 pontos do MoveNet + confiança, as métricas e os
  metadados, em CSV, com ID anônimo e aleatório (ex.: `P3F9A2C`).

## Arquivos

| Arquivo | Função |
|---|---|
| `coleta.py` | Câmera, janela do OpenCV, perguntas no terminal e gravação dos CSV |
| `coleta_logica.py` | **Lógica pura**: etapas, análise de cada quadro, resumo e a sequência (máquina de estados). Sem câmera |
| `test_coleta.py` | Testes sem câmera (pontos sintéticos, relógio falso) + 1 teste com o MoveNet de verdade |
| `VERSAO` | Hash do commit quando o repo é baixado como **zip** (sem `.git`); ver "Versão do código" |
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

1. **No terminal:** o **ID é automático e aleatório** (`P` + 6 hexadecimais, ex.: `P3F9A2C`;
   ninguém digita). Aleatório porque a coleta roda em **vários computadores**: numerado, cada
   máquina começaria do `P01` e os IDs se repetiriam ao juntar os dados. A chance de dois
   computadores sortearem o mesmo ID com 30 pessoas é de ~0,003% (conta, "paradoxo do
   aniversário"); na mesma pasta nunca repete.
   Depois: termo aceito, sexo (`m` = mulher, `h` = homem), **altura da pessoa** em cm (número,
   de 100 a 230), óculos, cabelo cobrindo a orelha, cadeira, distância da câmera, altura da
   câmera (**texto livre**), webcam (`n` = do notebook, `t` = do TCC, a Bresser), notebook,
   observações.
2. **Na janela:**
   - **Enquadramento:** ajuste a câmera até os 3 pontos (orelha, ombro do lado da orelha, outro
     ombro) ficarem **verdes**, com folga pra pessoa se encurvar. `C` troca de câmera.
   - **Cada etapa:** o texto aparece → `ESPAÇO` → **5 s pra se ajeitar** → **grava 5 s** →
     resultado. `ESPAÇO` aceita, `R` repete.
   - **Saídas do participante** (pode usar sem justificar; nas duas o que já foi gravado fica):
     `P` **pula a etapa** (não vale na etapa 1: sem baseline as outras não têm referência) e
     `D` **desiste** (encerra a coleta dessa pessoa).
   - `ESC` encerra a qualquer momento (o operador saiu; motivo `interrompida`).
3. **Ao fechar a janela, o terminal pede as observações finais** (o que aconteceu: cabelo na
   orelha, desconforto, etapa repetida...). Enter = nenhuma, e o programa encerra.

Opções: `--duracao 5` (segundos gravados), `--contagem 5`, `--dados PASTA`, `--video ARQ`
(testar sem câmera), `--mjpg` (a Bresser **não** tem MJPG, por isso não é o padrão).

Tempo por etapa: ~10 s de gravação (5 + 5) mais a leitura do texto e a revisão.

## As 7 etapas

| # | Chave | O que a pessoa faz |
|---|---|---|
| 1 | `correta` | Postura correta (texto da OSHA, abaixo). **Vira a baseline** (média, igual ao `postura recalibrar`) |
| 2 | `incl_esquerda` | Orelha esquerda em direção ao ombro esquerdo dela, **sem girar o rosto** |
| 3 | `incl_direita` | Orelha direita em direção ao ombro direito dela, **sem girar o rosto** |
| 4 | `relaxada` | Jeito normal dela no computador, relaxado e o mais natural possível, sem corrigir |
| 5 | `ma_postura` | Encurvada: ombros pra frente e cabeça levemente caída |
| 6 | `cabeca_baixa` | Olhando pro colo |
| 7 | `projecao` | Só a cabeça pra frente, ombros parados (T4: testa a razão `c/b`) |

**Texto da postura correta:** OSHA, *Computer Workstations eTool*, "Good Working Positions"
(cabeça nivelada e alinhada com o tronco, olhando para o monitor; ombros relaxados com os braços
soltos ao lado do corpo; tronco e pescoço mais ou menos na vertical; pés apoiados).

**Etapas 2 a 7 começam voltando à postura correta** (1ª linha do texto de cada uma): cada medida
é comparada com a baseline da etapa 1, e uma etapa que começasse torta pela anterior misturaria
as duas. **Etapas 2 e 3** pedem "orelha em direção ao ombro, sem girar o rosto": na 1ª coleta
(participante 01) a pessoa **girou** a cabeça (ângulo quase parado e razão mudando muito; essa
leitura é inferência, não foi testada). Os textos foram aprovados pelo Wellington em 20/11/2026.

**Só a etapa 1 obriga repetir** quando vêm menos de 5 quadros válidos (sem baseline não dá pra
comparar nada). Nas outras, perder os pontos é **dado do estudo** (hipótese do T3: perde-se mais
com postura ruim), então a etapa é aceita mesmo com perdas.

## O que é gravado (`dados/`)

| Arquivo | Uma linha por | Conteúdo |
|---|---|---|
| `quadros_<ID>_<data>.csv` | quadro gravado (todas as tentativas) | etapa, tentativa, tempo, `valido`, ângulo, razão, `c/b`, distâncias `a`/`b`/`c` em pixels, desvio e queda em relação à baseline, `ruim_quadro`, e os **17 pontos** (`x`, `y`, `conf`) |
| `etapas.csv` | tentativa de etapa | `aceita` (1/0), **`motivo`**, nº de quadros, **% sem usuário**, fps, mediana e desvio-padrão de cada métrica, baseline (na etapa 1) |
| `participantes.csv` | pessoa | metadados (inclusive `sexo`, `altura_pessoa_cm`, `webcam`, `observacoes_fim`), `completa`, **`motivo_fim`**, etapas aceitas e puladas, baseline (ângulo, razão, largura dos ombros `b0`, `c/b`), fonte, sistema, versões, interpretador, hash do modelo, limiares em uso |

**`motivo`** (só nas tentativas com `aceita=0`): `repetir` (o operador apertou R: rejeição por
qualidade), `pulou` (o participante pulou), `desistiu` (parou nessa etapa), `interrompida` (ESC,
janela fechada, câmera ou vídeo acabou). Uma etapa pulada ou abandonada **antes de gravar** também
vira linha (com `n_total=0`), pra ficar registrado onde aconteceu.

**`completa`** = as 7 etapas **aceitas** (o mesmo sentido de antes). **`motivo_fim`**: `fim` (chegou
ao fim, mesmo pulando alguma), `desistiu`, `interrompida`, `camera_falhou` ou `video_acabou`.

**Arquivo de formato antigo:** se `etapas.csv` ou `participantes.csv` já existem com outras
colunas (coleta anterior a esta versão), o programa **renomeia** o antigo pra
`*_formato_antigo_<data>.csv` e começa um novo. Nada se perde; a análise junta os dois.

Definições (as mesmas do serviço):
- **válido** = orelha + os dois ombros com confiança **acima** de 0,4 (`LIMIAR_CONFIANCA`);
- `a` = orelha–ombro do mesmo lado, `b` = largura dos ombros, `c` = orelha–orelha;
  `razao` = `a/b`, `razao_cb` = `c/b` (só quando a outra orelha aparece);
- `desvio_angulo`, `queda_razao_pct` e `ruim_quadro` são **por quadro**, sem a média móvel de 5
  do serviço (a análise offline pode refazer qualquer suavização a partir dos dados crus);
- "esq"/"dir" nos nomes dos pontos são os rótulos do MoveNet na imagem **espelhada** (como no
  serviço), não necessariamente o lado da pessoa.

## Na análise (offline)

- **Usar só as tentativas aceitas:** o `quadros_*.csv` guarda **todas** as tentativas (as
  repetidas também). Cruzar `(participante, etapa, tentativa)` com `aceita=1` do `etapas.csv`.
- **Etapa pulada = dado faltante informativo**, não rejeição por qualidade: reportar a **taxa
  de pulos por etapa** (pode indicar uma etapa desconfortável) e não misturar com `repetir`.
- Reportar a **taxa de `SEM_USUARIO` por pessoa e etapa** (ex.: cabelo cobrindo a orelha na
  cabeça baixa é limitação do método, não falha da coleta).

## Versão do código

`versao_codigo` (em `participantes.csv`) vem, nesta ordem: (1) do `git`, num clone, com
`+alterado` se algum arquivo versionado foi mexido sem commit; (2) do arquivo `VERSAO`, quando
o repo foi baixado como **zip** pelo GitHub (o zip é gerado com `git archive`, que troca o
marcador `$Format:%h$` pelo hash do commit, pelo atributo `export-subst` no `.gitattributes`);
(3) `desconhecida`. Ninguém precisa editar o `VERSAO` à mão.

## Testes (sem câmera)

```bash
python -m unittest -v        # de dentro de coleta/
```

Testa a análise de cada quadro (métricas iguais às de `postura_logica`; em 2000 quadros
aleatórios, "válido" aqui = o serviço não dar `SEM_USUARIO`), o resumo, a sequência inteira
(contagem não grava, baseline ruim obriga repetir, perdas aceitas nas etapas ruins, sair no meio,
pular, não pular a baseline, desistir, motivos), os textos aprovados (ASCII, 1ª linha das etapas
2 a 7), os metadados validados, o CSV de formato antigo, a versão pelo `VERSAO` e os CSV. Um teste roda o MoveNet de verdade e confere que os 17 pontos da coleta dão a mesma
validade e as mesmas métricas que o serviço (pula se não houver interpretador instalado).

## Limitações (declarar na banca)

- **Não testado no Windows nem com a Bresser** (desenvolvido e testado no Linux, com câmera
  falsa e MoveNet em quadros sintéticos). Antes da coleta: teste de 5 min na escola (a Bresser
  abre? os pontos aparecem?).
- Postura errada **encenada** (instruída), não espontânea.
- Câmera frontal: a literatura define cabeça pra frente na vista **lateral** (plano sagital).
- Distância e altura da câmera são anotadas à mão, aproximadas; a altura da câmera é texto livre
  (não dá pra medir automático, e em cm não serviria porque o enquadramento varia).
- Altura e sexo são **declarados** pelo participante (não medidos).
- O fps do notebook não vale como fps do Pi: por isso as métricas são guardadas por quadro e
  sem suavização.
