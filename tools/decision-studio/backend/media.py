from __future__ import annotations

import base64
import io
import math
from pathlib import Path

import cv2
from PIL import Image, ImageOps

from .models import InferenceConfig

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}
VIDEO_EXT = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v"}
Image.MAX_IMAGE_PIXELS = 60_000_000


def inspect_media(path: Path, preview: Path) -> dict:
    if path.suffix.lower() in IMAGE_EXT:
        with Image.open(path) as img:
            img.load()
            if getattr(img, "n_frames", 1) > 1:
                raise ValueError("Imagens com várias páginas/quadros não são aceitas; exporte as páginas como imagens individuais.")
            im = ImageOps.exif_transpose(img).convert("RGB")
            w, h = im.size
            im.thumbnail((600, 400))
            im.save(preview, "JPEG", quality=85)
        return {"kind": "image", "width": w, "height": h}
    if path.suffix.lower() not in VIDEO_EXT:
        raise ValueError("Formato não suportado.")
    cap = cv2.VideoCapture(str(path))
    try:
        fps = cap.get(cv2.CAP_PROP_FPS)
        frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        ok, frame = cap.read()
        if not ok or not math.isfinite(fps) or fps <= 0 or frames <= 0:
            raise ValueError("Vídeo ilegível ou sem FPS/duração válidos. Tente MP4/H.264.")
        h, w = frame.shape[:2]
        im = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        im.thumbnail((600, 400))
        im.save(preview, "JPEG", quality=85)
        return {"kind": "video", "width": w, "height": h, "fps": fps, "frame_count": frames, "duration": frames / fps}
    finally:
        cap.release()


def frame_plan(media: dict, config: InferenceConfig) -> tuple[range, int]:
    if media["kind"] == "image":
        return range(1), 1
    fps = media["fps"]
    first = math.ceil(config.start_seconds * fps)
    last = min(media["frame_count"], math.ceil((config.end_seconds or media["duration"]) * fps))
    stride = 1 if config.video_mode == "all" else max(1, round(config.frame_interval * fps))
    full = range(first, max(first, last), stride)
    return full[:config.max_frames], len(full)


class Sampler:
    def __init__(self, media: dict, root: Path, target: Path, config: InferenceConfig):
        self.media, self.config, self.target = media, config, target
        self.path = root / media["path"]
        self.indices, self.requested = frame_plan(media, config)
        self.iterator = iter(self.indices)
        self.cap = cv2.VideoCapture(str(self.path)) if media["kind"] == "video" else None
        target.mkdir(parents=True, exist_ok=True)

    def next(self) -> dict | None:
        index = next(self.iterator, None)
        if index is None:
            return None
        if self.cap is not None:
            if int(self.cap.get(cv2.CAP_PROP_POS_FRAMES)) != index:
                self.cap.set(cv2.CAP_PROP_POS_FRAMES, index)
            ok, frame = self.cap.read()
            if not ok:
                raise ValueError(f"Não foi possível decodificar o quadro {index} de {self.media['name']}.")
            im = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            timestamp = index / self.media["fps"]
        else:
            with Image.open(self.path) as source:
                im = ImageOps.exif_transpose(source).convert("RGB")
            timestamp = None
        im.thumbnail((self.config.image_max_side, self.config.image_max_side))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=self.config.jpeg_quality)
        path = self.target / f"{self.media['id']}-{index}.jpg"
        path.write_bytes(buf.getvalue())
        return {"media_id": self.media["id"], "name": self.media["name"], "relative_path": self.media.get("relative_path"), "frame_index": index if self.cap is not None else None, "timestamp": timestamp, "image": "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii"), "frame_path": str(path.relative_to(self.target.parent.parent)).replace("\\", "/")}

    def close(self):
        if self.cap is not None:
            self.cap.release()
