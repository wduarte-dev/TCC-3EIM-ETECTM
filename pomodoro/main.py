import time
minutos = int(input("Digite o tempo em minutos: "))
tempo_total_em_segundos = minutos * 60
segundos = minutos = horas = 0
while True:
    time.sleep(1)
    tempo_total_em_segundos -= 1
    if tempo_total_em_segundos == 0:
        print("TEMPO ACABOU!")
        exit()
    segundos += 1
    if segundos == 60:
        segundos = 0
        minutos += 1
        if minutos == 60:
            minutos = 0
            horas += 1
    print(f"{horas}h {minutos}min {segundos}s")

    
    