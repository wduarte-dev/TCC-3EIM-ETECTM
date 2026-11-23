#!/usr/bin/env bash
# Instala o pomodoro (display + botões) como serviço do systemd.
# Rode como usuário normal (SEM sudo na frente), de dentro da pasta pomodoro:
#     bash instalar.sh
# Se o Python certo não for achado sozinho, passe o caminho dele:
#     bash instalar.sh /caminho/do/python3
set -e

DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
USUARIO="$(id -un)"

if [ "$USUARIO" = "root" ]; then
    echo "Rode sem sudo:  bash instalar.sh   (o script pede a senha quando precisar)"
    exit 1
fi

testar_python() {
    "$1" -c "import PIL, luma.oled, gpiozero" 2>/dev/null
}

PY="${1:-}"
if [ -z "$PY" ]; then
    for candidato in "$HOME/venv-tcc/bin/python" python3.11 python3; do
        caminho="$(command -v "$candidato" 2>/dev/null || true)"
        if [ -n "$caminho" ] && testar_python "$caminho"; then
            PY="$caminho"
            break
        fi
    done
fi

if [ -z "$PY" ] || ! testar_python "$PY"; then
    echo "Não achei um Python com pillow + luma.oled + gpiozero."
    echo "Ative o venv e rode:  pip install -r req.txt"
    echo "Depois:  bash instalar.sh /caminho/do/venv/bin/python"
    exit 1
fi
echo "Python: $PY"

# Fonte da tela (acentos e tamanhos aprovados dependem dela)
if [ ! -f /usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf ]; then
    echo "AVISO: fonte DejaVu Sans Bold não encontrada: sem ela os acentos somem da tela."
    echo "       Instale com:  sudo apt install fonts-dejavu-core"
fi

sudo tee /etc/systemd/system/pomodoro.service >/dev/null <<EOF
[Unit]
Description=Pomodoro com display (LCD 16x2 ou OLED) e botoes (TCC)
After=multi-user.target postura.service

[Service]
Type=simple
User=$USUARIO
WorkingDirectory=$DIR
Environment=PYTHONUNBUFFERED=1
ExecStartPre=-/bin/bash "$DIR/../atualizar_codigo.sh"
ExecStart="$PY" "$DIR/main.py"
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

# Comando `pomodoro` (presets: adicionar/listar/remover)
sudo tee /usr/local/bin/pomodoro >/dev/null <<EOF
#!/usr/bin/env bash
exec "$PY" "$DIR/pomodoro_ctl.py" "\$@"
EOF
sudo chmod +x /usr/local/bin/pomodoro

# Comando `wifi` (escolhe a rede: wifi --ssid X --senha Y)
sudo tee /usr/local/bin/wifi >/dev/null <<EOF
#!/usr/bin/env bash
exec "$PY" "$DIR/wifi_ctl.py" "\$@"
EOF
sudo chmod +x /usr/local/bin/wifi

# Wi-Fi (T7): perfil do projeto no NetworkManager com a rede configurada (padrão DIHMO).
# Prioridade de autoconnect -10: abaixo das redes que você já usa pra SSH.
if command -v nmcli >/dev/null 2>&1; then
    if (cd "$DIR" && "$PY" -c "import sys, wifi; s, p, _ = wifi.carregar(); sys.exit(0 if wifi.aplicar_perfil(s, p) else 1)"); then
        echo "Perfil Wi-Fi 'tcc-wifi' pronto no NetworkManager."
    else
        echo "AVISO: não consegui criar o perfil Wi-Fi 'tcc-wifi' (o B1 tenta de novo ao conectar)."
    fi
    echo "Permissões do NetworkManager pro usuário $USUARIO (o B1 precisa de network-control = yes;"
    echo "se vier 'auth' ou 'no', o B1 usa 'sudo -n nmcli', que exige sudo sem senha):"
    nmcli general permissions 2>/dev/null | grep -E "network-control|settings.modify.system" || true
else
    echo "AVISO: nmcli não encontrado; o B1 'WIFI CONECTAR' vai mostrar WIFI FALHOU."
fi

sudo systemctl daemon-reload
sudo systemctl enable pomodoro
sudo systemctl restart pomodoro

echo
echo "Pronto! O pomodoro já está rodando e vai iniciar sozinho no boot."
echo "  sudo journalctl -u pomodoro -f   -> log ao vivo (Ctrl+C sai)"
echo "  sudo systemctl restart pomodoro  -> reinicia"
echo "  pomodoro listar                  -> presets (pomodoro adicionar --preset 50/10/20)"
echo "  wifi                             -> rede Wi-Fi configurada (wifi --ssid X --senha Y troca)"
