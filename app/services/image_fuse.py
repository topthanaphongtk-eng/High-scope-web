"""Focus-stack two aligned frames into a single all-in-focus image.

    img_a ─┐
           ├─► ECC align ─► focus-measure mask ─► fused frame
    img_b ─┘
"""

from __future__ import annotations

import logging
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

log = logging.getLogger(__name__)


def load_as_bgr(path: Path | str) -> np.ndarray:
    with Image.open(path) as im:
        rgb = np.asarray(im.convert("RGB"), dtype=np.uint8)
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)


def _align_b_to_a(gray_a: np.ndarray, gray_b: np.ndarray) -> np.ndarray:
    warp = np.eye(2, 3, dtype=np.float32)
    criteria = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 200, 1e-6)
    try:
        _, warp = cv2.findTransformECC(
            templateImage=gray_a,
            inputImage=gray_b,
            warpMatrix=warp,
            motionType=cv2.MOTION_EUCLIDEAN,
            criteria=criteria,
        )
    except cv2.error as e:
        log.info("ECC alignment skipped (%s)", e)
    return warp


def _prepare_pair(img_a: np.ndarray, img_b: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    if img_a.shape != img_b.shape:
        img_b = cv2.resize(img_b, (img_a.shape[1], img_a.shape[0]))
    gray_a = cv2.cvtColor(img_a, cv2.COLOR_BGR2GRAY)
    gray_b = cv2.cvtColor(img_b, cv2.COLOR_BGR2GRAY)
    warp = _align_b_to_a(gray_a, gray_b)
    h, w = gray_a.shape
    aligned_b = cv2.warpAffine(
        img_b, warp, (w, h),
        flags=cv2.INTER_LINEAR + cv2.WARP_INVERSE_MAP,
        borderMode=cv2.BORDER_REFLECT,
    )
    return gray_a, cv2.cvtColor(aligned_b, cv2.COLOR_BGR2GRAY), aligned_b


def focus_stack(img_a: np.ndarray, img_b: np.ndarray) -> np.ndarray:
    """Focus-stack two aligned frames into a single all-in-focus BGR image."""
    gray_a, gray_b, aligned_bgr_b = _prepare_pair(img_a, img_b)

    lap_a = cv2.Laplacian(gray_a, cv2.CV_32F, ksize=5)
    lap_b = cv2.Laplacian(gray_b, cv2.CV_32F, ksize=5)
    k = (7, 7)
    focus_a = cv2.boxFilter(lap_a * lap_a, ddepth=-1, ksize=k)
    focus_b = cv2.boxFilter(lap_b * lap_b, ddepth=-1, ksize=k)

    pick_a = cv2.GaussianBlur((focus_a >= focus_b).astype(np.float32), (9, 9), 0)
    pick_a = pick_a[..., None]

    fused = pick_a * img_a.astype(np.float32) + (1.0 - pick_a) * aligned_bgr_b.astype(np.float32)
    return np.clip(fused, 0, 255).astype(np.uint8)
