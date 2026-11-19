#!/usr/bin/env python3
"""
Diagnóstico dos módulos de botão no Pi: mostra as BORDAS cruas de cada pino (sem filtro
nenhum), pra separar três problemas:

  1. repique (várias bordas em milissegundos num único aperto)  → o filtro do main.py resolve;
  2. ruído com o botão solto (bordas sem tocar em nada)         → fio, emenda ou pino flutuando;
  3. polaridade (nível parado alto ou baixo)                    → o main.py descobre sozinho.

Rode COM O POMODORO PARADO (`sudo systemctl stop pomodoro`), de dentro da pasta pomodoro/:

    python diagnostico_botoes.py                 # 5 s sem tocar, depois aperte à vontade; Ctrl+C encerra
    python diagnostico_botoes.py --pull baixo    # repete com pull-down interno
    python diagnostico_botoes.py --pull cima     # ...e com pull-up interno

Passo a passo: (1) não toque em nada durante a contagem; (2) dê 5 cliques curtos em cada botão;
(3) segure um deles por ~2 s e solte; (4) Ctrl+C e mande o resumo final.
"""
import argparse
import statistics
import time

from pomodoro_config import GPIO_B1, GPIO_B2, GPIO_B3

JANELA_REPIQUE_S = 0.05   # borda a menos de 50 ms da anterior conta como repique


def resumir(bordas, inicio_aperto_s, janela_repique_s=JANELA_REPIQUE_S):
    """
    bordas: lista de (t_s, nivel_alto) de UM pino, em ordem. `inicio_aperto_s`: instante em
    que o usuário foi liberado pra apertar (bordas antes disso = botão solto).
    Devolve um dict com as contagens.
    """
    antes = [b for b in bordas if b[0] < inicio_aperto_s]
    depois = [b for b in bordas if b[0] >= inicio_aperto_s]
    intervalos = [b[0] - a[0] for a, b in zip(bordas, bordas[1:])]
    repiques = sum(1 for dt in intervalos if dt < janela_repique_s)
    return {
        "bordas_com_botao_solto": len(antes),
        "bordas_durante_apertos": len(depois),
        "repiques": repiques,
        "menor_intervalo_ms": round(min(intervalos) * 1000, 1) if intervalos else None,
        "mediana_intervalo_ms": round(statistics.median(intervalos) * 1000, 1) if intervalos else None,
    }


def veredito(nome, r, nivel_inicial):
    linhas = [f"{nome}: parado em {'ALTO' if nivel_inicial else 'BAIXO'}"]
    if r["bordas_com_botao_solto"]:
        linhas.append(f"  ! {r['bordas_com_botao_solto']} borda(s) com o botão solto → ruído / fio ou emenda ruim "
                      "/ pino flutuando (software não conserta isso)")
    else:
        linhas.append("  ok: linha firme com o botão solto")
    if r["bordas_durante_apertos"] == 0:
        linhas.append("  (nenhuma borda nos apertos: não apertou, ou OUT desconectado)")
    elif r["repiques"]:
        linhas.append(f"  repique: {r['repiques']} borda(s) a menos de {JANELA_REPIQUE_S * 1000:.0f} ms da anterior "
                      f"(menor intervalo {r['menor_intervalo_ms']} ms) → o filtro do main.py trata")
    else:
        linhas.append(f"  sem repique (mediana entre bordas {r['mediana_intervalo_ms']} ms)")
    return "\n".join(linhas)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pull", choices=["nenhum", "cima", "baixo"], default="nenhum")
    ap.add_argument("--ocioso", type=float, default=5.0, help="segundos sem tocar em nada no início")
    ap.add_argument("--tempo", type=float, default=0.0, help="encerra sozinho depois disso (0 = só no Ctrl+C)")
    args = ap.parse_args()

    from gpiozero import DigitalInputDevice   # só no Pi
    pull_up, ativo = {"nenhum": (None, True), "baixo": (False, None), "cima": (True, None)}[args.pull]
    pinos = {"B1": GPIO_B1, "B2": GPIO_B2, "B3": GPIO_B3}
    t0 = time.monotonic()
    bordas = {nome: [] for nome in pinos}
    dispositivos = {}

    def registrar(nome, disp):
        def borda():
            t = time.monotonic() - t0
            nivel = bool(disp.pin.state)
            lista = bordas[nome]
            dt = (t - lista[-1][0]) * 1000 if lista else None
            lista.append((t, nivel))
            marca = "  <- REPIQUE" if dt is not None and dt < JANELA_REPIQUE_S * 1000 else ""
            intervalo = f"(+{dt:.1f} ms)" if dt is not None else ""
            print(f"{t:8.3f}s  {nome} GPIO{pinos[nome]} -> {'ALTO ' if nivel else 'BAIXO'} {intervalo}{marca}", flush=True)
        return borda

    for nome, pino in pinos.items():
        kw = {"pull_up": pull_up}
        if ativo is not None:
            kw["active_state"] = ativo
        disp = DigitalInputDevice(pino, **kw)     # sem bounce_time: bordas cruas
        dispositivos[nome] = disp
    niveis_iniciais = {nome: bool(d.pin.state) for nome, d in dispositivos.items()}
    for nome, disp in dispositivos.items():
        cb = registrar(nome, disp)
        disp.when_activated = cb      # os dois eventos chamam a mesma função: ela lê o nível real
        disp.when_deactivated = cb

    print(f"pull interno: {args.pull}. NÃO TOQUE em nenhum botão por {args.ocioso:.0f} s...", flush=True)
    try:
        while time.monotonic() - t0 < args.ocioso:
            time.sleep(0.05)
        print(">>> pode apertar (5 cliques curtos em cada botão; depois segure um por ~2 s). Ctrl+C encerra.", flush=True)
        while not args.tempo or time.monotonic() - t0 < args.ocioso + args.tempo:
            time.sleep(0.1)
    except KeyboardInterrupt:
        pass
    finally:
        for d in dispositivos.values():
            d.close()
    print("\n=== RESUMO ===")
    for nome in pinos:
        print(veredito(nome, resumir(bordas[nome], args.ocioso), niveis_iniciais[nome]))


if __name__ == "__main__":
    main()
