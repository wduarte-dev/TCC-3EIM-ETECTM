"""
Testes das telas do LCD 16x2 (sem Pi, sem hardware). Rodar de dentro de pomodoro/:

    python -m unittest -v test_display_lcd
"""
import unittest
from unittest import mock

from pomodoro_logica import Pomodoro, CURTO, LONGO
import display_lcd as L
from postura_cliente import texto_curto
import energia
import recalibracao
import wifi

PRESET = [{"nome": "25/5", "foco": 25, "pausa": 5, "pausa_longa": 15}]
LONGO_NOME = [{"nome": "50/10/20", "foco": 50, "pausa": 10, "pausa_longa": 20}]


def tempo(t):
    return mock.patch("display_lcd.time.monotonic", return_value=t)


class FakeCGRAM:
    def __init__(self):
        self.gravados = []
        self.escritos = []

    def criar_caractere(self, slot, bits):
        self.gravados.append(slot)

    def posicao(self, linha, coluna=0):
        self.escritos.append(("pos", linha))

    def escrever(self, codigos):
        self.escritos.append(("txt", codigos))


class TestQuadro(unittest.TestCase):
    def checar(self, q):
        self.assertEqual(len(q.linhas), 2)
        for linha in q.linhas:
            self.assertEqual(len(linha), 16)
        self.assertLessEqual(len(q.glifos()), 8)

    def test_todos_os_textos_da_linha_de_baixo_cabem_sem_rolar(self):
        textos = [texto_curto(None)] + [texto_curto({"status": s, "texto": "Calibrando em 10s"}) for s in (
            "CORRETA", "ATENCAO", "ALERTA", "AGUARDANDO_CALIBRACAO", "CONTAGEM", "CALIBRANDO",
            "CALIBRACAO_FALHOU", "SEM_CAMERA", "SEM_USUARIO", "PAUSADO")]
        textos += ["POSTURA: DESCANSO", energia.TEXTO_DESLIGANDO, energia.TEXTO_FALHOU,
                   energia.TEXTO_SOLTE, energia.TEXTO_DICA, "SEGURE 1s: DESLIGAR", wifi.TEXTO_SSH,
                   "SOLTE: PAUSAR", "SOLTE: RETOMAR", "SEGURE 5s: PAUSAR", "SEGURE 5s: RETOMAR",
                   "SOLTE: WIFI CONECTAR", "WIFI CONECTAR", "SOLTE: RECAL POSTURA",
                   "SOLTE: CALIB POSTURA", "RECALIBRAR: POSTURA", "CALIBRAR: POSTURA"]
        for t in textos:
            self.assertLessEqual(len(L.compactar(t)), 16, t)

    def test_desligando_vira_desligado_na_tela_toda(self):
        q = L.desenhar(Pomodoro(PRESET), energia.TEXTO_DESLIGANDO)
        self.assertEqual(q.texto(), ["   DESLIGADO    "] * 2)

    def test_com_os_3_pontos_o_texto_cabe_em_13(self):
        for t in ("COMEÇANDO EM: 10s", "CALIBRANDO...", "CALIBRACAO FALHOU", "SEM USUARIO"):
            self.assertLessEqual(len(L.compactar(t, 13)), 13, t)

    def test_rodando_tem_fase_e_tempo_na_linha_1_e_postura_inteira_na_2(self):
        p = Pomodoro(PRESET)
        p.botao(LONGO)
        with tempo(100):
            q = L.desenhar(p, "POSTURA: ATENÇÃO", "ATENCAO")
        self.checar(q)
        self.assertEqual(q.texto(), ["FOCO 1/4   25:00", "POSTURA: ATENÇÃO"])

    def test_pausado_mostra_icone_antes_da_fase(self):
        p = Pomodoro(PRESET)
        p.botao(LONGO)
        p.botao(CURTO)
        with tempo(100):
            q = L.desenhar(p, "POSTURA: BOA")
        self.assertIs(q.linhas[0][0], L.ICONE_PAUSA)
        self.assertEqual(q.texto()[0], "#FOCO 1/4  25:00")

    def test_preset_aparece_de_tempos_em_tempos(self):
        p = Pomodoro(LONGO_NOME)
        p.botao(LONGO)
        with tempo(7.0):
            self.assertEqual(L.desenhar(p, "x").texto()[0], "50/10/20   50:00")

    def test_alerta_alterna_texto_e_blocos(self):
        p = Pomodoro(PRESET)
        with tempo(100.0):
            a = L.desenhar(p, "POSTURA: RUIM", "ALERTA").texto()[1]
        with tempo(100.6):
            b = L.desenhar(p, "POSTURA: RUIM", "ALERTA").texto()[1]
        self.assertIn("RUIM", a)
        self.assertEqual(b, L.BLOCO * 16)

    def test_figura_dos_pontos_ocupa_as_2_ultimas_colunas(self):
        p = Pomodoro(PRESET)
        with tempo(100):
            q = L.desenhar(p, "COMEÇANDO EM: 10s", "CONTAGEM", pontos=(True, False, True))
        self.checar(q)
        self.assertEqual(q.linhas[1][-2:], L.figura_pontos((True, False, True)))
        self.assertEqual(q.texto()[1][:13], "COMEÇA EM 10s")

    def test_piscando_enche_a_tela(self):
        q = L.desenhar(Pomodoro(PRESET), "x", piscando=True)
        self.assertEqual(q.texto(), [L.BLOCO * 16] * 2)

    def test_mais_de_8_desenhos_vira_letra_sem_acento(self):
        q = L._fechar_quadro([L._celulas("ÇÃÕÁÀÂÉÊ"), L._celulas("ÍÓÔÚ")])
        self.assertLessEqual(len(q.glifos()), 8)
        self.assertEqual(q.texto()[1][:4], "IOOU")

    def test_barra_invertida_e_til_nao_viram_iene_e_seta(self):
        cel = L._celulas("a\\b~")
        self.assertIsInstance(cel[1], L.Glifo)
        self.assertIsInstance(cel[3], L.Glifo)

    def test_wifi(self):
        with tempo(100):
            for q in (L.desenhar_wifi_espera("DIHMO", "admin1234", 3),
                      L.desenhar_wifi_resultado(True, "DIHMO"),
                      L.desenhar_wifi_resultado(False, "UMA REDE COM NOME BEM COMPRIDO")):
                self.checar(q)

    def test_wifi_espera_mostra_rede_e_senha_juntas_no_comeco(self):
        L._espera.update(inicio=None, ultima=0.0)
        textos = []
        for k in range(0, 56):                       # 14 s a 4 quadros/s, como no laço do main
            with tempo(500.0 + k * 0.25):
                textos.append(L.desenhar_wifi_espera("DIHMO", "admin1234", 1).texto())
        self.assertEqual(textos[0], ["REDE: DIHMO     ", "SENHA: admin1234"])
        self.assertEqual(textos[int(5.5 / 0.25)], textos[0])          # ainda na 1ª página aos 5,5 s
        self.assertTrue(textos[int(6.5 / 0.25)][0].startswith("#"))   # depois vem o CONECTANDO...
        self.assertTrue(any("CANCELAR" in t[1] for t in textos))

    def test_rolagem_vai_do_comeco_ao_fim(self):
        texto = "ABCDEFGHIJKLMNOPQRST"
        self.assertEqual(L.rolar(texto, 16, t=0.0), texto[:16])
        self.assertEqual(L.rolar(texto, 16, t=1.5 + 4 / 3.0 + 0.1), texto[4:])


class TestBackend(unittest.TestCase):
    def test_so_grava_cgram_e_linha_quando_muda(self):
        tela = L.DisplayLCD.__new__(L.DisplayLCD)
        tela._lcd = FakeCGRAM()
        tela._cgram = [None] * 8
        tela._ultimas = [None] * 2
        p = Pomodoro(PRESET)
        p.botao(LONGO)
        p.botao(CURTO)
        with tempo(100):
            q = L.desenhar(p, "POSTURA: ATENÇÃO")
        tela.mostrar(q)
        self.assertEqual(len(tela._lcd.gravados), 3)          # pausa, Ç, Ã
        n = len(tela._lcd.escritos)
        tela.mostrar(q)                                       # igual: não escreve nada
        self.assertEqual(len(tela._lcd.gravados), 3)
        self.assertEqual(len(tela._lcd.escritos), n)


class PinoFalso:
    def __init__(self, pino, initial_value=False):
        self.pino, self.value = pino, int(initial_value)

    def on(self):
        self.value = 1

    def off(self):
        self.value = 0

    def close(self):
        pass


class TestDriver(unittest.TestCase):
    """Decodifica os nibbles que o driver manda (na descida do E) e confere o protocolo."""

    def setUp(self):
        import sys
        import types
        import lcd_hd44780 as H
        self.H = H
        self.eventos = []
        fake = types.ModuleType("gpiozero")
        fake.DigitalOutputDevice = PinoFalso
        self._antigo = sys.modules.get("gpiozero")
        sys.modules["gpiozero"] = fake
        self._sleep = H.time.sleep
        H.time.sleep = lambda s: None
        eventos = self.eventos
        self._pulso = H.LCD4Bits._pulso

        def pulso(lcd):
            nibble = sum(int(p.value) << i for i, p in enumerate(lcd._dados))
            eventos.append((int(lcd._rs.value), nibble))
        H.LCD4Bits._pulso = pulso

    def tearDown(self):
        import sys
        self.H.time.sleep = self._sleep
        self.H.LCD4Bits._pulso = self._pulso
        if self._antigo is None:
            sys.modules.pop("gpiozero", None)
        else:
            sys.modules["gpiozero"] = self._antigo

    def bytes_(self, eventos):
        return [(eventos[i][0], (eventos[i][1] << 4) | eventos[i + 1][1]) for i in range(0, len(eventos), 2)]

    def test_inicializacao_segue_o_datasheet(self):
        self.H.LCD4Bits(5, 6, 13, 19, 26, 16)
        self.assertEqual([n for _, n in self.eventos[:4]], [0x3, 0x3, 0x3, 0x2])   # reset ×3, depois 4 bits
        comandos = [b for rs, b in self.bytes_(self.eventos[4:])]
        self.assertEqual(comandos, [0x28, 0x08, 0x01, 0x06, 0x0C])   # 2 linhas, apaga, limpa, entrada, liga

    def test_posicao_e_texto(self):
        lcd = self.H.LCD4Bits(5, 6, 13, 19, 26, 16)
        self.eventos.clear()
        lcd.posicao(1, 0)
        lcd.escrever(b"Oi")
        self.assertEqual(self.bytes_(self.eventos), [(0, 0xC0), (1, 0x4F), (1, 0x69)])   # linha 2 = 0x40

    def test_cgram(self):
        lcd = self.H.LCD4Bits(5, 6, 13, 19, 26, 16)
        self.eventos.clear()
        lcd.criar_caractere(2, (1, 2, 3, 4, 5, 6, 7, 8))
        dados = self.bytes_(self.eventos)
        self.assertEqual(dados[0], (0, 0x40 | (2 << 3)))
        self.assertEqual([b for _, b in dados[1:]], [1, 2, 3, 4, 5, 6, 7, 8])


if __name__ == "__main__":
    unittest.main()
