"""
Testes (sem Pi, sem hardware). Rodar de dentro da pasta pomodoro/:

    python -m unittest -v
"""
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
from botoes import classificar, ClassificadorAperto

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


if __name__ == "__main__":
    unittest.main()
