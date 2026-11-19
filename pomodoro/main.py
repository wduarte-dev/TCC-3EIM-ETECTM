#!/usr/bin/env python3
"""
Pomodoro com display OLED + 3 botões, ligado ao monitor de postura.

    No Pi (OLED e botões de verdade):      python main.py
    No notebook (sem hardware):            python main.py --display png --botoes teclado --voz simulada
    Demo acelerada (1 s real = 1 min):     python main.py --display png --botoes teclado --velocidade 60

Botões:
    B1 (GPIO17)  RECALIBRAÇÃO (não mexe no pomodoro):
                 curto alterna POSTURA ↔ VOZ, longo recalibra a opção mostrada
    B2 (GPIO27)  SELEÇÃO: curto troca o preset, longo inicia
                 rodando/pausado: longo pausa/retoma, muito longo reinicia
    B3 (GPIO22)  DESLIGAR O PI: segure 3 s e solte (sudo poweroff); soltar antes cancela
"""
import argparse
import os
import queue
import signal
import sys
import time

from pomodoro_config import (
    ATUALIZACAO_TELA_S, PISCAR_MUDANCA_FASE_S, CAMINHO_BASELINE_VOZ,
    POLARIDADE_BOTOES, PULL_INTERNO_BOTOES,
)
from pomodoro_logica import Pomodoro, EV_FASE_MUDOU, LONGO, MUITO_LONGO
from recalibracao import MenuB1, ACAO_RECALIBRAR, POSTURA, VOZ
from postura_cliente import MonitorPostura, texto_curto
from voz_cliente import RecalibradorVoz, VozSimulada
from display import criar_display, desenhar
from energia import Desligamento, TEXTO_DESLIGANDO


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--display", choices=["oled", "pygame", "png"], default="oled")
    ap.add_argument("--botoes", choices=["gpio", "teclado"], default="gpio")
    ap.add_argument("--polaridade", choices=["auto", "alto", "baixo"], default=POLARIDADE_BOTOES,
                    help="OUT do módulo: auto = descobre lendo o botão solto (não aperte nada ao iniciar); "
                         "alto = sobe ao apertar; baixo = desce ao apertar")
    ap.add_argument("--pull", choices=["nenhum", "cima", "baixo"], default=PULL_INTERNO_BOTOES or "nenhum",
                    help="resistor interno do Pi no pino do OUT (o módulo já tem o dele: nenhum)")
    ap.add_argument("--voz", choices=["real", "simulada"], default="real",
                    help="simulada = recalibração de voz de mentira (sem mic/Praat), pra testar no notebook")
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
        botoes = BotoesGPIO(fila, polaridade=args.polaridade,
                            pull=None if args.pull == "nenhum" else args.pull)
    else:
        from botoes import BotoesTeclado
        botoes = BotoesTeclado(fila)

    monitor = MonitorPostura()
    pomo = Pomodoro()
    menu = MenuB1()
    if args.botoes == "teclado":
        # no notebook o "3m" NUNCA desliga a máquina de verdade: só mostra o comando
        desligamento = Desligamento(executar=lambda c: print(f"[simulado] desligaria com: {' '.join(c)}",
                                                               flush=True) or True)
    else:
        desligamento = Desligamento()
    voz = RecalibradorVoz(carregar=lambda: VozSimulada) if args.voz == "simulada" else RecalibradorVoz()
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
        dt_real = agora - ultimo
        dt = dt_real * args.velocidade     # só o pomodoro acelera na demo; o menu usa tempo real
        ultimo = agora

        eventos = []
        while True:
            try:
                origem, tipo = fila.get_nowait()
            except queue.Empty:
                break
            if origem == "SAIR":
                rodando["sim"] = False
            elif desligamento.em_andamento:
                continue                 # desligando: ignora qualquer botão
            elif origem == "B3":
                desligamento.botao(tipo)
            elif origem == "B1":
                menu.ocupado = voz.ocupado
                acao = menu.botao(tipo)
                if acao:
                    _, opcao = acao
                    if opcao == POSTURA:
                        monitor.recalibrar()
                    else:
                        voz.iniciar()
            elif origem == "B2":
                eventos += pomo.botao(tipo)
        eventos += pomo.tick(dt)
        menu.ocupado = voz.ocupado
        menu.tick(dt_real)

        if EV_FASE_MUDOU in eventos:
            piscar_ate = agora + PISCAR_MUDANCA_FASE_S

        if agora - ultimo_desenho >= ATUALIZACAO_TELA_S:
            ultimo_desenho = agora
            estado_postura = monitor.estado
            segurando = botoes.aperto_b2.tipo_se_soltar_agora()
            segurando_b1 = botoes.aperto_b1.tipo_se_soltar_agora() in (LONGO, MUITO_LONGO)
            # Linha de baixo: B3/desligar > voz recalibrando > menu do B1 > postura
            calibrado = {   # sem baseline/calibração ainda, o menu mostra CALIBRAR em vez de RECALIBRAR
                POSTURA: (estado_postura or {}).get("status") != "AGUARDANDO_CALIBRACAO",
                VOZ: os.path.isfile(CAMINHO_BASELINE_VOZ),
            }
            texto_baixo = (desligamento.texto(botoes.aperto_b3.segurando_ha())
                           or voz.mensagem or menu.texto(segurando_b1, calibrado))
            imagem = desenhar(
                pomo,
                texto_baixo or texto_curto(estado_postura),
                status_postura=None if texto_baixo else (estado_postura or {}).get("status"),
                segurando_tipo=segurando if segurando in (LONGO, MUITO_LONGO) else None,
                piscando=agora < piscar_ate and int(agora * 2) % 2 == 0,   # pisca ~2x por segundo
            )
            tela.mostrar(imagem)

        time.sleep(0.05)

    monitor.parar()
    botoes.fechar()
    if desligamento.em_andamento:
        # o systemd manda SIGTERM ao desligar: deixa o aviso na tela em vez de apagá-la
        tela.mostrar(desenhar(pomo, TEXTO_DESLIGANDO))
    else:
        tela.fechar()


if __name__ == "__main__":
    main()
