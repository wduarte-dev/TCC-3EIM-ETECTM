import mediapipe as mp
import cv2

MODEL_PATH = "pose_landmarker_lite.task"

BaseOptions = mp.tasks.BaseOptions
PoseLandmarker = mp.tasks.vision.PoseLandmarker
PoseLandmarkerOptions = mp.tasks.vision.PoseLandmarkerOptions
RunningMode = mp.tasks.vision.RunningMode

options = PoseLandmarkerOptions(
    base_options=BaseOptions(model_asset_path=MODEL_PATH),
    running_mode=RunningMode.VIDEO
)


def pegar_landmarks(frame, landmarker, timestamp):

    frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

    mp_image = mp.Image(
        image_format=mp.ImageFormat.SRGB,
        data=frame_rgb
    )

    resultado = landmarker.detect_for_video(
        mp_image,
        timestamp
    )

    if resultado.pose_landmarks:

        pessoa = resultado.pose_landmarks[0]

        nariz = pessoa[0]
        ombro_esq = pessoa[11]
        ombro_dir = pessoa[12]

        return nariz, ombro_esq, ombro_dir

    return None