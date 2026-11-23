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


if __name__ == "__main__":
    unittest.main()
