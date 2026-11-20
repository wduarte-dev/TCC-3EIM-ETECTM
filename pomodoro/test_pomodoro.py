"""
Testes (sem Pi, sem hardware). Rodar de dentro da pasta pomodoro/:

    python -m unittest -v
"""
import contextlib
import io
import json
import os
import socket
import tempfile
import threading
import unittest

from pomodoro_logica import (
    Pomodoro, SELECAO, FOCO, PAUSA, PAUSA_LONGA, PAUSADO,
    CURTO, LONGO, MUITO_LONGO,
    EV_FASE_MUDOU, EV_INICIOU, EV_PAUSOU, EV_RETOMOU, EV_REINICIOU, EV_PRESET_MUDOU,
)
from botoes import (
    classificar, ClassificadorAperto, Debouncer, detectar_ocioso, EntradaBotao, BotoesTeclado,
)
import energia
from energia import Desligamento, montar_comando, rodar_comando
from diagnostico_botoes import resumir
from recalibracao import MenuB1, POSTURA, WIFI, ACAO_RECALIBRAR

PRESETS = [
    {"nome": "A", "foco": 2, "pausa": 1, "pausa_longa": 3},
    {"nome": "B", "foco": 5, "pausa": 1, "pausa_longa": 2},
]


def novo(ciclos=2):
    return Pomodoro(presets=PRESETS, ciclos_ate_longa=ciclos)


class TesteSelecao(unittest.TestCase):
    def test_curto_troca_preset_e_da_a_volta(self):
        p = novo()
        self.assertEqual(p.botao(CURTO), [EV_PRESET_MUDOU])
        self.assertEqual(p.preset["nome"], "B")
        p.botao(CURTO)
        self.assertEqual(p.preset["nome"], "A")
        self.assertEqual(p.estado, SELECAO)

    def test_longo_inicia_o_foco_com_a_duracao_do_preset(self):
        p = novo()
        p.botao(CURTO)   # B
        self.assertEqual(p.botao(LONGO), [EV_INICIOU])
        self.assertEqual(p.estado, FOCO)
        self.assertEqual(p.restante_s, 5 * 60)

    def test_muito_longo_na_selecao_vale_como_longo(self):
        p = novo()
        self.assertEqual(p.botao(MUITO_LONGO), [EV_INICIOU])
        self.assertEqual(p.estado, FOCO)

    def test_tick_na_selecao_nao_faz_nada(self):
        p = novo()
        self.assertEqual(p.tick(100), [])
        self.assertEqual(p.estado, SELECAO)


class TesteCiclo(unittest.TestCase):
    def test_foco_vira_pausa_sozinho_e_volta_pro_foco(self):
        p = novo()
        p.botao(LONGO)
        self.assertEqual(p.tick(120), [EV_FASE_MUDOU])
        self.assertEqual(p.estado, PAUSA)
        self.assertEqual(p.restante_s, 60)
        self.assertEqual(p.tick(60), [EV_FASE_MUDOU])
        self.assertEqual(p.estado, FOCO)

    def test_pausa_longa_a_cada_n_focos(self):
        p = novo(ciclos=2)
        p.botao(LONGO)
        p.tick(120)                 # foco 1 → pausa curta
        self.assertEqual(p.estado, PAUSA)
        p.tick(60)                  # → foco 2
        p.tick(120)                 # foco 2 → pausa LONGA
        self.assertEqual(p.estado, PAUSA_LONGA)
        self.assertEqual(p.restante_s, 3 * 60)
        p.tick(180)                 # → foco 3 (novo bloco)
        self.assertEqual(p.estado, FOCO)
        self.assertEqual(p.ciclo_atual, 1)

    def test_numero_do_ciclo_mostrado(self):
        p = novo(ciclos=2)
        p.botao(LONGO)
        self.assertEqual(p.ciclo_atual, 1)
        p.tick(120)
        self.assertEqual(p.ciclo_atual, 1)    # na pausa, ainda é o foco que acabou
        p.tick(60)
        self.assertEqual(p.ciclo_atual, 2)
        p.tick(120)
        self.assertEqual(p.ciclo_atual, 2)    # pausa longa depois do 2º foco

    def test_dt_grande_atravessa_varias_fases_sem_perder_tempo(self):
        p = novo()
        p.botao(LONGO)
        # 120 (foco) + 60 (pausa) + 30 dentro do 2º foco
        p.tick(210)
        self.assertEqual(p.estado, FOCO)
        self.assertAlmostEqual(p.restante_s, 120 - 30)

    def test_contagem_regressiva_normal(self):
        p = novo()
        p.botao(LONGO)
        p.tick(30)
        self.assertEqual(p.restante_s, 90)


class TestePausaEReinicio(unittest.TestCase):
    """Mapa do B2 de 19/11: rodando/pausado, curto pausa/retoma e longo volta pra seleção."""

    def test_curto_pausa_congela_e_curto_retoma(self):
        p = novo()
        p.botao(LONGO)
        p.tick(30)
        self.assertEqual(p.botao(CURTO), [EV_PAUSOU])
        self.assertEqual(p.estado, PAUSADO)
        p.tick(1000)                                  # tempo passa, timer não
        self.assertEqual(p.restante_s, 90)
        self.assertEqual(p.botao(CURTO), [EV_RETOMOU])
        self.assertEqual(p.estado, FOCO)
        p.tick(10)
        self.assertEqual(p.restante_s, 80)

    def test_pausar_e_retomar_no_descanso_tambem(self):
        p = novo()
        p.botao(LONGO)
        p.tick(120)                                   # entrou na PAUSA
        p.botao(CURTO)
        self.assertEqual(p.estado, PAUSADO)
        self.assertEqual(p.fase_atual, PAUSA)
        p.botao(CURTO)
        self.assertEqual(p.estado, PAUSA)

    def test_longo_e_muito_longo_voltam_pra_selecao(self):
        for tipo in (LONGO, MUITO_LONGO):
            for pausar_antes in (False, True):
                p = novo()
                p.botao(CURTO)                        # preset B
                p.botao(LONGO)
                p.tick(50)
                if pausar_antes:
                    p.botao(CURTO)
                self.assertEqual(p.botao(tipo), [EV_REINICIOU])
                self.assertEqual(p.estado, SELECAO)
                self.assertEqual(p.focos_concluidos, 0)
                self.assertEqual(p.preset["nome"], "B")   # mantém o preset escolhido
                p.botao(LONGO)
                self.assertEqual(p.restante_s, 5 * 60)    # recomeça do zero

    def test_rotulos_da_dica_enquanto_segura(self):
        p = novo()
        self.assertEqual(p.rotulo_aperto(LONGO), "INICIAR")
        self.assertEqual(p.rotulo_aperto(MUITO_LONGO), "INICIAR")
        self.assertEqual(p.rotulo_aperto(CURTO), "")
        p.botao(LONGO)
        self.assertEqual(p.rotulo_aperto(LONGO), "VOLTAR")
        self.assertEqual(p.rotulo_aperto(MUITO_LONGO), "VOLTAR")
        p.botao(CURTO)
        self.assertEqual(p.rotulo_aperto(LONGO), "VOLTAR")


class TestePresets(unittest.TestCase):
    """T6: um pré-configurado + presets do usuário num JSON."""

    def setUp(self):
        import presets
        self.presets = presets
        self.pasta = tempfile.mkdtemp()
        self.arq = os.path.join(self.pasta, "sub", "presets.json")

    def test_de_fabrica_so_o_25_5_com_pausa_longa_15(self):
        from pomodoro_config import PRESETS
        self.assertEqual(PRESETS, [{"nome": "25/5", "foco": 25, "pausa": 5, "pausa_longa": 15}])
        self.assertEqual(self.presets.todos(self.arq), PRESETS)       # sem arquivo

    def test_interpretar(self):
        f = self.presets.interpretar
        self.assertEqual(f("50/10"), {"nome": "50/10", "foco": 50, "pausa": 10, "pausa_longa": None})
        self.assertEqual(f(" 50/10/20 "), {"nome": "50/10/20", "foco": 50, "pausa": 10, "pausa_longa": 20})
        for ruim in ("50", "50/10/20/5", "50/x", "0/5", "181/5", "50/-1", "50/10/5", "5.5/1", ""):
            with self.assertRaises(self.presets.PresetInvalido, msg=ruim):
                f(ruim)
        self.assertEqual(f("180/180/180")["foco"], 180)
        self.assertEqual(f("50/10/10")["pausa_longa"], 10)            # 3º igual à pausa vale

    def test_adicionar_listar_remover(self):
        self.presets.adicionar("50/10/20", self.arq)
        self.presets.adicionar("90/20", self.arq)
        nomes = [p["nome"] for p in self.presets.todos(self.arq)]
        self.assertEqual(nomes, ["25/5", "50/10/20", "90/20"])
        self.presets.remover("50/10/20", self.arq)
        self.assertEqual([p["nome"] for p in self.presets.todos(self.arq)], ["25/5", "90/20"])

    def test_duplicata_e_padrao_sao_recusados_sem_gravar(self):
        self.presets.adicionar("50/10", self.arq)
        antes = open(self.arq, encoding="utf-8").read()
        for texto in ("50/10", "25/5", "25/5/15"):
            with self.assertRaises(self.presets.PresetInvalido, msg=texto):
                self.presets.adicionar(texto, self.arq)
        with self.assertRaises(self.presets.PresetInvalido):
            self.presets.adicionar("50/10/5", self.arq)                # 3º < pausa
        self.assertEqual(open(self.arq, encoding="utf-8").read(), antes)

    def test_padrao_nao_e_removivel_e_inexistente_avisa(self):
        for texto in ("25/5", "25/5/15", "40/10"):
            with self.assertRaises(self.presets.PresetInvalido, msg=texto):
                self.presets.remover(texto, self.arq)

    def test_arquivo_estragado_nao_derruba(self):
        os.makedirs(os.path.dirname(self.arq))
        with open(self.arq, "w", encoding="utf-8") as f:
            f.write('{"presets": ["50/10", "lixo", "0/5", "50/10"]}')
        self.assertEqual([p["nome"] for p in self.presets.todos(self.arq)], ["25/5", "50/10"])
        with open(self.arq, "w", encoding="utf-8") as f:
            f.write("isso não é json")
        self.assertEqual(len(self.presets.todos(self.arq)), 1)

    def test_sem_pausa_longa_alterna_foco_e_pausa(self):
        p = Pomodoro(presets=[{"nome": "2/1", "foco": 2, "pausa": 1, "pausa_longa": None}])
        p.botao(LONGO)
        fases = []
        for _ in range(10):
            p.tick(60)
            fases.append(p.estado)
        self.assertNotIn(PAUSA_LONGA, fases)
        self.assertIn(PAUSA, fases)

    def test_trocar_presets_so_na_selecao_e_mantem_o_escolhido(self):
        a = {"nome": "A", "foco": 2, "pausa": 1, "pausa_longa": 3}
        b = {"nome": "B", "foco": 5, "pausa": 1, "pausa_longa": None}
        p = Pomodoro(presets=[a, b])
        p.botao(CURTO)                                   # B
        self.assertTrue(p.trocar_presets([a, {"nome": "C", "foco": 1, "pausa": 1, "pausa_longa": None}, b]))
        self.assertEqual(p.preset["nome"], "B")
        self.assertTrue(p.trocar_presets([a]))          # B sumiu: volta pro 1º
        self.assertEqual(p.preset["nome"], "A")
        p.botao(LONGO)
        self.assertFalse(p.trocar_presets([b]))         # rodando: não troca

    def test_comando(self):
        import pomodoro_ctl
        os.environ["POMODORO_PRESETS"] = self.arq
        try:
            import presets as mod
            from unittest import mock
            with mock.patch.object(mod, "CAMINHO_PRESETS", self.arq), \
                    mock.patch.object(mod.adicionar, "__defaults__", (self.arq,)), \
                    mock.patch.object(mod.remover, "__defaults__", (self.arq,)), \
                    mock.patch.object(mod.todos, "__defaults__", (self.arq,)):
                saida = io.StringIO()
                with contextlib.redirect_stdout(saida):
                    pomodoro_ctl.main(["adicionar", "--preset", "50/10/20"])
                    pomodoro_ctl.main(["listar"])
                self.assertIn("50/10/20", saida.getvalue())
                with self.assertRaises(SystemExit) as erro, contextlib.redirect_stderr(io.StringIO()):
                    pomodoro_ctl.main(["adicionar", "--preset", "25/5"])
                self.assertIn("Nada foi gravado", str(erro.exception))
        finally:
            del os.environ["POMODORO_PRESETS"]

    def test_nome_longo_cabe_na_selecao(self):
        try:
            import display
        except ImportError:
            self.skipTest("Pillow não instalado")
        for nome in ("25/5", "50/10/20", "180/180/180"):
            t = display._tamanho_que_cabe(nome)
            self.assertLessEqual(display._largura(nome, t), 126, nome)
        self.assertEqual(display._tamanho_que_cabe("25/5"), 26)


class TesteMenuB1(unittest.TestCase):
    def test_curto_abre_em_postura_e_alterna_com_wifi(self):
        m = MenuB1(timeout_s=5)
        self.assertFalse(m.aberto)
        self.assertIsNone(m.botao(CURTO))
        self.assertEqual(m.opcao, POSTURA)
        m.botao(CURTO)
        self.assertEqual(m.opcao, WIFI)
        m.botao(CURTO)
        self.assertEqual(m.opcao, POSTURA)

    def test_longo_executa_a_opcao_mostrada_e_fecha_o_menu(self):
        for cliques, esperada in ((1, POSTURA), (2, WIFI)):
            m = MenuB1(timeout_s=5)
            for _ in range(cliques):
                m.botao(CURTO)
            self.assertEqual(m.botao(LONGO), (ACAO_RECALIBRAR, esperada))
            self.assertFalse(m.aberto)            # volta ao estado inicial

    def test_muito_longo_conta_como_longo(self):
        m = MenuB1()
        m.botao(CURTO)
        self.assertEqual(m.botao(MUITO_LONGO), (ACAO_RECALIBRAR, POSTURA))

    def test_longo_com_menu_fechado_e_ignorado(self):
        m = MenuB1()
        self.assertIsNone(m.botao(LONGO))
        self.assertFalse(m.aberto)

    def test_menu_fecha_sozinho_sem_clique(self):
        m = MenuB1(timeout_s=5)
        m.botao(CURTO)
        m.tick(4.9)
        self.assertTrue(m.aberto)
        m.botao(CURTO)                            # novo clique renova o prazo
        m.tick(4.9)
        self.assertTrue(m.aberto)
        m.tick(0.2)
        self.assertFalse(m.aberto)
        self.assertIsNone(m.texto())

    def test_ocupado_ignora_o_b1_e_nao_fecha_o_menu_por_tempo(self):
        m = MenuB1(timeout_s=5)
        m.botao(CURTO)
        m.ocupado = True
        self.assertIsNone(m.botao(LONGO))
        self.assertIsNone(m.botao(CURTO))
        self.assertEqual(m.opcao, POSTURA)
        m.tick(100)
        self.assertTrue(m.aberto)

    def test_nao_mexe_no_pomodoro(self):
        # o B1 nem conhece o Pomodoro; este teste documenta a regra
        p = novo()
        p.botao(LONGO)
        p.tick(30)
        antes = (p.estado, p.restante_s)
        m = MenuB1()
        m.botao(CURTO)
        m.botao(CURTO)
        m.botao(LONGO)
        self.assertEqual((p.estado, p.restante_s), antes)

    def test_calibrar_antes_da_primeira_vez_e_recalibrar_depois(self):
        m = MenuB1()
        m.botao(CURTO)
        nada = {POSTURA: False}
        self.assertEqual(m.texto(calibrado=nada), "CALIBRAR: POSTURA")
        self.assertEqual(m.texto(True, nada), "SOLTE: CALIB POSTURA")
        self.assertEqual(m.texto(calibrado={POSTURA: True}), "RECALIBRAR: POSTURA")

    def test_textos(self):
        m = MenuB1()
        m.botao(CURTO)
        self.assertEqual(m.texto(), "RECALIBRAR: POSTURA")
        self.assertEqual(m.texto(segurando_longo=True), "SOLTE: RECAL POSTURA")
        m.botao(CURTO)
        self.assertEqual(m.texto(), "WIFI CONECTAR")
        self.assertEqual(m.texto(segurando_longo=True), "SOLTE: WIFI CONECTAR")

    def test_abrir_em_reabre_na_opcao(self):
        m = MenuB1(timeout_s=5)
        m.abrir_em(WIFI)
        self.assertEqual(m.opcao, WIFI)
        self.assertEqual(m.botao(LONGO), (ACAO_RECALIBRAR, WIFI))


class NmFalso:
    """Faz o papel do nmcli: responde por comando e registra o que foi chamado."""
    def __init__(self, ativo="", ip=False, perfil=None, sobe_na_tentativa=1, ssh=False):
        self.ativo, self.ip, self.perfil = ativo, ip, perfil
        self.sobe_na_tentativa, self.ssh = sobe_na_tentativa, ssh
        self.tentativas = 0
        self.chamadas = []

    def __call__(self, comando, timeout=10, cancelado=None):
        self.chamadas.append(comando)
        if comando[0] == "ss":
            return 0, "ESTAB 0 0 10.0.0.2:22 10.0.0.9:5000\n" if self.ssh else ""
        if comando[:2] == ["nmcli", "-g"] and comando[2].startswith("GENERAL"):
            return 0, f"{self.ativo}\n{'192.168.43.20/24' if self.ip else ''}\n"
        if comando[:2] == ["nmcli", "-g"]:
            return (0, self.perfil + "\n") if self.perfil is not None else (10, "Error: no such connection")
        if "add" in comando or "modify" in comando:
            self.perfil = comando[comando.index("ssid") + 1] if "ssid" in comando else \
                comando[comando.index("802-11-wireless.ssid") + 1]
            return 0, ""
        if "up" in comando:
            self.tentativas += 1
            if self.tentativas >= self.sobe_na_tentativa:
                self.ativo, self.ip = "tcc-wifi", True
                return 0, ""
            return 4, "Error: no network with SSID"
        return 0, ""


class TesteWifi(unittest.TestCase):
    def setUp(self):
        import wifi
        self.wifi = wifi
        self.t = [0.0]

    def _novo(self, nm, **kw):
        kw.setdefault("intervalo_s", 0.01)
        kw.setdefault("timeout_s", 5)
        return self.wifi.WifiConectar(executar=nm, relogio=lambda: self.t[0], tem_nm=lambda: True,
                                      carregar_rede=lambda: ("DIHMO", "admin1234", False), **kw)

    def _esperar_fim(self, w):
        for _ in range(400):
            if w.tela is None or w.tela[0] == "resultado":
                return
            threading.Event().wait(0.005)

    def test_padrao_sem_arquivo(self):
        arq = os.path.join(tempfile.mkdtemp(), "wifi.json")
        self.assertEqual(self.wifi.carregar(arq), ("DIHMO", "admin1234", False))

    def test_salvar_e_carregar(self):
        arq = os.path.join(tempfile.mkdtemp(), "x", "wifi.json")
        self.wifi.salvar("Casa", "senha1234", arq)
        self.assertEqual(self.wifi.carregar(arq), ("Casa", "senha1234", True))
        if os.name != "nt":
            self.assertEqual(os.stat(arq).st_mode & 0o777, 0o600)     # tem senha: só o dono

    def test_validacao_wpa2(self):
        v = lambda s, p: self.wifi.validar(s, p, medir=len)            # medir por letra só pra isolar a regra
        for ssid, senha in (("", "12345678"), ("x" * 33, "12345678"), ("Casa", "1234567"),
                            ("Casa", "x" * 64), ("Casa", "senhaçãoo")):
            with self.assertRaises(self.wifi.WifiInvalido, msg=(ssid, senha)):
                self.wifi.validar(ssid, senha, medir=lambda t: 0)
        v("Casa", "12345678")

    def test_recusa_o_que_nao_cabe_na_tela_e_diz_o_maximo(self):
        try:
            import display  # noqa: F401
        except ImportError:
            self.skipTest("Pillow não instalado")
        self.wifi.validar("DIHMO", "admin1234")                       # padrão cabe com folga
        with self.assertRaises(self.wifi.WifiInvalido) as erro:
            self.wifi.validar("MinhaRedeDeCasaMuitoLonga", "admin1234")
        self.assertIn("cabem só", str(erro.exception))
        with self.assertRaises(self.wifi.WifiInvalido):
            self.wifi.validar("Casa", "WWWWWWWWWWWW")                   # só W: pior caso

    def test_conecta_na_segunda_tentativa(self):
        nm = NmFalso(sobe_na_tentativa=2)
        w = self._novo(nm)
        self.assertEqual(w.pedir(), "iniciou")
        self.assertEqual(w.tela[0], "espera")
        self.assertEqual(w.tela[1:3], ("DIHMO", "admin1234"))
        self._esperar_fim(w)
        self.assertEqual(w.tela, ("resultado", True, "DIHMO"))
        self.assertEqual(nm.tentativas, 2)
        self.assertTrue(any("rescan" in c for c in nm.chamadas))
        self.t[0] += 3.1                                                 # some depois de 3 s
        self.assertIsNone(w.tela)

    def test_ja_conectado_nao_desconecta(self):
        nm = NmFalso(ativo="tcc-wifi", ip=True, perfil="DIHMO")
        w = self._novo(nm)
        w.pedir()
        self._esperar_fim(w)
        self.assertEqual(w.tela, ("resultado", True, "DIHMO"))
        self.assertFalse(any("up" in c for c in nm.chamadas))

    def test_falha_por_tempo(self):
        nm = NmFalso(sobe_na_tentativa=10**6)
        relogio = {"t": 0.0}
        def tempo():
            relogio["t"] += 1.0               # cada leitura do relógio "passa" 1 s
            return relogio["t"]
        w = self.wifi.WifiConectar(executar=nm, relogio=tempo, tem_nm=lambda: True,
                                   carregar_rede=lambda: ("DIHMO", "admin1234", False),
                                   timeout_s=20, intervalo_s=0.0, resultado_s=10**6)
        w.pedir()
        for _ in range(400):
            if w._fase == "resultado":
                break
            threading.Event().wait(0.005)
        self.assertEqual(w._fase, "resultado")
        self.assertFalse(w._ok)

    def test_sem_nmcli_falha(self):
        w = self.wifi.WifiConectar(executar=NmFalso(), relogio=lambda: self.t[0], tem_nm=lambda: False,
                                   carregar_rede=lambda: ("DIHMO", "admin1234", False))
        w.pedir()
        self._esperar_fim(w)
        self.assertEqual(w.tela, ("resultado", False, "DIHMO"))

    def test_cancelar_volta_ao_normal(self):
        nm = NmFalso(sobe_na_tentativa=10**6)
        w = self._novo(nm, intervalo_s=60, timeout_s=600)
        w.pedir()
        self.assertTrue(w.esperando)
        w.cancelar()
        self.assertIsNone(w.tela)
        self.assertFalse(w.ocupado)

    def test_ssh_ativo_noutra_rede_pede_confirmacao(self):
        nm = NmFalso(ativo="casa", ip=True, perfil="DIHMO", ssh=True)
        w = self._novo(nm)
        self.assertEqual(w.pedir(), "confirmar")
        self.assertEqual(w.mensagem(), "SSH ATIVO: REPITA")
        self.assertIsNone(w.tela)
        self.assertEqual(w.pedir(), "iniciou")                         # repetiu dentro de 5 s
        self._esperar_fim(w)
        self.assertIsNone(w.mensagem())

    def test_ssh_confirmacao_expira(self):
        nm = NmFalso(ativo="casa", ip=True, perfil="DIHMO", ssh=True)
        w = self._novo(nm)
        w.pedir()
        self.t[0] += 5.1
        self.assertIsNone(w.mensagem())
        self.assertEqual(w.pedir(), "confirmar")                       # passou o prazo: pede de novo

    def test_sem_ssh_nao_pede_confirmacao(self):
        w = self._novo(NmFalso(ativo="casa", ip=True, perfil="DIHMO", ssh=False))
        self.assertEqual(w.pedir(), "iniciou")

    def test_telas_cheias(self):
        try:
            import display
        except ImportError:
            self.skipTest("Pillow não instalado")
        for img in (display.desenhar_wifi_espera("DIHMO", "admin1234", 3),
                    display.desenhar_wifi_resultado(True, "DIHMO"),
                    display.desenhar_wifi_resultado(False, "DIHMO")):
            self.assertEqual(img.size, (128, 64))
            self.assertIsNotNone(img.getbbox())
        fonte12 = display._fonte(12)
        self.assertLessEqual(fonte12.getlength("WIFI CONECTADO"), 128)

    def test_comando_wifi(self):
        import wifi_ctl
        from unittest import mock
        arq = os.path.join(tempfile.mkdtemp(), "wifi.json")
        with mock.patch.object(self.wifi.salvar, "__defaults__", (arq,)), \
                mock.patch.object(self.wifi.carregar, "__defaults__", (arq,)), \
                mock.patch.object(self.wifi, "tem_nmcli", lambda: False):
            saida = io.StringIO()
            with contextlib.redirect_stdout(saida):
                wifi_ctl.main(["--ssid", "Casa", "--senha", "senha1234"])
                wifi_ctl.main([])
            self.assertIn("Rede:  Casa", saida.getvalue())
            with self.assertRaises(SystemExit) as erro, contextlib.redirect_stdout(io.StringIO()):
                wifi_ctl.main(["--ssid", "Casa", "--senha", "curta"])
            self.assertIn("Nada foi gravado", str(erro.exception))


class TesteClassificacao(unittest.TestCase):
    def test_limites(self):
        self.assertEqual(classificar(0.1), CURTO)
        self.assertEqual(classificar(0.99), CURTO)
        self.assertEqual(classificar(1.0), LONGO)
        self.assertEqual(classificar(2.99), LONGO)
        self.assertEqual(classificar(3.0), MUITO_LONGO)
        self.assertEqual(classificar(10), MUITO_LONGO)

    def test_classificador_com_relogio_falso(self):
        t = [0.0]
        c = ClassificadorAperto(relogio=lambda: t[0])
        self.assertIsNone(c.soltou())                 # soltar sem apertar
        c.apertou()
        t[0] = 0.4
        self.assertEqual(c.tipo_se_soltar_agora(), CURTO)
        t[0] = 1.5
        self.assertEqual(c.tipo_se_soltar_agora(), LONGO)
        t[0] = 3.2
        self.assertEqual(c.soltou(), MUITO_LONGO)
        self.assertEqual(c.segurando_ha(), 0.0)       # voltou ao zero
        self.assertIsNone(c.tipo_se_soltar_agora())

    def test_repique_de_apertar_nao_zera_a_contagem(self):
        t = [0.0]
        c = ClassificadorAperto(relogio=lambda: t[0])
        c.apertou()
        t[0] = 2.0
        c.apertou()                                   # repique: ignorado
        t[0] = 2.5
        self.assertEqual(c.soltou(), LONGO)


class TesteTela(unittest.TestCase):
    def setUp(self):
        try:
            import PIL  # noqa: F401
        except ImportError:
            self.skipTest("Pillow não instalado")
        import display
        self.display = display

    def test_formatar_tempo(self):
        f = self.display.formatar_tempo
        self.assertEqual(f(25 * 60), "25:00")
        self.assertEqual(f(59.2), "01:00")             # arredonda pra cima
        self.assertEqual(f(0), "00:00")
        self.assertEqual(f(-5), "00:00")
        self.assertEqual(f(90 * 60), "90:00")

    def test_desenha_todas_as_telas_no_tamanho_certo(self):
        p = novo()
        imagens = [self.display.desenhar(p, "POSTURA: BOA")]                       # seleção
        imagens.append(self.display.desenhar(p, "X", segurando_tipo=LONGO))
        p.botao(LONGO)
        imagens.append(self.display.desenhar(p, "POSTURA: BOA", "CORRETA"))        # foco
        imagens.append(self.display.desenhar(p, "POSTURA: RUIM", "ALERTA"))        # alerta
        imagens.append(self.display.desenhar(p, "POSTURA: BOA", piscando=True))    # piscando
        p.botao(CURTO)
        imagens.append(self.display.desenhar(p, "POSTURA: BOA"))                   # pausado
        for img in imagens:
            self.assertEqual(img.size, (128, 64))
            self.assertEqual(img.mode, "1")
            self.assertGreater(len(set(img.tobytes())), 1)                          # não é tela em branco

    def test_textos_do_b1_cabem_na_tela(self):
        from PIL import ImageFont
        fonte = self.display._fonte(9)
        textos = ["RECALIBRAR: POSTURA", "SOLTE: RECAL POSTURA", "CALIBRAR: POSTURA", "SOLTE: CALIB POSTURA",
                  "WIFI CONECTAR", "SOLTE: WIFI CONECTAR", "SSH ATIVO: REPITA"]
        for t in textos:
            self.assertLessEqual(fonte.getlength(t), 128, t)

    def test_figura_dos_pontos_cheio_e_vazado(self):
        p = novo()
        d = self.display
        cheio = d.desenhar(p, "AJEITE-SE! 7s", pontos=(True, True, True))
        falta = d.desenhar(p, "AJEITE-SE! 7s", pontos=(True, True, False))
        self.assertTrue(cheio.getpixel((d.X_OUTRO_OMBRO, d.Y_OMBROS)))   # centro preenchido
        self.assertFalse(falta.getpixel((d.X_OUTRO_OMBRO, d.Y_OMBROS)))     # só o contorno
        self.assertTrue(falta.getpixel((d.X_OMBRO_ORELHA, d.Y_ORELHA)))

    def test_textos_com_figura_nao_encostam_nos_pontos(self):
        fonte = self.display._fonte(9)
        limite = self.display.X_OUTRO_OMBRO - self.display.RAIO_PONTO - 2
        for t in ("COMEÇANDO EM: 10s", "CALIBRANDO...", "CALIBRACAO FALHOU", "SEM USUARIO"):
            self.assertLessEqual(fonte.getlength(t), limite, t)

    def test_selecao_sem_dica_fixa(self):
        p = novo()
        img = self.display.desenhar(p, "POSTURA: BOA")
        self.assertIsNone(img.crop((0, 40, 128, 50)).getbbox())    # faixa da dica vazia
        img = self.display.desenhar(p, "POSTURA: BOA", segurando_tipo=LONGO)
        self.assertIsNotNone(img.crop((0, 40, 128, 50)).getbbox())  # SOLTE: INICIAR

    def test_topo_mostra_fase_e_ciclo_e_icone_so_pausado(self):
        p = Pomodoro(presets=PRESETS)                  # 4 ciclos
        p.botao(LONGO)
        self.assertEqual(self.display._texto_fase(p), "FOCO 1/4")
        p.tick(120)
        self.assertEqual(self.display._texto_fase(p), "PAUSA 1/4")
        largura = self.display._largura("PAUSA 1/4", 9)
        x_icone = 127 - int(round(largura)) - 12
        rodando = self.display.desenhar(p, "X")
        self.assertIsNone(rodando.crop((x_icone, 1, x_icone + 9, 10)).getbbox())
        p.botao(CURTO)
        pausado = self.display.desenhar(p, "X")
        self.assertEqual(self.display._texto_fase(p), "PAUSA 1/4")
        self.assertIsNotNone(pausado.crop((x_icone, 1, x_icone + 9, 10)).getbbox())

    def test_pausa_longa_abreviada(self):
        p = novo(ciclos=1)
        p.botao(LONGO)
        p.tick(120)
        self.assertEqual(self.display._texto_fase(p), "P.LONGA 1/1")

    def test_piscar_inverte_a_imagem(self):
        p = novo()
        normal = self.display.desenhar(p, "OK")
        invertida = self.display.desenhar(p, "OK", piscando=True)
        self.assertNotEqual(normal.tobytes(), invertida.tobytes())


class TestePostura(unittest.TestCase):
    def test_texto_curto(self):
        from postura_cliente import texto_curto
        self.assertEqual(texto_curto(None), "POSTURA: SEM SERVIÇO")
        self.assertEqual(texto_curto({"status": "CORRETA"}), "POSTURA: BOA")
        self.assertEqual(texto_curto({"status": "CALIBRADO"}), "POSTURA: BOA")
        self.assertEqual(texto_curto({"status": "ATENCAO"}), "POSTURA: ATENÇÃO")
        self.assertEqual(texto_curto({"status": "ALERTA"}), "POSTURA: RUIM")
        self.assertEqual(texto_curto({"status": "AGUARDANDO_CALIBRACAO"}), "APERTE B1: CALIBRAR")
        self.assertEqual(
            texto_curto({"status": "CONTAGEM", "texto": "Fique na postura CORRETA. Calibrando em 7s..."}),
            "COMEÇANDO EM: 7s")
        try:
            import display
        except ImportError:
            return
        fonte = display._fonte(9)
        for status in ("CORRETA", "ATENCAO", "ALERTA", "AGUARDANDO_CALIBRACAO", "CALIBRANDO",
                       "CALIBRACAO_FALHOU", "SEM_CAMERA", "SEM_USUARIO", "INICIANDO", None):
            estado = None if status is None else {"status": status, "texto": "em 3s"}
            self.assertLessEqual(fonte.getlength(texto_curto(estado)), 128, status)
        # na contagem divide a linha com a figura dos 3 pontos
        limite = display.X_OUTRO_OMBRO - display.RAIO_PONTO - 2
        self.assertLessEqual(fonte.getlength(texto_curto({"status": "CONTAGEM", "texto": "em 10s"})), limite)

    def test_pontos_do_enquadramento(self):
        from postura_cliente import pontos_enquadramento
        vis = {"orelha": True, "ombro_orelha": False, "outro_ombro": True}
        self.assertEqual(pontos_enquadramento({"status": "CONTAGEM", "pontos_visiveis": vis}),
                         (True, False, True))
        self.assertIsNone(pontos_enquadramento({"status": "CORRETA", "pontos_visiveis": vis}))
        self.assertIsNone(pontos_enquadramento({"status": "SEM_USUARIO", "pontos_visiveis": None}))
        self.assertIsNone(pontos_enquadramento(None))

    def test_enviar_sem_servico_devolve_none(self):
        from postura_cliente import enviar
        self.assertIsNone(enviar({"acao": "status"}, caminho="/tmp/nao-existe-postura.sock"))

    def test_enviar_com_servidor_falso(self):
        from postura_cliente import enviar
        caminho = os.path.join(tempfile.mkdtemp(), "p.sock")
        servidor = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        servidor.bind(caminho)
        servidor.listen(1)
        recebido = {}

        def atender():
            conn, _ = servidor.accept()
            recebido["pedido"] = json.loads(conn.recv(4096).decode().strip())
            conn.sendall((json.dumps({"ok": True, "estado": {"status": "CORRETA"}}) + "\n").encode())
            conn.close()

        threading.Thread(target=atender, daemon=True).start()
        resposta = enviar({"acao": "status"}, caminho=caminho)
        servidor.close()
        self.assertEqual(recebido["pedido"], {"acao": "status"})
        self.assertEqual(resposta["estado"]["status"], "CORRETA")


def simular(entrada, niveis, dt=0.01, relogio=None):
    """Alimenta o EntradaBotao com uma sequência de leituras (uma a cada dt s). Devolve os eventos."""
    eventos = []
    for nivel in niveis:
        relogio[0] += dt
        tipo = entrada.amostrar(nivel)
        if tipo:
            eventos.append(tipo)
    return eventos


def nova_entrada(nivel_ocioso=False):
    t = [0.0]
    return EntradaBotao(nivel_ocioso, relogio=lambda: t[0]), t


class TesteFiltroBotao(unittest.TestCase):
    def test_debouncer_so_muda_com_leituras_seguidas(self):
        d = Debouncer(False, n=3)
        self.assertFalse(d.alimentar(True))
        self.assertFalse(d.alimentar(True))
        self.assertTrue(d.alimentar(True))             # 3ª seguida
        self.assertTrue(d.alimentar(False))
        self.assertTrue(d.alimentar(True))             # leitura igual ao estado zera a contagem
        self.assertTrue(d.alimentar(False))
        self.assertTrue(d.alimentar(False))
        self.assertFalse(d.alimentar(False))

    def test_detectar_ocioso(self):
        self.assertEqual(detectar_ocioso([0] * 60), (False, 0.0))
        self.assertEqual(detectar_ocioso([1] * 59 + [0]), (True, 1 / 60))
        ocioso, minoria = detectar_ocioso([0, 1] * 30)  # linha flutuando
        self.assertAlmostEqual(minoria, 0.5)
        with self.assertRaises(ValueError):
            detectar_ocioso([])

    def test_clique_curto_limpo(self):
        e, t = nova_entrada(False)
        self.assertEqual(simular(e, [0] * 5 + [1] * 20 + [0] * 10, relogio=t), [CURTO])

    def test_repique_ao_apertar_e_ao_soltar_vira_um_evento_so(self):
        e, t = nova_entrada(False)
        niveis = [0] * 5 + [1, 0, 1, 0, 1] + [1] * 20 + [0, 1, 0, 1, 0] + [0] * 10
        self.assertEqual(simular(e, niveis, relogio=t), [CURTO])

    def test_pico_mais_curto_que_o_filtro_e_ignorado(self):
        e, t = nova_entrada(False)
        self.assertEqual(simular(e, [0] * 5 + [1] * 3 + [0] * 20, relogio=t), [])

    def test_clique_longo_com_falhas_no_meio_continua_um_aperto_so(self):
        e, t = nova_entrada(False)
        # 3,3 s apertado, com 3 quedas de 3 leituras (30 ms) no meio: antes isso quebrava o aperto
        niveis = [0] * 5 + [1] * 50 + [0] * 3 + [1] * 100 + [0] * 3 + [1] * 150 + [0] * 10
        self.assertEqual(simular(e, niveis, relogio=t), [MUITO_LONGO])

    def test_tempos_medio_e_longo(self):
        e, t = nova_entrada(False)
        self.assertEqual(simular(e, [0] * 5 + [1] * 150 + [0] * 10, relogio=t), [LONGO])      # 1,5 s
        e, t = nova_entrada(False)
        self.assertEqual(simular(e, [0] * 5 + [1] * 320 + [0] * 10, relogio=t), [MUITO_LONGO])  # 3,2 s
        e, t = nova_entrada(False)
        self.assertEqual(simular(e, [0] * 5 + [1] * 60 + [0] * 10, relogio=t), [CURTO])        # 0,6 s

    def test_polaridade_invertida_funciona_igual(self):
        e, t = nova_entrada(True)       # módulo parado em alto, desce ao apertar
        niveis = [1] * 5 + [0, 1, 0] + [0] * 150 + [1, 0, 1] + [1] * 10
        self.assertEqual(simular(e, niveis, relogio=t), [LONGO])

    def test_dois_cliques_seguidos(self):
        e, t = nova_entrada(False)
        niveis = [0] * 5 + [1] * 20 + [0] * 10 + [1] * 20 + [0] * 10
        self.assertEqual(simular(e, niveis, relogio=t), [CURTO, CURTO])

    def test_mostra_o_aperto_em_andamento_pra_tela(self):
        e, t = nova_entrada(False)
        simular(e, [0] * 5 + [1] * 150, relogio=t)
        self.assertEqual(e.aperto.tipo_se_soltar_agora(), LONGO)


class TesteBotoesGPIOComPinoFalso(unittest.TestCase):
    """O caminho real do gpiozero, com pinos simulados (MockFactory). Pula se não houver gpiozero."""

    def setUp(self):
        try:
            from gpiozero.pins.mock import MockFactory
        except ImportError:
            self.skipTest("gpiozero não instalado")
        import queue
        import botoes
        self.fila = queue.Queue()
        self.fab = MockFactory()
        self.botoes = None
        self.mod = botoes
        self.mensagens = []

    def tearDown(self):
        if self.botoes:
            self.botoes.fechar()

    def criar(self, polaridade, pull=None):
        self.botoes = self.mod.BotoesGPIO(self.fila, polaridade=polaridade, pull=pull,
                                          fabrica_pinos=self.fab, log=self.mensagens.append)
        return self.botoes

    def apertar(self, gpio, segundos, alto=True):
        import time
        pino = self.fab.pin(gpio)
        (pino.drive_high if alto else pino.drive_low)()
        time.sleep(segundos)
        (pino.drive_low if alto else pino.drive_high)()
        time.sleep(0.15)

    def eventos(self):
        saida = []
        while not self.fila.empty():
            saida.append(self.fila.get_nowait())
        return saida

    def test_modulo_que_sobe_ao_apertar_sem_pull_interno(self):
        for gpio in (17, 27, 22):
            self.fab.pin(gpio).drive_low()
        self.criar("alto")
        self.apertar(17, 0.2)
        self.apertar(22, 0.2)
        self.assertEqual(self.eventos(), [("B1", CURTO), ("B3", CURTO)])

    def test_modulo_que_desce_ao_apertar(self):
        for gpio in (17, 27, 22):
            self.fab.pin(gpio).drive_high()
        self.criar("baixo")
        self.apertar(27, 0.2, alto=False)
        self.assertEqual(self.eventos(), [("B2", CURTO)])

    def test_polaridade_auto_descobre_as_duas(self):
        self.fab.pin(17).drive_low()      # B1 sobe ao apertar
        self.fab.pin(27).drive_high()     # B2 desce ao apertar
        self.fab.pin(22).drive_low()
        b = self.criar("auto")
        self.assertEqual(b.info["B1"]["parado_em"], "baixo")
        self.assertEqual(b.info["B2"]["parado_em"], "alto")
        self.apertar(17, 0.2)
        self.apertar(27, 0.2, alto=False)
        self.assertEqual(self.eventos(), [("B1", CURTO), ("B2", CURTO)])

    def test_aperto_longo_pelo_gpio(self):
        for gpio in (17, 27, 22):
            self.fab.pin(gpio).drive_low()
        self.criar("alto")
        self.apertar(27, 1.1)
        self.assertEqual(self.eventos(), [("B2", LONGO)])

    def test_pull_interno_invalido_e_polaridade_invalida(self):
        with self.assertRaises(ValueError):
            self.criar("talvez")
        with self.assertRaises(ValueError):
            self.criar("auto", pull="meio")


class TesteDesligamento(unittest.TestCase):
    def test_comando_com_e_sem_root(self):
        self.assertEqual(montar_comando(root=False), ["sudo", "-n", "poweroff"])
        self.assertEqual(montar_comando(root=True), ["poweroff"])

    def test_so_o_muito_longo_desliga(self):
        chamadas = []
        d = Desligamento(executar=lambda c: chamadas.append(c) or True, root=False)
        self.assertFalse(d.botao(CURTO))
        self.assertFalse(d.botao(LONGO))
        self.assertEqual(chamadas, [])
        self.assertFalse(d.em_andamento)
        self.assertTrue(d.botao(MUITO_LONGO))
        self.assertEqual(chamadas, [["sudo", "-n", "poweroff"]])
        self.assertTrue(d.em_andamento)

    def test_nao_dispara_duas_vezes(self):
        chamadas = []
        d = Desligamento(executar=lambda c: chamadas.append(c) or True, root=False)
        d.botao(MUITO_LONGO)
        self.assertFalse(d.botao(MUITO_LONGO))
        self.assertEqual(len(chamadas), 1)

    def test_falha_mostra_aviso_por_3_s_e_deixa_tentar_de_novo(self):
        t = [100.0]
        resultados = iter([False, True])
        d = Desligamento(executar=lambda c: next(resultados), relogio=lambda: t[0], root=False)
        self.assertFalse(d.botao(MUITO_LONGO))
        self.assertFalse(d.em_andamento)
        self.assertEqual(d.texto(0), energia.TEXTO_FALHOU)
        t[0] += 3.1
        self.assertIsNone(d.texto(0))
        self.assertTrue(d.botao(MUITO_LONGO))
        self.assertEqual(d.texto(0), energia.TEXTO_DESLIGANDO)

    def test_texto_enquanto_segura(self):
        d = Desligamento(executar=lambda c: True, root=False)
        self.assertIsNone(d.texto(0.0))
        self.assertIsNone(d.texto(0.3))                # toque rápido não mostra nada
        self.assertEqual(d.texto(0.5), "SEGURE 3s: DESLIGAR")
        self.assertEqual(d.texto(1.2), "SEGURE 2s: DESLIGAR")
        self.assertEqual(d.texto(2.9), "SEGURE 1s: DESLIGAR")
        self.assertEqual(d.texto(3.0), energia.TEXTO_SOLTE)

    def test_clique_curto_mostra_a_dica_por_2_s(self):
        t = [0.0]
        d = Desligamento(executar=lambda c: True, relogio=lambda: t[0], root=False)
        d.botao(CURTO)
        self.assertEqual(d.texto(0), "SEGURE 3s: DESLIGAR")
        t[0] = 1.9
        self.assertEqual(d.texto(0), "SEGURE 3s: DESLIGAR")
        t[0] = 2.1
        self.assertIsNone(d.texto(0))
        d.botao(LONGO)                                 # longo solto antes dos 3 s: nada
        self.assertIsNone(d.texto(0))

    def test_rodar_comando_devolve_false_em_vez_de_quebrar(self):
        import sys
        self.assertTrue(rodar_comando([sys.executable, "-c", "pass"]))
        self.assertFalse(rodar_comando([sys.executable, "-c", "raise SystemExit(1)"]))
        self.assertFalse(rodar_comando(["comando-que-nao-existe-xyz"]))

    def test_teclado_tem_o_b3(self):
        self.assertEqual(BotoesTeclado.COMANDOS["3m"], ("B3", MUITO_LONGO))

    def test_textos_cabem_na_tela(self):
        try:
            import display
        except ImportError:
            self.skipTest("Pillow não instalado")
        fonte = display._fonte(9)
        for t in (energia.TEXTO_DESLIGANDO, energia.TEXTO_FALHOU, energia.TEXTO_SOLTE, "SEGURE 3s: DESLIGAR"):
            self.assertLessEqual(fonte.getlength(t), 128, t)


class TesteDiagnostico(unittest.TestCase):
    def test_resumo_separa_ruido_parado_de_repique(self):
        bordas = [(1.0, True), (2.0, False),                       # antes de liberar: ruído com o botão solto
                  (6.0, True), (6.004, False), (6.009, True), (6.3, False)]
        r = resumir(bordas, inicio_aperto_s=5.0)
        self.assertEqual(r["bordas_com_botao_solto"], 2)
        self.assertEqual(r["bordas_durante_apertos"], 4)
        self.assertEqual(r["repiques"], 2)
        self.assertEqual(r["menor_intervalo_ms"], 4.0)

    def test_resumo_sem_bordas(self):
        r = resumir([], 5.0)
        self.assertEqual(r["repiques"], 0)
        self.assertIsNone(r["menor_intervalo_ms"])


if __name__ == "__main__":
    unittest.main()
