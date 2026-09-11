def verificar_postura(posicao_atual, referencia, tolerancia=0.05):

    diferenca_x = abs(posicao_atual[0] - referencia[0])
    diferenca_y = abs(posicao_atual[1] - referencia[1])

    if diferenca_x > tolerancia or diferenca_y > tolerancia:
        return False

    return True