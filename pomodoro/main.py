#!/usr/bin/env python3
"""
Pomodoro com display OLED + 3 botões, ligado ao monitor de postura.

    No Pi (OLED e botões de verdade):      python main.py
    No notebook (sem hardware):            python main.py --display png --botoes teclado
    Demo acelerada (1 s real = 1 min):     python main.py --display png --botoes teclado --velocidade 60

Botões:
    B1 (GPIO17)  RECALIBRAÇÃO (não mexe no pomodoro):
                 curto alterna POSTURA → WIFI CONECTAR, longo executa a opção mostrada
                 (na espera do Wi-Fi, clique curto cancela)
    B2 (GPIO27)  SELEÇÃO: curto troca o preset, longo inicia
                 rodando/pausado: curto pausa/retoma, longo volta pra seleção
    B3 (GPIO22)  DESLIGAR O PI: segure 3 s e solte (sudo poweroff); soltar antes cancela;
                 clique curto só mostra a dica por 2 s
"""
import argparse
import queue
import signal
import sys
import time

from pomodoro_config import (
    ATUALIZACAO_TELA_S, PISCAR_MUDANCA_FASE_S,
    POLARIDADE_BOTOES, PULL_INTERNO_BOTOES,
)
from pomodoro_logica import Pomodoro, EV_FASE_MUDOU, CURTO, LONGO, MUITO_LONGO, SELECAO
import presets
from recalibracao import MenuB1, POSTURA, WIFI
from postura_cliente import MonitorPostura, texto_curto, pontos_enquadramento
from wifi import WifiConectar
from display import criar_display, desenhar, desenhar_wifi_espera, desenhar_wifi_resultado
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
    pomo = Pomodoro(presets=presets.todos())
    assinatura_presets = presets.assinatura()
    menu = MenuB1()
    if args.botoes == "teclado":
        # no notebook o "3m" NUNCA desliga a máquina de verdade: só mostra o comando
        desligamento = Desligamento(executar=lambda c: print(f"[simulado] desligaria com: {' '.join(c)}",
                                                               flush=True) or True)
    else:
        desligamento = Desligamento()
    wifi = WifiConectar()
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
                if wifi.esperando:
                    if tipo == CURTO:
                        wifi.cancelar()          # clique curto na espera volta ao inicial
                    continue
                if wifi.ocupado:
                    continue                     # resultado na tela: só espera sumir
                acao = menu.botao(tipo)
                if acao:
                    _, opcao = acao
                    if opcao == POSTURA:
                        monitor.recalibrar()
                    elif opcao == WIFI and wifi.pedir() == "confirmar":
                        menu.abrir_em(WIFI)      # SSH ativo: repetir o longo confirma
            elif origem == "B2":
                if not wifi.ocupado:             # tela do Wi-Fi cobre o pomodoro: B2 não age escondido
                    eventos += pomo.botao(tipo)
        eventos += pomo.tick(dt)
        # `pomodoro adicionar/remover` mexeu no arquivo: recarrega na tela de escolha
        if pomo.estado == SELECAO and presets.assinatura() != assinatura_presets:
            assinatura_presets = presets.assinatura()
            pomo.trocar_presets(presets.todos())
        menu.tick(dt_real)

        if EV_FASE_MUDOU in eventos:
            piscar_ate = agora + PISCAR_MUDANCA_FASE_S

        if agora - ultimo_desenho >= ATUALIZACAO_TELA_S:
            ultimo_desenho = agora
            estado_postura = monitor.estado
            segurando = botoes.aperto_b2.tipo_se_soltar_agora()
            segurando_b1 = botoes.aperto_b1.tipo_se_soltar_agora() in (LONGO, MUITO_LONGO)
            # Linha de baixo: B3/desligar > aviso do Wi-Fi (SSH) > menu do B1 > postura
            calibrado = {   # sem baseline/calibração ainda, o menu mostra CALIBRAR em vez de RECALIBRAR
                POSTURA: (estado_postura or {}).get("status") != "AGUARDANDO_CALIBRACAO",
            }
            texto_b3 = desligamento.texto(botoes.aperto_b3.segurando_ha())
            texto_baixo = texto_b3 or wifi.mensagem() or menu.texto(segurando_b1, calibrado)
            tela_wifi = None if texto_b3 else wifi.tela    # o B3 sempre aparece por cima
            if tela_wifi and tela_wifi[0] == "espera":
                tela.mostrar(desenhar_wifi_espera(*tela_wifi[1:]))
                time.sleep(0.05)
                continue
            if tela_wifi:
                tela.mostrar(desenhar_wifi_resultado(*tela_wifi[1:]))
                time.sleep(0.05)
                continue
            imagem = desenhar(
                pomo,
                texto_baixo or texto_curto(estado_postura),
                status_postura=None if texto_baixo else (estado_postura or {}).get("status"),
                segurando_tipo=segurando if segurando in (LONGO, MUITO_LONGO) else None,
                piscando=agora < piscar_ate and int(agora * 2) % 2 == 0,   # pisca ~2x por segundo
                pontos=None if texto_baixo else pontos_enquadramento(estado_postura),
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
