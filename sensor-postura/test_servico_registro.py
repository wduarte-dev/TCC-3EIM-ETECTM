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

    def test_pausa_grava_eventos_e_retoma_recalibrando(self):
        with mock.patch("builtins.print"), \
                mock.patch.object(self.m, "_dormir", lambda s: self.m.comandos.put(("retomar", None))):
            proxima = self.m._pausado()
        self.assertEqual(proxima, ("live", None))
        self.assertTrue(self.m._recalibrar_pendente)
        self.assertEqual([e[1:] for e in self.eventos()], [
            ("medicao_pausada", ""), ("estado", "PAUSADO"), ("medicao_retomada", ""),
        ])

    def test_comandos_pausar_e_retomar(self):
        with self.m.lock:
            self.m.estado["status"] = "CORRETA"
        self.assertFalse(self.m._tratar_comando({"acao": "retomar"})["ok"])   # não está pausada
        self.assertTrue(self.m._tratar_comando({"acao": "pausar"})["ok"])
        self.assertEqual(self.m.comandos.get_nowait(), ("pausar", None))
        with self.m.lock:
            self.m.estado["status"] = "CALIBRANDO"
        self.assertFalse(self.m._tratar_comando({"acao": "pausar"})["ok"])    # calibrando: espera
        with self.m.lock:
            self.m.estado["status"] = "PAUSADO"
        self.assertTrue(self.m._tratar_comando({"acao": "retomar"})["ok"])
        self.assertEqual(self.m.comandos.get_nowait(), ("retomar", None))



@unittest.skipIf(ps is None, "sem OpenCV/numpy")
class TesteRotacaoCSVQuadros(unittest.TestCase):
    def test_abre_o_dia_roda_e_grava_versao_e_fuso(self):
        from datetime import date, timedelta
        with tempfile.TemporaryDirectory() as pasta:
            hoje = date.today()
            for dias in (3, 8, 30):
                with open(os.path.join(pasta, f"postura_{hoje - timedelta(days=dias)}.csv"), "w") as f:
                    f.write("x\n")
            log = ps.LogCSV(pasta, versao="abc1234")
            log.registrar(data_hora=ps.agora_iso(), fonte="video", video="teste #2.mp4",
                          status="CORRETA", angulo=1.23456)
            log.fechar()
            nomes = sorted(os.listdir(pasta))
            self.assertEqual(nomes, sorted([f"postura_{hoje - timedelta(days=3)}.csv",
                                            f"postura_{hoje}.csv"]))   # 8 e 30 dias saíram
            caminho = os.path.join(pasta, f"postura_{hoje}.csv")
            with open(caminho, encoding="utf-8") as f:
                bruto = f.read().splitlines()
            self.assertEqual(bruto[0], ",".join(ps.LogCSV.CABECALHO))
            self.assertTrue(bruto[1].startswith("# versao_codigo=abc1234 processo=postura"))
            linha = ler(caminho)[0]
            self.assertEqual((linha["video"], linha["angulo"]), ("teste n.2.mp4", "1.235"))
            self.assertRegex(linha["data_hora"], r"T\d\d:\d\d:\d\d\.\d{3}[+-]\d\d:\d\d$")

    def test_teto_de_300_mb_do_grupo(self):
        self.assertEqual(ps.TETO_QUADROS, 300 * 1024 * 1024)
        self.assertEqual(ps.GRUPO_QUADROS, ("postura",))


if __name__ == "__main__":
    unittest.main()
