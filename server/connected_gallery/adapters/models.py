from __future__ import annotations
import hashlib
import json
import os
import threading
from pathlib import Path
import numpy as np


class LocalModels:
    """Lazy model loading. A missing optional model is an explicit tool error, never a semantic fallback."""

    def __init__(self, root: Path):
        self.root = root
        self.loaded = {}
        self.lock = threading.RLock()
        # GPU inference remains serialized. CPU OCR/face work can proceed without
        # blocking unrelated image/text embeddings or interactive GPU searches.
        self.ocr_lock = threading.RLock()
        self.face_lock = threading.RLock()
        self.import_lock = threading.RLock()
        self.pins = (
            json.loads(
                (Path(__file__).resolve().parents[2] / "model-lock.json").read_text()
            )
            if (Path(__file__).resolve().parents[2] / "model-lock.json").exists()
            else {}
        )

    @property
    def visual_space(self):
        return "siglip2-base-224@" + self.pins.get(
            "google/siglip2-base-patch16-224", "unresolved"
        )

    @property
    def text_space(self):
        return "multilingual-e5-small@" + self.pins.get(
            "intfloat/multilingual-e5-small", "unresolved"
        )

    def _transformer(self, key, cls, model_id):
        with self.import_lock:
            return self._load_transformer(key, cls, model_id)

    def _load_transformer(self, key, cls, model_id):
        from transformers import AutoProcessor, AutoTokenizer

        if key not in self.loaded:
            revision = self.pins.get(model_id, "main")
            processor = (
                AutoTokenizer if key == "text" else AutoProcessor
            ).from_pretrained(model_id, revision=revision)
            import torch

            model = cls.from_pretrained(model_id, revision=revision).eval()
            model.to("cuda" if torch.cuda.is_available() else "cpu")
            self.loaded[key] = (processor, model)
        return self.loaded[key]

    def image(self, image):
        with self.import_lock:
            import torch
            from transformers import AutoModel

        with self.lock, torch.inference_mode():
            p, m = self._transformer(
                "visual", AutoModel, "google/siglip2-base-patch16-224"
            )
            v = m.get_image_features(
                **p(images=image, return_tensors="pt").to(m.device)
            )
            if not isinstance(v, torch.Tensor):
                v = v.pooler_output
            return self.visual_space, v[0].cpu().numpy()

    def text(self, text, visual=False, query=True):
        with self.import_lock:
            import torch
            from transformers import AutoModel

        with self.lock, torch.inference_mode():
            if visual:
                p, m = self._transformer(
                    "visual", AutoModel, "google/siglip2-base-patch16-224"
                )
                v = m.get_text_features(
                    **p(
                        text=[text],
                        padding="max_length",
                        truncation=True,
                        return_tensors="pt",
                    ).to(m.device)
                )
                if not isinstance(v, torch.Tensor):
                    v = v.pooler_output
                return self.visual_space, v[0].cpu().numpy()
            p, m = self._transformer(
                "text", AutoModel, "intfloat/multilingual-e5-small"
            )
            inputs = p(
                ("query: " if query else "passage: ") + text,
                return_tensors="pt",
                truncation=True,
                max_length=512,
            ).to(m.device)
            out = m(**inputs).last_hidden_state
            mask = inputs["attention_mask"].unsqueeze(-1)
            return self.text_space, ((out * mask).sum(1) / mask.sum(1))[0].cpu().numpy()

    def ocr(self, image):
        with self.ocr_lock:
            with self.import_lock:
                from paddleocr import PaddleOCR
                if "ocr" not in self.loaded:
                    self.loaded["ocr"] = PaddleOCR(
                        lang="korean",
                        enable_mkldnn=False,
                        use_doc_orientation_classify=False,
                        use_doc_unwarping=False,
                        use_textline_orientation=False,
                    )
            result = self.loaded["ocr"].predict(np.array(image))
            return {"pages": [r.json for r in result]}

    def ground(self, image, query):
        with self.import_lock:
            import torch
            from transformers import AutoModelForZeroShotObjectDetection

        with self.lock, torch.inference_mode():
            p, m = self._transformer(
                "ground",
                AutoModelForZeroShotObjectDetection,
                "IDEA-Research/grounding-dino-tiny",
            )
            inputs = p(images=image, text=query, return_tensors="pt").to(m.device)
            output = m(**inputs)
            result = p.post_process_grounded_object_detection(
                output, inputs.input_ids, target_sizes=[(image.height, image.width)]
            )[0]
            return {
                k: v.tolist() if hasattr(v, "tolist") else v for k, v in result.items()
            }

    def faces(self, image):
        import cv2

        with self.face_lock:
            # Public model weights may be shared, while every gallery's images,
            # observations and execution state remain in its own data root.
            model_dir = Path(os.getenv("CG_MODEL_DIR", str(self.root / "models")))
            yunet = model_dir / "face_detection_yunet_2023mar.onnx"
            sface = model_dir / "face_recognition_sface_2021dec.onnx"
            if not yunet.exists() or not sface.exists():
                raise RuntimeError(
                    "Run scripts/prepare-models.py to install face models"
                )
            mat = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)
            detector = cv2.FaceDetectorYN.create(
                str(yunet), "", (image.width, image.height)
            )
            recognizer = cv2.FaceRecognizerSF.create(str(sface), "")
            _, faces = detector.detect(mat)
            output = []
            for f in [] if faces is None else faces:
                x, y, w, h = f[:4]
                x = max(0, float(x))
                y = max(0, float(y))
                output.append(
                    {
                        "box": {
                            "x": x / image.width,
                            "y": y / image.height,
                            "width": min(float(w), image.width - x) / image.width,
                            "height": min(float(h), image.height - y) / image.height,
                        },
                        "vector": recognizer.feature(recognizer.alignCrop(mat, f))[
                            0
                        ].tolist(),
                    }
                )
            return {"faces": output}
