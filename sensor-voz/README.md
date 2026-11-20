# Sensor de voz (fora do escopo do TCC)

> **Estado (19/11/2026): fora do escopo.** O sensor de fadiga vocal foi retirado do sistema
> entregue porque validar a medição exigiria muito mais coleta e pesquisa do que cabia no prazo.
> O pomodoro não usa mais nada daqui (o B1 ficou com postura e Wi-Fi). A pasta fica no repositório
> como **registro do que foi feito**: pipeline **testado no PC, não validado no Raspberry Pi**.

## O que existe

| Arquivo | Função |
|---|---|
| `main.py` | Grava 3 s de vogal sustentada ("AAAA") a 48 kHz, chama o Praat e compara com uma baseline pessoal |
| `analisar_voz.praat` | Script do Praat que extrai jitter, shimmer e HNR da gravação |
| `req.txt` | Dependências (scipy, numpy, sounddevice + Praat instalado à parte) |
| `teste_audio.wav` | Última gravação de teste |
| `praat` | Binário do Praat via **Git LFS** (≈118 MB); sem `git lfs pull` vem só o ponteiro de texto |

**Ideia do método:** jitter (variação do período), shimmer (variação da amplitude) e HNR (relação
harmônico/ruído) medidos numa vogal sustentada, comparados com a baseline da própria pessoa
(aumento relativo de 30% como limiar, escolha do projeto). O jitter é o sinal principal; o shimmer só
reforça; HNR abaixo de 15 dB marca a gravação como ruidosa. A pesquisa sobre esses parâmetros está nos
docs do projeto (`claude/sensor-voz.md`) e vale como **revisão de literatura**, não como resultado.

## Por que saiu (pra declarar na banca)

- Os limiares (+30%, 15 dB) não foram validados com pessoas; a relação jitter/shimmer × fadiga na
  literatura depende de protocolo, microfone e ambiente.
- Não houve teste com o microfone e o Praat no Pi 3B.
- **Trabalho futuro:** validar o protocolo de gravação e os limiares com várias pessoas antes de
  integrar de novo ao sistema.

## Limpezas pendentes (sem prioridade)

- `._praat` é um arquivo de metadados do macOS (AppleDouble), sem uso.
- O binário `praat` no LFS e o `teste_audio.wav` podem sair do repositório se a pasta for arquivada.
