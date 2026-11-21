#!/usr/bin/env python3
"""
LOG DE SAÚDE DO PI: sempre ligado desde o boot, independente do serviço de postura.

Uma amostra a cada ~5 s em ~/tcc-logs/saude_AAAA-MM-DD.csv, gravada no cartão a cada
amostra (fsync): se a energia cair, é o registro que mais interessa (motivo: o reboot de
20/11/2026 ficou sem explicação porque não havia log do que veio antes).

Colunas:
    data_hora          ISO com fuso (mesmo relógio dos eventos e do CSV da postura)
    throttled          `vcgencmd get_throttled` em hex (bits "agora" + bits "já aconteceu")
    subtensao_agora    bit 0: subtensão NESTE instante (1/0)
    throttling_agora   bit 2: CPU limitada NESTE instante (1/0)
    temp_c             temperatura da CPU
    carga_1min         carga média de 1 min (o Pi 3B tem 4 núcleos: 4,0 = tudo ocupado)
    ram_disponivel_mb  MemAvailable do /proc/meminfo
    uptime_s           segundos desde o boot (uptime pequeno logo depois de outro grande = reboot)

Os bits 16 a 19 ("já aconteceu") ficam marcados até o próximo reboot; por isso a amostragem:
só os bits 0 a 3 dizem QUANDO aconteceu. Fora do Pi os campos do Pi ficam vazios.

Uso:  python3 saude.py              (o serviço `tcc-saude` roda assim; ver instalar.sh)
      python3 saude.py --uma        (imprime uma amostra e sai: teste rápido)
"""
import argparse
import os
import signal
import subprocess
import sys
import time

from registro_comum import (
    ArquivoDiario, RegistroEventos, GRUPO_SAUDE_EVENTOS, TETO_SAUDE_EVENTOS, agora_iso,
    versao_codigo, DIR_REGISTRO,
)

INTERVALO_S = 5.0
CAB_SAUDE = ["data_hora", "throttled", "subtensao_agora", "throttling_agora", "temp_c",
             "carga_1min", "ram_disponivel_mb", "uptime_s"]
BIT_SUBTENSAO_AGORA, BIT_THROTTLING_AGORA = 0, 2

ARQ_TEMP = "/sys/class/thermal/thermal_zone0/temp"
ARQ_MEMINFO = "/proc/meminfo"
ARQ_UPTIME = "/proc/uptime"


def ler_throttled(executar=subprocess.run):
    """'throttled=0x50005' → 0x50005 (int). None se não houver vcgencmd (fora do Pi)."""
    try:
        saida = executar(["vcgencmd", "get_throttled"], capture_output=True, text=True,
                         timeout=3).stdout.strip()
        return int(saida.split("=", 1)[1], 16)
    except (OSError, subprocess.SubprocessError, IndexError, ValueError):
        return None


def _ler(caminho):
    try:
        with open(caminho, encoding="ascii") as arq:
            return arq.read()
    except OSError:
        return None


def ler_temp_c(caminho=ARQ_TEMP):
    texto = _ler(caminho)          # em milésimos de grau
    try:
        return int(texto.strip()) / 1000.0
    except (AttributeError, ValueError):
        return None


def ler_ram_disponivel_mb(caminho=ARQ_MEMINFO):
    texto = _ler(caminho) or ""
    for linha in texto.splitlines():
        if linha.startswith("MemAvailable:"):
            try:
                return int(linha.split()[1]) / 1024.0      # kB → MB
            except (IndexError, ValueError):
                return None
    return None


def ler_uptime_s(caminho=ARQ_UPTIME):
    texto = _ler(caminho)
    try:
        return float(texto.split()[0])
    except (AttributeError, IndexError, ValueError):
        return None


def ler_carga_1min():
    try:
        return os.getloadavg()[0]
    except (AttributeError, OSError):      # Windows não tem
        return None


def amostra(executar=subprocess.run, temp=ARQ_TEMP, meminfo=ARQ_MEMINFO, uptime=ARQ_UPTIME):
    """Uma linha do log, na ordem de CAB_SAUDE."""
    t = ler_throttled(executar)
    return [
        agora_iso(),
        f"0x{t:x}" if t is not None else None,
        (t >> BIT_SUBTENSAO_AGORA) & 1 if t is not None else None,
        (t >> BIT_THROTTLING_AGORA) & 1 if t is not None else None,
        ler_temp_c(temp),
        ler_carga_1min(),
        ler_ram_disponivel_mb(meminfo),
        ler_uptime_s(uptime),
    ]


def main():
    ap = argparse.ArgumentParser(description="Log de saúde do Pi (TCC)")
    ap.add_argument("--uma", action="store_true", help="imprime uma amostra e sai")
    ap.add_argument("--intervalo", type=float, default=INTERVALO_S)
    args = ap.parse_args()

    if args.uma:
        print(dict(zip(CAB_SAUDE, amostra())))
        return

    versao = versao_codigo()
    log = ArquivoDiario("saude", CAB_SAUDE, "saude", grupo=GRUPO_SAUDE_EVENTOS,
                        teto_bytes=TETO_SAUDE_EVENTOS, fsync=True, versao=versao)
    eventos = RegistroEventos("saude", versao=versao)
    print(f"Log de saúde em {DIR_REGISTRO} a cada {args.intervalo:g} s | versão do código: {versao}",
          flush=True)
    eventos.servico_iniciou("saude")

    rodando = {"sim": True}

    def parar(*_):
        rodando["sim"] = False
    signal.signal(signal.SIGTERM, parar)
    signal.signal(signal.SIGINT, parar)

    proxima = time.monotonic()
    while rodando["sim"]:
        log.registrar(*amostra())
        proxima += args.intervalo
        espera = proxima - time.monotonic()
        if espera < 0:                 # atrasou (Pi travado/sobrecarregado): não acumula
            proxima = time.monotonic()
            espera = 0
        fim = time.monotonic() + espera
        while rodando["sim"] and time.monotonic() < fim:
            time.sleep(min(0.5, max(0.0, fim - time.monotonic())))

    eventos.servico_parou("saude")
    log.fechar()
    eventos.fechar()
    print("Log de saúde encerrado.", flush=True)


if __name__ == "__main__":
    sys.exit(main())
