"""
Recalibração da voz pelo B1, sem teclado. Reaproveita as funções do
`sensor-voz/main.py` (gravar, Praat, baseline): nada de análise é duplicado aqui.

Roda numa thread pra tela e botões não travarem durante os ~15 s da calibração.
`mensagem` é a linha curta que a tela mostra (None = nada a mostrar).

Mensagens padrão (sem acento, cabem na tela):
    VOZ 1/2: PREPARE-SE   →  VOZ 1/2: FALE AAAA   →  VOZ 1/2: ANALISANDO
    (idem 2/2)            →  VOZ CALIBRADA   ou   VOZ FALHOU / SEM MIC/PRAAT
"""
import importlib.util
import sys
import threading
import time
import traceback

from pomodoro_config import (
    CAMINHO_SENSOR_VOZ, PREPARO_VOZ_S, MENSAGEM_FINAL_VOZ_S,
)


def carregar_sensor_voz(caminho=CAMINHO_SENSOR_VOZ):
    """Importa o sensor-voz/main.py (o nome da pasta tem hífen, então não dá pra `import`)."""
    spec = importlib.util.spec_from_file_location("sensor_voz_main", caminho)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)   # só define funções; não roda o teste (tem `if __name__`)
    return modulo


class RecalibradorVoz:
    def __init__(self, carregar=carregar_sensor_voz, preparo_s=PREPARO_VOZ_S,
                 final_s=MENSAGEM_FINAL_VOZ_S, dormir=time.sleep):
        self._carregar = carregar
        self.preparo_s = preparo_s
        self.final_s = final_s
        self._dormir = dormir
        self.mensagem = None
        self.ocupado = False
        self._trava = threading.Lock()

    def iniciar(self):
        """Começa a recalibrar. Devolve a thread, ou None se já está rodando."""
        with self._trava:
            if self.ocupado:
                return None
            self.ocupado = True
            self.mensagem = "VOZ: INICIANDO"
        t = threading.Thread(target=self._rodar, daemon=True)
        t.start()
        return t

    def _progresso(self, etapa, i, n):
        if etapa == "gravando":
            self.mensagem = f"VOZ {i}/{n}: PREPARE-SE"
            self._dormir(self.preparo_s)
            self.mensagem = f"VOZ {i}/{n}: FALE AAAA"
        else:
            self.mensagem = f"VOZ {i}/{n}: ANALISANDO"

    def _rodar(self):
        try:
            modulo = self._carregar()
            modulo.calibrar_baseline(esperar_enter=False, ao_progredir=self._progresso)
            self.mensagem = "VOZ CALIBRADA"
        except (ImportError, OSError):   # sounddevice/scipy/PortAudio ausentes ou praat fora do PATH
            traceback.print_exc(file=sys.stderr)
            self.mensagem = "SEM MIC/PRAAT"
        except Exception:                          # mic ausente, voz não detectada, etc.
            traceback.print_exc(file=sys.stderr)
            self.mensagem = "VOZ FALHOU"
        self._dormir(self.final_s)                 # deixa o resultado na tela um tempo
        self.mensagem = None
        self.ocupado = False


class VozSimulada:
    """Pra testar no notebook sem mic nem Praat: `python main.py --voz simulada`."""

    @staticmethod
    def calibrar_baseline(esperar_enter=True, ao_progredir=None):
        for i in (1, 2):
            ao_progredir("gravando", i, 2)
            time.sleep(3)
            ao_progredir("analisando", i, 2)
            time.sleep(1)
