"""
Testes do registro do serviço (eventos e CSV por quadro), sem câmera e sem MoveNet:
o detector é trocado por um falso. Precisa de OpenCV/numpy (o serviço importa cv2).
Rodar de dentro de sensor-postura/:  python -m unittest -v
"""
import csv
import os
import tempfile
import unittest
from unittest import mock

try:
    import postura_servico as ps
    from registro_comum import RegistroEventos
except ImportError as erro:          # sem cv2/numpy
    ps = None
    MOTIVO = str(erro)


def ler(caminho):
    with open(caminho, encoding="utf-8") as arq:
        return list(csv.DictReader(l for l in arq if not l.startswith("#")))


class DetectorFalso:
    ultimas_confiancas = (0.9, 0.9, 0.9)
    ultima_razao_cb = None
    valido = True

    def detectar_metricas_postura(self, frame, limiar):
        if self.valido:
            return 5.0, 0.8, (1, 1, 1, 1, 1, 1)
        self.ultimas_confiancas = (0.1, 0.9, 0.9)   # orelha fora
        return None, None, None


class CapFalsa:
    def read(self):
        import numpy as np
        return True, np.zeros((48, 64, 3), dtype=np.uint8)


@unittest.skipIf(ps is None, "sem OpenCV/numpy")
class TesteEventosDoServico(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        with mock.patch.object(ps, "DetectorPostura", DetectorFalso), \
                mock.patch.object(ps, "DIR_LOGS", os.path.join(self.tmp.name, "logs")), \
                mock.patch.object(ps, "carregar_baseline_do_mesmo_boot", lambda: None):
            self.m = ps.MonitorPostura()
        self.m.log = ps.LogCSV(os.path.join(self.tmp.name, "logs"))
        self.m.eventos = RegistroEventos("postura", pasta=self.tmp.name, versao="teste")

    def tearDown(self):
        self.m.eventos.fechar()
        self.m.log.fechar()
        self.tmp.cleanup()

    def eventos(self):
        nome = next(n for n in os.listdir(self.tmp.name) if n.startswith("eventos_"))
        return [(l["origem"], l["evento"], l["detalhe"]) for l in ler(os.path.join(self.tmp.name, nome))]

    def test_so_grava_quando_o_estado_muda(self):
        with mock.patch("builtins.print"):
            self.m.mostrar_status("AGUARDANDO_CALIBRACAO", "x")
            self.m.mostrar_status("AGUARDANDO_CALIBRACAO", "x")
            self.m.mostrar_status("CORRETA", "ok", fps=4.1)
            self.m.mostrar_status("CORRETA", "ok", fps=4.2)
            self.m.mostrar_status("ALERTA", "ruim", fps=3.9)
            self.m.mostrar_status("SEM_USUARIO", "-", fps=4.0)
        self.assertEqual(self.eventos(), [
            ("postura", "estado", "AGUARDANDO_CALIBRACAO"),
            ("postura", "estado", "CORRETA fps=4.1"),
            ("postura", "estado", "ALERTA fps=3.9"),
            ("postura", "estado", "SEM_USUARIO fps=4.0"),
        ])

    def calibrar(self, valido):
        self.m.detector.valido = valido
        with mock.patch("builtins.print"):
            return self.m._calibrar(CapFalsa(), "video", 2.0)    # vídeo: 5 s × 2 fps = 10 quadros

    def test_calibracao_ok_vai_pros_eventos(self):
        self.assertEqual(self.calibrar(True)[0], "ok")
        ok = [e for e in self.eventos() if e[1] == "calibracao_ok"]
        self.assertEqual(len(ok), 1)
        self.assertIn("angulo=5.00 razao=0.8000 validos=10/10", ok[0][2])

    def test_calibracao_falhou_diz_o_ponto(self):
        self.assertEqual(self.calibrar(False)[0], "falhou")
        falhou = [e for e in self.eventos() if e[1] == "calibracao_falhou"]
        self.assertEqual(len(falhou), 1)
        self.assertIn("validos=0/10", falhou[0][2])
        self.assertIn("fora da imagem", falhou[0][2])

    def test_detalhe_sem_fps_fora_da_analise(self):
        self.assertEqual(ps.detalhe_estado("CALIBRANDO", 4.0), "CALIBRANDO")
        self.assertEqual(ps.detalhe_estado("ATENCAO", 0.0), "ATENCAO")
        self.assertEqual(ps.detalhe_estado("ATENCAO", 2.345), "ATENCAO fps=2.3")


if __name__ == "__main__":
    unittest.main()
