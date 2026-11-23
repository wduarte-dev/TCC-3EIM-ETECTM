"""
Driver mínimo do LCD de caracteres HD44780 (16x2) em modo 4 bits, por GPIO.

Por que um driver próprio em vez do RPLCD: o RPLCD em modo GPIO usa o RPi.GPIO, que
seria mais uma dependência compilada no venv; aqui uso o gpiozero (já instalado pros
botões, backend lgpio). O protocolo é curto (datasheet do HD44780U):

- RW fica FIXO no GND (só escrita): não dá pra ler o "busy flag", então espero o tempo
  de execução de cada comando (37 µs típico; clear/home 1,52 ms) com folga.
- O LCD lê os dados na DESCIDA do E (falling edge).
- Modo 4 bits: cada byte vai em dois pedaços (nibble alto, depois baixo) em D4..D7;
  D0..D3 ficam soltos (pull-up interno do controlador).
- Inicialização "por instrução" (Figura 24 do datasheet): esperar > 40 ms depois de
  ligar, mandar 0x3 três vezes (esperas de 4,1 ms e 100 µs) e então 0x2 (entra em 4
  bits). Funciona a partir de qualquer estado, inclusive lixo de boot nos pinos.
- Nível lógico: com o LCD em 5 V, a entrada alta mínima (VIH) é 2,2 V no datasheet
  (faixa 4,5–5,5 V), então os 3,3 V do GPIO bastam. Alguns clones pedem 0,7·VCC
  (3,5 V): se o display não responder de jeito nenhum, essa é uma suspeita.
"""
import time

# Comandos (datasheet)
_LIMPAR = 0x01
_MODO_ENTRADA = 0x06       # cursor anda pra direita, sem deslocar a tela
_TELA_LIGADA = 0x0C        # display on, cursor off, blink off
_TELA_DESLIGADA = 0x08
_FUNCAO_4BITS_2LINHAS = 0x28
_CGRAM = 0x40
_DDRAM = 0x80
_INICIO_LINHA = (0x00, 0x40)   # endereço da DDRAM no começo de cada linha (16x2)

_ESPERA_COMANDO_S = 100e-6     # 37 µs no datasheet; o sleep do Python já passa disso
_ESPERA_LIMPAR_S = 3e-3        # 1,52 ms no datasheet, com folga


class LCD4Bits:
    def __init__(self, rs, e, d4, d5, d6, d7, colunas=16, linhas=2):
        from gpiozero import DigitalOutputDevice
        # E primeiro e já em nível baixo: a descida que isso causa grava um nibble de
        # lixo, que a sequência de inicialização abaixo corrige.
        self._e = DigitalOutputDevice(e, initial_value=False)
        self._rs = DigitalOutputDevice(rs, initial_value=False)
        self._dados = [DigitalOutputDevice(p, initial_value=False) for p in (d4, d5, d6, d7)]
        self.colunas, self.linhas = colunas, linhas
        self._iniciar()

    # ------------------------------------------------------------ baixo nível --
    def _pulso(self):
        self._e.on()               # largura mínima 450 ns: a própria chamada já demora mais
        self._e.off()              # grava aqui (descida)
        time.sleep(_ESPERA_COMANDO_S)

    def _nibble(self, valor):
        for bit, pino in enumerate(self._dados):
            pino.value = (valor >> bit) & 1
        self._pulso()

    def _enviar(self, byte, rs):
        self._rs.value = rs
        self._nibble(byte >> 4)
        self._nibble(byte & 0x0F)

    def comando(self, byte):
        self._enviar(byte, 0)
        if byte in (_LIMPAR, 0x02):
            time.sleep(_ESPERA_LIMPAR_S)

    def dado(self, byte):
        self._enviar(byte, 1)

    def _iniciar(self):
        time.sleep(0.05)                       # > 40 ms depois de ligar
        self._rs.off()
        for espera in (4.5e-3, 4.5e-3, 150e-6):
            self._nibble(0x3)                  # "8 bits", 3 vezes
            time.sleep(espera)
        self._nibble(0x2)                      # agora em 4 bits
        for c in (_FUNCAO_4BITS_2LINHAS, _TELA_DESLIGADA, _LIMPAR, _MODO_ENTRADA, _TELA_LIGADA):
            self.comando(c)

    # ------------------------------------------------------------- alto nível --
    def limpar(self):
        self.comando(_LIMPAR)

    def ligar_tela(self, ligada=True):
        self.comando(_TELA_LIGADA if ligada else _TELA_DESLIGADA)

    def posicao(self, linha, coluna=0):
        self.comando(_DDRAM | (_INICIO_LINHA[linha] + coluna))

    def escrever(self, codigos):
        """Escreve bytes (códigos da ROM do LCD ou 0..7 = caracteres próprios)."""
        for c in codigos:
            self.dado(c)

    def criar_caractere(self, slot, linhas8):
        """Grava o desenho 5x8 (8 inteiros de 5 bits) no slot 0..7 da CGRAM."""
        self.comando(_CGRAM | ((slot & 7) << 3))
        for linha in linhas8:
            self.dado(linha & 0x1F)

    def fechar(self):
        for pino in [self._e, self._rs] + self._dados:
            pino.close()
