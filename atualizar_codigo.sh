#!/usr/bin/env bash
# Atualiza o código do repo (git pull origin main) quando um serviço do TCC inicia.
# Chamado pelo systemd em ExecStartPre= (pomodoro.service e postura.service).
# NUNCA atrapalha a subida: qualquer falha (sem internet, conflito, git ausente) só vira
# uma linha no journal e o serviço sobe com o código que já está no Pi.
#
# Pular a atualização: criar o arquivo  ~/.tcc-sem-atualizar   (rm pra voltar)
DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
cd "$DIR" || exit 0

[ -e "$HOME/.tcc-sem-atualizar" ] && { echo "[atualizar] desligado (~/.tcc-sem-atualizar)"; exit 0; }
command -v git >/dev/null || { echo "[atualizar] git não instalado"; exit 0; }

# Os dois serviços sobem juntos: um trava, o outro espera e vê que já está atualizado.
exec 9>"/tmp/tcc-atualizar.lock"
flock -w 60 9 || exit 0

antes="$(git rev-parse --short HEAD 2>/dev/null)"
# Sem terminal pra pedir senha; sem rede = desiste em 20 s; --ff-only = nunca mistura nem sobrescreve.
if GIT_TERMINAL_PROMPT=0 timeout 20 git pull --ff-only -q origin main 2>&1; then
    depois="$(git rev-parse --short HEAD)"
    if [ "$antes" = "$depois" ]; then
        echo "[atualizar] já estava em $depois"
    else
        echo "[atualizar] $antes -> $depois"
    fi
else
    echo "[atualizar] não atualizou (sem rede, alterações locais ou divergência); segue em $antes"
fi
exit 0
