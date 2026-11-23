#!/usr/bin/env python3
"""
Teste de bancada do LCD 16x2 (HD44780) no Raspberry Pi. Usa o MESMO driver e os mesmos
pinos do pomodoro (pomodoro/lcd_hd44780.py e pomodoro/pomodoro_config.py), então se
isso funciona, o `python main.py` funciona.

    python teste_lcd.py              # sequência básica (~20 s), diz no terminal o que ver
    python teste_lcd.py --contraste  # só blocos, até Ctrl+C: pra regular o contraste (V0)
    python teste_lcd.py --telas      # as telas reais do pomodoro (precisa do pillow)

Antes: `sudo systemctl stop pomodoro` se o serviço estiver rodando (ele também usa o GPIO).
Bibliotecas: pip install gpiozero lgpio   (--telas: + pillow)
Se o lgpio não instalar, o gpiozero cai sozinho num backend próprio (native) e funciona.
"""
import argparse
import os
import sys
import time

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(AQUI, "pomodoro"))

from pomodoro_config import (   # noqa: E402  (precisa do sys.path acima)
    LCD_GPIO_RS, LCD_GPIO_E, LCD_GPIO_D4, LCD_GPIO_D5, LCD_GPIO_D6, LCD_GPIO_D7,
    LCD_COLUNAS, LCD_LINHAS,
)

BLOCO = 0xFF

# Caracteres próprios (5x8) só pra conferir a CGRAM: pausa, Ç, Ã e um ponto 3x3.
GLIFOS = {
    0: (0b00000, 0b11011, 0b11011, 0b11011, 0b11011, 0b11011, 0b11011, 0b00000),   # ‖
    1: (0b01110, 0b10001, 0b10000, 0b10000, 0b10001, 0b01110, 0b00100, 0b01100),   # Ç
    2: (0b01101, 0b10010, 0b01110, 0b10001, 0b10001, 0b11111, 0b10001, 0b10001),   # Ã
    3: (0b00000, 0b00000, 0b01110, 0b01110, 0b01110, 0b00000, 0b00000, 0b00000),   # ●
}


def linha(lcd, n, texto):
    lcd.posicao(n, 0)
    lcd.escrever(texto.ljust(LCD_COLUNAS)[:LCD_COLUNAS].encode("latin-1", "replace"))


def etapa(lcd, titulo, o_que_ver, l1, l2, segundos=3.0):
    print(f"\n[{titulo}] {o_que_ver}")
    lcd.limpar()
    linha(lcd, 0, l1)
    linha(lcd, 1, l2)
    time.sleep(segundos)


def teste_basico(lcd):
    etapa(lcd, "1/5 blocos", "as 2 linhas inteiras cheias de quadrados brancos/escuros, sem falhas",
          bytes([BLOCO] * 16).decode("latin-1"), bytes([BLOCO] * 16).decode("latin-1"))
    etapa(lcd, "2/5 texto", "'LCD 16x2 OK' em cima e 'Ola, TCC!' embaixo",
          "LCD 16x2 OK", "Ola, TCC!")
    etapa(lcd, "3/5 alfabeto", "ABCDEFGHIJKLMNOP / QRSTUVWXYZ012345 (letra errada = fio de dados trocado)",
          "ABCDEFGHIJKLMNOP", "QRSTUVWXYZ012345")
    for slot, bits in GLIFOS.items():
        lcd.criar_caractere(slot, bits)
    lcd.limpar()
    print("\n[4/5 caracteres próprios] ‖ Ç Ã ● (pausa, cedilha, til, ponto) na 1ª linha")
    lcd.posicao(0, 0)
    lcd.escrever(bytes([0, 32, 1, 32, 2, 32, 3]))
    linha(lcd, 1, "CGRAM OK?")
    time.sleep(3)
    print("\n[5/5 contador] linha de baixo conta de 0 a 9 (confere se atualiza sem piscar)")
    lcd.limpar()
    linha(lcd, 0, "CONTANDO...")
    for i in range(10):
        linha(lcd, 1, f"valor: {i}")
        time.sleep(0.4)


def teste_contraste(lcd):
    print("Linhas cheias de blocos. Ajuste o V0 até enxergar blocos nítidos. Ctrl+C sai.")
    cheia = bytes([BLOCO] * 16).decode("latin-1")
    linha(lcd, 0, cheia)
    linha(lcd, 1, cheia)
    while True:
        time.sleep(1)


def teste_telas():
    from unittest import mock
    from display_lcd import DisplayLCD, desenhar, desenhar_wifi_espera, desenhar_wifi_resultado
    from pomodoro_config import PRESETS
    from pomodoro_logica import Pomodoro, CURTO, LONGO

    tela = DisplayLCD()
    try:
        pomo = Pomodoro(PRESETS)
        t = lambda x: mock.patch("display_lcd.time.monotonic", return_value=x)  # noqa: E731
        passos = []
        with t(100):
            passos.append(("escolha do tempo, sem serviço de postura",
                           desenhar(pomo, "POSTURA: SEM SERVIÇO")))
        pomo.botao(LONGO)
        with t(100):
            passos += [
                ("foco, postura boa", desenhar(pomo, "POSTURA: BOA", "CORRETA")),
                ("postura em atenção (Ç e Ã próprios)", desenhar(pomo, "POSTURA: ATENÇÃO", "ATENCAO")),
                ("calibrando: texto + 3 pontos (cheio/vazio/cheio)",
                 desenhar(pomo, "COMEÇANDO EM: 7s", "CONTAGEM", pontos=(True, False, True))),
                ("segurando o B3", desenhar(pomo, "SEGURE 3s: DESLIGAR")),
            ]
        with t(100.6):
            passos.append(("postura RUIM, fase 'blocos' do pisca",
                           desenhar(pomo, "POSTURA: RUIM", "ALERTA")))
        with t(7.0):
            passos.append(("preset aparecendo no lugar da fase",
                           desenhar(pomo, "POSTURA: BOA", "CORRETA")))
        pomo.botao(CURTO)
        with t(100):
            passos.append(("pausado (ícone ‖)", desenhar(pomo, "POSTURA: BOA", "CORRETA")))
            passos.append(("Wi-Fi conectando", desenhar_wifi_espera("DIHMO", "admin1234", 3)))
            passos.append(("Wi-Fi conectado", desenhar_wifi_resultado(True, "DIHMO")))
            passos.append(("Wi-Fi falhou", desenhar_wifi_resultado(False, "DIHMO")))
        for nome, quadro in passos:
            print(f"[tela] {nome}:  {quadro.texto()}")
            tela.mostrar(quadro)
            time.sleep(3)
    finally:
        tela.fechar()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    modo = ap.add_mutually_exclusive_group()
    modo.add_argument("--contraste", action="store_true", help="só blocos, até Ctrl+C")
    modo.add_argument("--telas", action="store_true", help="telas reais do pomodoro (precisa do pillow)")
    args = ap.parse_args()

    print("LCD 16x2: RS=GPIO%d E=GPIO%d D4..D7=GPIO%d/%d/%d/%d (pinos físicos 29/31/33/35/37/36)" % (
        LCD_GPIO_RS, LCD_GPIO_E, LCD_GPIO_D4, LCD_GPIO_D5, LCD_GPIO_D6, LCD_GPIO_D7))
    try:
        if args.telas:
            teste_telas()
            return
        from lcd_hd44780 import LCD4Bits
        lcd = LCD4Bits(LCD_GPIO_RS, LCD_GPIO_E, LCD_GPIO_D4, LCD_GPIO_D5, LCD_GPIO_D6, LCD_GPIO_D7,
                       LCD_COLUNAS, LCD_LINHAS)
    except ImportError as erro:
        sys.exit(f"Falta uma biblioteca: {erro}\n  pip install gpiozero lgpio" + ("  pillow" if args.telas else ""))
    except Exception as erro:   # GPIO ocupado, sem permissão...
        sys.exit(f"Não consegui abrir o GPIO: {erro}\n  O serviço do pomodoro está rodando? "
                 "`sudo systemctl stop pomodoro`")
    try:
        if args.contraste:
            teste_contraste(lcd)
        else:
            teste_basico(lcd)
            print("\nTerminou. Se tudo apareceu certo, o LCD e a fiação estão ok.")
    except KeyboardInterrupt:
        print()
    finally:
        lcd.limpar()
        lcd.fechar()


if __name__ == "__main__":
    main()
