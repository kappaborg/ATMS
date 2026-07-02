"""CLIP-based zero-shot brand identifier.

Drop-in alternative to the trained YOLOv8 brand detector at
`models/car_brand_classification/.../best.pt`. Pros and cons:

| Property              | Trained YOLO (13 classes)  | CLIP zero-shot (any prompt) |
|-----------------------|----------------------------|-----------------------------|
| Brand coverage        | 13 (training set only)     | 70+ (every prompt we list)  |
| Inference cost (CPU)  | ~30 ms per crop            | ~150-300 ms per crop        |
| Setup                 | bundled `.pt` weights      | downloads CLIP from HF      |
| Adding a new brand    | retrain                    | edit one list               |
| Accuracy on known     | high (trained on close-ups)| medium (zero-shot)          |

Used by `simulation.demo` when `--brand-model clip` is passed. The pipeline
treats both identifiers uniformly via the `identify_batch` contract — same
caching, throttling, and size-filtering logic applies.

Implementation note: text embeddings for the brand prompts are computed ONCE
at startup. Per-frame work is image-encoding + a single dot product against
the precomputed text matrix.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger("atms.video.clip")


# All keys from shared.atms_common.emissions._DEFAULT_BRAND_MULTIPLIERS that
# CLIP should try to recognise. Adding a brand here is a one-line change.
# Multi-word brands ("land rover", "rolls-royce") use natural English to give
# CLIP its best chance.
# Multi-prompt ensemble templates. CLIP's zero-shot accuracy improves when
# the brand is queried via several diverse prompts and the per-brand scores
# are averaged. These templates were chosen for naturalness on intersection
# footage (front, side, and rear views, daytime + night).
_PROMPT_TEMPLATES: tuple[str, ...] = (
    "a photo of a {brand} car",
    "a photo of a {brand} car driving on the street",
    "a {brand} vehicle seen from a traffic camera",
    "a side view of a {brand} car",
)


DEFAULT_BRAND_PROMPTS: list[str] = [
    "tesla",
    "polestar",
    "lucid",
    "rivian",
    "nio",
    "xpeng",
    "vinfast",
    "byd",
    "mg",
    "geely",
    "chery",
    "toyota",
    "lexus",
    "honda",
    "acura",
    "mazda",
    "hyundai",
    "kia",
    "fiat",
    "nissan",
    "infiniti",
    "mitsubishi",
    "subaru",
    "suzuki",
    "volkswagen",
    "skoda",
    "seat",
    "cupra",
    "opel",
    "vauxhall",
    "renault",
    "dacia",
    "peugeot",
    "citroen",
    "ds",
    "volvo",
    "saab",
    "ford",
    "chevrolet",
    "buick",
    "gmc",
    "lincoln",
    "cadillac",
    "audi",
    "bmw",
    "mini",
    "mercedes-benz",
    "smart",
    "land rover",
    "range rover",
    "jaguar",
    "alfa romeo",
    "maserati",
    "porsche",
    "bentley",
    "rolls-royce",
    "ferrari",
    "lamborghini",
    "aston martin",
    "ram",
    "jeep",
    "dodge",
    "chrysler",
    "isuzu",
]


class CLIPBrandIdentifier:
    """Zero-shot brand identifier using OpenAI CLIP (`clip-vit-base-patch32`).

    The model + processor are loaded lazily on the first identify_batch call.
    Text embeddings for every brand prompt are computed once at load time and
    reused for every subsequent inference — the per-call cost is dominated
    by image encoding.
    """

    def __init__(
        self,
        brands: list[str] | None = None,
        conf_threshold: float = 0.30,
        min_margin: float = 0.05,
        model_name: str = "openai/clip-vit-base-patch32",
    ) -> None:
        self._brands = brands or DEFAULT_BRAND_PROMPTS
        # Multi-prompt per brand. CLIP gets a richer signal than from a
        # single canonical prompt; we average the softmax probability across
        # all prompts for the same brand. Each `_prompt_brand_idx[i]` is the
        # brand index that prompt `i` belongs to.
        self._prompts: list[str] = []
        self._prompt_brand_idx: list[int] = []
        for b_idx, brand in enumerate(self._brands):
            for template in _PROMPT_TEMPLATES:
                self._prompts.append(template.format(brand=brand))
                self._prompt_brand_idx.append(b_idx)
        self._conf_threshold = conf_threshold
        # `min_margin`: required gap between the top-1 brand probability and
        # the top-2. If margin < this, the identifier returns None (the
        # "unknown" opt-out). Without this, CLIP always commits to *some*
        # brand even when its embedding is ~equidistant from many.
        self._min_margin = min_margin
        self._model_name = model_name
        self._model: Any = None
        self._processor: Any = None
        # available iff transformers + torch import successfully on first use
        self._available = True

    @property
    def available(self) -> bool:
        # Trigger the lazy load to learn whether the imports work.
        self._ensure_loaded()
        return self._available

    def _ensure_loaded(self) -> None:
        if self._model is not None or not self._available:
            return
        try:
            import torch  # noqa: PLC0415  lazy — transformers is heavy and opt-in
            from transformers import CLIPModel, CLIPProcessor  # noqa: PLC0415

            log.info("loading CLIP brand identifier (%s) ...", self._model_name)
            self._model = CLIPModel.from_pretrained(self._model_name)
            self._model.eval()
            self._processor = CLIPProcessor.from_pretrained(self._model_name)
            log.info("CLIP ready - %d brand prompts wired", len(self._brands))
            _ = torch  # touch torch so the import isn't elided
        except ImportError as e:
            log.warning(
                "CLIP unavailable (%s) - install with: "
                "python3 -m pip install --break-system-packages transformers torch",
                e,
            )
            self._available = False
        except Exception as e:
            log.warning("CLIP failed to load (%s); proceeding without brand id", e)
            self._available = False

    def identify_batch(self, crops: list[Any]) -> list[tuple[str, float] | None]:
        """For each crop, return `(brand, confidence)` or `None` if no brand
        scored above `conf_threshold`. Parallel to the input crop list.

        Uses the combined `model(text=..., images=...)` call which is the
        only path that returns projected embeddings in transformers v5 —
        `get_text_features` / `get_image_features` now return the raw
        backbone output object, not the projected tensor.

        The cost: we re-encode the text prompts on every call. With 65
        short prompts this is fast relative to the image-encoding pass.
        """
        self._ensure_loaded()
        if self._model is None or not crops:
            return [None] * len(crops)

        try:
            import torch  # noqa: PLC0415  lazy — same reason as in _ensure_loaded
            from PIL import Image  # noqa: PLC0415
        except ImportError:
            return [None] * len(crops)

        # OpenCV gives BGR uint8; CLIP wants PIL RGB.
        pil_crops: list[Any] = []
        for c in crops:
            if c is None or c.size == 0:
                pil_crops.append(None)
                continue
            rgb = c[..., ::-1]  # BGR -> RGB without importing cv2 here
            pil_crops.append(Image.fromarray(rgb))

        valid_idx = [i for i, p in enumerate(pil_crops) if p is not None]
        if not valid_idx:
            return [None] * len(crops)

        try:
            with torch.no_grad():
                inputs = self._processor(
                    text=self._prompts,
                    images=[pil_crops[i] for i in valid_idx],
                    return_tensors="pt",
                    padding=True,
                )
                model_out = self._model(**inputs)
                # logits_per_image shape: (N_images, N_prompts).
                # Softmax over the prompt axis -> per-prompt probabilities.
                prompt_probs = model_out.logits_per_image.softmax(dim=-1)
                # Aggregate by brand: sum the probabilities of all prompts
                # belonging to each brand. This is the multi-prompt ensemble.
                n_brands = len(self._brands)
                brand_probs = torch.zeros(prompt_probs.shape[0], n_brands, dtype=prompt_probs.dtype)
                idx_tensor = torch.tensor(self._prompt_brand_idx, dtype=torch.long)
                brand_probs.index_add_(1, idx_tensor, prompt_probs)
                # `brand_probs` now sums to 1 per image, distributed over brands.
                # Top-1 and top-2 for the margin check.
                top2 = brand_probs.topk(k=2, dim=-1)
                top_conf = top2.values[:, 0]
                second_conf = top2.values[:, 1]
                top_idx = top2.indices[:, 0]
        except Exception as e:
            log.warning("CLIP inference failed: %s", e)
            return [None] * len(crops)

        out: list[tuple[str, float] | None] = [None] * len(crops)
        for slot, orig_idx in enumerate(valid_idx):
            conf = float(top_conf[slot].item())
            margin = conf - float(second_conf[slot].item())
            # Two gates: absolute confidence floor AND top-1 vs top-2 margin.
            # The margin check is the "unknown" opt-out — when CLIP is roughly
            # equidistant from many brands, no single one wins by enough to
            # commit. This is the missing capability vs a fine-tuned model
            # that has an explicit "other" class.
            if conf < self._conf_threshold or margin < self._min_margin:
                continue
            brand = self._brands[int(top_idx[slot].item())]
            out[orig_idx] = (brand, conf)
        return out

    def identify_for_bbox(
        self, frame: Any, bbox: tuple[float, float, float, float]
    ) -> tuple[str, float] | None:
        """Single-bbox convenience wrapper around identify_batch."""
        x1, y1, x2, y2 = bbox
        h, w = frame.shape[:2]
        cx1 = max(0, int(x1))
        cy1 = max(0, int(y1))
        cx2 = min(w, int(x2))
        cy2 = min(h, int(y2))
        if cx2 <= cx1 or cy2 <= cy1:
            return None
        crop = frame[cy1:cy2, cx1:cx2]
        if crop.size == 0:
            return None
        return self.identify_batch([crop])[0]
