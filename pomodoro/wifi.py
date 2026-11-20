"""
Wi-Fi do Pi (T7): qual rede usar, validação, e a conexão disparada pelo B1.

- Rede padrão: SSID DIHMO, senha admin1234 (fraca de propósito: o usuário cria um
  hotspot com esse nome/senha e o Pi entra). O comando `wifi --ssid X --senha Y`
  troca (wifi_ctl.py) e grava em ~/.config/pomodoro/wifi.json, que é a fonte da
  verdade da tela (ler a senha de volta do NetworkManager exige privilégio).
- A conexão usa o NetworkManager (nmcli), que é o padrão do Raspberry Pi OS atual
  (Trixie, NM 1.52.1). Perfil próprio do projeto: WIFI_PERFIL_NM.
- WifiConectar roda numa thread (a tela e os botões não travam), no molde do
  RecalibradorVoz que existia: expõe `tela` (o que desenhar) e `ocupado`.

Nada disto foi testado no Pi: ver "A testar" no README.
"""
import json
import os
import shutil
import subprocess
import threading
import time

from pomodoro_config import (
    WIFI_SSID_PADRAO, WIFI_SENHA_PADRAO, CAMINHO_WIFI, WIFI_PERFIL_NM, WIFI_INTERFACE,
    WIFI_PRIORIDADE, WIFI_TIMEOUT_S, WIFI_INTERVALO_S, WIFI_RESULTADO_S,
    WIFI_CONFIRMA_SSH_S, LARGURA,
)

PREFIXO_REDE = "REDE:  "
PREFIXO_SENHA = "SENHA: "
LARGURA_MAX_PX = LARGURA - 1          # 127 px: mesma régua da tela de espera
TEXTO_SSH = "SSH ATIVO: REPITA"


class WifiInvalido(ValueError):
    """Mensagem pronta pra mostrar ao usuário."""


# ------------------------------------------------------------ configuração ----

def carregar(caminho=CAMINHO_WIFI):
    """(ssid, senha, do_usuario). Sem arquivo (ou estragado) = a rede padrão."""
    try:
        with open(caminho, encoding="utf-8") as f:
            dados = json.load(f)
        ssid, senha = str(dados["ssid"]), str(dados["senha"])
        validar(ssid, senha)
        return ssid, senha, True
    except (OSError, ValueError, KeyError, TypeError):
        return WIFI_SSID_PADRAO, WIFI_SENHA_PADRAO, False


def _medidor():
    """Mede em pixels com a MESMA fonte da tela (se a fonte cair no fallback, mede com ela)."""
    try:
        import display
        fonte = display._fonte(9)
        if fonte is not None:
            return fonte.getlength
    except Exception:   # sem Pillow (ex.: Windows sem as dependências da tela)
        pass
    return None


def _quanto_cabe(prefixo, texto, medir):
    n = len(texto)
    while n > 0 and medir(prefixo + texto[:n]) > LARGURA_MAX_PX:
        n -= 1
    return n


def validar(ssid, senha, medir=None):
    """
    Regras do WPA2 (SSID de 1 a 32 bytes, senha de 8 a 63 caracteres ASCII) e, além
    disso, rede e senha têm que CABER na tela de espera (prefixo + texto <= 127 px na
    fonte da tela). Em vez de cortar o texto na tela, recusa e diz o máximo.
    """
    if not 1 <= len(ssid.encode("utf-8")) <= 32:
        raise WifiInvalido("a rede (SSID) precisa ter de 1 a 32 caracteres")
    if not 8 <= len(senha) <= 63:
        raise WifiInvalido("a senha WPA2 precisa ter de 8 a 63 caracteres")
    if not all(32 <= ord(c) <= 126 for c in senha):
        raise WifiInvalido("a senha só pode ter caracteres ASCII (sem acento)")
    medir = medir or _medidor()
    if medir is None:
        return
    for prefixo, texto, nome in ((PREFIXO_REDE, ssid, "o nome da rede"), (PREFIXO_SENHA, senha, "a senha")):
        if medir(prefixo + texto) > LARGURA_MAX_PX:
            cabe = _quanto_cabe(prefixo, texto, medir)
            raise WifiInvalido(f"{nome} não cabe na tela do Pi: desse jeito cabem só {cabe} "
                               f"caracteres ('{texto[:cabe]}'). Use um nome/senha mais curto "
                               "(texto comum: ~14 na rede, ~13 na senha)")


def salvar(ssid, senha, caminho=CAMINHO_WIFI):
    validar(ssid, senha)
    pasta = os.path.dirname(caminho)
    if pasta:
        os.makedirs(pasta, exist_ok=True)
    temporario = caminho + ".tmp"
    fd = os.open(temporario, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)   # tem senha: só o dono lê
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump({"ssid": ssid, "senha": senha}, f, indent=2)
    os.replace(temporario, caminho)


# ------------------------------------------------------------------ nmcli ----

def rodar(comando, timeout=10, cancelado=None):
    """(código, saída). Tenta sem sudo; se o NetworkManager negar permissão, tenta
    `sudo -n` (igual ao poweroff do B3). Nunca levanta exceção: falha = código != 0."""
    for prefixo in ([], ["sudo", "-n"]):
        codigo, saida = _rodar_uma(prefixo + comando, timeout, cancelado)
        negado = codigo != 0 and ("not authorized" in saida.lower() or "insufficient privileges" in saida.lower()
                                  or "permission" in saida.lower())
        if not negado or os.name == "nt":
            return codigo, saida
    return codigo, saida


def _rodar_uma(comando, timeout, cancelado):
    try:
        proc = subprocess.Popen(comando, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    except OSError as erro:
        return 127, str(erro)
    fim = time.monotonic() + timeout
    while proc.poll() is None:
        if (cancelado is not None and cancelado.is_set()) or time.monotonic() > fim:
            proc.kill()
            proc.wait()
            return 124, "interrompido"
        time.sleep(0.05)
    return proc.returncode, proc.stdout.read() if proc.stdout else ""


def tem_nmcli():
    return shutil.which("nmcli") is not None


def conexao_ativa(executar=rodar):
    """(nome do perfil ativo no wlan0 ou '', tem IPv4?)."""
    codigo, saida = executar(["nmcli", "-g", "GENERAL.CONNECTION,IP4.ADDRESS", "device", "show", WIFI_INTERFACE], 5)
    if codigo != 0:
        return "", False
    linhas = [l.strip() for l in saida.splitlines()]
    nome = linhas[0] if linhas else ""
    tem_ip = any(l and l[0].isdigit() for l in linhas[1:])
    return nome, tem_ip


def ssid_do_perfil(executar=rodar):
    codigo, saida = executar(["nmcli", "-g", "802-11-wireless.ssid", "connection", "show", WIFI_PERFIL_NM], 5)
    return saida.strip() if codigo == 0 else None


def aplicar_perfil(ssid, senha, executar=rodar):
    """Cria ou atualiza o perfil do projeto no NetworkManager. True se deu certo."""
    if ssid_do_perfil(executar) is None:
        comando = ["nmcli", "connection", "add", "type", "wifi", "con-name", WIFI_PERFIL_NM,
                   "ifname", WIFI_INTERFACE, "ssid", ssid,
                   "wifi-sec.key-mgmt", "wpa-psk", "wifi-sec.psk", senha,
                   "connection.autoconnect", "yes",
                   "connection.autoconnect-priority", str(WIFI_PRIORIDADE)]
    else:
        comando = ["nmcli", "connection", "modify", WIFI_PERFIL_NM,
                   "802-11-wireless.ssid", ssid, "wifi-sec.key-mgmt", "wpa-psk", "wifi-sec.psk", senha]
    return executar(comando, 15)[0] == 0


def sessao_ssh_ativa(executar=rodar):
    """Há alguém conectado por SSH agora? (o SSH de desenvolvimento é por Wi-Fi)."""
    codigo, saida = executar(["ss", "-Htn", "state", "established", "( sport = :22 )"], 3)
    return codigo == 0 and bool(saida.strip())


# ------------------------------------------------------- conexão (thread) ----

class WifiConectar:
    """
    Fluxo do B1 longo em WIFI CONECTAR:
      1. Se o Wi-Fi está noutra rede E há sessão SSH, pede confirmação (TEXTO_SSH na linha
         de baixo; repetir o longo em WIFI_CONFIRMA_SSH_S): trocar de rede derruba o SSH.
      2. Tela cheia de ESPERA com rede, senha e banda; a thread garante o perfil e repete
         `nmcli device wifi rescan` + `nmcli connection up` a cada WIFI_INTERVALO_S (o
         usuário costuma criar o hotspot DEPOIS de ler a senha na tela).
      3. Já conectado na rede configurada → sucesso direto, sem desconectar.
      4. Resultado em tela cheia por WIFI_RESULTADO_S: conectado (conexão ativa com IPv4)
         ou falhou (WIFI_TIMEOUT_S sem conseguir, ou sem nmcli). Depois volta ao normal.
      Clique curto do B1 na espera cancela e volta ao normal.
    """

    def __init__(self, executar=rodar, relogio=time.monotonic, carregar_rede=carregar,
                 tem_nm=tem_nmcli, timeout_s=WIFI_TIMEOUT_S, intervalo_s=WIFI_INTERVALO_S,
                 resultado_s=WIFI_RESULTADO_S, confirma_ssh_s=WIFI_CONFIRMA_SSH_S):
        self._executar = executar
        self._relogio = relogio
        self._carregar = carregar_rede
        self._tem_nm = tem_nm
        self.timeout_s = timeout_s
        self.intervalo_s = intervalo_s
        self.resultado_s = resultado_s
        self.confirma_ssh_s = confirma_ssh_s
        self._lock = threading.Lock()
        self._cancelado = threading.Event()
        self._fase = None              # None | "espera" | "resultado"
        self._ok = False
        self._ssid = self._senha = ""
        self._inicio = 0.0
        self._resultado_ate = 0.0
        self._confirmar_ate = 0.0
        self._thread = None

    # ---- leitura (main.py) ----
    @property
    def ocupado(self):
        return self.tela is not None

    @property
    def esperando(self):
        return self.tela is not None and self.tela[0] == "espera"

    @property
    def tela(self):
        """None | ("espera", ssid, senha, n_pontos 1..3) | ("resultado", ok, ssid)."""
        with self._lock:
            agora = self._relogio()
            if self._fase == "espera":
                pontos = int((agora - self._inicio) * 2) % 3 + 1      # CONECTANDO. .. ... (0,5 s cada)
                return ("espera", self._ssid, self._senha, pontos)
            if self._fase == "resultado":
                if agora < self._resultado_ate:
                    return ("resultado", self._ok, self._ssid)
                self._fase = None
            return None

    def mensagem(self):
        """Linha de baixo enquanto espera a confirmação do SSH (ou None)."""
        return TEXTO_SSH if self._relogio() < self._confirmar_ate else None

    # ---- entrada ----
    def pedir(self):
        """B1 longo em WIFI CONECTAR. Devolve 'iniciou', 'confirmar' ou 'ocupado'."""
        if self.ocupado:
            return "ocupado"
        agora = self._relogio()
        if agora >= self._confirmar_ate and self._tem_nm() and self._derrubaria_ssh():
            self._confirmar_ate = agora + self.confirma_ssh_s
            return "confirmar"
        self._confirmar_ate = 0.0
        ssid, senha, _ = self._carregar()
        with self._lock:
            self._ssid, self._senha = ssid, senha
            self._fase = "espera"
            self._inicio = agora
            self._cancelado.clear()
        self._thread = threading.Thread(target=self._conectar, args=(ssid, senha), daemon=True)
        self._thread.start()
        return "iniciou"

    def cancelar(self):
        """Clique curto na espera: volta ao normal (o nmcli em andamento é interrompido)."""
        self._cancelado.set()
        with self._lock:
            if self._fase == "espera":
                self._fase = None

    # ---- internos ----
    def _derrubaria_ssh(self):
        ativo, _ = conexao_ativa(self._executar)
        if not ativo or ativo == WIFI_PERFIL_NM:
            return False
        return sessao_ssh_ativa(self._executar)

    def _terminar(self, ok):
        with self._lock:
            if self._fase != "espera":      # cancelado no meio
                return
            self._ok = ok
            self._fase = "resultado"
            self._resultado_ate = self._relogio() + self.resultado_s

    def _conectar(self, ssid, senha):
        if not self._tem_nm():
            self._terminar(False)
            return
        ex = self._executar
        ativo, tem_ip = conexao_ativa(ex)
        if ativo == WIFI_PERFIL_NM and tem_ip and ssid_do_perfil(ex) == ssid:
            self._terminar(True)                   # já está na rede configurada: não desconecta
            return
        if not aplicar_perfil(ssid, senha, ex):    # garante SSID e senha atuais no perfil
            self._terminar(False)
            return
        limite = self._relogio() + self.timeout_s
        while not self._cancelado.is_set() and self._relogio() < limite:
            inicio = self._relogio()
            ex(["nmcli", "device", "wifi", "rescan"], 5, self._cancelado)     # falha aqui não importa
            espera = max(1, int(min(self.intervalo_s, limite - self._relogio())))
            codigo, _ = ex(["nmcli", "--wait", str(espera), "connection", "up", WIFI_PERFIL_NM],
                           espera + 5, self._cancelado)
            if codigo == 0 and conexao_ativa(ex)[1]:
                self._terminar(True)
                return
            # não deu: espera o resto do intervalo (sai na hora se cancelar)
            self._cancelado.wait(max(0.0, self.intervalo_s - (self._relogio() - inicio)))
        self._terminar(False)
