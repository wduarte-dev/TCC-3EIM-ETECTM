#!/usr/bin/env python3
"""
Comando `wifi`: escolhe a rede Wi-Fi que o Pi usa (T7). Instalado pelo instalar.sh.

    wifi                             mostra a rede configurada (padrão: DIHMO / admin1234)
    wifi --ssid MinhaRede --senha 12345678
                                     troca a rede: grava pra tela mostrar e atualiza o
                                     perfil no NetworkManager

Depois, no Pi: B1 até WIFI CONECTAR e segure; a tela mostra rede, senha e banda
(2.4 GHz) enquanto o Pi tenta entrar.

Atenção: a senha digitada aqui fica no histórico do shell.
"""
import argparse
import sys

import wifi
from pomodoro_config import CAMINHO_WIFI


def main(argv=None):
    ap = argparse.ArgumentParser(prog="wifi", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ssid", help="nome da rede (hotspot do celular, roteador...)")
    ap.add_argument("--senha", help="senha WPA2 (8 a 63 caracteres)")
    args = ap.parse_args(argv)

    if args.ssid is None and args.senha is None:
        ssid, senha, do_usuario = wifi.carregar()
        origem = "configurada com o comando wifi" if do_usuario else "PADRÃO (troque com: wifi --ssid X --senha Y)"
        print(f"Rede:  {ssid}\nSenha: {senha}\nBanda: 2.4 GHz (o Pi 3B não tem 5 GHz)\nOrigem: {origem}")
        return
    if args.ssid is None or args.senha is None:
        sys.exit("Erro: passe as duas coisas:  wifi --ssid NOME --senha SENHA")

    try:
        wifi.salvar(args.ssid, args.senha)
    except wifi.WifiInvalido as erro:
        sys.exit(f"Erro: {erro}. Nada foi gravado.")
    except OSError as erro:
        sys.exit(f"Erro ao gravar {CAMINHO_WIFI}: {erro}")
    print(f"Rede gravada: {args.ssid}")

    if not wifi.tem_nmcli():
        print("Sem NetworkManager (nmcli) nesta máquina: só gravei pra tela. No Pi, rode de novo lá.")
        return
    if wifi.aplicar_perfil(args.ssid, args.senha):
        print("Perfil do NetworkManager atualizado. Pra conectar agora: B1 → WIFI CONECTAR (segure).")
    else:
        print("Aviso: não consegui atualizar o perfil do NetworkManager (permissão?).\n"
              "  A rede ficou gravada e o B1 tenta de novo na hora de conectar.\n"
              "  Pra conferir as permissões:  nmcli general permissions")


if __name__ == "__main__":
    main()
