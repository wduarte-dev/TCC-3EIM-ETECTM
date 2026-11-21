"""
Testes do programa de coleta, sem câmera: pontos sintéticos, relógio falso e
registro falso. Rodar de dentro de coleta/:  python -m unittest -v
"""
import csv
import math
import os
import random
import tempfile
import unittest

import coleta_logica as cl
from coleta_logica import (
    analisar_quadro, resumir_etapa, Sessao, ETAPAS,
    ENQUADRAR, INSTRUCAO, CONTAGEM, GRAVANDO, REVISAO, FIM,
)
from postura_config import LIMIAR_CONFIANCA
from postura_logica import metricas, AvaliadorPostura, SEM_USUARIO


def pessoa(orelha=(260, 180), ombro=(250, 300), outro_ombro=(390, 300), outra_orelha=(330, 180),
           conf=0.9, conf_outra_orelha=0.9):
    """17 pontos: os 4 que importam com confiança `conf`, o resto baixo."""
    kps = [(0, 0, 0.05)] * 17
    kps[cl.I_ORELHA] = (*orelha, conf)
    kps[cl.I_OMBRO_ORELHA] = (*ombro, conf)
    kps[cl.I_OUTRO_OMBRO] = (*outro_ombro, conf)
    kps[cl.I_OUTRA_ORELHA] = (*outra_orelha, conf_outra_orelha)
    return kps


class RegistroFalso:
    def __init__(self):
        self.quadros, self.etapas, self.motivos = [], [], []

    def quadro(self, sessao, t, analise, kps):
        self.quadros.append((sessao.etapa.chave, sessao.tentativa, t, analise["valido"]))

    def etapa(self, sessao, resumo, aceita, motivo=""):
        self.etapas.append((sessao.etapa.chave, sessao.tentativa, aceita, resumo["n_total"]))
        self.motivos.append(motivo)


class TesteAnalisarQuadro(unittest.TestCase):
    def test_sem_leitura(self):
        r = analisar_quadro(None)
        self.assertFalse(r["valido"])
        self.assertIsNone(r["angulo"])

    def test_confianca_no_limiar_nao_vale(self):
        # igual ao serviço: precisa ser ACIMA do limiar
        self.assertFalse(analisar_quadro(pessoa(conf=LIMIAR_CONFIANCA))["valido"])
        self.assertTrue(analisar_quadro(pessoa(conf=LIMIAR_CONFIANCA + 0.01))["valido"])

    def test_metricas_iguais_as_do_servico(self):
        kps = pessoa()
        r = analisar_quadro(kps)
        ang, raz = metricas((260, 180, 250, 300, 390, 300))
        self.assertEqual((r["angulo"], r["razao"]), (ang, raz))
        self.assertAlmostEqual(r["b_px"], 140)
        self.assertAlmostEqual(r["a_px"], math.hypot(10, 120))
        self.assertAlmostEqual(r["c_px"], 70)
        self.assertAlmostEqual(r["razao_cb"], 70 / 140)

    def test_cb_so_com_a_outra_orelha(self):
        r = analisar_quadro(pessoa(conf_outra_orelha=0.1))
        self.assertTrue(r["valido"])
        self.assertIsNone(r["razao_cb"])
        self.assertIsNone(r["c_px"])

    def test_comparacao_com_baseline(self):
        base = analisar_quadro(pessoa())
        baseline = (base["angulo"], base["razao"])
        # pescoço 30% mais curto: queda de 30% > 12% → ruim
        r = analisar_quadro(pessoa(orelha=(253, 216)), baseline)
        self.assertAlmostEqual(r["queda_razao_pct"], 30.0, delta=0.5)
        self.assertTrue(r["ruim_quadro"])
        self.assertFalse(analisar_quadro(pessoa(), baseline)["ruim_quadro"])
        self.assertIsNone(analisar_quadro(pessoa())["ruim_quadro"])   # sem baseline não julga

    def test_validade_igual_a_do_avaliador_do_servico(self):
        """Em quadros aleatórios, 'válido' aqui = o serviço não dar SEM_USUARIO."""
        rnd = random.Random(7)
        for _ in range(2000):
            kps = [(rnd.randint(0, 640), rnd.randint(0, 480), rnd.random()) for _ in range(17)]
            r = analisar_quadro(kps)
            confs = [kps[i][2] for i in (cl.I_ORELHA, cl.I_OMBRO_ORELHA, cl.I_OUTRO_OMBRO)]
            pontos = None
            if min(confs) > LIMIAR_CONFIANCA:
                (xo, yo, _), (xe, ye, _), (xd, yd, _) = (kps[i] for i in (3, 5, 6))
                pontos = (xo, yo, xe, ye, xd, yd)
            sem = AvaliadorPostura(5.0, 0.8).avaliar(pontos).status == SEM_USUARIO
            self.assertEqual(r["valido"], not sem)


class TesteResumo(unittest.TestCase):
    def test_contagens_e_baseline(self):
        analises = [analisar_quadro(pessoa())] * 8 + [analisar_quadro(None)] * 2
        r = resumir_etapa(analises, 2.0)
        self.assertEqual((r["n_total"], r["n_validos"]), (10, 8))
        self.assertAlmostEqual(r["pct_sem_usuario"], 20.0)
        self.assertAlmostEqual(r["fps_medio"], 5.0)
        self.assertIsNotNone(r["baseline"])
        self.assertEqual(r["angulo_dp"], 0.0)

    def test_poucos_validos_sem_baseline(self):
        r = resumir_etapa([analisar_quadro(pessoa())] * 4, 1.0)
        self.assertIsNone(r["baseline"])

    def test_tudo_perdido(self):
        r = resumir_etapa([analisar_quadro(None)] * 5, 1.0)
        self.assertEqual(r["pct_sem_usuario"], 100.0)
        self.assertIsNone(r["angulo_mediana"])
        self.assertIsNone(r["pct_ruim_quadro"])


class TesteSessao(unittest.TestCase):
    def setUp(self):
        self.reg = RegistroFalso()
        self.s = Sessao(self.reg, duracao_s=1.0, contagem_s=0.5)
        self.t = 0.0

    def passar(self, segundos, kps, passo=0.1):
        fim = self.t + segundos
        while self.t < fim - 1e-9:
            self.t += passo
            self.s.quadro(kps, self.t)

    def gravar_etapa(self, kps):
        self.s.tecla("espaco", self.t)          # INSTRUCAO → CONTAGEM
        self.assertEqual(self.s.estado, CONTAGEM)
        self.passar(1.7, kps)                   # 0,5 s de contagem + 1 s gravando + folga
        self.assertEqual(self.s.estado, REVISAO)

    def test_contagem_nao_grava(self):
        self.s.tecla("espaco", self.t)
        self.s.tecla("espaco", self.t)
        self.passar(0.4, pessoa())
        self.assertEqual(self.s.estado, CONTAGEM)
        self.assertEqual(self.reg.quadros, [])

    def test_fluxo_completo(self):
        self.assertEqual(self.s.estado, ENQUADRAR)
        self.s.quadro(pessoa(), self.t)          # enquadramento não grava
        self.s.tecla("espaco", self.t)
        self.assertEqual(self.s.estado, INSTRUCAO)
        for etapa in ETAPAS:
            self.gravar_etapa(pessoa())
            self.assertTrue(self.s.pode_aceitar())
            self.s.tecla("espaco", self.t)
        self.assertEqual(self.s.estado, FIM)
        self.assertTrue(self.s.completa)
        self.assertEqual(self.s.motivo_fim, "fim")
        self.assertEqual(self.s.aceitas, [e.chave for e in ETAPAS])
        self.assertEqual(len(self.reg.etapas), 7)
        self.assertTrue(all(aceita for _, _, aceita, _ in self.reg.etapas))
        self.assertIsNotNone(self.s.baseline)
        self.assertAlmostEqual(self.s.baseline_b_px, 140)
        # ~1 s a 10 quadros/s por etapa (0,1 s de passo)
        for _, _, _, n in self.reg.etapas:
            self.assertIn(n, (9, 10, 11))

    def test_baseline_ruim_obriga_repetir(self):
        self.s.tecla("espaco", self.t)
        self.gravar_etapa(None)                  # só perdas
        self.assertFalse(self.s.pode_aceitar())
        self.s.tecla("espaco", self.t)           # não aceita
        self.assertEqual(self.s.estado, REVISAO)
        self.assertIn("repita", self.s.aviso_revisao())
        self.s.tecla("r", self.t)
        self.assertEqual((self.s.estado, self.s.tentativa), (INSTRUCAO, 2))
        self.assertEqual(self.reg.etapas[-1][:3], ("correta", 1, False))
        self.gravar_etapa(pessoa())
        self.s.tecla("espaco", self.t)
        self.assertEqual(self.s.etapa.chave, "incl_esquerda")
        self.assertEqual(self.reg.etapas[-1][:3], ("correta", 2, True))
        # os quadros das duas tentativas ficam gravados, cada um com a sua tentativa
        self.assertEqual({q[1] for q in self.reg.quadros}, {1, 2})

    def test_perdas_nas_etapas_ruins_sao_aceitas(self):
        self.s.tecla("espaco", self.t)
        for _ in range(5):                       # etapas 1 a 5 normais
            self.gravar_etapa(pessoa())
            self.s.tecla("espaco", self.t)
        self.assertEqual(self.s.etapa.chave, "cabeca_baixa")
        self.gravar_etapa(None)                  # cabeça baixa perdendo tudo
        self.assertTrue(self.s.pode_aceitar())
        self.assertIn("dado", self.s.aviso_revisao())

    def test_sair_no_meio_da_gravacao(self):
        self.s.tecla("espaco", self.t)
        self.s.tecla("espaco", self.t)
        self.passar(0.9, pessoa())               # já gravando
        self.assertEqual(self.s.estado, GRAVANDO)
        self.s.tecla("sair", self.t)
        self.assertEqual(self.s.estado, FIM)
        self.assertFalse(self.s.completa)
        self.assertEqual(self.reg.etapas[-1][:3], ("correta", 1, False))
        self.assertEqual((self.reg.motivos[-1], self.s.motivo_fim), ("interrompida", "interrompida"))

    def ate_etapa(self, n):
        """Aceita as etapas antes da `n` (1 = começa na baseline)."""
        self.s.tecla("espaco", self.t)
        for _ in range(n - 1):
            self.gravar_etapa(pessoa())
            self.s.tecla("espaco", self.t)

    def test_contagem_padrao_5_s(self):
        self.assertEqual(Sessao(self.reg).contagem_s, 5.0)

    def test_nao_pula_a_baseline(self):
        self.ate_etapa(1)
        self.assertFalse(self.s.pode_pular())
        self.s.tecla("pular", self.t)
        self.assertEqual((self.s.etapa.chave, self.s.estado), ("correta", INSTRUCAO))
        self.assertEqual(self.reg.etapas, [])

    def test_pular_no_meio_da_gravacao_guarda_os_quadros(self):
        self.ate_etapa(3)
        self.s.tecla("espaco", self.t)
        self.passar(0.9, pessoa())               # 0,5 s de contagem + ~0,4 s gravando
        n = len(self.reg.quadros)
        self.s.tecla("pular", self.t)
        self.assertEqual(self.s.etapa.chave, "relaxada")
        self.assertEqual(self.s.estado, INSTRUCAO)
        self.assertEqual(self.reg.etapas[-1][:3], ("incl_direita", 1, False))
        self.assertGreater(self.reg.etapas[-1][3], 0)
        self.assertEqual(self.reg.motivos[-1], "pulou")
        self.assertEqual(len(self.reg.quadros), n)  # nada apagado
        self.assertEqual(self.s.puladas, ["incl_direita"])

    def test_pular_antes_de_gravar_registra_linha_vazia(self):
        self.ate_etapa(2)
        self.s.tecla("pular", self.t)            # na tela de instrução
        self.assertEqual(self.reg.etapas[-1], ("incl_esquerda", 1, False, 0))
        self.assertEqual(self.reg.motivos[-1], "pulou")

    def test_pular_a_ultima_termina_incompleta(self):
        self.ate_etapa(7)
        self.s.tecla("pular", self.t)
        self.assertEqual(self.s.estado, FIM)
        self.assertFalse(self.s.completa)        # completa = as 7 ACEITAS
        self.assertEqual(self.s.motivo_fim, "fim")
        self.assertEqual(len(self.s.aceitas), 6)

    def test_desistir_salva_e_encerra(self):
        self.ate_etapa(4)
        self.gravar_etapa(pessoa())              # na revisão, ainda não aceita
        self.s.tecla("desistir", self.t)
        self.assertEqual(self.s.estado, FIM)
        self.assertEqual(self.s.motivo_fim, "desistiu")
        self.assertFalse(self.s.completa)
        self.assertEqual(self.reg.etapas[-1][:3], ("relaxada", 1, False))
        self.assertEqual(self.reg.motivos[-1], "desistiu")
        self.s.tecla("desistir", self.t)         # depois do fim não grava de novo
        self.assertEqual(len(self.reg.etapas), 4)

    def test_desistir_no_enquadramento_nao_cria_etapa(self):
        self.s.tecla("desistir", self.t)
        self.assertEqual((self.s.estado, self.s.motivo_fim, self.reg.etapas), (FIM, "desistiu", []))

    def test_repetir_tem_motivo(self):
        self.ate_etapa(1)
        self.gravar_etapa(pessoa())
        self.s.tecla("r", self.t)
        self.assertEqual(self.reg.motivos[-1], "repetir")

    def test_textos_aprovados(self):
        for e in ETAPAS[1:]:
            self.assertEqual(e.instrucoes[0], "Volte a postura correta (como na etapa 1).")
        for e in ETAPAS[1:3]:
            self.assertIn("ORELHA", " ".join(e.instrucoes))
            self.assertIn("NAO gire o rosto", " ".join(e.instrucoes))
        for e in ETAPAS:
            for linha in (e.titulo, *e.instrucoes):
                linha.encode("ascii")            # a janela do OpenCV só aceita ASCII

    def test_desvio_usa_a_baseline_aceita(self):
        self.s.tecla("espaco", self.t)
        self.gravar_etapa(pessoa())
        self.s.tecla("espaco", self.t)
        a = self.s.quadro(pessoa(orelha=(253, 216)), self.t)
        self.assertTrue(a["ruim_quadro"])


class TesteRegistroCSV(unittest.TestCase):
    """Precisa do OpenCV instalado (coleta.py importa cv2)."""

    def test_arquivos_e_colunas(self):
        try:
            import coleta
        except ImportError as erro:
            self.skipTest(f"sem OpenCV/numpy: {erro}")
        with tempfile.TemporaryDirectory() as pasta:
            self.assertEqual(coleta.proximo_id(pasta)[0], "P01")
            # termo, sexo, altura (1 erro + 1 fora da faixa antes), óculos, cabelo, cadeira,
            # distância, altura da câmera, webcam (1 inválida antes), notebook, observações
            respostas = iter(["s", "x", "m", "abc", "1,72", "172,5", "n", "s", "com encosto", "60",
                              "abaixo, so o tronco", "q", "t", "", ""])
            meta = coleta.perguntar_metadados(pasta, "nb-teste", entrada=lambda _: next(respostas))
            self.assertEqual((meta["participante"], meta["notebook"], meta["oculos"]), ("P01", "nb-teste", "n"))
            self.assertEqual((meta["sexo"], meta["altura_pessoa_cm"], meta["webcam"]), ("mulher", 172.5, "tcc"))
            self.assertEqual(meta["altura_camera"], "abaixo, so o tronco")   # texto livre
            meta["observacoes_fim"] = "cabelo na orelha"
            reg = coleta.RegistroCSV(pasta, "P01")
            s = Sessao(reg, duracao_s=0.5, contagem_s=0.0)
            t = 0.0
            s.tecla("espaco", t)
            for etapa in range(2):
                s.tecla("espaco", t)
                for i in range(8):
                    t += 0.1
                    s.quadro(None if etapa == 1 and i in (2, 3) else pessoa(), t)
                self.assertTrue(s.pode_aceitar())
                s.tecla("espaco", t)
            s.tecla("pular", t)                  # pula a etapa 3 (sem gravar)
            s.tecla("desistir", t)               # e desiste na 4
            reg.participante_fim(s, meta, dict(fonte="teste", modelo_md5="x"))
            reg.fechar()
            with open(reg.caminho_quadros, encoding="utf-8") as arq:
                linhas = list(csv.reader(arq))
            self.assertEqual(linhas[0], coleta.RegistroCSV.CAB_QUADROS)
            self.assertTrue(all(len(l) == len(linhas[0]) for l in linhas))
            self.assertGreater(len(linhas), 5)
            with open(os.path.join(pasta, "etapas.csv"), encoding="utf-8") as arq:
                etapas = list(csv.DictReader(arq))
            self.assertEqual([e["etapa_chave"] for e in etapas],
                             ["correta", "incl_esquerda", "incl_direita", "relaxada"])
            self.assertEqual([e["motivo"] for e in etapas], ["", "", "pulou", "desistiu"])
            self.assertEqual([e["aceita"] for e in etapas], ["1", "1", "0", "0"])
            self.assertTrue(etapas[0]["baseline_angulo"])
            with open(os.path.join(pasta, "participantes.csv"), encoding="utf-8") as arq:
                parts = list(csv.DictReader(arq))
            self.assertEqual(parts[0]["etapas_aceitas"], "correta|incl_esquerda")
            self.assertEqual(parts[0]["etapas_puladas"], "incl_direita")
            self.assertEqual((parts[0]["completa"], parts[0]["motivo_fim"]), ("0", "desistiu"))
            self.assertEqual((parts[0]["sexo"], parts[0]["altura_pessoa_cm"]), ("mulher", "172.5"))
            self.assertEqual(parts[0]["observacoes_fim"], "cabelo na orelha")
            self.assertEqual(coleta.proximo_id(pasta)[0], "P02")

    def test_csv_de_formato_antigo_e_guardado(self):
        try:
            import coleta
        except ImportError as erro:
            self.skipTest(f"sem OpenCV/numpy: {erro}")
        with tempfile.TemporaryDirectory() as pasta:
            antigo = os.path.join(pasta, "participantes.csv")
            with open(antigo, "w", newline="", encoding="utf-8") as arq:
                csv.writer(arq).writerows([["participante", "completa"], ["P01", "1"]])
            arq, escritor = coleta._abrir_csv(antigo, coleta.RegistroCSV.CAB_PARTICIPANTES)
            arq.close()
            nomes = sorted(os.listdir(pasta))
            self.assertEqual(len(nomes), 2)
            self.assertTrue(nomes[1].startswith("participantes_formato_antigo_"))
            self.assertEqual(coleta._cabecalho_atual(antigo), coleta.RegistroCSV.CAB_PARTICIPANTES)
            # o P01 do arquivo antigo continua contando como usado
            self.assertEqual(coleta.proximo_id(pasta)[0], "P02")

    def test_versao_pelo_arquivo_sem_git(self):
        try:
            import coleta
        except ImportError as erro:
            self.skipTest(f"sem OpenCV/numpy: {erro}")
        original = coleta._git
        coleta._git = lambda *a: ""              # como num zip: sem .git
        try:
            with tempfile.TemporaryDirectory() as pasta:
                arq = os.path.join(pasta, "VERSAO")
                self.assertEqual(coleta._versao_codigo(arq), "desconhecida")   # não existe
                with open(arq, "w", encoding="utf-8") as f:
                    f.write("$Format:%h$\n")
                self.assertEqual(coleta._versao_codigo(arq), "desconhecida")   # marcador cru
                with open(arq, "w", encoding="utf-8") as f:
                    f.write("027b861\n")
                self.assertEqual(coleta._versao_codigo(arq), "027b861")
        finally:
            coleta._git = original

    def test_observacoes_fim_e_quebra_de_linha(self):
        try:
            import coleta
        except ImportError as erro:
            self.skipTest(f"sem OpenCV/numpy: {erro}")
        self.assertEqual(coleta.perguntar_observacoes_fim(lambda _: "  repetiu a 6 "), "repetiu a 6")
        def interrompe(_):
            raise EOFError
        self.assertEqual(coleta.perguntar_observacoes_fim(interrompe), "")
        texto = "palavra " * 30
        linhas = coleta.quebrar_linha(texto, largura_px=200)
        self.assertGreater(len(linhas), 1)
        self.assertEqual(" ".join(linhas).split(), texto.split())


class TesteDetectorDeVerdade(unittest.TestCase):
    """Roda o MoveNet de verdade (pula se não houver interpretador). Confere que os 17
    pontos da coleta dão a MESMA decisão de validade e as mesmas métricas do serviço."""

    def test_mesmo_resultado_do_servico(self):
        try:
            import numpy as np
            import coleta
            det = coleta.DetectorColeta()
        except Exception as erro:   # sem cv2/numpy/interpretador
            self.skipTest(f"sem MoveNet aqui: {erro}")
        rnd = np.random.default_rng(1)
        for _ in range(5):
            frame = rnd.integers(0, 255, (480, 640, 3), dtype=np.uint8)
            kps = det.detectar(frame)
            self.assertEqual(len(kps), 17)
            ang, raz, _ = det.det.detectar_metricas_postura(frame, LIMIAR_CONFIANCA)
            r = analisar_quadro(kps)
            self.assertEqual(r["valido"], ang is not None)
            if ang is not None:
                self.assertEqual((r["angulo"], r["razao"]), (ang, raz))


if __name__ == "__main__":
    unittest.main()
