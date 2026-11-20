#!/usr/bin/env python3
"""
PROGRAMA DE COLETA DO ESTUDO DE VALIDAÇÃO DOS LIMIARES (T1b + etapa 7 do T4)

Roda no notebook (fora do Pi), com a mesma câmera do sistema (Bresser) e o MESMO
modelo e pré-processamento do serviço (importa DetectorPostura de
sensor-postura/postura_servico.py). Não salva imagem nenhuma: só os 17 pontos do
MoveNet + confiança, as métricas e os metadados, em CSV.

Uso (de dentro de coleta/):
    python coleta.py                      # câmera 0
    python coleta.py --camera 1           # outra câmera (ex.: a Bresser no notebook)
    python coleta.py --video teste.mp4    # testar sem câmera, com um vídeo

Teclas na janela: ESPAÇO avança/aceita, R repete a etapa, C troca de câmera
(só no enquadramento), ESC sai (o que já foi gravado fica salvo).
"""
import argparse
import csv
import hashlib
import os
import platform
import subprocess
import sys
import time
import unicodedata
from datetime import datetime

import cv2
import numpy as np

import coleta_logica as cl   # coloca sensor-postura/ no sys.path
from coleta_logica import (
    Sessao, ETAPAS, METRICAS, NOMES_PONTOS, ENQUADRAR, INSTRUCAO, CONTAGEM, GRAVANDO, REVISAO, FIM,
)
from postura_config import (
    CAMINHO_MODELO, LARGURA, ALTURA, LIMIAR_CONFIANCA, LIMIAR_DESVIO_ANGULO, LIMIAR_QUEDA_RAZAO,
    EH_WINDOWS,
)

VERSAO = "1.0 (20/11/2026)"
DIR_COLETA = os.path.dirname(os.path.realpath(__file__))
DIR_DADOS_PADRAO = os.path.join(DIR_COLETA, "dados")
NOME_JANELA = "Coleta - estudo de postura (TCC)"
LARGURA_PAINEL = 480

VERDE, VERMELHO, AMARELO, BRANCO, CINZA = (0, 200, 0), (0, 0, 230), (0, 220, 255), (255, 255, 255), (150, 150, 150)


# =====================================================================
# Detector: o MESMO do serviço, só que devolvendo os 17 pontos em pixels
# =====================================================================

class DetectorColeta:
    def __init__(self):
        from postura_servico import DetectorPostura, carregar_classe_interpretador, desnormalizar_keypoint
        self._desnormalizar = desnormalizar_keypoint
        self.interpretador = carregar_classe_interpretador().__module__
        self.det = DetectorPostura()

    def detectar(self, frame):
        """Frame BGR (já espelhado) → 17 tuplas (x_px, y_px, conf), na ordem do MoveNet."""
        self.det.detectar_metricas_postura(frame, LIMIAR_CONFIANCA)
        tamanho, escala, ox, oy = self.det.ultimo_letterbox
        return [(*self._desnormalizar(x, y, tamanho, escala, ox, oy), float(c))
                for (y, x, c) in self.det.ultimos_keypoints]


# =====================================================================
# Câmera / vídeo
# =====================================================================

def abrir_fonte(camera, video=None, mjpg=False):
    """Devolve (cap, descrição) ou (None, motivo). Testa com uma leitura de verdade."""
    if video:
        cap = cv2.VideoCapture(video)
        if not cap.isOpened():
            return None, f"nao abriu o video {video}"
        return cap, f"video {os.path.basename(video)}"
    if EH_WINDOWS:
        backends = [("DSHOW", cv2.CAP_DSHOW), ("MSMF", cv2.CAP_MSMF), ("ANY", cv2.CAP_ANY)]
    elif sys.platform.startswith("linux"):
        backends = [("V4L2", cv2.CAP_V4L2), ("ANY", cv2.CAP_ANY)]
    else:
        backends = [("ANY", cv2.CAP_ANY)]
    for nome, backend in backends:
        cap = cv2.VideoCapture(camera, backend)
        if not cap.isOpened():
            cap.release()
            continue
        if mjpg:   # a Bresser NÃO tem MJPG; por padrão não força (ela só faz YUYV)
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, LARGURA)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, ALTURA)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        ok, frame = cap.read()
        if ok and frame is not None:
            return cap, f"camera {camera} ({nome}, {frame.shape[1]}x{frame.shape[0]})"
        cap.release()
    return None, f"camera {camera} nao abriu ou nao entregou quadro"


# =====================================================================
# Gravação em CSV
# =====================================================================

def _fmt(v):
    if v is None:
        return ""
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, float):
        return round(v, 4)
    return v


def _abrir_csv(caminho, cabecalho):
    novo = not os.path.exists(caminho) or os.path.getsize(caminho) == 0
    arq = open(caminho, "a", newline="", encoding="utf-8")
    escritor = csv.writer(arq)
    if novo:
        escritor.writerow(cabecalho)
    return arq, escritor


class RegistroCSV:
    """
    dados/quadros_<ID>_<data>.csv  um por pessoa: cada quadro gravado (todas as tentativas)
    dados/etapas.csv               uma linha por tentativa de etapa (aceita = 1 ou 0)
    dados/participantes.csv        uma linha por pessoa: metadados + baseline + ambiente
    """
    CAB_QUADROS = (["participante", "etapa", "etapa_chave", "tentativa", "t_s", "quadro", "valido",
                    "angulo", "razao", "razao_cb", "a_px", "b_px", "c_px",
                    "desvio_angulo", "queda_razao_pct", "ruim_quadro"]
                   + [f"{n}_{c}" for n in NOMES_PONTOS for c in ("x", "y", "conf")])
    CAB_ETAPAS = (["participante", "etapa", "etapa_chave", "tentativa", "aceita", "data_hora",
                   "n_total", "n_validos", "pct_sem_usuario", "fps_medio", "pct_ruim_quadro", "n_cb"]
                  + [f"{m}_{s}" for m in METRICAS for s in ("mediana", "dp")]
                  + ["baseline_angulo", "baseline_razao"])
    CAB_PARTICIPANTES = [
        "participante", "data_hora_inicio", "data_hora_fim", "completa", "etapas_aceitas",
        "termo_ok", "oculos", "cabelo_cobre_orelha", "cadeira", "distancia_camera_cm",
        "altura_camera", "notebook", "observacoes",
        "baseline_angulo", "baseline_razao", "baseline_b_px", "baseline_cb",
        "fonte", "fps_medio", "sistema", "python", "opencv", "interpretador", "modelo_md5",
        "limiar_confianca", "limiar_angulo", "limiar_queda", "duracao_etapa_s", "contagem_s",
        "versao_programa", "versao_codigo",
    ]

    def __init__(self, pasta, participante):
        os.makedirs(pasta, exist_ok=True)
        self.pasta = pasta
        self.participante = participante
        carimbo = datetime.now().strftime("%Y%m%d-%H%M%S")
        self.caminho_quadros = os.path.join(pasta, f"quadros_{participante}_{carimbo}.csv")
        self._arq_q, self._csv_q = _abrir_csv(self.caminho_quadros, self.CAB_QUADROS)
        self._arq_e, self._csv_e = _abrir_csv(os.path.join(pasta, "etapas.csv"), self.CAB_ETAPAS)
        self._n_quadro = 0
        self.total_quadros = 0
        self.tempo_gravado = 0.0

    def quadro(self, sessao, t_s, analise, kps):
        self._n_quadro += 1
        pontos = []
        for i in range(len(NOMES_PONTOS)):
            if kps is None:
                pontos += ["", "", ""]
            else:
                x, y, c = kps[i]
                pontos += [int(x), int(y), round(float(c), 4)]
        a = analise
        self._csv_q.writerow([_fmt(v) for v in (
            self.participante, sessao.etapa.num, sessao.etapa.chave, sessao.tentativa, t_s,
            self._n_quadro, a["valido"], a["angulo"], a["razao"], a["razao_cb"], a["a_px"],
            a["b_px"], a["c_px"], a["desvio_angulo"], a["queda_razao_pct"], a["ruim_quadro"],
        )] + pontos)
        self._arq_q.flush()

    def etapa(self, sessao, resumo, aceita):
        self.total_quadros += resumo["n_total"]
        if resumo["fps_medio"]:
            self.tempo_gravado += resumo["n_total"] / resumo["fps_medio"]
        base = resumo["baseline"] or (None, None)
        self._csv_e.writerow([_fmt(v) for v in (
            [self.participante, sessao.etapa.num, sessao.etapa.chave, sessao.tentativa, aceita,
             datetime.now().isoformat(timespec="seconds"), resumo["n_total"], resumo["n_validos"],
             resumo["pct_sem_usuario"], resumo["fps_medio"], resumo["pct_ruim_quadro"], resumo["n_cb"]]
            + [resumo[f"{m}_{s}"] for m in METRICAS for s in ("mediana", "dp")]
            + [base[0], base[1]])])
        self._arq_e.flush()

    def participante_fim(self, sessao, meta, ambiente):
        base = sessao.baseline or (None, None)
        fps = (self.total_quadros / self.tempo_gravado) if self.tempo_gravado > 0 else None
        linha = dict(meta, **ambiente)
        linha.update(
            participante=self.participante, data_hora_fim=datetime.now().isoformat(timespec="seconds"),
            completa=sessao.completa, etapas_aceitas="|".join(sessao.aceitas),
            baseline_angulo=base[0], baseline_razao=base[1],
            baseline_b_px=sessao.baseline_b_px, baseline_cb=sessao.baseline_cb, fps_medio=fps,
        )
        arq, escritor = _abrir_csv(os.path.join(self.pasta, "participantes.csv"), self.CAB_PARTICIPANTES)
        escritor.writerow([_fmt(linha.get(c)) for c in self.CAB_PARTICIPANTES])
        arq.close()

    def fechar(self):
        self._arq_q.close()
        self._arq_e.close()


# =====================================================================
# Metadados (no terminal, antes de abrir a janela)
# =====================================================================

def proximo_id(pasta):
    usados = set()
    caminho = os.path.join(pasta, "participantes.csv")
    if os.path.exists(caminho):
        with open(caminho, encoding="utf-8") as arq:
            usados |= {linha["participante"] for linha in csv.DictReader(arq)}
    if os.path.isdir(pasta):
        usados |= {n.split("_")[1] for n in os.listdir(pasta) if n.startswith("quadros_P")}
    n = 1
    while f"P{n:02d}" in usados:
        n += 1
    return f"P{n:02d}", usados


def _sim_nao(pergunta, entrada):
    while True:
        r = entrada(f"{pergunta} (s/n): ").strip().lower()
        if r in ("s", "sim"):
            return "s"
        if r in ("n", "nao", "não"):
            return "n"
        print("  responda s ou n")


def perguntar_metadados(pasta, notebook_padrao, entrada=input):
    sugestao, usados = proximo_id(pasta)
    print("\n=== Participante (ID anonimo: nada de nome) ===")
    while True:
        pid = entrada(f"ID [{sugestao}]: ").strip().upper() or sugestao
        if pid not in usados or _sim_nao(f"  {pid} ja existe nos dados. Usar mesmo assim?", entrada) == "s":
            break
    meta = dict(participante=pid, data_hora_inicio=datetime.now().isoformat(timespec="seconds"))
    meta["termo_ok"] = _sim_nao("Termo de participacao aceito", entrada)
    if meta["termo_ok"] == "n":
        print("  AVISO: sem termo aceito. Confira com o orientador antes de usar estes dados.")
    meta["oculos"] = _sim_nao("Usa oculos agora", entrada)
    meta["cabelo_cobre_orelha"] = _sim_nao("Cabelo cobre a orelha", entrada)
    meta["cadeira"] = entrada("Cadeira (ex.: escolar sem encosto, com encosto, gamer): ").strip()
    meta["distancia_camera_cm"] = entrada("Distancia aproximada camera-pessoa (cm): ").strip()
    meta["altura_camera"] = entrada("Altura da camera (ex.: na altura dos olhos, abaixo, acima): ").strip()
    nb = entrada(f"Notebook [{notebook_padrao}]: ").strip()
    meta["notebook"] = nb or notebook_padrao
    meta["observacoes"] = entrada("Observacoes (enter = nenhuma): ").strip()
    return meta


def _md5(caminho):
    h = hashlib.md5()
    with open(caminho, "rb") as arq:
        h.update(arq.read())
    return h.hexdigest()[:12]


def _versao_codigo():
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=DIR_COLETA, capture_output=True,
                              text=True, timeout=3).stdout.strip() or "desconhecida"
    except (OSError, subprocess.SubprocessError):
        return "desconhecida"


# =====================================================================
# Tela (janela do OpenCV): vídeo à esquerda, painel de texto à direita
# =====================================================================

def _ascii(texto):
    return unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode("ascii")


def _texto(img, texto, y, cor=BRANCO, escala=0.5, x=12, grossura=1):
    cv2.putText(img, _ascii(texto), (x, y), cv2.FONT_HERSHEY_SIMPLEX, escala, cor, grossura, cv2.LINE_AA)


def desenhar_pontos(frame, kps, analise):
    if kps is None:
        return
    for (x, y, c) in kps:   # os 17, pequenos (contexto)
        if c > LIMIAR_CONFIANCA:
            cv2.circle(frame, (int(x), int(y)), 3, CINZA, -1)
    confs = (analise["conf_orelha"], analise["conf_ombro_orelha"], analise["conf_outro_ombro"])
    idx = (cl.I_ORELHA, cl.I_OMBRO_ORELHA, cl.I_OUTRO_OMBRO)
    for i, c in zip(idx, confs):
        x, y, _ = kps[i]
        cor = VERDE if c > LIMIAR_CONFIANCA else VERMELHO
        cv2.circle(frame, (int(x), int(y)), 8, cor, -1 if c > LIMIAR_CONFIANCA else 2)
    if analise["valido"]:
        (xo, yo, _), (xe, ye, _), (xd, yd, _) = (kps[i] for i in idx)
        cv2.line(frame, (int(xo), int(yo)), (int(xe), int(ye)), BRANCO, 2)
        cv2.line(frame, (int(xe), int(ye)), (int(xd), int(yd)), BRANCO, 1)


def montar_tela(frame, kps, analise, sessao, agora, participante, fps, fonte):
    video = frame.copy()
    desenhar_pontos(video, kps, analise)
    h = 480
    if video.shape[0] != h:
        video = cv2.resize(video, (int(video.shape[1] * h / video.shape[0]), h))
    painel = np.zeros((h, LARGURA_PAINEL, 3), dtype=np.uint8)
    etapa = sessao.etapa
    num = f"Etapa {etapa.num}/{len(ETAPAS)}" if etapa and sessao.estado != ENQUADRAR else "Enquadramento"
    _texto(painel, f"{participante} | {num} | {fps:4.1f} fps", 24, CINZA)
    y = 60
    if sessao.estado == ENQUADRAR:
        _texto(painel, "AJUSTE A CAMERA", y, AMARELO, 0.7, grossura=2)
        y += 36
        nomes = (("orelha", "conf_orelha"), ("ombro do lado da orelha", "conf_ombro_orelha"),
                 ("outro ombro", "conf_outro_ombro"))
        for nome, chave in nomes:
            ok = analise[chave] > LIMIAR_CONFIANCA
            _texto(painel, f"[{'OK' if ok else 'FALTA'}] {nome}", y, VERDE if ok else VERMELHO, 0.55)
            y += 26
        y += 14
        for linha in ("Os 3 pontos verdes, com folga", "pra pessoa se encurvar e inclinar.",
                      f"Fonte: {fonte}"):
            _texto(painel, linha, y)
            y += 24
        y = h - 50
        _texto(painel, "C = trocar camera | ESC = sair", y, CINZA)
        _texto(painel, "ESPACO = comecar", y + 26, AMARELO, 0.6, grossura=2)
    elif sessao.estado == INSTRUCAO:
        _texto(painel, etapa.titulo, y, AMARELO, 0.6, grossura=2)
        y += 34
        for linha in etapa.instrucoes:
            _texto(painel, linha, y)
            y += 24
        if sessao.tentativa > 1:
            _texto(painel, f"(tentativa {sessao.tentativa})", y + 10, CINZA)
        y = h - 50
        _texto(painel, f"Grava {sessao.duracao_s:g} s depois de {sessao.contagem_s:g} s", y, CINZA)
        _texto(painel, "ESPACO = gravar | ESC = sair", y + 26, AMARELO, 0.6, grossura=2)
    elif sessao.estado == CONTAGEM:
        _texto(painel, etapa.titulo, y, AMARELO, 0.6, grossura=2)
        _texto(painel, "Assuma a pose e fique parado", y + 50, BRANCO, 0.6)
        _texto(painel, f"{sessao.restante_s(agora):.0f}", y + 160, AMARELO, 3.0, x=170, grossura=5)
    elif sessao.estado == GRAVANDO:
        _texto(painel, etapa.titulo, y, AMARELO, 0.6, grossura=2)
        _texto(painel, f"GRAVANDO {sessao.restante_s(agora):.1f} s", y + 60, VERMELHO, 0.9, grossura=2)
        _texto(painel, f"quadros: {sessao.gravados} (validos {sessao.gravados_validos})", y + 100)
        cv2.circle(video, (24, 24), 10, VERMELHO, -1)
    elif sessao.estado == REVISAO:
        r = sessao.resumo
        _texto(painel, f"{etapa.titulo}: resultado", y, AMARELO, 0.55, grossura=2)
        y += 34
        linhas = [f"Quadros validos: {r['n_validos']}/{r['n_total']}"
                  f" ({100 - (r['pct_sem_usuario'] or 0):.0f}%)"]
        if r["angulo_mediana"] is not None:
            linhas.append(f"angulo (mediana): {r['angulo_mediana']:.1f} graus")
            linhas.append(f"razao pescoco/ombros: {r['razao_mediana']:.3f}")
        if r["desvio_angulo_mediana"] is not None:
            linhas.append(f"desvio x baseline: {r['desvio_angulo_mediana']:.1f} graus")
            linhas.append(f"queda da razao: {r['queda_razao_pct_mediana']:.1f}%")
        for linha in linhas:
            _texto(painel, linha, y)
            y += 24
        aviso = sessao.aviso_revisao()
        if aviso:
            _texto(painel, aviso, y + 14, AMARELO, 0.45)
        y = h - 50
        _texto(painel, "R = repetir esta etapa", y, CINZA)
        if sessao.pode_aceitar():
            _texto(painel, "ESPACO = aceitar e seguir", y + 26, VERDE, 0.6, grossura=2)
    elif sessao.estado == FIM:
        _texto(painel, "FIM DESTA PESSOA", y, VERDE, 0.8, grossura=2)
        _texto(painel, "Dados salvos. Feche ou aperte ESC.", y + 40)
    return np.hstack([video, painel])


# =====================================================================
# Laço principal
# =====================================================================

TECLAS = {32: "espaco", ord("r"): "r", ord("R"): "r", 27: "sair"}


def rodar_janela(sessao, detector, cap, fonte, args, participante):
    fps, t_ant, falhas = 0.0, time.monotonic(), 0
    camera = args.camera
    cv2.namedWindow(NOME_JANELA, cv2.WINDOW_AUTOSIZE)
    while True:
        ok, frame = cap.read()
        if not ok or frame is None:
            falhas += 1
            if args.video or falhas > 60:
                print("Video acabou." if args.video else "Erro: a camera parou de entregar quadros.")
                sessao.tecla("sair", time.monotonic())
                break
            continue
        falhas = 0
        frame = cv2.flip(frame, 1)   # espelho, igual ao serviço (o MoveNet vê a mesma imagem)
        kps = detector.detectar(frame)
        agora = time.monotonic()
        analise = sessao.quadro(kps, agora)
        dt = agora - t_ant
        t_ant = agora
        if dt > 0:
            fps = 1 / dt if fps == 0 else 0.9 * fps + 0.1 / dt
        cv2.imshow(NOME_JANELA, montar_tela(frame, kps, analise, sessao, agora, participante, fps, fonte))
        k = cv2.waitKey(1) & 0xFF
        if cv2.getWindowProperty(NOME_JANELA, cv2.WND_PROP_VISIBLE) < 1:
            sessao.tecla("sair", agora)
            break
        if k in (ord("c"), ord("C")) and sessao.estado == ENQUADRAR and not args.video:
            cap.release()
            for tentativa in range(1, 6):   # procura a próxima câmera que abre (0..5)
                candidato = (camera + tentativa) % 6
                novo, desc = abrir_fonte(candidato, mjpg=args.mjpg)
                if novo is not None:
                    cap, camera, fonte = novo, candidato, desc
                    break
            else:
                cap, fonte = abrir_fonte(camera, mjpg=args.mjpg)
                if cap is None:
                    print(f"Erro: {fonte}")
                    sessao.tecla("sair", agora)
                    break
            print(f"Fonte: {fonte}")
            continue
        if k in TECLAS:
            sessao.tecla(TECLAS[k], agora)
        if sessao.estado == FIM and k == 27:
            break
    if cap is not None:
        cap.release()
    cv2.destroyAllWindows()
    return fonte


def main():
    ap = argparse.ArgumentParser(description="Coleta do estudo de validação dos limiares de postura")
    ap.add_argument("--camera", type=int, default=0, help="índice da câmera (padrão 0)")
    ap.add_argument("--video", help="usar um vídeo em vez da câmera (teste)")
    ap.add_argument("--duracao", type=float, default=5.0, help="segundos gravados por etapa (padrão 5)")
    ap.add_argument("--contagem", type=float, default=2.0, help="segundos pra assumir a pose (padrão 2)")
    ap.add_argument("--dados", default=DIR_DADOS_PADRAO, help="pasta dos CSV (padrão coleta/dados)")
    ap.add_argument("--mjpg", action="store_true", help="pedir MJPG à câmera (a Bresser não tem)")
    ap.add_argument("--notebook", default=platform.node(), help="nome/modelo do notebook")
    args = ap.parse_args()

    if not os.path.exists(CAMINHO_MODELO):
        sys.exit(f"Modelo nao encontrado: {CAMINHO_MODELO}")
    print("Carregando o MoveNet...")
    detector = DetectorColeta()
    print(f"  interpretador: {detector.interpretador}")

    cap, fonte = abrir_fonte(args.camera, args.video, args.mjpg)
    if cap is None:
        sys.exit(f"Erro: {fonte}. Tente --camera 1 (ou 2).")
    print(f"Fonte: {fonte}")

    meta = perguntar_metadados(args.dados, args.notebook)
    ambiente = dict(
        sistema=f"{platform.system()} {platform.release()}", python=platform.python_version(),
        opencv=cv2.__version__, interpretador=detector.interpretador, modelo_md5=_md5(CAMINHO_MODELO),
        limiar_confianca=LIMIAR_CONFIANCA, limiar_angulo=LIMIAR_DESVIO_ANGULO,
        limiar_queda=LIMIAR_QUEDA_RAZAO, duracao_etapa_s=args.duracao, contagem_s=args.contagem,
        versao_programa=VERSAO, versao_codigo=_versao_codigo(),
    )
    registro = RegistroCSV(args.dados, meta["participante"])
    sessao = Sessao(registro, duracao_s=args.duracao, contagem_s=args.contagem)
    print("\nJanela aberta. ESPACO avanca, R repete, C troca de camera (no enquadramento), ESC sai.")
    try:
        ambiente["fonte"] = rodar_janela(sessao, detector, cap, fonte, args, meta["participante"])
    finally:
        ambiente.setdefault("fonte", fonte)
        registro.participante_fim(sessao, meta, ambiente)
        registro.fechar()
        situacao = "COMPLETA" if sessao.completa else f"INCOMPLETA ({len(sessao.aceitas)}/{len(ETAPAS)} etapas)"
        print(f"\n{meta['participante']}: {situacao}. Dados em {args.dados}")


if __name__ == "__main__":
    main()
