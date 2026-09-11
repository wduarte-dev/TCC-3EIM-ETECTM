from analise_postura import (
    calcular_meio_ombros,
    calcular_posicao_cabeca
)


def adicionar_dado(dados, nariz, ombro_esq, ombro_dir):

    meio_ombros = calcular_meio_ombros(
        ombro_esq,
        ombro_dir
    )

    posicao_cabeca = calcular_posicao_cabeca(
        nariz,
        meio_ombros
    )

    dados.append(posicao_cabeca)


def calcular_referencia(dados):

    soma_x = sum(dado[0] for dado in dados)
    soma_y = sum(dado[1] for dado in dados)

    media_x = soma_x / len(dados)
    media_y = soma_y / len(dados)

    return media_x, media_y