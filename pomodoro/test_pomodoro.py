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
from recalibracao import MenuB1, POSTURA, VOZ, ACAO_RECALIBRAR
from voz_cliente import RecalibradorVoz

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

    def test_muito_longo_na_selecao_nao_faz_nada(self):
        p = novo()
        self.assertEqual(p.botao(MUITO_LONGO), [])
        self.assertEqual(p.estado, SELECAO)

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
    def test_longo_pausa_congela_e_longo_retoma(self):
        p = novo()
        p.botao(LONGO)
        p.tick(30)
        self.assertEqual(p.botao(LONGO), [EV_PAUSOU])
        self.assertEqual(p.estado, PAUSADO)
        p.tick(1000)                                  # tempo passa, timer não
        self.assertEqual(p.restante_s, 90)
        self.assertEqual(p.botao(LONGO), [EV_RETOMOU])
        self.assertEqual(p.estado, FOCO)
        p.tick(10)
        self.assertEqual(p.restante_s, 80)

    def test_pausar_e_retomar_no_descanso_tambem(self):
        p = novo()
        p.botao(LONGO)
        p.tick(120)                                   # entrou na PAUSA
        p.botao(LONGO)
        self.assertEqual(p.estado, PAUSADO)
        self.assertEqual(p.fase_atual, PAUSA)
        p.botao(LONGO)
        self.assertEqual(p.estado, PAUSA)

    def test_curto_fora_da_selecao_e_ignorado(self):
        p = novo()
        p.botao(LONGO)
        self.assertEqual(p.botao(CURTO), [])
        self.assertEqual(p.estado, FOCO)
        p.botao(LONGO)
        self.assertEqual(p.botao(CURTO), [])
        self.assertEqual(p.estado, PAUSADO)

    def test_muito_longo_reinicia_rodando_e_pausado(self):
        for pausar_antes in (False, True):
            p = novo()
            p.botao(CURTO)                            # preset B
            p.botao(LONGO)
            p.tick(50)
            if pausar_antes:
                p.botao(LONGO)
            self.assertEqual(p.botao(MUITO_LONGO), [EV_REINICIOU])
            self.assertEqual(p.estado, SELECAO)
            self.assertEqual(p.focos_concluidos, 0)
            self.assertEqual(p.preset["nome"], "B")   # mantém o preset escolhido
            p.botao(LONGO)
            self.assertEqual(p.restante_s, 5 * 60)    # recomeça do zero

    def test_rotulos_da_dica_enquanto_segura(self):
        p = novo()
        self.assertEqual(p.rotulo_aperto(LONGO), "INICIAR")
        self.assertEqual(p.rotulo_aperto(MUITO_LONGO), "")
        p.botao(LONGO)
        self.assertEqual(p.rotulo_aperto(LONGO), "PAUSAR")
        self.assertEqual(p.rotulo_aperto(MUITO_LONGO), "REINICIAR")
        p.botao(LONGO)
        self.assertEqual(p.rotulo_aperto(LONGO), "RETOMAR")


class TesteMenuB1(unittest.TestCase):
    def test_curto_abre_em_postura_e_alterna_com_voz(self):
        m = MenuB1(timeout_s=5)
        self.assertFalse(m.aberto)
        self.assertIsNone(m.botao(CURTO))
        self.assertEqual(m.opcao, POSTURA)
        m.botao(CURTO)
        self.assertEqual(m.opcao, VOZ)
        m.botao(CURTO)
        self.assertEqual(m.opcao, POSTURA)

    def test_longo_executa_a_opcao_mostrada_e_fecha_o_menu(self):
        for cliques, esperada in ((1, POSTURA), (2, VOZ)):
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
        nada = {POSTURA: False, VOZ: False}
        self.assertEqual(m.texto(calibrado=nada), "CALIBRAR: POSTURA")
        self.assertEqual(m.texto(True, nada), "SOLTE: CALIB POSTURA")
        self.assertEqual(m.texto(calibrado={POSTURA: True, VOZ: False}), "RECALIBRAR: POSTURA")
        m.botao(CURTO)                                   # VOZ, só ela sem baseline
        self.assertEqual(m.texto(calibrado={POSTURA: True, VOZ: False}), "CALIBRAR: VOZ")
        self.assertEqual(m.texto(calibrado={POSTURA: False, VOZ: True}), "RECALIBRAR: VOZ")

    def test_textos(self):
        m = MenuB1()
        m.botao(CURTO)
        self.assertEqual(m.texto(), "RECALIBRAR: POSTURA")
        self.assertEqual(m.texto(segurando_longo=True), "SOLTE: RECAL POSTURA")
        m.botao(CURTO)
        self.assertEqual(m.texto(), "RECALIBRAR: VOZ")


class FakeSensorVoz:
    """Faz o papel do sensor-voz/main.py: chama o ao_progredir como o real."""
    def __init__(self, erro=None):
        self.erro = erro
        self.chamadas = []

    def calibrar_baseline(self, esperar_enter=True, ao_progredir=None):
        self.chamadas.append(esperar_enter)
        for i in (1, 2):
            ao_progredir("gravando", i, 2)
            ao_progredir("analisando", i, 2)
        if self.erro:
            raise self.erro


class TesteRecalibradorVoz(unittest.TestCase):
    def _rodar(self, sensor=None, carregar=None):
        mensagens = []
        r = RecalibradorVoz(carregar=carregar or (lambda: sensor), preparo_s=0, final_s=0,
                            dormir=lambda s: mensagens.append(r.mensagem))
        with contextlib.redirect_stderr(io.StringIO()):   # esconde os tracebacks esperados
            t = r.iniciar()
            t.join(timeout=5)
        return r, mensagens

    def test_sequencia_de_mensagens_padrao(self):
        sensor = FakeSensorVoz()
        r, vistas = self._rodar(sensor)
        self.assertEqual(vistas, ["VOZ 1/2: PREPARE-SE", "VOZ 2/2: PREPARE-SE", "VOZ CALIBRADA"])
        self.assertEqual(sensor.chamadas, [False])      # sem esperar ENTER (não há teclado)
        self.assertFalse(r.ocupado)
        self.assertIsNone(r.mensagem)

    def test_falha_mostra_mensagem_e_libera(self):
        r, vistas = self._rodar(FakeSensorVoz(erro=RuntimeError("sem voz")))
        self.assertEqual(vistas[-1], "VOZ FALHOU")
        self.assertFalse(r.ocupado)

    def test_sem_biblioteca_ou_praat(self):
        for erro in (ImportError("sounddevice"), FileNotFoundError("praat"), OSError("PortAudio library not found")):
            r, vistas = self._rodar(FakeSensorVoz(erro=erro))
            self.assertEqual(vistas[-1], "SEM MIC/PRAAT")
        def carregar():
            raise ImportError("sounddevice")
        r, vistas = self._rodar(carregar=carregar)
        self.assertEqual(vistas[-1], "SEM MIC/PRAAT")

    def test_segundo_pedido_enquanto_roda_e_ignorado(self):
        liberar = threading.Event()
        class Lento:
            def calibrar_baseline(self, esperar_enter=True, ao_progredir=None):
                liberar.wait(5)
        r = RecalibradorVoz(carregar=lambda: Lento(), preparo_s=0, final_s=0, dormir=lambda s: None)
        t = r.iniciar()
        self.assertTrue(r.ocupado)
        self.assertIsNone(r.iniciar())
        liberar.set()
        t.join(timeout=5)
        self.assertFalse(r.ocupado)


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
        imagens = [self.display.desenhar(p, "POSTURA OK")]                         # seleção
        imagens.append(self.display.desenhar(p, "X", segurando_tipo=LONGO))
        p.botao(LONGO)
        imagens.append(self.display.desenhar(p, "POSTURA OK", "CORRETA"))          # foco
        imagens.append(self.display.desenhar(p, "ALERTA: POSTURA!", "ALERTA"))     # alerta
        imagens.append(self.display.desenhar(p, "POSTURA OK", piscando=True))      # piscando
        p.botao(LONGO)
        imagens.append(self.display.desenhar(p, "POSTURA OK"))                     # pausado
        for img in imagens:
            self.assertEqual(img.size, (128, 64))
            self.assertEqual(img.mode, "1")
            self.assertGreater(len(set(img.tobytes())), 1)                          # não é tela em branco

    def test_textos_do_b1_e_da_voz_cabem_na_tela(self):
        from PIL import ImageFont
        fonte = self.display._fonte(9)
        textos = ["RECALIBRAR: POSTURA", "SOLTE: RECAL POSTURA", "CALIBRAR: POSTURA", "SOLTE: CALIB POSTURA", "RECALIBRAR: VOZ", "SOLTE: RECAL VOZ",
                  "VOZ 1/2: PREPARE-SE", "VOZ 1/2: FALE AAAA", "VOZ 2/2: ANALISANDO",
                  "VOZ CALIBRADA", "VOZ FALHOU", "SEM MIC/PRAAT", "VOZ: INICIANDO"]
        for t in textos:
            self.assertLessEqual(fonte.getlength(t), 128, t)

    def test_piscar_inverte_a_imagem(self):
        p = novo()
        normal = self.display.desenhar(p, "OK")
        invertida = self.display.desenhar(p, "OK", piscando=True)
        self.assertNotEqual(normal.tobytes(), invertida.tobytes())


class TestePostura(unittest.TestCase):
    def test_texto_curto(self):
        from postura_cliente import texto_curto
        self.assertEqual(texto_curto(None), "POSTURA OFFLINE")
        self.assertEqual(texto_curto({"status": "CORRETA"}), "POSTURA OK")
        self.assertEqual(texto_curto({"status": "ALERTA"}), "ALERTA: POSTURA!")
        self.assertEqual(texto_curto({"status": "AGUARDANDO_CALIBRACAO"}), "APERTE B1: CALIBRAR")
        self.assertEqual(
            texto_curto({"status": "CONTAGEM", "texto": "Fique na postura CORRETA. Calibrando em 7s..."}),
            "AJEITE-SE! 7s")
        for status in ("CORRETA", "ATENCAO", "ALERTA", "AGUARDANDO_CALIBRACAO", "CONTAGEM",
                       "CALIBRANDO", "CALIBRACAO_FALHOU", "SEM_CAMERA", "SEM_USUARIO", "INICIANDO"):
            self.assertLessEqual(len(texto_curto({"status": status, "texto": "em 3s"})), 21, status)

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
