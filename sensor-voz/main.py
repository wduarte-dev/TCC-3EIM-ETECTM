import sounddevice as sd
import numpy as np
from scipy.io.wavfile import write
import parselmouth
import os


SAMPLE_RATE = 48000
CANAIS = 1
DURACAO = 3

# Pega o caminho absoluto do diretório onde este arquivo .py está localizado
DIRETORIO_ATUAL = os.path.dirname(os.path.abspath(__file__))
ARQUIVO_AUDIO = os.path.join(DIRETORIO_ATUAL, "teste_audio.wav")

print("\n=== TESTE RECALIBRADO DE FADIGA VOCAL ===")
input("Pressione ENTER e faça 'AAAAA' de forma firme e constante...")

print(f"\n🎙️ GRAVANDO ({DURACAO}s)...")
audio_data = sd.rec(int(DURACAO * SAMPLE_RATE), samplerate=SAMPLE_RATE, channels=CANAIS, dtype='int16')
sd.wait()
print("✅ Gravação concluída!")

# Salva o arquivo WAV
write(ARQUIVO_AUDIO, SAMPLE_RATE, audio_data)

try:
    sound = parselmouth.Sound(ARQUIVO_AUDIO)
    
    # 1. Filtra a frequência fundamental (f0) para evitar pegar ruído ambiente
    pitch = sound.to_pitch()
    f0_medio = parselmouth.praat.call(pitch, "Get mean", 0, 0, "Hertz")
    
    # 2. Extrai Jitter e Shimmer com parâmetros ajustados para mic USB
    pointProcess = parselmouth.praat.call(sound, "To PointProcess (periodic, cc)", 75, 400)
    jitter = parselmouth.praat.call(pointProcess, "Get jitter (local)", 0, 0, 0.0001, 0.02, 1.3) * 100
    shimmer = parselmouth.praat.call([sound, pointProcess], "Get shimmer (local)", 0, 0, 0.0001, 0.02, 1.3, 1.6) * 100

    print("\n=== RESULTADOS MEDIDOS ===")
    print(f"📊 Frequência Média (Pitch): {f0_medio:.1f} Hz")
    print(f"🔹 Jitter Medido:  {jitter:.2f}%  (Limite Normal: <= 1.50%)")
    print(f"🔹 Shimmer Medido: {shimmer:.2f}%  (Limite Normal: <= 4.50%)")
    
    # Limiares mais tolerantes e realistas para ambiente de teste
    if jitter > 1.50 or shimmer > 4.50:
        print("\n⚠️ RESULTADO: SUSPEITA DE FADIGA VOCAL / ESTRESSE")
    else:
        print("\n✅ RESULTADO: VOZ ESTÁVEL (Sem fadiga detectada)")

except Exception as e:
    print(f"\n❌ Erro: {e}")