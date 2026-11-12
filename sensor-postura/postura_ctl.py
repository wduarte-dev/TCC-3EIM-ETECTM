#!/usr/bin/env python3
"""
Controle remoto do monitor de postura. Instalado como o comando `postura`.

    postura status        o que está rodando agora
    postura recalibrar    calibra (contagem de 10s pra se ajeitar, mostrada aqui)
    postura gravar N      grava N segundos da webcam em videos/ (N maior que 5)
    postura janela        abre o monitor com a janela da câmera (precisa de ssh -X)
    postura live          volta pra câmera ao vivo (fica aguardando calibração)
    postura video [N]     troca pra um vídeo da pasta videos/ (sem N, mostra a lista)
    postura videos        só lista os vídeos
    postura log           acompanha a saída do serviço ao vivo (Ctrl+C sai)
    postura parar | iniciar | reiniciar    controla o serviço do systemd
"""
import os
import sys
import json
import time
import socket
import subprocess

from postura_config import (
    CAMINHO_SOCKET, DIR_VIDEOS, listar_videos,
    DURACAO_CALIBRACAO, CONTAGEM_CALIBRACAO, CONTAGEM_GRAVACAO, GRAVACAO_MAX_S,
)

NOME_SERVICO = "postura"


def enviar(pedido):
    cliente = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    cliente.settimeout(3.0)
    try:
        cliente.connect(CAMINHO_SOCKET)
        cliente.sendall((json.dumps(pedido) + "\n").encode("utf-8"))
        dados = b""
        while not dados.endswith(b"\n"):
            pedaco = cliente.recv(4096)
            if not pedaco:
                break
            dados += pedaco
        return json.loads(dados.decode("utf-8"))
    except (FileNotFoundError, ConnectionRefusedError):
        sys.exit("O monitor de postura não está rodando.\n"
                 "  Ligar o serviço:   postura iniciar\n"
                 "  Ou rodar manual:   python3 postura_servico.py --preview")
    except socket.timeout:
        sys.exit("O monitor não respondeu (pode estar carregando o modelo). Tenta de novo em alguns segundos.")
    finally:
        cliente.close()


def mostrar_resposta(resposta):
    if resposta.get("ok"):
        print(resposta.get("msg", "OK"))
    else:
        sys.exit(f"Erro: {resposta.get('erro', 'desconhecido')}")


def acompanhar(chave, id_antes, tempo_max):
    """
    Mostra no terminal o que o serviço vai dizendo (contagem, "gravando...")
    até a calibração/gravação terminar. `chave` = "calibracao" ou "gravacao".
    """
    ultimo_texto = None
    limite = time.time() + tempo_max
    while time.time() < limite:
        estado = enviar({"acao": "status"})["estado"]
        if estado["texto"] != ultimo_texto:
            print(f"  {estado['texto']}")
            ultimo_texto = estado["texto"]
        fim = estado[chave]
        if fim["id"] != id_antes:
            if fim["ok"]:
                print(f"✅ {fim['msg']}")
                return
            sys.exit(f"❌ {fim['msg']}")
        time.sleep(0.25)
    sys.exit("O serviço demorou demais pra responder. Confira com: postura log")


def cmd_recalibrar():
    id_antes = enviar({"acao": "status"})["estado"]["calibracao"]["id"]
    mostrar_resposta(enviar({"acao": "recalibrar"}))
    acompanhar("calibracao", id_antes, CONTAGEM_CALIBRACAO + DURACAO_CALIBRACAO + 30)


def cmd_gravar(argumento):
    if argumento is None or not argumento.isdigit():
        sys.exit(f"Use: postura gravar N   (N em segundos, maior que {DURACAO_CALIBRACAO} e até {GRAVACAO_MAX_S})")
    segundos = int(argumento)
    id_antes = enviar({"acao": "status"})["estado"]["gravacao"]["id"]
    mostrar_resposta(enviar({"acao": "gravar", "segundos": segundos}))
    acompanhar("gravacao", id_antes, CONTAGEM_GRAVACAO + segundos + 30)


def cmd_status():
    estado = enviar({"acao": "status"})["estado"]
    if estado["fonte"] == "live":
        fonte = "câmera ao vivo"
    elif estado["fonte"] == "video":
        fonte = f"vídeo  {os.path.basename(estado['video'] or '')}"
    else:
        fonte = "-"
    print(f"Fonte:       {fonte}")
    print(f"Status:      {estado['texto']}")
    if estado.get("baseline_angulo") is not None:
        print(f"Baseline:    ângulo {estado['baseline_angulo']}° | razão {estado['baseline_razao']}")
    print(f"FPS:         {estado.get('fps', 0)}")
    print(f"Atualizado:  {estado.get('atualizado')}   (rodando desde {estado.get('inicio')})")


def cmd_videos():
    videos = listar_videos()
    if not videos:
        print(f"Nenhum vídeo em {DIR_VIDEOS}")
        print("Coloque arquivos .mp4/.avi/.mkv/.mov/.webm nessa pasta.")
        return []
    for i, nome in enumerate(videos, 1):
        print(f"  [{i}] {nome}")
    return videos


def cmd_video(argumento):
    videos = listar_videos()
    if not videos:
        cmd_videos()
        return

    if argumento is None:
        print("Vídeos disponíveis:")
        cmd_videos()
        try:
            argumento = input("Número do vídeo (0 cancela): ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if argumento in ("", "0"):
            print("Cancelado.")
            return

    if argumento.isdigit():
        indice = int(argumento)
        if not 1 <= indice <= len(videos):
            sys.exit(f"Número inválido. Escolha de 1 a {len(videos)}.")
        nome = videos[indice - 1]
    else:
        nome = argumento

    mostrar_resposta(enviar({"acao": "video", "arquivo": nome}))


def servico_ativo():
    return subprocess.call(["systemctl", "is-active", "--quiet", NOME_SERVICO]) == 0


def cmd_janela():
    """
    Abre o monitor COM JANELA neste terminal (precisa de ssh -X).
    Pausa o serviço antes (os dois disputariam a câmera) e religa ele no fim,
    dê certo ou dê erro. A baseline salva é reaproveitada nos dois sentidos.
    """
    if not os.environ.get("DISPLAY"):
        sys.exit("Sem tela pra abrir a janela. Entre no Pi com:  ssh -X wwwt@raspberrypi.local")

    estava_ativo = servico_ativo()
    if estava_ativo:
        print("Pausando o serviço pra liberar a câmera...")
        if subprocess.call(["sudo", "systemctl", "stop", NOME_SERVICO]) != 0:
            sys.exit("Não consegui pausar o serviço.")

    servico = os.path.join(os.path.dirname(os.path.realpath(__file__)), "postura_servico.py")
    print("Abrindo a janela. 'q' fecha, 'r' recalibra (ou Ctrl+C aqui).\n")
    codigo = 0
    processo = subprocess.Popen([sys.executable, servico, "--preview"])
    try:
        codigo = processo.wait()
    except KeyboardInterrupt:
        codigo = processo.wait()  # o Ctrl+C também chega nele, que encerra limpo
    finally:
        if codigo not in (0, -2):
            print(f"\n⚠️  O modo janela terminou com erro (código {codigo}). Veja a mensagem acima.")
        if estava_ativo:
            print("Religando o serviço...")
            if subprocess.call(["sudo", "systemctl", "start", NOME_SERVICO]) == 0:
                print("Serviço de volta, rodando sem janela.")
            else:
                print("Não consegui religar o serviço. Use: postura iniciar")


def cmd_systemctl(acao):
    codigo = subprocess.call(["sudo", "systemctl", acao, NOME_SERVICO])
    if codigo == 0:
        mensagens = {"stop": "Serviço parado.", "start": "Serviço iniciado.", "restart": "Serviço reiniciado."}
        print(mensagens.get(acao, "OK"))
    sys.exit(codigo)


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "ajuda"):
        print(__doc__)
        return

    comando = sys.argv[1].lower()
    argumento = sys.argv[2] if len(sys.argv) > 2 else None

    if comando == "status":
        cmd_status()
    elif comando in ("live", "aovivo"):
        mostrar_resposta(enviar({"acao": "live"}))
    elif comando == "video":
        cmd_video(argumento)
    elif comando == "videos":
        cmd_videos()
    elif comando in ("recalibrar", "recalibracao", "recalibração", "calibrar"):
        cmd_recalibrar()
    elif comando == "gravar":
        cmd_gravar(argumento)
    elif comando in ("janela", "videocapture", "preview", "ver"):
        cmd_janela()
    elif comando == "log":
        os.execvp("journalctl", ["journalctl", "-u", NOME_SERVICO, "-f", "-n", "30", "-o", "cat"])
    elif comando == "parar":
        cmd_systemctl("stop")
    elif comando == "iniciar":
        cmd_systemctl("start")
    elif comando == "reiniciar":
        cmd_systemctl("restart")
    else:
        print(f"Comando desconhecido: {comando}\n")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
