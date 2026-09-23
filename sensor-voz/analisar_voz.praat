form Analisar Voz
    sentence Audio_file
endform

# Lê o áudio gravado pelo main.py
Read from file: audio_file$
sound = selected("Sound")

# --- OTIMIZAÇÃO: corta onset/offset ---
# Os primeiros/últimos ~0.5s de uma vogal sustentada são naturalmente mais
# instáveis (ataque e finalização da fonação), o que infla artificialmente
# jitter e shimmer. Medimos só o trecho central, quando isso deixa pelo
# menos ~1s de sinal; senão, usamos a gravação inteira (evita erro em
# gravações muito curtas).
duracao = Get total duration
margem = 0.5
if duracao - (2 * margem) >= 1.0
    t1 = margem
    t2 = duracao - margem
else
    t1 = 0
    t2 = duracao
endif

# 1. Pitch médio (mesmos parâmetros padrão do parselmouth: 75-600 Hz)
selectObject: sound
pitch = To Pitch: 0, 75, 600
f0_medio = Get mean: t1, t2, "Hertz"

# 2. PointProcess periódico (mesmos parâmetros: 75, 400)
selectObject: sound
pointProcess = To PointProcess (periodic, cc): 75, 400

# 3. Jitter local, medido só no trecho central (t1, t2)
selectObject: pointProcess
jitter_local = Get jitter (local): t1, t2, 0.0001, 0.02, 1.3

# 4. Shimmer local, medido só no trecho central (t1, t2)
selectObject: sound, pointProcess
shimmer_local = Get shimmer (local): t1, t2, 0.0001, 0.02, 1.3, 1.6

# 5. HNR (Harmonics-to-Noise Ratio): usado como indicador de qualidade da
# gravação (ruído de fundo/distância do mic), não como métrica de fadiga.
# Valores baixos sinalizam que jitter/shimmer podem estar inflados por
# ruído, e não por uma mudança real na voz.
selectObject: sound
harmonicidade = To Harmonicity (cc): 0.01, 75, 0.1, 1.0
hnr_medio = Get mean: t1, t2

# Trata casos sem voz detectada / sem harmonicidade válida
if f0_medio = undefined
    f0_medio = -1
endif
if jitter_local = undefined
    jitter_local = -1
endif
if shimmer_local = undefined
    shimmer_local = -1
endif
if hnr_medio = undefined
    hnr_medio = -1
endif

# Imprime em uma linha CSV simples no stdout: f0,jitter,shimmer,hnr
writeInfoLine: f0_medio, ",", jitter_local, ",", shimmer_local, ",", hnr_medio
