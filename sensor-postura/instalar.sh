#!/usr/bin/env bash
# Instala o monitor de postura como serviço do systemd + o comando `postura`.
# Rode como usuário normal (SEM sudo na frente), de dentro da pasta sensor-postura:
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

# --- 1. Acha o Python que tem as bibliotecas (cv2 + tflite) ---
testar_python() {
    "$1" - <<'EOF' 2>/dev/null
import cv2, numpy
try:
    import tflite_runtime.interpreter
except ImportError:
    try:
        import ai_edge_litert.interpreter
    except ImportError:
        import tensorflow
EOF
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
    echo "Não achei um Python com cv2 + tflite instalados."
    echo "Descubra qual Python roda o main-otimizado.py e passe ele:  bash instalar.sh /caminho/do/python"
    exit 1
fi
echo "Python: $PY"

if [ ! -f "$DIR/movenet_lightning.tflite" ]; then
    echo "Modelo movenet_lightning.tflite não está em $DIR"
    exit 1
fi

mkdir -p "$DIR/videos" "$DIR/logs"

# --- 2. Serviço do systemd ---
sudo tee /etc/systemd/system/postura.service >/dev/null <<EOF
[Unit]
Description=Monitoramento de postura (TCC)
After=multi-user.target

[Service]
Type=simple
User=$USUARIO
WorkingDirectory=$DIR
Environment=PYTHONUNBUFFERED=1
ExecStart="$PY" "$DIR/postura_servico.py"
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

# --- 3. Comando `postura` ---
sudo tee /usr/local/bin/postura >/dev/null <<EOF
#!/usr/bin/env bash
exec "$PY" "$DIR/postura_ctl.py" "\$@"
EOF
sudo chmod +x /usr/local/bin/postura

# --- 4. Liga o serviço agora e em todo boot ---
sudo systemctl daemon-reload
sudo systemctl enable postura
sudo systemctl restart postura

echo
echo "Pronto! O serviço já está rodando e vai iniciar sozinho no boot."
echo "  postura status     -> o que está rodando"
echo "  postura log        -> acompanhar ao vivo (Ctrl+C sai)"
echo "  postura ajuda      -> todos os comandos"
