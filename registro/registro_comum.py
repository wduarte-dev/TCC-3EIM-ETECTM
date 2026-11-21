"""
Registro em arquivo comum aos serviços do Pi (saúde, eventos e o CSV por quadro da postura).

Decisões de 20/11/2026 (plano-coleta-ajustes-20-11.md, parte do Pi):
- um arquivo por dia (data no nome), horário em ISO COM FUSO (pra juntar por horário no pandas);
- rotação: ao abrir o arquivo do dia, apaga os mais antigos que 7 dias e, se o grupo passou do
  teto (100 MB saúde + eventos; 300 MB o CSV por quadro), apaga o mais antigo antes dos 7 dias;
- versão do código (hash do commit, "+alterado" se há mudança não commitada) numa linha de
  comentário `# versao_codigo=...` cada vez que um processo abre o arquivo. Ler no pandas com
  `pd.read_csv(arquivo, comment="#")`; por isso nenhum valor gravado pode conter "#".

Nunca derruba o serviço: falha de disco vira um aviso no terminal (journal) e segue.
Só biblioteca padrão; roda no Windows também (sem as leituras do Pi).
"""
import csv
import io
import os
import re
import subprocess
import time
from datetime import datetime, timedelta

DIR_REPO = os.path.realpath(os.path.join(os.path.dirname(os.path.realpath(__file__)), os.pardir))

# Saúde + eventos ficam na home (o serviço roda como o usuário, sem sudo; fácil de copiar por
# scp). TCC_LOGS troca a pasta (testes, notebook).
DIR_REGISTRO = os.environ.get("TCC_LOGS") or os.path.join(os.path.expanduser("~"), "tcc-logs")

MAX_DIAS = 7
MB = 1024 * 1024
TETO_SAUDE_EVENTOS = 100 * MB      # saude_*.csv + eventos_*.csv juntos
TETO_QUADROS = 300 * MB            # postura_*.csv (CSV por quadro)
INTERVALO_CONFERE_TETO_S = 600     # além da abertura, confere o teto a cada 10 min

# Grupos de rotação: os prefixos que dividem o mesmo teto
GRUPO_SAUDE_EVENTOS = ("saude", "eventos")
GRUPO_QUADROS = ("postura",)

CAB_EVENTOS = ["data_hora", "origem", "evento", "detalhe"]
ORIGEM_POMODORO, ORIGEM_POSTURA, ORIGEM_SISTEMA = "pomodoro", "postura", "sistema"

_RX_DATA = re.compile(r"_(\d{4}-\d{2}-\d{2})")


def agora_iso():
    """Horário local com fuso, ex.: 2026-11-20T21:39:05.123-03:00."""
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


def _git(*args):
    return subprocess.run(["git", *args], cwd=DIR_REPO, capture_output=True, text=True,
                          timeout=5).stdout.strip()


def versao_codigo():
    """Hash curto do commit do repo; "+alterado" se algum arquivo VERSIONADO foi mexido sem
    commit (senão o hash "mentiria" num teste); "desconhecida" sem git/.git."""
    try:
        h = _git("rev-parse", "--short", "HEAD")
        if not h:
            return "desconhecida"
        return h + ("+alterado" if _git("status", "--porcelain", "--untracked-files=no") else "")
    except (OSError, subprocess.SubprocessError):
        return "desconhecida"


def limpo(valor):
    """Valor pronto pro CSV: None → vazio, float com 3 casas, e sem "#" (vira comentário no
    pandas com comment="#") nem quebra de linha."""
    if valor is None:
        return ""
    if isinstance(valor, bool):
        return int(valor)
    if isinstance(valor, float):
        return f"{valor:.3f}"
    if isinstance(valor, str):
        return valor.replace("#", "n.").replace("\r", " ").replace("\n", " ")
    return valor


def data_do_nome(nome):
    m = _RX_DATA.search(nome)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%Y-%m-%d").date()
    except ValueError:
        return None


def limpar_antigos(pasta, prefixos, hoje=None, max_dias=MAX_DIAS, teto_bytes=None):
    """
    Rotação de um grupo de arquivos `<prefixo>_AAAA-MM-DD*.csv`:
      1. apaga os de data mais antiga que `max_dias` dias;
      2. se o total do grupo passou de `teto_bytes`, apaga os mais antigos (por data no nome)
         até caber, NUNCA o de hoje.
    Devolve a lista dos apagados. Erros de disco não sobem (só um aviso).
    """
    hoje = hoje or datetime.now().date()
    limite = hoje - timedelta(days=max_dias)
    apagados = []
    try:
        nomes = os.listdir(pasta)
    except OSError:
        return apagados
    arquivos = []
    for nome in nomes:
        if not nome.endswith(".csv") or not any(nome.startswith(p + "_") for p in prefixos):
            continue
        data = data_do_nome(nome)
        if data is None:
            continue
        caminho = os.path.join(pasta, nome)
        try:
            tamanho = os.path.getsize(caminho)
        except OSError:
            continue
        if data < limite:
            if _apagar(caminho):
                apagados.append(nome)
            continue
        arquivos.append((data, nome, caminho, tamanho))
    if teto_bytes is not None:
        total = sum(a[3] for a in arquivos)
        for data, nome, caminho, tamanho in sorted(arquivos):
            if total <= teto_bytes:
                break
            if data >= hoje:
                break           # o de hoje nunca: se só ele passa do teto, fica assim
            if _apagar(caminho):
                apagados.append(nome)
                total -= tamanho
    return apagados


def _apagar(caminho):
    try:
        os.remove(caminho)
        return True
    except OSError as erro:
        print(f"[REGISTRO] não consegui apagar {caminho}: {erro}", flush=True)
        return False


def linha_versao(processo, versao):
    return f"# versao_codigo={versao} processo={processo} aberto={agora_iso()}\n"


class ArquivoDiario:
    """
    CSV de um dia, que vira o do dia seguinte sozinho, com rotação do grupo.

    Pode ser escrito por MAIS DE UM PROCESSO ao mesmo tempo (o eventos_*.csv recebe do
    pomodoro e da postura): abre com O_APPEND e grava cada linha numa única chamada
    `os.write`, e o cabeçalho só é escrito por quem CRIOU o arquivo (O_EXCL).
    `fsync=True` força a gravação no cartão a cada linha (saúde: se a energia cair, o que
    estava só na memória se perde, e é justamente o registro que mais interessa).
    """

    def __init__(self, prefixo, cabecalho, processo, pasta=None, grupo=None, teto_bytes=None,
                 max_dias=MAX_DIAS, fsync=False, versao=None, relogio=None):
        self.prefixo = prefixo
        self.cabecalho = list(cabecalho)
        self.processo = processo
        self.pasta = pasta or DIR_REGISTRO
        self.grupo = tuple(grupo or (prefixo,))
        self.teto_bytes = teto_bytes
        self.max_dias = max_dias
        self.fsync = fsync
        self.versao = versao if versao is not None else versao_codigo()
        self._relogio = relogio or (lambda: datetime.now().date())
        self._fd = None
        self._data = None
        self._ultima_conferencia = 0.0
        self.caminho = None

    def _abrir(self, hoje):
        self.fechar()
        os.makedirs(self.pasta, exist_ok=True)
        limpar_antigos(self.pasta, self.grupo, hoje, self.max_dias, self.teto_bytes)
        self.caminho = os.path.join(self.pasta, f"{self.prefixo}_{hoje:%Y-%m-%d}.csv")
        flags = os.O_WRONLY | os.O_APPEND | getattr(os, "O_BINARY", 0)
        try:
            self._fd = os.open(self.caminho, flags | os.O_CREAT | os.O_EXCL, 0o644)
            self._escrever(_csv_linha(self.cabecalho))      # quem criou escreve o cabeçalho
        except FileExistsError:
            self._fd = os.open(self.caminho, flags)
        self._escrever(linha_versao(self.processo, self.versao))
        self._data = hoje
        self._ultima_conferencia = time.monotonic()

    def _escrever(self, texto, fsync=None):
        os.write(self._fd, texto.encode("utf-8"))
        if self.fsync if fsync is None else fsync:
            os.fsync(self._fd)

    def registrar(self, *valores, fsync=None):
        """Uma linha (valores na ordem do cabeçalho). `fsync` troca o padrão só desta linha.
        Nunca levanta exceção."""
        try:
            hoje = self._relogio()
            if hoje != self._data or self._fd is None:
                self._abrir(hoje)
            elif (self.teto_bytes is not None
                  and time.monotonic() - self._ultima_conferencia > INTERVALO_CONFERE_TETO_S):
                self._ultima_conferencia = time.monotonic()
                limpar_antigos(self.pasta, self.grupo, hoje, self.max_dias, self.teto_bytes)
            self._escrever(_csv_linha([limpo(v) for v in valores]), fsync)
            return True
        except OSError as erro:
            print(f"[REGISTRO] falha ao gravar {self.prefixo}: {erro}", flush=True)
            self.fechar()
            return False

    def fechar(self):
        if self._fd is not None:
            try:
                os.close(self._fd)
            except OSError:
                pass
        self._fd = None
        self._data = None


def _csv_linha(valores):
    buf = io.StringIO()
    csv.writer(buf, lineterminator="\n").writerow(valores)
    return buf.getvalue()


class RegistroEventos:
    """eventos_AAAA-MM-DD.csv: data_hora, origem, evento, detalhe. Só grava quando algo muda.
    Eventos de "sistema" (serviço iniciou/parou, desligar) vão com fsync; os demais não
    (a postura pode mudar de estado várias vezes por minuto e o fsync gasta o cartão)."""

    def __init__(self, processo, pasta=None, versao=None, relogio=None):
        self.versao = versao if versao is not None else versao_codigo()
        self.arquivo = ArquivoDiario("eventos", CAB_EVENTOS, processo, pasta=pasta,
                                     grupo=GRUPO_SAUDE_EVENTOS, teto_bytes=TETO_SAUDE_EVENTOS,
                                     versao=self.versao, relogio=relogio)

    def registrar(self, origem, evento, detalhe=""):
        return self.arquivo.registrar(agora_iso(), origem, evento, detalhe,
                                      fsync=origem == ORIGEM_SISTEMA)

    def servico_iniciou(self, servico):
        return self.registrar(ORIGEM_SISTEMA, "servico_iniciou",
                              f"{servico} versao={self.versao} pid={os.getpid()}")

    def servico_parou(self, servico):
        """Só aparece em parada LIMPA (systemctl stop, poweroff). Um iniciou sem o parou
        antes indica queda (energia, travamento); é indício, não prova."""
        return self.registrar(ORIGEM_SISTEMA, "servico_parou", servico)

    def fechar(self):
        self.arquivo.fechar()
