def calcular_meio_ombros(ombro_esq, ombro_dir):

    meio_x = (ombro_esq.x + ombro_dir.x) / 2
    meio_y = (ombro_esq.y + ombro_dir.y) / 2

    return meio_x, meio_y


def calcular_posicao_cabeca(nariz, meio_ombros):

    diferenca_x = nariz.x - meio_ombros[0]
    diferenca_y = nariz.y - meio_ombros[1]

    return diferenca_x, diferenca_y