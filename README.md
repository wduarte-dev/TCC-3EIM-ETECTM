# TCC-3EIM-ETECTM

TCC de Técnico em Eletrônica na Escola Técnica Estadual Takashi Morita (3º EIM).

**Sistema de monitoramento de home office** num Raspberry Pi 3B, sem tela, teclado nem mouse:
o usuário vê tudo num display OLED 128x64 e usa 3 botões.

| Pasta | O que é | Estado |
|---|---|---|
| [`sensor-postura/`](sensor-postura/) | Postura pela webcam (MoveNet): serviço do systemd + comando `postura` | Em uso |
| [`pomodoro/`](pomodoro/) | Timer pomodoro no OLED, 3 botões (B1 menu postura/Wi-Fi, B2 pomodoro, B3 desligar) + comandos `pomodoro` e `wifi` | Em uso |
| [`registro/`](registro/) | Logs do Pi: saúde (serviço `tcc-saude`, desde o boot), rotação de 7 dias e versão do código | Novo, não testado no Pi |
| [`coleta/`](coleta/) | Programa de coleta do estudo de validação dos limiares (~30 pessoas, roda no notebook) | Pronto, não testado no Windows |
| [`sensor-voz/`](sensor-voz/) | Fadiga vocal (jitter/shimmer/HNR via Praat) | **Fora do escopo** desde 19/11/2026 |

Cada pasta tem o seu README com instalação, uso, testes e limitações.

**Ambiente do Pi:** Raspberry Pi OS 64-bit, Python 3.11 compilado com venv em `~/venv-tcc`,
acesso só por SSH. O código também roda no Windows/notebook pra desenvolvimento (sem o hardware).
