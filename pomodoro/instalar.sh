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

sudo tee /etc/systemd/system/pomodoro.service >/dev/null <<EOF
[Unit]
Description=Pomodoro com display OLED e botoes (TCC)
After=multi-user.target postura.service

[Service]
Type=simple
User=$USUARIO
WorkingDirectory=$DIR
Environment=PYTHONUNBUFFERED=1
ExecStart="$PY" "$DIR/main.py"
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable pomodoro
sudo systemctl restart pomodoro

echo
echo "Pronto! O pomodoro já está rodando e vai iniciar sozinho no boot."
echo "  sudo journalctl -u pomodoro -f   -> log ao vivo (Ctrl+C sai)"
echo "  sudo systemctl restart pomodoro  -> reinicia"
