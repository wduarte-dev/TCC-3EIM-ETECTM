#!/usr/bin/env bash
# Instala o LOG DE SAÚDE do Pi como serviço do systemd (tcc-saude), ligado desde o boot.
# Rode como usuário normal (SEM sudo na frente), de dentro da pasta registro:
#     bash instalar.sh
# Só usa a biblioteca padrão do Python: roda com o python3 do sistema (não precisa do venv).
set -e

DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
USUARIO="$(id -un)"

if [ "$USUARIO" = "root" ]; then
    echo "Rode sem sudo:  bash instalar.sh   (o script pede a senha quando precisar)"
    exit 1
fi

PY="${1:-}"
if [ -z "$PY" ]; then
    if [ -x /usr/bin/python3 ]; then PY=/usr/bin/python3; else PY="$(command -v python3)"; fi
fi
echo "Python: $PY"

if ! command -v vcgencmd >/dev/null 2>&1; then
    echo "AVISO: vcgencmd não encontrado; a coluna throttled vai ficar vazia."
fi

mkdir -p "$HOME/tcc-logs"
echo "Teste de uma amostra:"
(cd "$DIR" && "$PY" saude.py --uma)

sudo tee /etc/systemd/system/tcc-saude.service >/dev/null <<EOF
[Unit]
Description=Log de saude do Pi (TCC): get_throttled, temperatura, carga, RAM, uptime
After=local-fs.target

[Service]
Type=simple
User=$USUARIO
WorkingDirectory=$DIR
Environment=PYTHONUNBUFFERED=1
ExecStart="$PY" "$DIR/saude.py"
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable tcc-saude
sudo systemctl restart tcc-saude

echo
echo "Pronto! O log de saúde já está rodando e vai iniciar sozinho no boot."
echo "  tail -f ~/tcc-logs/saude_\$(date +%F).csv      -> ver as amostras chegando"
echo "  sudo journalctl -u tcc-saude -n 20             -> mensagens do serviço"
echo "  Arquivos com mais de 7 dias são apagados; pra guardar um período, copie antes."
