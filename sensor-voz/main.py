import sounddevice as sd
import numpy as np
from scipy.io.wavfile import write
import subprocess
import platform
import json
import sys
import os


SAMPLE_RATE = 48000
CANAIS = 1
DURACAO = 3

# Pega o caminho absoluto do diretório onde este arquivo .py está localizado
DIRETORIO_ATUAL = os.path.dirname(os.path.abspath(__file__))
ARQUIVO_AUDIO = os.path.join(DIRETORIO_ATUAL, "teste_audio.wav")
SCRIPT_PRAAT = os.path.join(DIRETORIO_ATUAL, "analisar_voz.praat")
ARQUIVO_BASELINE = os.path.join(DIRETORIO_ATUAL, "baseline_voz.json")

# Quantas gravações usar pra montar a baseline (calibração). Fazer mais de
# uma e tirar a média reduz o efeito de ruído pontual numa única gravação
# — importante porque é a referência que TODAS as medições futuras vão
# usar como comparação.
REPETICOES_CALIBRACAO = 2

# Limiares de AUMENTO RELATIVO em relação à baseline pessoal do usuário
# (não são mais limiares fixos de população). O jitter é tratado como
# sinal primário; o shimmer só reforça a suspeita, não decide sozinho —
# isso segue a literatura, que mostra shimmer menos consistente que
# jitter como indicador de estresse/fadiga e mais sensível a ruído de
# gravação.
LIMIAR_AUMENTO_JITTER = 0.30    # +30% de jitter em relação à baseline
LIMIAR_AUMENTO_SHIMMER = 0.30   # +30% de shimmer em relação à baseline

# Abaixo desse HNR (dB), a gravação é considerada ruidosa/pouco confiável
# (mic longe, ruído de fundo, etc.) — não invalida o resultado, mas ele
# vem com aviso.
LIMIAR_HNR_MINIMO = 15.0

# Caminho do executável do Praat. No Raspberry Pi, o binário foi extraído
# na própria pasta do projeto (setup manual via tar.gz), então usamos ele
# SE a máquina atual for ARM (é o que platform.machine() indica: armv7l,
# armv6l, aarch64...). No PC normal (x86_64/AMD64), mesmo que sobre um
# binário "praat" ARM na pasta (ex: copiado sem querer do repositório),
# ele é ignorado e usamos o "praat" instalado via apt, que fica no PATH.
# Isso evita o "Exec format error" de tentar rodar um binário da
# arquitetura errada.
_arch = platform.machine().lower()
_eh_arm = _arch.startswith("arm") or _arch.startswith("aarch")
_praat_local = os.path.join(DIRETORIO_ATUAL, "praat")
PRAAT_EXECUTAVEL = _praat_local if (_eh_arm and os.path.isfile(_praat_local)) else "praat"


def gravar_audio(rotulo):
    """Grava DURACAO segundos de áudio e salva em ARQUIVO_AUDIO."""
    input(f"Pressione ENTER e faça 'AAAAA' de forma firme e constante ({rotulo})...")
    print(f"\n🎙️ GRAVANDO ({DURACAO}s)...")
    audio_data = sd.rec(int(DURACAO * SAMPLE_RATE), samplerate=SAMPLE_RATE, channels=CANAIS, dtype='int16')
    sd.wait()
    print("✅ Gravação concluída!")
    write(ARQUIVO_AUDIO, SAMPLE_RATE, audio_data)


def rodar_praat():
    """
    Chama o Praat de verdade (binário nativo) em modo headless, rodando o
    script analisar_voz.praat, que faz EXATAMENTE as mesmas chamadas (To
    Pitch, To PointProcess periodic/cc, Get jitter local, Get shimmer
    local, com os mesmos parâmetros) que o parselmouth fazia por baixo dos
    panos — preservando a mesma precisão, já que é o mesmo motor de
    análise acústica. Também mede HNR, usado só como indicador de
    qualidade da gravação.
    Retorna um dict {"f0", "jitter", "shimmer", "hnr"}.
    """
    try:
        resultado = subprocess.run(
            [PRAAT_EXECUTAVEL, "--run", SCRIPT_PRAAT, ARQUIVO_AUDIO],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except OSError as erro_exec:
        # errno 8 = Exec format error: o binário escolhido não é compatível
        # com esta arquitetura (ex: binário ARM leftover num PC x86_64).
        # Nesse caso, tenta de novo usando o "praat" instalado no PATH.
        if erro_exec.errno == 8 and PRAAT_EXECUTAVEL != "praat":
            print(
                f"\n⚠️ '{PRAAT_EXECUTAVEL}' não é compatível com esta máquina "
                "(Exec format error). Tentando com o 'praat' do PATH..."
            )
            resultado = subprocess.run(
                ["praat", "--run", SCRIPT_PRAAT, ARQUIVO_AUDIO],
                capture_output=True,
                text=True,
                timeout=30,
            )
        else:
            raise

    if resultado.returncode != 0:
        raise RuntimeError(
            f"Praat retornou erro (código {resultado.returncode}):\n{resultado.stderr.strip()}"
        )

    # O script .praat imprime a última linha como "f0,jitter,shimmer,hnr"
    linha_saida = resultado.stdout.strip().splitlines()[-1]
    f0_str, jitter_str, shimmer_str, hnr_str = linha_saida.split(",")
    f0_medio = float(f0_str)
    jitter = float(jitter_str) * 100
    shimmer = float(shimmer_str) * 100
    hnr = float(hnr_str)

    if f0_medio < 0 or jitter < 0 or shimmer < 0:
        raise RuntimeError("Praat não conseguiu detectar voz periódica suficiente no áudio gravado.")

    return {"f0": f0_medio, "jitter": jitter, "shimmer": shimmer, "hnr": hnr}


def carregar_baseline():
    if os.path.isfile(ARQUIVO_BASELINE):
        with open(ARQUIVO_BASELINE, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def salvar_baseline(dados):
    with open(ARQUIVO_BASELINE, "w", encoding="utf-8") as f:
        json.dump(dados, f, indent=2, ensure_ascii=False)


def calibrar_baseline():
    """
    Grava REPETICOES_CALIBRACAO amostras e usa a MÉDIA como baseline
    pessoal. Isso deve ser feito num momento de referência (ex: início do
    expediente, sem fadiga/estresse), não durante o teste que se quer
    avaliar.
    """
    print("\n=== CALIBRAÇÃO DE BASELINE PESSOAL ===")
    print(
        f"Vamos gravar {REPETICOES_CALIBRACAO}x sua voz de referência. "
        "Faça isso num momento tranquilo (ex: início do dia), não quando "
        "já estiver cansado/estressado — é essa gravação que vai virar a "
        "referência de comparação daqui pra frente.\n"
    )

    amostras = []
    for i in range(REPETICOES_CALIBRACAO):
        gravar_audio(f"calibração {i + 1}/{REPETICOES_CALIBRACAO}")
        amostras.append(rodar_praat())

    baseline = {
        "f0": sum(a["f0"] for a in amostras) / len(amostras),
        "jitter": sum(a["jitter"] for a in amostras) / len(amostras),
        "shimmer": sum(a["shimmer"] for a in amostras) / len(amostras),
        "hnr": sum(a["hnr"] for a in amostras) / len(amostras),
    }
    salvar_baseline(baseline)

    print("\n✅ Baseline calibrada e salva:")
    print(f"📊 Pitch: {baseline['f0']:.1f} Hz")
    print(f"🔹 Jitter: {baseline['jitter']:.2f}%")
    print(f"🔹 Shimmer: {baseline['shimmer']:.2f}%")
    print(f"🔹 HNR: {baseline['hnr']:.1f} dB")
    return baseline


print("\n=== TESTE RECALIBRADO DE FADIGA VOCAL ===")

try:
    recalibrar = "--calibrar" in sys.argv
    baseline = None if recalibrar else carregar_baseline()

    if baseline is None:
        baseline = calibrar_baseline()
        print(
            "\nRode o programa novamente mais tarde (ex: fim do "
            "expediente) para comparar seu estado atual com essa baseline."
        )

    else:
        print(
            f"Baseline carregada (jitter={baseline['jitter']:.2f}%, "
            f"shimmer={baseline['shimmer']:.2f}%). Rode com --calibrar "
            "para refazer a baseline."
        )

        gravar_audio("teste")
        medicao = rodar_praat()

        # Variação relativa em relação à PRÓPRIA baseline, não a um
        # limiar fixo de população.
        delta_jitter = (medicao["jitter"] - baseline["jitter"]) / baseline["jitter"]
        delta_shimmer = (medicao["shimmer"] - baseline["shimmer"]) / baseline["shimmer"]

        jitter_alto = delta_jitter > LIMIAR_AUMENTO_JITTER
        shimmer_alto = delta_shimmer > LIMIAR_AUMENTO_SHIMMER

        print("\n=== RESULTADOS MEDIDOS ===")
        print(f"📊 Frequência Média (Pitch): {medicao['f0']:.1f} Hz")
        print(f"🔹 Jitter Medido:  {medicao['jitter']:.2f}%  (baseline: {baseline['jitter']:.2f}%, variação: {delta_jitter*100:+.0f}%)")
        print(f"🔹 Shimmer Medido: {medicao['shimmer']:.2f}%  (baseline: {baseline['shimmer']:.2f}%, variação: {delta_shimmer*100:+.0f}%)")
        print(f"🔹 HNR Medido: {medicao['hnr']:.1f} dB")

        if medicao["hnr"] < LIMIAR_HNR_MINIMO:
            print(
                "\n⚠️ AVISO: HNR baixo — a gravação parece ter bastante "
                "ruído de fundo ou o microfone estava longe. Os valores de "
                "jitter/shimmer acima podem estar inflados por isso, não "
                "necessariamente por fadiga vocal real."
            )

        # Jitter é o sinal primário (mais consistente na literatura);
        # shimmer sozinho não decide, só reforça a suspeita quando o
        # jitter já está alto.
        if jitter_alto and shimmer_alto:
            print("\n⚠️ RESULTADO: FORTE SUSPEITA DE FADIGA VOCAL / ESTRESSE (jitter e shimmer elevados)")
        elif jitter_alto:
            print("\n⚠️ RESULTADO: SUSPEITA MODERADA DE FADIGA VOCAL / ESTRESSE (jitter elevado)")
        else:
            print("\n✅ RESULTADO: VOZ ESTÁVEL (sem variação relevante em relação à baseline)")

except FileNotFoundError:
    print(
        f"\n❌ Erro: executável do Praat ('{PRAAT_EXECUTAVEL}') não encontrado. "
        "Confira se ele está no PATH ou ajuste PRAAT_EXECUTAVEL para o caminho absoluto."
    )
except Exception as e:
    print(f"\n❌ Erro: {e}")
