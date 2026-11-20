"""
Presets do pomodoro (T6): um pré-configurado (25/5 com pausa longa de 15) + os do usuário.

Formato do usuário: MM/MM (foco/pausa, em minutos) ou MM/MM/MM (o 3º é a pausa longa).
Sem o 3º, o preset não tem pausa longa: foco e pausa se alternam sem fim.

Os presets do usuário ficam num JSON FORA do repositório (padrão
~/.config/pomodoro/presets.json; outro caminho pela variável POMODORO_PRESETS), pra um
`git pull` não apagar. Lógica sem GPIO nem tela: o comando `pomodoro` (pomodoro_ctl.py)
e o main.py usam este módulo.
"""
import json
import os

from pomodoro_config import PRESET_PADRAO, CAMINHO_PRESETS, MINUTOS_MIN, MINUTOS_MAX


class PresetInvalido(ValueError):
    """Mensagem pronta pra mostrar ao usuário."""


def interpretar(texto):
    """'50/10' ou '50/10/20' → dict do preset. Erro claro (PresetInvalido) se não valer."""
    partes = str(texto).strip().split("/")
    if len(partes) not in (2, 3):
        raise PresetInvalido(f"'{texto}': use FOCO/PAUSA ou FOCO/PAUSA/PAUSA_LONGA, em minutos (ex.: 50/10 ou 50/10/20)")
    numeros = []
    for parte in partes:
        if not parte.strip().isdigit():
            raise PresetInvalido(f"'{texto}': '{parte}' não é um número inteiro de minutos")
        n = int(parte)
        if not MINUTOS_MIN <= n <= MINUTOS_MAX:
            raise PresetInvalido(f"'{texto}': {n} min fora da faixa ({MINUTOS_MIN} a {MINUTOS_MAX} min)")
        numeros.append(n)
    foco, pausa = numeros[0], numeros[1]
    longa = numeros[2] if len(numeros) == 3 else None
    if longa is not None and longa < pausa:
        raise PresetInvalido(f"'{texto}': a pausa longa ({longa}) não pode ser menor que a pausa ({pausa})")
    nome = "/".join(str(n) for n in numeros)
    return {"nome": nome, "foco": foco, "pausa": pausa, "pausa_longa": longa}


def _mesmo(a, b):
    return a["nome"] == b["nome"] or (a["foco"], a["pausa"], a["pausa_longa"]) == (b["foco"], b["pausa"], b["pausa_longa"])


def carregar_usuario(caminho=CAMINHO_PRESETS):
    """Presets do usuário (lista). Arquivo ausente = nenhum. Linha estragada é ignorada."""
    try:
        with open(caminho, encoding="utf-8") as f:
            dados = json.load(f)
    except (OSError, ValueError):
        return []
    lista = []
    for item in dados.get("presets", []) if isinstance(dados, dict) else []:
        try:
            preset = interpretar(item)
        except PresetInvalido:
            continue
        if not _mesmo(preset, PRESET_PADRAO) and not any(_mesmo(preset, p) for p in lista):
            lista.append(preset)
    return lista


def todos(caminho=CAMINHO_PRESETS):
    """Pré-configurado primeiro, depois os do usuário na ordem em que foram adicionados."""
    return [dict(PRESET_PADRAO)] + carregar_usuario(caminho)


def _salvar(lista, caminho):
    pasta = os.path.dirname(caminho)
    if pasta:
        os.makedirs(pasta, exist_ok=True)
    temporario = caminho + ".tmp"
    with open(temporario, "w", encoding="utf-8") as f:
        json.dump({"presets": [p["nome"] for p in lista]}, f, indent=2)
    os.replace(temporario, caminho)     # troca atômica: nunca fica meio escrito


def adicionar(texto, caminho=CAMINHO_PRESETS):
    """Valida e grava. Devolve o preset. Erro (PresetInvalido) = nada gravado."""
    preset = interpretar(texto)
    if _mesmo(preset, PRESET_PADRAO):
        raise PresetInvalido(f"'{preset['nome']}' já existe: é o pré-configurado "
                             f"({PRESET_PADRAO['foco']}/{PRESET_PADRAO['pausa']} com pausa longa de "
                             f"{PRESET_PADRAO['pausa_longa']})")
    lista = carregar_usuario(caminho)
    if any(_mesmo(preset, p) for p in lista):
        raise PresetInvalido(f"'{preset['nome']}' já existe")
    lista.append(preset)
    _salvar(lista, caminho)
    return preset


def remover(texto, caminho=CAMINHO_PRESETS):
    """Remove um preset do usuário. O pré-configurado não sai."""
    preset = interpretar(texto)
    if preset["nome"] == PRESET_PADRAO["nome"] or _mesmo(preset, PRESET_PADRAO):
        raise PresetInvalido(f"o pré-configurado {PRESET_PADRAO['nome']} não pode ser removido")
    lista = carregar_usuario(caminho)
    restantes = [p for p in lista if p["nome"] != preset["nome"]]
    if len(restantes) == len(lista):
        raise PresetInvalido(f"'{preset['nome']}' não está na lista (veja com: pomodoro listar)")
    _salvar(restantes, caminho)
    return preset


def assinatura(caminho=CAMINHO_PRESETS):
    """Muda quando o arquivo muda (o main.py usa pra recarregar sem reiniciar)."""
    try:
        estado = os.stat(caminho)
        return (estado.st_mtime_ns, estado.st_size)
    except OSError:
        return None
