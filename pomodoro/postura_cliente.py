"""
Cliente do serviço de postura. Fala com o socket Unix do postura_servico.py
(o mesmo que o comando `postura` usa) e NÃO mexe na câmera.

Se o serviço não estiver rodando, devolve None e a tela mostra "POSTURA OFFLINE".
"""
import json
import socket
import threading
import time

from pomodoro_config import (
    CAMINHO_SOCKET_POSTURA, INTERVALO_CONSULTA_POSTURA_S, TIMEOUT_POSTURA_S,
)


def enviar(pedido, caminho=CAMINHO_SOCKET_POSTURA, timeout=TIMEOUT_POSTURA_S):
    """Manda um pedido JSON. Devolve a resposta (dict) ou None se falhar."""
    cliente = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    cliente.settimeout(timeout)
    try:
        cliente.connect(caminho)
        cliente.sendall((json.dumps(pedido) + "\n").encode("utf-8"))
        dados = b""
        while not dados.endswith(b"\n"):
            pedaco = cliente.recv(4096)
            if not pedaco:
                break
            dados += pedaco
        return json.loads(dados.decode("utf-8"))
    except (OSError, ValueError):   # sem socket, recusado, timeout, JSON ruim
        return None
    finally:
        cliente.close()


def texto_curto(estado):
    """
    Estado do serviço → texto curto pra caber na linha da tela (~21 caracteres,
    sem acento: a fonte padrão do display não tem).
    """
    if estado is None:
        return "POSTURA OFFLINE"
    status = estado.get("status", "")
    if status == "CORRETA":
        return "POSTURA OK"
    if status == "ATENCAO":
        return "POSTURA: ATENCAO"
    if status == "ALERTA":
        return "ALERTA: POSTURA!"
    if status == "AGUARDANDO_CALIBRACAO":
        return "APERTE B1: CALIBRAR"
    if status == "CONTAGEM":
        # texto original: "Fique na postura CORRETA. Calibrando em 7s..."
        numero = "".join(c for c in estado.get("texto", "").split("em")[-1] if c.isdigit())
        return f"AJEITE-SE! {numero}s" if numero else "AJEITE-SE!"
    if status == "CALIBRANDO":
        return "CALIBRANDO..."
    if status == "CALIBRADO":
        return "POSTURA OK"
    if status == "CALIBRACAO_FALHOU":
        return "CALIBRACAO FALHOU"
    if status == "SEM_CAMERA":
        return "SEM CAMERA"
    if status == "SEM_USUARIO":
        return "SEM USUARIO"
    return status[:21] or "..."


# Status em que a tela mostra a mini-figura dos 3 pontos (enquadramento, T2'):
# a pessoa se ajeitando pra calibrar, calibrando, falhou, ou o sistema não acha ela.
STATUS_COM_PONTOS = ("CONTAGEM", "CALIBRANDO", "CALIBRACAO_FALHOU", "SEM_USUARIO")
ORDEM_PONTOS = ("orelha", "ombro_orelha", "outro_ombro")


def pontos_enquadramento(estado):
    """(orelha, ombro, outro ombro) visíveis, ou None quando a figura não deve aparecer."""
    if not estado or estado.get("status") not in STATUS_COM_PONTOS:
        return None
    visiveis = estado.get("pontos_visiveis")
    if not visiveis:
        return None
    return tuple(bool(visiveis.get(n)) for n in ORDEM_PONTOS)


class MonitorPostura:
    """Thread que consulta o status de tempos em tempos (a tela nunca trava esperando o socket)."""

    def __init__(self, intervalo=INTERVALO_CONSULTA_POSTURA_S):
        self.intervalo = intervalo
        self.estado = None            # último estado conhecido (None = offline)
        self._ativo = True
        threading.Thread(target=self._rodar, daemon=True).start()

    def _rodar(self):
        while self._ativo:
            resposta = enviar({"acao": "status"})
            self.estado = resposta.get("estado") if resposta and resposta.get("ok") else None
            time.sleep(self.intervalo)

    def recalibrar(self):
        """Pede recalibração em outra thread (não segura a tela). Devolve a thread."""
        def pedir():
            enviar({"acao": "recalibrar"})
        t = threading.Thread(target=pedir, daemon=True)
        t.start()
        return t

    def parar(self):
        self._ativo = False
