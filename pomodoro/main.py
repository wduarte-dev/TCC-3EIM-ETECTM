#!/usr/bin/env python3
"""
Pomodoro com display OLED + 2 botões, ligado ao monitor de postura.

    No Pi (OLED e botões de verdade):      python main.py
    No notebook (sem hardware):            python main.py --display png --botoes teclado
    Demo acelerada (1 s real = 1 min):     python main.py --display png --botoes teclado --velocidade 60

Botões:
    B1 (GPIO17)  qualquer aperto → recalibrar a postura
    B2 (GPIO27)  SELEÇÃO: curto troca o preset, longo inicia
                 rodando/pausado: longo pausa/retoma, muito longo reinicia
"""
import argparse
import queue
import signal
import sys
import time

from pomodoro_config import ATUALIZACAO_TELA_S, PISCAR_MUDANCA_FASE_S
from pomodoro_logica import Pomodoro, EV_FASE_MUDOU, LONGO, MUITO_LONGO
from postura_cliente import MonitorPostura, texto_curto
from display import criar_display, desenhar


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--display", choices=["oled", "pygame", "png"], default="oled")
    ap.add_argument("--botoes", choices=["gpio", "teclado"], default="gpio")
    ap.add_argument("--velocidade", type=float, default=1.0,
                    help="multiplica a passagem do tempo (60 = 1 s real vale 1 min; só pra demo/teste)")
    args = ap.parse_args()

    try:
        tela = criar_display(args.display)
    except Exception as erro:   # I2C sem resposta, biblioteca ausente...
        sys.exit(f"Não consegui abrir o display '{args.display}': {erro}\n"
                 "  No Pi: confira a ligação e rode `i2cdetect -y 1` (tem que aparecer 3c).")

    fila = queue.Queue()
    if args.botoes == "gpio":
        from botoes import BotoesGPIO
        botoes = BotoesGPIO(fila)
    else:
        from botoes import BotoesTeclado
        botoes = BotoesTeclado(fila)

    monitor = MonitorPostura()
    pomo = Pomodoro()
    rodando = {"sim": True}

    def encerrar(*_):
        rodando["sim"] = False
    signal.signal(signal.SIGINT, encerrar)
    signal.signal(signal.SIGTERM, encerrar)

    ultimo = time.monotonic()
    ultimo_desenho = 0.0
    piscar_ate = 0.0

    while rodando["sim"]:
        agora = time.monotonic()
        dt = (agora - ultimo) * args.velocidade
        ultimo = agora

        eventos = []
        while True:
            try:
                origem, tipo = fila.get_nowait()
            except queue.Empty:
                break
            if origem == "SAIR":
                rodando["sim"] = False
            elif origem == "B1":
                monitor.recalibrar()
            elif origem == "B2":
                eventos += pomo.botao(tipo)
        eventos += pomo.tick(dt)

        if EV_FASE_MUDOU in eventos:
            piscar_ate = agora + PISCAR_MUDANCA_FASE_S

        if agora - ultimo_desenho >= ATUALIZACAO_TELA_S:
            ultimo_desenho = agora
            estado_postura = monitor.estado
            segurando = botoes.aperto_b2.tipo_se_soltar_agora()
            imagem = desenhar(
                pomo,
                texto_curto(estado_postura),
                status_postura=(estado_postura or {}).get("status"),
                segurando_tipo=segurando if segurando in (LONGO, MUITO_LONGO) else None,
                piscando=agora < piscar_ate and int(agora * 2) % 2 == 0,   # pisca ~2x por segundo
            )
            tela.mostrar(imagem)

        time.sleep(0.05)

    monitor.parar()
    botoes.fechar()
    tela.fechar()


if __name__ == "__main__":
    main()
