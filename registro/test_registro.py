"""
Testes do registro (rotação, versão, eventos) e do log de saúde, sem o Pi.
Rodar de dentro de registro/:  python -m unittest -v
"""
import csv
import io
import os
import subprocess
import tempfile
import unittest
from datetime import date, timedelta
from types import SimpleNamespace

import registro_comum as rc
import saude


def ler_csv(caminho):
    """Igual ao pandas com comment="#": pula as linhas de versão."""
    with open(caminho, encoding="utf-8") as arq:
        return list(csv.reader(l for l in arq if not l.startswith("#")))


def criar(pasta, nome, tamanho=10):
    with open(os.path.join(pasta, nome), "w") as arq:
        arq.write("x" * tamanho)


class TesteRotacao(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.pasta = self.tmp.name
        self.hoje = date(2026, 11, 20)

    def tearDown(self):
        self.tmp.cleanup()

    def nomes(self):
        return sorted(os.listdir(self.pasta))

    def test_apaga_mais_antigos_que_7_dias(self):
        for d in (0, 6, 7, 8, 30):
            criar(self.pasta, f"saude_{self.hoje - timedelta(days=d)}.csv")
        apagados = rc.limpar_antigos(self.pasta, ("saude",), self.hoje)
        self.assertEqual(sorted(apagados), ["saude_2026-10-21.csv", "saude_2026-11-12.csv"])
        self.assertEqual(len(self.nomes()), 3)          # hoje, 6 e 7 dias atrás ficam

    def test_so_mexe_no_grupo(self):
        velho = self.hoje - timedelta(days=20)
        for nome in (f"saude_{velho}.csv", f"postura_{velho}.csv", f"outro_{velho}.csv",
                     "saude_sem_data.csv"):
            criar(self.pasta, nome)
        rc.limpar_antigos(self.pasta, ("saude", "eventos"), self.hoje)
        self.assertEqual(self.nomes(), sorted([f"postura_{velho}.csv", f"outro_{velho}.csv",
                                               "saude_sem_data.csv"]))

    def test_teto_apaga_o_mais_antigo_do_grupo_inteiro(self):
        criar(self.pasta, "saude_2026-11-17.csv", 40)
        criar(self.pasta, "eventos_2026-11-18.csv", 40)
        criar(self.pasta, "saude_2026-11-19.csv", 40)
        criar(self.pasta, "eventos_2026-11-20.csv", 40)
        apagados = rc.limpar_antigos(self.pasta, ("saude", "eventos"), self.hoje, teto_bytes=100)
        self.assertEqual(apagados, ["saude_2026-11-17.csv", "eventos_2026-11-18.csv"])

    def test_teto_nunca_apaga_o_de_hoje(self):
        criar(self.pasta, "saude_2026-11-20.csv", 500)
        self.assertEqual(rc.limpar_antigos(self.pasta, ("saude",), self.hoje, teto_bytes=100), [])
        self.assertEqual(self.nomes(), ["saude_2026-11-20.csv"])

    def test_sufixo_de_versao_conta_como_do_mesmo_dia(self):
        criar(self.pasta, "postura_2026-11-01_v2.csv")
        criar(self.pasta, "postura_2026-11-19_v2.csv")
        rc.limpar_antigos(self.pasta, ("postura",), self.hoje)
        self.assertEqual(self.nomes(), ["postura_2026-11-19_v2.csv"])


class TesteArquivoDiario(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dia = [date(2026, 11, 20)]

    def tearDown(self):
        self.tmp.cleanup()

    def arquivo(self, **kw):
        return rc.ArquivoDiario("saude", ["data_hora", "valor"], "teste", pasta=self.tmp.name,
                                versao="abc1234", relogio=lambda: self.dia[0], **kw)

    def test_cabecalho_versao_e_linhas(self):
        a = self.arquivo(fsync=True)
        a.registrar("t1", 1.23456)
        a.registrar("t2", None)
        a.fechar()
        with open(os.path.join(self.tmp.name, "saude_2026-11-20.csv"), encoding="utf-8") as arq:
            bruto = arq.read().splitlines()
        self.assertEqual(bruto[0], "data_hora,valor")
        self.assertTrue(bruto[1].startswith("# versao_codigo=abc1234 processo=teste"))
        self.assertEqual(bruto[2:], ["t1,1.235", "t2,"])

    def test_dois_processos_no_mesmo_arquivo_um_cabecalho(self):
        a, b = self.arquivo(), self.arquivo()
        a.registrar("a", 1)
        b.registrar("b", 2)
        a.registrar("a", 3)
        linhas = ler_csv(os.path.join(self.tmp.name, "saude_2026-11-20.csv"))
        self.assertEqual(linhas, [["data_hora", "valor"], ["a", "1"], ["b", "2"], ["a", "3"]])

    def test_vira_o_dia_e_roda(self):
        criar(self.tmp.name, "saude_2026-11-13.csv")
        a = self.arquivo()
        a.registrar("x", 1)
        self.assertIn("saude_2026-11-13.csv", os.listdir(self.tmp.name))   # 7 dias: ainda fica
        self.dia[0] = date(2026, 11, 21)
        a.registrar("y", 2)                                                   # abriu o do dia 21
        self.assertEqual(sorted(os.listdir(self.tmp.name)),
                         ["saude_2026-11-20.csv", "saude_2026-11-21.csv"])   # com 8 dias saiu

    def test_valor_com_cerquilha_e_quebra_de_linha(self):
        a = self.arquivo()
        a.registrar("t", "video #3\nfim")
        linhas = ler_csv(os.path.join(self.tmp.name, "saude_2026-11-20.csv"))
        self.assertEqual(linhas[1], ["t", "video n.3 fim"])

    def test_falha_de_disco_nao_derruba(self):
        a = rc.ArquivoDiario("saude", ["x"], "teste", pasta=os.path.join(self.tmp.name, "arq"),
                             versao="v")
        criar(self.tmp.name, "arq")          # um ARQUIVO no lugar da pasta: makedirs falha
        self.assertFalse(a.registrar(1))


class TesteEventos(unittest.TestCase):
    def test_iniciou_parou_e_detalhe(self):
        with tempfile.TemporaryDirectory() as pasta:
            ev = rc.RegistroEventos("pomodoro", pasta=pasta, versao="abc1234+alterado")
            ev.servico_iniciou("pomodoro")
            ev.registrar(rc.ORIGEM_POMODORO, "foco_inicio", "preset=25/5 ciclo=1/4")
            ev.servico_parou("pomodoro")
            ev.fechar()
            nome = os.listdir(pasta)[0]
            self.assertTrue(nome.startswith("eventos_"))
            linhas = ler_csv(os.path.join(pasta, nome))
        self.assertEqual(linhas[0], rc.CAB_EVENTOS)
        self.assertEqual([l[1:3] for l in linhas[1:]], [["sistema", "servico_iniciou"],
                                                        ["pomodoro", "foco_inicio"],
                                                        ["sistema", "servico_parou"]])
        self.assertIn("versao=abc1234+alterado", linhas[1][3])
        self.assertRegex(linhas[1][0], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}[+-]\d\d:\d\d$")


class TesteVersao(unittest.TestCase):
    def test_hash_e_alterado_num_repo_de_verdade(self):
        with tempfile.TemporaryDirectory() as repo:
            def git(*a):
                subprocess.run(["git", *a], cwd=repo, check=True, capture_output=True)
            try:
                git("init", "-q")
            except (OSError, subprocess.CalledProcessError):
                self.skipTest("sem git")
            git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "x")
            criar(repo, "a.py")
            git("add", "a.py")
            git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "a")
            original = rc.DIR_REPO
            rc.DIR_REPO = repo
            try:
                limpo = rc.versao_codigo()
                self.assertRegex(limpo, r"^[0-9a-f]{7,}$")
                criar(repo, "novo_nao_versionado.txt")
                self.assertEqual(rc.versao_codigo(), limpo)      # não versionado não conta
                criar(repo, "a.py", 20)
                self.assertEqual(rc.versao_codigo(), limpo + "+alterado")
                rc.DIR_REPO = os.path.join(repo, "nao_existe")
                self.assertEqual(rc.versao_codigo(), "desconhecida")
            finally:
                rc.DIR_REPO = original


class TesteSaude(unittest.TestCase):
    def test_amostra_com_leituras_falsas(self):
        with tempfile.TemporaryDirectory() as pasta:
            temp, mem, up = (os.path.join(pasta, n) for n in ("temp", "mem", "up"))
            with open(temp, "w") as a:
                a.write("54230\n")
            with open(mem, "w") as a:
                a.write("MemTotal: 944000 kB\nMemAvailable:   547840 kB\n")
            with open(up, "w") as a:
                a.write("1234.56 4000.00\n")
            def vcgencmd(cmd, **kw):
                self.assertEqual(cmd, ["vcgencmd", "get_throttled"])
                return SimpleNamespace(stdout="throttled=0x50005\n")
            linha = dict(zip(saude.CAB_SAUDE, saude.amostra(vcgencmd, temp, mem, up)))
        self.assertEqual(linha["throttled"], "0x50005")
        self.assertEqual((linha["subtensao_agora"], linha["throttling_agora"]), (1, 1))
        self.assertAlmostEqual(linha["temp_c"], 54.23)
        self.assertAlmostEqual(linha["ram_disponivel_mb"], 535.0)
        self.assertAlmostEqual(linha["uptime_s"], 1234.56)

    def test_so_ja_aconteceu(self):
        linha = saude.amostra(lambda *a, **k: SimpleNamespace(stdout="throttled=0x50000"),
                              "/nao/existe", "/nao/existe", "/nao/existe")
        d = dict(zip(saude.CAB_SAUDE, linha))
        self.assertEqual((d["subtensao_agora"], d["throttling_agora"]), (0, 0))
        self.assertIsNone(d["temp_c"])

    def test_fora_do_pi(self):
        def sem_vcgencmd(*a, **k):
            raise FileNotFoundError("vcgencmd")
        d = dict(zip(saude.CAB_SAUDE, saude.amostra(sem_vcgencmd, "/x", "/x", "/x")))
        self.assertIsNone(d["throttled"])
        self.assertIsNone(d["subtensao_agora"])


if __name__ == "__main__":
    unittest.main()
