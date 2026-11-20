#!/usr/bin/env python3
"""
Comando `pomodoro`: gerencia os presets (T6). Instalado pelo instalar.sh.

    pomodoro listar                       mostra os presets (o 1º é o pré-configurado)
    pomodoro adicionar --preset 50/10     foco/pausa, em minutos (sem pausa longa)
    pomodoro adicionar --preset 50/10/20  o 3º número é a pausa longa (a cada 4 focos)
    pomodoro remover --preset 50/10       tira um preset seu (o pré-configurado fica)

Os presets ficam em ~/.config/pomodoro/presets.json (fora do repositório). O serviço
percebe a mudança sozinho na próxima vez que a tela de escolha (TEMPO) aparecer.
No Windows: python pomodoro_ctl.py listar
"""
import argparse
import sys

import presets
from pomodoro_config import CAMINHO_PRESETS, CICLOS_ATE_PAUSA_LONGA


def descrever(p):
    longa = (f", pausa longa {p['pausa_longa']} min a cada {CICLOS_ATE_PAUSA_LONGA} focos"
             if p["pausa_longa"] is not None else ", sem pausa longa")
    return f"{p['nome']:<10} foco {p['foco']} min, pausa {p['pausa']} min{longa}"


def main(argv=None):
    ap = argparse.ArgumentParser(prog="pomodoro", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="comando", required=True)
    sub.add_parser("listar", help="mostra os presets")
    for nome in ("adicionar", "remover"):
        p = sub.add_parser(nome, help=f"{nome} um preset")
        p.add_argument("--preset", required=True, metavar="MM/MM[/MM]")
    args = ap.parse_args(argv)

    try:
        if args.comando == "adicionar":
            p = presets.adicionar(args.preset)
            print(f"Adicionado: {descrever(p)}")
        elif args.comando == "remover":
            p = presets.remover(args.preset)
            print(f"Removido: {p['nome']}")
        else:
            for i, p in enumerate(presets.todos()):
                print(("* " if i == 0 else "  ") + descrever(p))
            print(f"\n* pré-configurado (não removível). Arquivo: {CAMINHO_PRESETS}")
    except presets.PresetInvalido as erro:
        sys.exit(f"Erro: {erro}. Nada foi gravado.")
    except OSError as erro:
        sys.exit(f"Erro ao gravar {CAMINHO_PRESETS}: {erro}")


if __name__ == "__main__":
    main()
