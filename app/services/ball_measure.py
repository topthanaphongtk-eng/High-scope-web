"""Focus stacking + pad detection and size measurement.

The pad is the bright square substrate that the operator images — it has a much
cleaner signal (big uniform bright region) than the ball inside, so we measure
that instead.

    img_a ─┐
           ├─► ECC align ─► focus stack ─► Otsu bright-mask ─► best contour → bbox
    img_b ─┘                                                         │
                                                               centroid + area
                                                                       │
                                                                PadMeasurement

If the operator clicks, the click is used as a spatial prior — useful when the
frame contains more than one pad and the wrong one scores highest.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image

log = logging.getLogger(__name__)

_INCH_TO_UM = 25_400.0
_UM_PER_MIL = 25.4   # 1 mil = 0.001 inch = 25.4 µm


def _unit_scale(unit: str) -> tuple[float, str]:
    """Return (scale, label) for displaying lengths. Areas scale by `scale**2`."""
    if unit == "mil":
        return 1.0 / _UM_PER_MIL, "mil"
    return 1.0, "um"


# --------------------------------------------------------------------- models


@dataclass
class BallMeasurement:
    """Circle that fits the dark ball impression inside a pad."""

    center_x_px: int
    center_y_px: int
    radius_px: float
    diameter_px: float
    radius_um: float
    diameter_um: float
    circularity: float
    fill_ratio: float          # contour area / enclosing circle area
    method: str
    pixel_size_um: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class GapMeasurement:
    """Distance from the ball edge to each side of the pad, plus annulus area."""

    min_gap_px: float
    max_gap_px: float
    mean_gap_px: float
    min_gap_um: float
    max_gap_um: float
    mean_gap_um: float
    min_gap_side: int          # 0..3 — which pad edge is closest
    per_side_um: list[float]   # gap for each of the 4 pad sides

    # Annulus (pad area minus ball area)
    annulus_area_px2: float
    annulus_area_um2: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PadMeasurement:
    """Rotated rectangle that fits the detected pad, measured in px and µm."""

    # axis-aligned bbox (for ROI / display convenience)
    x_px: int
    y_px: int
    width_px: int             # axis-aligned bbox width
    height_px: int            # axis-aligned bbox height

    # actual rotated-rect geometry (this is what's reported as the pad dimensions)
    center_x_px: int
    center_y_px: int
    pad_w_px: float           # shorter side of the rotated rect (pixels)
    pad_h_px: float           # longer side of the rotated rect (pixels)
    angle_deg: float          # rotation of the rotated rect

    # the four corner points (clockwise, px coords)
    corners_px: list[tuple[int, int]]

    # dimensions — use the rotated rect's sides, not the axis-aligned bbox
    width_um: float           # = pad_w_px * pixel_size
    height_um: float          # = pad_h_px * pixel_size
    diagonal_um: float
    area_px2: int
    area_um2: float

    # shape quality
    aspect_ratio: float       # longer / shorter (>=1.0)
    fill_ratio: float         # contour area / rotated-rect area  (1.0 = perfect)

    # qualitative
    confidence: str           # high | medium | low
    method: str

    # calibration
    pixel_size_um: float

    # provenance
    source_a_name: str
    source_b_name: str

    seeded: bool = False

    # Optional ball measurement found inside this pad. Attached by
    # `detect_ball_in_pad` / `detect_pad_best_of` when a dark circular feature is
    # detected; None when no ball passes the filters.
    ball: BallMeasurement | None = None

    # Gap / annulus between ball edge and pad edges — populated whenever a ball
    # is attached. Recomputed when the operator adjusts ball radius via the UI.
    gap: GapMeasurement | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# --------------------------------------------------------------------- io helpers


def load_as_bgr(path: Path | str) -> np.ndarray:
    with Image.open(path) as im:
        rgb = np.asarray(im.convert("RGB"), dtype=np.uint8)
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)


def pixel_size_um_from_ome(physical_size: float | None, unit: str | None) -> float:
    if physical_size is None or physical_size <= 0:
        return 1.0
    u = (unit or "").strip().lower()
    if u in {"in", "inch", "inches"}:
        return physical_size * _INCH_TO_UM
    if u in {"µm", "um", "micrometer", "micrometre"}:
        return physical_size
    if u in {"mm", "millimeter", "millimetre"}:
        return physical_size * 1000.0
    log.warning("Unknown PhysicalSize unit %r — treating value as µm", unit)
    return physical_size


# --------------------------------------------------------------------- focus stack


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


# --------------------------------------------------------------------- pad detection


@dataclass
class _Tier:
    """One attempt at pad detection with a specific threshold + filter set."""

    # Exactly one of these is used to pick the threshold:
    percentile: float | None      # e.g. 92.0 → threshold = p92 of blurred intensities
    otsu_offset: float            # ignored when percentile is not None

    # Post-threshold contour filters
    area_min_frac: float
    area_max_frac: float
    aspect_max: float
    fill_min: float
    name: str


# Percentile-based tiers handle the common case of dark frames with tiny bright
# pads (where Otsu's split is dark-vs-die rather than die-vs-pad). Otsu-based
# tiers are the backstop for images with a more balanced histogram.
#
# `aspect_max` is generous (up to 6:1) so rectangular long pads pass the gate;
# the per-contour score still penalises high aspect (1/aspect), so square pads
# win cleanly when both shapes are present in a frame.
_TIERS: list[_Tier] = [
    _Tier(percentile=92.0, otsu_offset=0,
          area_min_frac=0.005, area_max_frac=0.20,
          aspect_max=5.0, fill_min=0.70, name="p92"),
    _Tier(percentile=90.0, otsu_offset=0,
          area_min_frac=0.003, area_max_frac=0.25,
          aspect_max=5.5, fill_min=0.55, name="p90"),
    _Tier(percentile=85.0, otsu_offset=0,
          area_min_frac=0.002, area_max_frac=0.30,
          aspect_max=6.0, fill_min=0.40, name="p85"),
    _Tier(percentile=None, otsu_offset=+10,
          area_min_frac=0.005, area_max_frac=0.20,
          aspect_max=5.0, fill_min=0.55, name="otsu_tight"),
    _Tier(percentile=None, otsu_offset=0,
          area_min_frac=0.003, area_max_frac=0.30,
          aspect_max=6.0, fill_min=0.40, name="otsu_loose"),
]


def _pad_mask(gray: np.ndarray, *, tier: _Tier) -> np.ndarray:
    """Binary mask of bright pads using the tier's threshold strategy.

    Strategies:
      * percentile=P  → threshold at the P-th percentile of blurred intensities.
                         Robust when the image is dark overall with small bright
                         pads — Otsu would split dark-vs-mid, missing the pads.
      * percentile=None → Otsu threshold + otsu_offset (classic bimodal split).

    Pipeline:
      * threshold (strategy)
      * close 31x31 to stitch pad patches together
      * open 5x5 to drop speckle
    """
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    if tier.percentile is not None:
        thresh = float(np.percentile(blurred, tier.percentile))
    else:
        level, _ = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        thresh = float(np.clip(level + tier.otsu_offset, 1.0, 250.0))

    _, th = cv2.threshold(blurred, thresh, 255, cv2.THRESH_BINARY)

    # 1. Open strips individual mesh-speckle dots.
    # 2. Size filter — with speckles now isolated, drop every connected component
    #    below the smallest valid-pad area. CRITICAL so that the next close step
    #    cannot bridge the pad into any residual speckle cluster.
    # 3. Small close to stitch ring notches WITHOUT bridging adjacent pads.
    #    A pad with a dark ball is a bright "ring"; small breaks in the ring
    #    would leak the external contour through to the ball hole. 21x21 is big
    #    enough to seal those notches but smaller than typical pad-to-pad gaps,
    #    so 4-pad arrays stay separate. Filling the (often large) ball hole is
    #    NOT this step's job — the next fill_holes step handles that.
    # 4. Fill holes on every external contour so the pad becomes a solid
    #    polygon — this is what fills the ball hole inside each pad's outline.
    open_k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (11, 11))
    th = cv2.morphologyEx(th, cv2.MORPH_OPEN, open_k)

    frame_area = th.shape[0] * th.shape[1]
    min_blob_area = int(frame_area * 0.0025)  # below smallest valid-pad area
    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(th, connectivity=8)
    if num_labels > 1:
        filtered = np.zeros_like(th)
        for i in range(1, num_labels):  # label 0 is background
            if stats[i, cv2.CC_STAT_AREA] >= min_blob_area:
                filtered[labels == i] = 255
        th = filtered

    close_k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (11, 11))
    th = cv2.morphologyEx(th, cv2.MORPH_CLOSE, close_k)

    # Use convex hull, not the raw contour, for the fill step. A real bond pad
    # is a convex shape (square/rectangle); after threshold, the bright pad
    # ring around the dark ball often has tiny notches that connect interior
    # to exterior. The external contour then "leaks" inward and represents
    # only the thin ring instead of the full pad — fill_ratio drops to 0.2-0.4
    # and the pad gets rejected. Convex hull seals those leaks: the hull of a
    # broken/notched ring is the full pad outline. Drawing it FILLED gives the
    # solid pad-shaped blob downstream code expects.
    contours, _ = cv2.findContours(th, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if contours:
        filled = np.zeros_like(th)
        hulls = [cv2.convexHull(c) for c in contours]
        cv2.drawContours(filled, hulls, -1, 255, thickness=cv2.FILLED)
        th = filled
    return th


def _find_all_pad_contours(
    gray: np.ndarray,
) -> tuple[list[tuple[np.ndarray, float]], str]:
    """Multi-pad mode: walk EVERY tier strict→loose, accumulate every pad that
    passes its filters, then dedup overlapping detections of the same physical
    pad (kept at the strictest tier where it first appeared).

    Returning at the first tier with hits — like single-pad mode does — misses
    any pad that needs a looser tier than its sibling. Walking the full ladder
    and deduplicating by centroid proximity catches mixed-brightness frames
    (e.g. one bright pad + one dimmer pad with a large dark ball).

    Returns (list_of_(contour, score), tier_label). `tier_label` is "p92+p90"
    style when results came from multiple tiers.
    """
    h, w = gray.shape
    frame_area = float(w * h)
    edge_margin = 4

    accepted_all: list[tuple[np.ndarray, float, str, float, float, float]] = []
    # tuple = (contour, score, tier_name, cx, cy, mean_side_px) — last three
    # are used for dedup (centroid distance vs. typical pad radius).

    seen_tiers: list[str] = []
    for tier in _TIERS:
        th = _pad_mask(gray, tier=tier)
        contours, _ = cv2.findContours(th, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            continue
        tier_hit = False
        for c in contours:
            area = cv2.contourArea(c)
            if area < frame_area * tier.area_min_frac or area > frame_area * tier.area_max_frac:
                continue
            rect = cv2.minAreaRect(c)
            (rcx, rcy), (rw, rh), _ = rect
            if rw < 3 or rh < 3:
                continue
            bx, by, bw, bh = cv2.boundingRect(c)
            if (bx < edge_margin or by < edge_margin
                or bx + bw > w - edge_margin or by + bh > h - edge_margin):
                continue
            aspect = max(rw, rh) / max(1.0, min(rw, rh))
            if aspect > tier.aspect_max:
                continue
            rect_area = rw * rh
            fill = area / max(1.0, rect_area)
            if fill < tier.fill_min:
                continue
            score = (area / frame_area) * (1.0 / np.sqrt(aspect)) * fill
            mean_side = (rw + rh) * 0.5

            # Dedup: if this contour's centroid is within ~half the previously
            # detected pad's mean side, treat it as the same pad and skip
            # (earlier tier was stricter, so its detection is preferred).
            is_dup = False
            for _c0, _s0, _t0, cx0, cy0, ms0 in accepted_all:
                dist = float(np.hypot(rcx - cx0, rcy - cy0))
                threshold = 0.5 * max(mean_side, ms0)
                if dist < threshold:
                    is_dup = True
                    break
            if is_dup:
                continue

            accepted_all.append((c, float(score), tier.name,
                                 float(rcx), float(rcy), float(mean_side)))
            tier_hit = True
        if tier_hit and tier.name not in seen_tiers:
            seen_tiers.append(tier.name)

    if not accepted_all:
        return [], "none"

    # Size-similarity filter: real bond pads on the same die share the same
    # design size, so any "extra" pad whose area is much smaller than the
    # dominant detection is almost certainly a fragment / artefact from a
    # looser tier (especially common when a real pad's mask splinters at lower
    # thresholds and a piece falls outside the dedup centroid radius).
    areas = [float(cv2.contourArea(t[0])) for t in accepted_all]
    max_area = max(areas)
    min_keep_area = max_area * 0.40
    accepted_all = [
        t for t, a in zip(accepted_all, areas) if a >= min_keep_area
    ]

    accepted_all.sort(key=lambda t: t[1], reverse=True)
    out = [(c, s) for (c, s, _t, _cx, _cy, _ms) in accepted_all]
    label = "+".join(seen_tiers) if seen_tiers else "none"
    return out, label


def _find_pad_contour(
    gray: np.ndarray,
    *,
    seed_center: tuple[float, float] | None = None,
    diag: dict[str, Any] | None = None,
) -> tuple[np.ndarray, float, str] | None:
    """Score every bright-pad contour, trying progressively looser tiers.

    If `diag` is a dict, per-tier statistics are written into it for debug logging.
    """
    h, w = gray.shape
    frame_area = float(w * h)
    tx, ty = seed_center if seed_center is not None else (w / 2.0, h / 2.0)

    edge_margin = 4  # touches-edge rejection needs to be small — real pads can brush frame bounds

    for tier in _TIERS:
        th = _pad_mask(gray, tier=tier)
        contours, _ = cv2.findContours(th, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        tier_diag: dict[str, Any] = {
            "white_px": int((th > 0).sum()),
            "contours": len(contours),
            "rejections": [],
            "accepted": None,
        }
        if diag is not None:
            diag[tier.name] = tier_diag
        if not contours:
            continue

        def score(c: np.ndarray, t: _Tier = tier) -> float:
            area = cv2.contourArea(c)
            area_frac = area / frame_area
            rect = cv2.minAreaRect(c)
            (rcx, rcy), (rw, rh), _ = rect
            bx, by, bw, bh = cv2.boundingRect(c)
            reason = None
            if area < frame_area * t.area_min_frac:
                reason = f"too_small area={area_frac:.3%}"
            elif area > frame_area * t.area_max_frac:
                reason = f"too_big area={area_frac:.3%}"
            elif rw < 3 or rh < 3:
                reason = "degenerate_rect"
            elif (bx < edge_margin or by < edge_margin
                  or bx + bw > w - edge_margin or by + bh > h - edge_margin):
                reason = "touches_edge"
            if reason:
                tier_diag["rejections"].append(reason)
                return -1e9

            aspect = max(rw, rh) / max(1.0, min(rw, rh))
            rect_area = rw * rh
            fill = area / max(1.0, rect_area)
            if aspect > t.aspect_max:
                tier_diag["rejections"].append(f"aspect={aspect:.2f}")
                return -1e9
            if fill < t.fill_min:
                tier_diag["rejections"].append(f"fill={fill:.2f}")
                return -1e9

            # `sqrt(aspect)` softens the aspect penalty so a 4:1 long pad can
            # still beat a smaller, lower-fill square — without removing the
            # bias toward squares when both are equally good.
            base = (area / frame_area) * (1.0 / np.sqrt(aspect)) * fill

            if seed_center is not None:
                inside = cv2.pointPolygonTest(c, (float(tx), float(ty)), False) >= 0
                if inside:
                    return base * 10.0
                dist = np.hypot(rcx - tx, rcy - ty)
                return base * (1.0 / (1.0 + dist / w))

            dist = np.hypot(rcx - tx, rcy - ty)
            return base * (1.0 / (1.0 + dist / w))

        best: np.ndarray | None = None
        best_score = -1e9
        for c in contours:
            s = score(c)
            if s > best_score:
                best_score = s
                best = c
        if best is not None and best_score > 0:
            rect = cv2.minAreaRect(best)
            (rcx, rcy), (rw, rh), _ = rect
            tier_diag["accepted"] = {
                "center": (int(rcx), int(rcy)),
                "rect_px": (float(rw), float(rh)),
                "area_px": float(cv2.contourArea(best)),
                "score": float(best_score),
            }
            return best, float(best_score), tier.name

    return None


def detect_pad(
    fused: np.ndarray,
    *,
    pixel_size_um: float,
    source_a_name: str = "",
    source_b_name: str = "",
    seed_center: tuple[float, float] | None = None,
) -> PadMeasurement:
    """Locate the pad and measure it using a rotated rectangle that hugs its edges.

    The rotated rect (`cv2.minAreaRect`) is the tightest rectangle that still
    contains the whole contour — so it follows the pad's actual orientation and
    doesn't inflate when the pad is slightly tilted vs. the camera axes.

    Raises ValueError if no bright contour in the valid size range exists.
    """
    gray = cv2.cvtColor(fused, cv2.COLOR_BGR2GRAY)

    diag: dict[str, Any] = {}
    result = _find_pad_contour(gray, seed_center=seed_center, diag=diag)
    if result is None:
        # Dump the fused image + each tier's mask so we can see why.
        try:
            _dump_failure_debug(fused, gray, diag)
        except Exception:
            log.exception("failed to dump debug")
        summary = " | ".join(
            f"{name}: {d['contours']}c, rej={','.join(d['rejections'][:3])}"
            for name, d in diag.items()
        )
        log.error("pad detection failed. Tier summary: %s", summary)
        raise ValueError(
            "No pad contour found — see logs/pad_fail_*.png for diagnostics "
            "(fused image + mask of each tier). You can also click the pad "
            "to seed detection."
        )
    contour, _score, tier_name = result

    # Rotated rect — this is what we report as the pad dimensions.
    rect = cv2.minAreaRect(contour)
    (rcx, rcy), (rw, rh), angle = rect
    corners = cv2.boxPoints(rect)
    corners_int = [(int(round(px)), int(round(py))) for (px, py) in corners]

    # Axis-aligned bbox for UI / ROI convenience.
    ax, ay, aw, ah = cv2.boundingRect(contour)

    pad_w = float(min(rw, rh))
    pad_h = float(max(rw, rh))
    area_px = float(cv2.contourArea(contour))
    rect_area = float(max(1.0, rw * rh))
    aspect = float(pad_h / max(1.0, pad_w))
    fill = float(area_px / rect_area)

    width_um = pad_w * pixel_size_um
    height_um = pad_h * pixel_size_um
    diagonal_um = float(np.hypot(width_um, height_um))
    area_um2 = area_px * pixel_size_um * pixel_size_um

    # Confidence is driven by fill_ratio (how cleanly the contour matches a
    # rectangle) rather than aspect — long/skinny rectangular pads are valid
    # parts and shouldn't auto-flag as low confidence just for being long.
    if fill >= 0.88:
        confidence = "high"
    elif fill >= 0.70:
        confidence = "medium"
    else:
        confidence = "low"

    return PadMeasurement(
        x_px=int(ax), y_px=int(ay),
        width_px=int(aw), height_px=int(ah),
        center_x_px=int(round(rcx)), center_y_px=int(round(rcy)),
        pad_w_px=pad_w, pad_h_px=pad_h,
        angle_deg=float(angle),
        corners_px=corners_int,
        width_um=float(width_um), height_um=float(height_um),
        diagonal_um=diagonal_um,
        area_px2=int(round(area_px)), area_um2=float(area_um2),
        aspect_ratio=aspect,
        fill_ratio=fill,
        confidence=confidence,
        method=(
            f"otsu_rotrect_{tier_name}+seed"
            if seed_center is not None
            else f"otsu_rotrect_{tier_name}"
        ),
        pixel_size_um=float(pixel_size_um),
        source_a_name=source_a_name,
        source_b_name=source_b_name,
        seeded=seed_center is not None,
    )


# --------------------------------------------------------------------- ball detection


def _refine_ball_radius_radial(
    gray_roi: np.ndarray,
    cx: float, cy: float,
    r_coarse: float,
    *,
    search_window_frac: float = 0.5,
) -> float:
    """Refine ball radius to the VISUAL outer edge using the radial intensity
    gradient on the GRAYSCALE roi.

    The dark→bright transition has three phases as we walk outward:
        interior (flat dark) → ramp (steep positive gradient) → exterior (flat bright)
    Hough/mask methods land near the GRADIENT PEAK (mid-ramp), which is a few
    pixels INSIDE where the eye sees the ball end. The visual edge sits at the
    OUTER end of the ramp — where the gradient subsides back to the noise
    floor. We find the peak first, then walk outward until the gradient drops
    below 30% of peak; that point is reported as the refined radius.

    Returns r_coarse unchanged if the search window is too small or the
    gradient signal is too weak to be trusted.
    """
    h, w = gray_roi.shape
    if not (0 <= cx < w and 0 <= cy < h):
        return r_coarse
    max_possible_r = int(min(cx, w - cx, cy, h - cy)) - 2
    if max_possible_r < 10:
        return r_coarse

    yy, xx = np.indices((h, w), dtype=np.float32)
    dist = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2).astype(np.int32)

    # Cap radius array length to what's reachable from (cx, cy).
    max_r = min(max_possible_r, int(r_coarse * 2.0))
    flat_d = dist.ravel()
    flat_g = gray_roi.astype(np.float64).ravel()
    # Mask out radii that lie outside our cap so they don't bleed into the bincount.
    valid = flat_d <= max_r
    counts = np.bincount(flat_d[valid], minlength=max_r + 1)[: max_r + 1]
    sums = np.bincount(flat_d[valid], weights=flat_g[valid], minlength=max_r + 1)[: max_r + 1]
    with np.errstate(divide="ignore", invalid="ignore"):
        profile = np.where(counts > 0, sums / np.maximum(counts, 1), 0.0)

    # Smooth so per-pixel speckle in the rim doesn't dominate the gradient peak.
    k = np.ones(7, dtype=np.float64) / 7.0
    profile_s = np.convolve(profile, k, mode="same")
    deriv = np.gradient(profile_s)

    half = max(8, int(round(r_coarse * search_window_frac)))
    r_lo = max(5, int(round(r_coarse)) - half)
    r_hi = min(max_r - 2, int(round(r_coarse)) + half)
    if r_hi - r_lo < 3:
        return r_coarse

    window = deriv[r_lo:r_hi + 1]
    if window.size == 0:
        return r_coarse
    # The ball-to-pad edge is a dark→bright transition → positive derivative.
    peak_idx = int(np.argmax(window))
    r_peak = r_lo + peak_idx
    peak_val = float(window[peak_idx])

    # Sanity: refined edge gradient should be clearly positive vs the noise floor.
    floor = float(np.median(np.abs(deriv)) + 1e-6)
    if peak_val < 2.5 * floor:
        return r_coarse

    # Walk INWARD from the gradient peak until the derivative drops to 80% of
    # peak — just 2-3 px inside the steepest-slope point. The visible dark
    # area ends slightly INSIDE the gradient peak (where the ramp begins to
    # rise out of the dark interior). 80% lands tight against the visible
    # dark blob with no visible gap; lower values (50%) cut into the dark
    # interior; higher (peak) leaves a small halo gap.
    inner_thresh = peak_val * 0.80
    r_inner = r_peak
    walk_limit = max(r_lo, r_peak - max(3, int(r_coarse * 0.08)))
    for r in range(r_peak - 1, walk_limit - 1, -1):
        if deriv[r] < inner_thresh:
            r_inner = r
            break
    else:
        r_inner = walk_limit

    return float(r_inner)


def _detect_ball_hough(
    gray_full: np.ndarray,
    pad: PadMeasurement,
    *,
    pixel_size_um: float,
    seed_xy_fused: tuple[float, float] | None = None,
) -> BallMeasurement | None:
    """Hough-Circle-based ball detection. Reliable when the pad surface isn't
    bright enough for the mask-based path (Otsu fails, dark mask spans the
    whole ROI). Hough uses the gradient signal directly — finds circular dark
    features even on dim/grey pad surfaces.

    Returns None if no plausible circle found inside the pad polygon. Caller
    is expected to fall back to the mask-based path in that case.
    """
    px, py, pw, ph = pad.x_px, pad.y_px, pad.width_px, pad.height_px
    # EXPAND the ROI outward by ~10% of the pad's shorter side. The ball can be
    # large enough that the gradient ramp extends past the pad bounding box;
    # if we shrink the ROI inward (the old behaviour) the ball falls partly
    # outside, the radial-gradient refiner runs out of profile, and the
    # detected radius gets truncated. The pad-polygon test below still keeps
    # the Hough centre inside the actual pad outline.
    margin = max(6, int(min(pw, ph) * 0.10))
    rx0 = max(0, px - margin)
    ry0 = max(0, py - margin)
    rx1 = min(gray_full.shape[1], px + pw + margin)
    ry1 = min(gray_full.shape[0], py + ph + margin)
    if rx1 - rx0 < 30 or ry1 - ry0 < 30:
        return None
    roi = gray_full[ry0:ry1, rx0:rx1]

    # Median + Gaussian: median strips speckle, Gaussian smooths the gradient
    # signal that HoughCircles relies on.
    blurred = cv2.medianBlur(roi, 5)
    blurred = cv2.GaussianBlur(blurred, (5, 5), 1.5)

    pad_min = float(min(pad.pad_w_px, pad.pad_h_px))
    min_r = max(8, int(pad_min * 0.15))
    max_r = max(min_r + 5, int(pad_min * 0.48))
    min_dist = max(20, int(pad_min * 0.5))

    pad_poly_fused = np.array(pad.corners_px, dtype=np.int32)

    # Run Hough at multiple parameter settings and pool every valid circle.
    # Different (param1, param2) pairs land on slightly different radii — the
    # accumulator can lock onto either the gradient PEAK (mid-ramp, smaller r)
    # or the gradient TAIL (visual edge, larger r). Pooling lets us favour the
    # larger reading per pad, which matches what an operator sees.
    raw: list[tuple[float, float, float, float, float]] = []
    # tuple = (cx_roi, cy_roi, r, inner_mean, contrast)

    for p1, p2 in [(80, 30), (60, 25), (50, 18), (40, 15)]:
        circles = cv2.HoughCircles(
            blurred, cv2.HOUGH_GRADIENT,
            dp=1.2, minDist=min_dist,
            param1=p1, param2=p2,
            minRadius=min_r, maxRadius=max_r,
        )
        if circles is None:
            continue
        for cx, cy, r in circles[0]:
            cx_fused = float(cx) + rx0
            cy_fused = float(cy) + ry0
            if cv2.pointPolygonTest(pad_poly_fused,
                                    (cx_fused, cy_fused), False) < 0:
                continue
            # Darkness contrast: real ball has inner < outer by a wide margin.
            inner_mask = np.zeros(roi.shape, dtype=np.uint8)
            cv2.circle(inner_mask, (int(cx), int(cy)), int(r * 0.7), 255, -1)
            if not (inner_mask > 0).any():
                continue
            inner_mean = float(roi[inner_mask > 0].mean())
            outer_mask = np.zeros(roi.shape, dtype=np.uint8)
            cv2.circle(outer_mask, (int(cx), int(cy)), int(r * 1.4), 255, -1)
            cv2.circle(outer_mask, (int(cx), int(cy)), int(r * 1.05), 0, -1)
            outer_pixels = roi[outer_mask > 0]
            if outer_pixels.size == 0:
                continue
            outer_mean = float(outer_pixels.mean())
            contrast = outer_mean - inner_mean
            if contrast < 18.0:
                continue
            raw.append(
                (float(cx), float(cy), float(r), inner_mean, contrast)
            )

    # Cluster by centre proximity — different param settings often return the
    # SAME physical ball at slightly different radii. Within each cluster keep
    # the LARGEST radius (Hough's accumulator preference for the gradient peak
    # otherwise undersizes the ball).
    candidates: list[tuple[float, float, float, float, float]] = []
    cluster_radius_px = max(8.0, pad_min * 0.08)
    raw.sort(key=lambda t: t[2], reverse=True)  # largest r first
    for cand in raw:
        cx, cy, r, im, ct = cand
        merged = False
        for j, (kx, ky, kr, kim, kct) in enumerate(candidates):
            if (cx - kx) ** 2 + (cy - ky) ** 2 < cluster_radius_px ** 2:
                # Already represented — drop the smaller-radius copy.
                if r > kr:
                    candidates[j] = cand
                merged = True
                break
        if not merged:
            candidates.append(cand)

    if not candidates:
        return None

    # If operator clicked, prefer circles whose interior contains the click.
    if seed_xy_fused is not None:
        sx_roi = seed_xy_fused[0] - rx0
        sy_roi = seed_xy_fused[1] - ry0
        seeded = [
            t for t in candidates
            if (t[0] - sx_roi) ** 2 + (t[1] - sy_roi) ** 2 <= t[2] ** 2
        ]
        if seeded:
            candidates = seeded

    # Score: contrast is the dominant cue (real balls are markedly darker
    # than the surrounding pad). Tiebreak by closeness to pad centre.
    cx_roi_centre = (rx1 - rx0) / 2.0
    cy_roi_centre = (ry1 - ry0) / 2.0
    roi_diag = float(np.hypot(rx1 - rx0, ry1 - ry0))

    def _score(t: tuple[float, float, float, float, float]) -> float:
        cx, cy, _r, _im, contrast = t
        d = float(np.hypot(cx - cx_roi_centre, cy - cy_roi_centre)) / max(1.0, roi_diag)
        return contrast * (1.0 - min(1.0, d * 1.5))

    candidates.sort(key=_score, reverse=True)
    cx_best, cy_best, r_best, inner_mean, contrast = candidates[0]

    # Refine: nudge the radius outward to the actual edge using radial gradient
    # on the gray ROI. Hough is sometimes a few pixels short.
    r_refined = _refine_ball_radius_radial(
        roi, cx_best, cy_best, r_best, search_window_frac=0.25,
    )
    # Hard physical cap — the ball can't be wider than the pad's narrow side
    # (it has to fit on the pad). Refine can otherwise walk past the ROI's
    # gradient noise floor and report an impossibly large radius.
    r_max_physical = float(max_r)  # same as Hough's maxRadius (0.48 * pad_min)
    if r_refined > r_max_physical:
        r_refined = r_max_physical

    cx_abs = cx_best + rx0
    cy_abs = cy_best + ry0
    diameter_px = 2.0 * r_refined

    # Estimate "fill" and "circularity" for compatibility with the existing
    # quality fields. Hough circles are by definition circular (1.0) but we
    # compute fill from the dark pixels inside the circle vs. circle area.
    inside_mask = np.zeros(roi.shape, dtype=np.uint8)
    cv2.circle(inside_mask, (int(cx_best), int(cy_best)), int(round(r_best)),
               255, -1)
    dark_thresh = inner_mean + max(15.0, contrast * 0.4)
    dark_pixels = ((roi < dark_thresh) & (inside_mask > 0)).sum()
    fill = float(dark_pixels) / max(1.0, np.pi * r_best * r_best)
    fill = min(1.0, max(0.0, fill))

    method = (
        "hough+radial_edge"
        if abs(r_refined - r_best) > 0.5 else "hough"
    )
    return BallMeasurement(
        center_x_px=int(round(cx_abs)),
        center_y_px=int(round(cy_abs)),
        radius_px=float(r_refined),
        diameter_px=float(diameter_px),
        radius_um=float(r_refined * pixel_size_um),
        diameter_um=float(diameter_px * pixel_size_um),
        circularity=1.0,  # Hough output is by definition circular
        fill_ratio=fill,
        method=method,
        pixel_size_um=float(pixel_size_um),
    )


def detect_ball_in_pad(
    fused: np.ndarray,
    pad: PadMeasurement,
    *,
    pixel_size_um: float,
    seed_xy_fused: tuple[float, float] | None = None,
) -> BallMeasurement | None:
    """Find the dark circular ball impression inside a detected pad.

    Two-stage pipeline:
      1. HoughCircles (primary) — works even when Otsu can't separate the
         ball from a dim pad surface.
      2. Mask-based dark-blob (fallback) — used when Hough returns no valid
         circle. Picks the largest, darkest, most-centred dark contour.

    `seed_xy_fused` (operator click in fused coords) is honoured by both
    stages: blobs/circles whose interior contains the click are preferred.
    Returns None when neither stage finds a plausible ball.
    """
    gray = cv2.cvtColor(fused, cv2.COLOR_BGR2GRAY)

    # Primary: Hough — much more reliable than mask thresholding for
    # circular features on grey/textured surfaces.
    hough_result = _detect_ball_hough(
        gray, pad, pixel_size_um=pixel_size_um, seed_xy_fused=seed_xy_fused,
    )
    if hough_result is not None:
        return hough_result
    px, py, pw, ph = pad.x_px, pad.y_px, pad.width_px, pad.height_px

    # Inset slightly so pad edges / shadows don't leak into the dark-region mask.
    inset = max(6, int(min(pw, ph) * 0.06))
    rx0 = max(0, px + inset)
    ry0 = max(0, py + inset)
    rx1 = min(gray.shape[1], px + pw - inset)
    ry1 = min(gray.shape[0], py + ph - inset)
    if rx1 - rx0 < 30 or ry1 - ry0 < 30:
        return None

    roi = gray[ry0:ry1, rx0:rx1]
    rh, rw = roi.shape

    # Invert so the ball (originally dark) becomes bright → Otsu picks it naturally.
    inverted = cv2.bitwise_not(roi)
    blurred = cv2.GaussianBlur(inverted, (5, 5), 0)
    _, mask = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    # Clean: strip thin speckle only. Skip an aggressive close — that inflates the
    # blob outside the true ball boundary and the inscribed-circle radius suffers.
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, k)
    k_small = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, k_small)
    ext, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if ext:
        filled = np.zeros_like(mask)
        cv2.drawContours(filled, ext, -1, 255, thickness=cv2.FILLED)
        mask = filled

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None

    # Score: prefer large, circular, centred, plausibly sized.
    cx_roi = rw / 2.0
    cy_roi = rh / 2.0
    pad_area_px = max(1.0, pad.pad_w_px * pad.pad_h_px)
    roi_diag = float(np.hypot(rw, rh))

    # Pad polygon (rotated rect corners) in fused-image coords — used to reject
    # ball candidates whose centre falls outside the actual pad outline. The
    # axis-aligned bbox can be larger than the pad polygon (especially after
    # convex-hull fill), so without this check, `detect_ball_in_pad` can latch
    # onto a dark blob that bleeds into the surrounding die / mesh area.
    pad_poly_fused = np.array(pad.corners_px, dtype=np.int32)

    # Optional operator-supplied seed: convert from fused coords to ROI coords
    # so we can test whether a contour contains the click.
    seed_in_roi: tuple[float, float] | None = None
    if seed_xy_fused is not None:
        sx_fused, sy_fused = seed_xy_fused
        seed_in_roi = (sx_fused - rx0, sy_fused - ry0)

    best: dict[str, Any] | None = None
    best_seed_hit: dict[str, Any] | None = None  # candidates that contain the seed
    for c in contours:
        area = float(cv2.contourArea(c))
        if area < 100.0:
            continue
        # A realistic ball sits somewhere between 3% and 85% of the pad's rotated area.
        frac_of_pad = area / pad_area_px
        if frac_of_pad < 0.03 or frac_of_pad > 0.85:
            continue
        perim = float(cv2.arcLength(c, True))
        if perim <= 0:
            continue
        circularity = min(1.0, 4 * np.pi * area / (perim * perim))

        # Centroid — stable centre regardless of rim noise.
        M = cv2.moments(c)
        if abs(M["m00"]) < 1e-6:
            continue
        cx_cnt = float(M["m10"] / M["m00"])
        cy_cnt = float(M["m01"] / M["m00"])

        # Reject if the centroid lies outside the actual pad rotated-rect.
        # This is the key guard against blobs that extend through the pad
        # bounding box into surrounding non-pad area.
        cx_fused = cx_cnt + rx0
        cy_fused = cy_cnt + ry0
        if cv2.pointPolygonTest(pad_poly_fused,
                                (float(cx_fused), float(cy_fused)),
                                False) < 0:
            continue

        # Inscribed-circle radius from the distance transform of THIS contour's
        # mask alone. Beats the area-equivalent radius `sqrt(area/π)` when the
        # dark blob isn't a clean disc — irregular extensions inflate `area`
        # but not the inscribed disc, so the starting radius stays inside the
        # actual ball impression.
        single_mask = np.zeros_like(mask)
        cv2.drawContours(single_mask, [c], -1, 255, thickness=cv2.FILLED)
        dt_local = cv2.distanceTransform(single_mask, cv2.DIST_L2, 5)
        _, r_inscribed_val, _, _ = cv2.minMaxLoc(dt_local)
        r_inscribed = float(r_inscribed_val)
        if r_inscribed < 3:
            continue

        # Diagnostic: how filled is the contour within its min-enclosing circle?
        _, r_enc = cv2.minEnclosingCircle(c)
        fill = area / max(1.0, np.pi * r_enc * r_enc)

        dist_norm = float(np.hypot(cx_cnt - cx_roi, cy_cnt - cy_roi)) / max(1.0, roi_diag)
        score = circularity * fill * (1.0 - min(1.0, dist_norm * 2.0))

        candidate = {
            "score": score,
            "cx": cx_cnt, "cy": cy_cnt,
            "r_coarse": r_inscribed,
            "circ": circularity, "fill": fill,
        }

        # If the operator provided a seed, prefer contours that actually contain
        # the click. Among seed-hits we pick the highest-scoring one; if no
        # contour contains the seed we fall back to the global best.
        if seed_in_roi is not None:
            inside = cv2.pointPolygonTest(
                c, (float(seed_in_roi[0]), float(seed_in_roi[1])), False,
            ) >= 0
            if inside and (best_seed_hit is None or score > best_seed_hit["score"]):
                best_seed_hit = candidate

        if best is None or score > best["score"]:
            best = candidate

    if best_seed_hit is not None:
        best = best_seed_hit
    elif best is None:
        return None

    # Quality gate — reject "ball" candidates that are clearly not balls. A real
    # gold-bond ball has high circularity and a high contour-fill against its
    # enclosing circle. When the pad has no actual ball (e.g. long bond-finger
    # pads), the darkest blob in the ROI is dust / texture / wire shadow with
    # very low circularity. Returning None makes the UI show "BALL not detected"
    # rather than drawing a misleading red zone over a non-ball feature.
    if best["circ"] < 0.40 or best["fill"] < 0.40:
        return None

    cx_roi_abs = best["cx"]
    cy_roi_abs = best["cy"]
    r_coarse = best["r_coarse"]

    # Refine radius using the radial intensity gradient on the original gray ROI.
    # This catches the actual dark→bright edge instead of the (often inflated)
    # threshold-mask boundary.
    r_refined = _refine_ball_radius_radial(roi, cx_roi_abs, cy_roi_abs, r_coarse)
    method = "dark_blob+radial_edge" if abs(r_refined - r_coarse) > 0.5 else "dark_blob_in_pad"

    cx_abs = cx_roi_abs + rx0
    cy_abs = cy_roi_abs + ry0
    diameter_px = 2.0 * r_refined
    return BallMeasurement(
        center_x_px=int(round(cx_abs)),
        center_y_px=int(round(cy_abs)),
        radius_px=float(r_refined),
        diameter_px=float(diameter_px),
        radius_um=float(r_refined * pixel_size_um),
        diameter_um=float(diameter_px * pixel_size_um),
        circularity=float(best["circ"]),
        fill_ratio=float(best["fill"]),
        method=method,
        pixel_size_um=float(pixel_size_um),
    )


# --------------------------------------------------------------------- gap / annulus


def compute_gap(pad: PadMeasurement) -> GapMeasurement | None:
    """Perpendicular distance from the ball edge to each of the pad's four sides.

    Assumes `pad.ball` is set and `pad.corners_px` has 4 corners. Returns None
    otherwise. Gap is edge-distance minus ball radius; negative values mean the
    ball overlaps the pad edge (a warning condition for the operator).
    """
    if pad.ball is None or not pad.corners_px or len(pad.corners_px) != 4:
        return None

    bx = float(pad.ball.center_x_px)
    by = float(pad.ball.center_y_px)
    br = float(pad.ball.radius_px)
    corners = [(float(x), float(y)) for (x, y) in pad.corners_px]

    gaps_px: list[float] = []
    for i in range(4):
        ax, ay = corners[i]
        cx, cy = corners[(i + 1) % 4]
        ex, ey = cx - ax, cy - ay
        len_sq = ex * ex + ey * ey
        if len_sq < 1e-9:
            gaps_px.append(0.0)
            continue
        # Parameter along the segment of the closest point
        t = ((bx - ax) * ex + (by - ay) * ey) / len_sq
        t = max(0.0, min(1.0, t))
        fx = ax + t * ex
        fy = ay + t * ey
        edge_dist = float(np.hypot(bx - fx, by - fy))
        gaps_px.append(edge_dist - br)

    min_px = min(gaps_px)
    max_px = max(gaps_px)
    mean_px = sum(gaps_px) / 4.0
    min_side = int(gaps_px.index(min_px))

    px_um = pad.pixel_size_um
    per_side_um = [g * px_um for g in gaps_px]

    # Annulus area = pad contour area minus ball disc area.
    ball_area_px = float(np.pi * br * br)
    annulus_px = max(0.0, float(pad.area_px2) - ball_area_px)

    return GapMeasurement(
        min_gap_px=float(min_px), max_gap_px=float(max_px), mean_gap_px=float(mean_px),
        min_gap_um=float(min_px * px_um),
        max_gap_um=float(max_px * px_um),
        mean_gap_um=float(mean_px * px_um),
        min_gap_side=min_side,
        per_side_um=per_side_um,
        annulus_area_px2=annulus_px,
        annulus_area_um2=float(annulus_px * px_um * px_um),
    )


def adjust_ball_radius(pad: PadMeasurement, delta_px: float) -> PadMeasurement:
    """Return a copy of `pad` whose ball radius is shifted by `delta_px` and gap
    is recomputed. Used by the UI tightness slider."""
    if pad.ball is None:
        return pad
    new_r = max(1.0, float(pad.ball.radius_px) + float(delta_px))
    ball = pad.ball
    adj_ball = BallMeasurement(
        center_x_px=ball.center_x_px,
        center_y_px=ball.center_y_px,
        radius_px=new_r,
        diameter_px=2.0 * new_r,
        radius_um=new_r * pad.pixel_size_um,
        diameter_um=2.0 * new_r * pad.pixel_size_um,
        circularity=ball.circularity,
        fill_ratio=ball.fill_ratio,
        method=f"{ball.method} r{delta_px:+.0f}px",
        pixel_size_um=ball.pixel_size_um,
    )
    from dataclasses import replace
    new_pad = replace(pad, ball=adj_ball, gap=None)
    new_pad.gap = compute_gap(new_pad)
    return new_pad


# --------------------------------------------------------------------- overlays


def _draw_pill(
    out: np.ndarray,
    text: str,
    center_xy: tuple[int, int],
    *,
    text_color: tuple[int, int, int] = (255, 255, 255),
    bg_color: tuple[int, int, int] = (35, 35, 35),
    border_color: tuple[int, int, int] | None = None,
    font_scale: float = 1.4,
    pad_x: int = 18,
    pad_y: int = 10,
    text_thickness: int = 2,
) -> tuple[int, int, int, int]:
    """Draw a rounded "pill" with text centred at `center_xy`.

    Returns the pill's bounding rect (x, y, w, h) so callers can chain placements.
    """
    font = cv2.FONT_HERSHEY_SIMPLEX
    (text_w, text_h), baseline = cv2.getTextSize(text, font, font_scale, text_thickness)
    box_w = text_w + 2 * pad_x
    box_h = text_h + 2 * pad_y
    cx, cy = center_xy
    x = int(cx - box_w / 2)
    y = int(cy - box_h / 2)
    radius = min(14, box_h // 2)

    # Filled body — rectangle minus corners + 4 corner circles
    cv2.rectangle(out, (x + radius, y), (x + box_w - radius, y + box_h), bg_color, -1, cv2.LINE_AA)
    cv2.rectangle(out, (x, y + radius), (x + box_w, y + box_h - radius), bg_color, -1, cv2.LINE_AA)
    for (cx_corner, cy_corner) in [
        (x + radius, y + radius),
        (x + box_w - radius, y + radius),
        (x + radius, y + box_h - radius),
        (x + box_w - radius, y + box_h - radius),
    ]:
        cv2.circle(out, (cx_corner, cy_corner), radius, bg_color, -1, cv2.LINE_AA)

    # Optional border (rounded outline) — drawn as 4 lines + 4 corner arcs.
    if border_color is not None:
        bw = 2
        cv2.line(out, (x + radius, y), (x + box_w - radius, y), border_color, bw, cv2.LINE_AA)
        cv2.line(out, (x + radius, y + box_h), (x + box_w - radius, y + box_h), border_color, bw, cv2.LINE_AA)
        cv2.line(out, (x, y + radius), (x, y + box_h - radius), border_color, bw, cv2.LINE_AA)
        cv2.line(out, (x + box_w, y + radius), (x + box_w, y + box_h - radius), border_color, bw, cv2.LINE_AA)
        for (cx_corner, cy_corner, ang_start, ang_end) in [
            (x + radius, y + radius, 180, 270),
            (x + box_w - radius, y + radius, 270, 360),
            (x + box_w - radius, y + box_h - radius, 0, 90),
            (x + radius, y + box_h - radius, 90, 180),
        ]:
            cv2.ellipse(out, (cx_corner, cy_corner), (radius, radius), 0,
                        ang_start, ang_end, border_color, bw, cv2.LINE_AA)

    # Text — placed so its baseline sits inside the pill nicely.
    text_x = x + pad_x
    text_y = y + box_h - pad_y - 2
    cv2.putText(out, text, (text_x, text_y),
                font, font_scale, text_color, text_thickness, cv2.LINE_AA)
    return x, y, box_w, box_h


def _draw_pad_shape(out: np.ndarray, m: PadMeasurement) -> None:
    """Draw the green pad rectangle + cyan centre marker on `out` in-place."""
    if m.corners_px and len(m.corners_px) == 4:
        pts = np.array(m.corners_px, dtype=np.int32)
        cv2.polylines(out, [pts], isClosed=True, color=(0, 255, 0), thickness=3)
    cv2.drawMarker(
        out, (m.center_x_px, m.center_y_px),
        (0, 255, 255), cv2.MARKER_CROSS, 24, 2,
    )


def _draw_ball_zone(out: np.ndarray, m: PadMeasurement) -> np.ndarray:
    """Gold disc + crisp outline + white centre marker.

    BGR (110, 215, 255) is a warm gold that stands out on textured silicon
    and metal backgrounds. Opacity 0.55 keeps the underlying ball visible
    underneath while making the detection zone unmistakable.
    """
    if m.ball is None:
        return out
    layer = out.copy()
    fill_color = (130, 215, 255)   # BGR — warm gold (rgb #ffd782)
    edge_color = (40, 165, 220)    # deeper gold for the rim
    cv2.circle(
        layer,
        (m.ball.center_x_px, m.ball.center_y_px),
        int(round(m.ball.radius_px)),
        fill_color, thickness=cv2.FILLED,
    )
    out = cv2.addWeighted(layer, 0.30, out, 0.70, 0)
    cv2.circle(
        out, (m.ball.center_x_px, m.ball.center_y_px),
        int(round(m.ball.radius_px)),
        edge_color, thickness=2, lineType=cv2.LINE_AA,
    )
    cv2.drawMarker(
        out, (m.ball.center_x_px, m.ball.center_y_px),
        (255, 255, 255), cv2.MARKER_CROSS, 14, 2,
    )
    return out


def _draw_gap_lines_per_side(out: np.ndarray, m: PadMeasurement, *, unit: str = "um") -> None:
    """Modern gap visualisation:

    - Solid line from ball edge to pad edge for each of the 4 sides.
    - Tick marks at both endpoints (perpendicular short lines).
    - Rounded pill label on each side showing the µm/mil value.
    - The MIN gap side gets a thicker, brighter line and a coloured pill border.
    """
    if m.gap is None or m.ball is None or not m.corners_px or len(m.corners_px) != 4:
        return
    scale, unit_str = _unit_scale(unit)

    bx = float(m.ball.center_x_px)
    by = float(m.ball.center_y_px)
    br = float(m.ball.radius_px)

    color_normal = (220, 200, 130)
    color_min    = (255, 80, 220)
    pill_bg      = (32, 32, 32)
    pill_text    = (245, 245, 245)
    # UI scale: half-strength so overlay never dominates the image. Labels are
    # placed OUTSIDE the pad along the gap-line direction so they don't cover
    # the ball/pad zone the operator is looking at.
    s = max(0.8, out.shape[1] / 1400.0)
    line_norm = max(2, int(round(2 * s)))
    line_min  = max(3, int(round(3 * s)))
    # Distance from the pad-edge foot, measured along the gap-line direction,
    # to the centre of the pill. Pushes the label clear of the pad outline.
    label_outside_offset = int(round(35 * s))

    for i in range(4):
        ax, ay = m.corners_px[i]
        cx, cy = m.corners_px[(i + 1) % 4]
        ex, ey = cx - ax, cy - ay
        len_sq = ex * ex + ey * ey
        if len_sq < 1e-9:
            continue
        t = ((bx - ax) * ex + (by - ay) * ey) / len_sq
        t = max(0.0, min(1.0, t))
        fx = ax + t * ex
        fy = ay + t * ey
        dx = fx - bx
        dy = fy - by
        dlen = (dx * dx + dy * dy) ** 0.5
        if dlen <= 1e-6:
            continue
        sx = bx + (dx / dlen) * br   # foot at ball edge
        sy = by + (dy / dlen) * br

        is_min = (i == m.gap.min_gap_side)
        line_color = color_min if is_min else color_normal
        line_thickness = line_min if is_min else line_norm
        out_x = dx / dlen
        out_y = dy / dlen

        # 1. Gap line: ball edge → pad edge (the actual measurement zone)
        cv2.line(out,
                 (int(round(sx)), int(round(sy))),
                 (int(round(fx)), int(round(fy))),
                 line_color, line_thickness, cv2.LINE_AA)

        # 2. Compute pill dimensions first so we can shove the entire pill —
        # not just its centre — clear of the pad boundary.
        gap_um_i = m.gap.per_side_um[i]
        if unit == "mil":
            label = f"{gap_um_i * scale:.2f}"
        else:
            label = f"{gap_um_i:.1f}"
        if is_min:
            label = "MIN " + label
        font = cv2.FONT_HERSHEY_SIMPLEX
        pill_font = 0.7 * s
        pill_pad_x = int(10 * s)
        pill_pad_y = int(5 * s)
        pill_text_th = max(1, int(round(1.5 * s)))
        (tw, th), _ = cv2.getTextSize(label, font, pill_font, pill_text_th)
        pill_w = tw + 2 * pill_pad_x
        pill_h = th + 2 * pill_pad_y
        # L1-projection of half-pill onto outward direction = how far the
        # pill's NEAREST edge sits from its centre along that vector.
        half_extent = abs(out_x) * (pill_w / 2.0) + abs(out_y) * (pill_h / 2.0)

        # 3. Leader line: from pad edge outward, just up to the pill's near edge.
        leader_end_x = fx + out_x * label_outside_offset
        leader_end_y = fy + out_y * label_outside_offset
        cv2.line(out,
                 (int(round(fx)), int(round(fy))),
                 (int(round(leader_end_x)), int(round(leader_end_y))),
                 line_color, max(1, line_thickness - 1), cv2.LINE_AA)

        # 4. Pill centre = leader end + half pill in outward direction so the
        # pill body never crosses back into the pad.
        label_cx = int(round(leader_end_x + out_x * half_extent))
        label_cy = int(round(leader_end_y + out_y * half_extent))
        _draw_pill(
            out, label, (label_cx, label_cy),
            text_color=pill_text, bg_color=pill_bg,
            border_color=line_color,
            font_scale=pill_font,
            pad_x=pill_pad_x, pad_y=pill_pad_y,
            text_thickness=pill_text_th,
        )


def _ui_scale(out: np.ndarray) -> float:
    """Scale factor based on image width — keeps overlays legible at canvas size
    without dominating the image."""
    return max(0.8, out.shape[1] / 1400.0)


def _draw_pad_label(out: np.ndarray, m: PadMeasurement, *, unit: str = "um") -> None:
    s, u = _unit_scale(unit)
    z = _ui_scale(out)
    pad_line = f"PAD  {m.width_um * s:.1f} x {m.height_um * s:.1f} {u}"
    pad_sub = (
        f"area {m.area_um2 * s * s:.0f} {u}^2   ({m.method}, {m.confidence})"
    )
    if m.seeded:
        pad_sub += "  [seed]"
    cv2.putText(out, pad_line, (int(16 * z), int(28 * z)),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8 * z, (0, 255, 0),
                max(1, int(round(1.5 * z))), cv2.LINE_AA)
    cv2.putText(out, pad_sub, (int(16 * z), int(50 * z)),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5 * z, (0, 255, 0),
                max(1, int(round(1.2 * z))), cv2.LINE_AA)


def _draw_ball_label(out: np.ndarray, m: PadMeasurement, *, y: int = 100, unit: str = "um") -> None:
    s, u = _unit_scale(unit)
    z = _ui_scale(out)
    y_scaled = int(70 * z)  # placed under PAD sub
    if m.ball is not None:
        ball_line = (
            f"BALL  d={m.ball.diameter_um * s:.1f} {u}   "
            f"circ {m.ball.circularity:.2f}   fill {m.ball.fill_ratio:.2f}"
        )
        cv2.putText(out, ball_line, (int(16 * z), y_scaled),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6 * z, (0, 0, 255),
                    max(1, int(round(1.3 * z))), cv2.LINE_AA)
    else:
        cv2.putText(out, "BALL  not detected", (int(16 * z), y_scaled),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55 * z, (120, 120, 255),
                    max(1, int(round(1.2 * z))), cv2.LINE_AA)


def draw_multi_pad_overlay(
    fused: np.ndarray,
    pads: list[PadMeasurement],
    *,
    unit: str = "um",
) -> np.ndarray:
    """Render every detected pad with its ball + gap on a single image.

    Each pad gets a small "#N" badge near its top-left corner so the operator
    can match overlay annotations with the result-panel table rows.
    """
    out = fused.copy()
    if not pads:
        return out
    z = _ui_scale(out)

    for i, m in enumerate(pads, start=1):
        _draw_pad_shape(out, m)
        out = _draw_ball_zone(out, m)
        _draw_gap_lines_per_side(out, m, unit=unit)
        # Badge "#N" pinned at the pad's top-left corner so it doesn't collide
        # with the gap labels (which sit at top/right/bottom/left midpoints).
        bx, by = m.x_px, m.y_px
        _draw_pill(
            out, f"#{i}", (bx + int(18 * z), by - int(8 * z)),
            text_color=(255, 255, 255), bg_color=(20, 90, 20),
            border_color=(80, 220, 80),
            font_scale=0.7 * z,
            pad_x=int(8 * z), pad_y=int(4 * z),
            text_thickness=max(1, int(round(1.5 * z))),
        )
    return out


def draw_pad_only_overlay(img: np.ndarray, m: PadMeasurement, *, unit: str = "um") -> np.ndarray:
    """Used by the Focus-Pad preview — show ONLY the green pad rectangle + label."""
    out = img.copy()
    _draw_pad_shape(out, m)
    _draw_pad_label(out, m, unit=unit)
    return out


def draw_ball_only_overlay(img: np.ndarray, m: PadMeasurement, *, unit: str = "um") -> np.ndarray:
    """Used by the Focus-Ball preview — show ONLY the red ball zone + label."""
    out = img.copy()
    out = _draw_ball_zone(out, m)
    _draw_ball_label(out, m, y=40, unit=unit)
    return out


def draw_multi_ball_only_overlay(
    img: np.ndarray, pads: list[PadMeasurement], *, unit: str = "um",
) -> np.ndarray:
    """Focus-Ball preview when there are multiple pads — draw every ball zone."""
    out = img.copy()
    for m in pads:
        out = _draw_ball_zone(out, m)
    return out


def draw_multi_pad_only_overlay(
    img: np.ndarray, pads: list[PadMeasurement], *, unit: str = "um",
) -> np.ndarray:
    """Focus-Pad preview when there are multiple pads — draw every pad rectangle."""
    out = img.copy()
    z = _ui_scale(out)
    for i, m in enumerate(pads, start=1):
        _draw_pad_shape(out, m)
        bx, by = m.x_px, m.y_px
        _draw_pill(
            out, f"#{i}", (bx + int(18 * z), by - int(8 * z)),
            text_color=(255, 255, 255), bg_color=(20, 90, 20),
            border_color=(80, 220, 80),
            font_scale=0.7 * z,
            pad_x=int(8 * z), pad_y=int(4 * z),
            text_thickness=max(1, int(round(1.5 * z))),
        )
    return out


def draw_pad_overlay(fused: np.ndarray, m: PadMeasurement, *, unit: str = "um") -> np.ndarray:
    """Full annotated overlay — pad + ball zone + per-side gap labels + summary."""
    out = fused.copy()
    _draw_pad_shape(out, m)
    out = _draw_ball_zone(out, m)
    _draw_gap_lines_per_side(out, m, unit=unit)
    _draw_pad_label(out, m, unit=unit)
    _draw_ball_label(out, m, y=100, unit=unit)

    s, u = _unit_scale(unit)
    z = _ui_scale(out)
    if m.gap is not None:
        g = m.gap
        gap_summary = (
            f"GAP  min {g.min_gap_um * s:.1f}  max {g.max_gap_um * s:.1f}  "
            f"mean {g.mean_gap_um * s:.1f} {u}"
        )
        # Compact pill at top-left below PAD/BALL labels — out of pad area.
        font = cv2.FONT_HERSHEY_SIMPLEX
        (tw, th), _ = cv2.getTextSize(gap_summary, font, 0.5 * z, 1)
        center_x = int(16 * z) + tw // 2 + int(10 * z)
        center_y = int(95 * z)
        _draw_pill(
            out, gap_summary, (center_x, center_y),
            text_color=(255, 200, 255), bg_color=(50, 20, 60),
            border_color=(255, 80, 220),
            font_scale=0.5 * z,
            pad_x=int(8 * z), pad_y=int(4 * z),
            text_thickness=max(1, int(round(1.2 * z))),
        )
    return out


def _dump_multi_debug(
    fused: np.ndarray,
    gray: np.ndarray,
    accepted: list[tuple[np.ndarray, float]],
    tier_label: str,
) -> None:
    """Dump every tier's mask + a summary so the user can see why pads were
    accepted/rejected in multi-pad mode. Triggered on every measure call when
    `debug_dump=True` so the operator never has to re-trigger the failure."""
    out_dir = Path("logs")
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    h, w = gray.shape
    frame_area = float(w * h)
    edge_margin = 4

    cv2.imwrite(str(out_dir / f"multi_{ts}_fused.png"), fused)

    # Annotate each tier's mask with what passed/failed
    summary_lines: list[str] = [
        f"Multi-pad detection at {ts}",
        f"Image: {w}x{h}  min={int(gray.min())} max={int(gray.max())} mean={gray.mean():.1f}",
        f"Accepted (post-dedup, post-size-filter): {len(accepted)}  tiers={tier_label}",
        "",
    ]

    for tier in _TIERS:
        th = _pad_mask(gray, tier=tier)
        cv2.imwrite(str(out_dir / f"multi_{ts}_mask_{tier.name}.png"), th)
        contours, _ = cv2.findContours(th, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        summary_lines.append(
            f"Tier {tier.name}: {len(contours)} contour(s), white_px={int((th>0).sum())}"
        )
        for i, c in enumerate(contours):
            area = cv2.contourArea(c)
            area_frac = area / frame_area
            rect = cv2.minAreaRect(c)
            (rcx, rcy), (rw, rh), _ = rect
            bx, by, bw, bh = cv2.boundingRect(c)
            aspect = max(rw, rh) / max(1.0, min(rw, rh)) if min(rw, rh) > 0 else 0
            rect_area = rw * rh
            fill = area / max(1.0, rect_area)
            reasons = []
            if area < frame_area * tier.area_min_frac:
                reasons.append(f"area_too_small({area_frac:.3%})")
            if area > frame_area * tier.area_max_frac:
                reasons.append(f"area_too_big({area_frac:.3%})")
            if rw < 3 or rh < 3:
                reasons.append("degenerate_rect")
            if (bx < edge_margin or by < edge_margin
                or bx + bw > w - edge_margin or by + bh > h - edge_margin):
                reasons.append("touches_edge")
            if aspect > tier.aspect_max:
                reasons.append(f"aspect={aspect:.2f}>max{tier.aspect_max}")
            if fill < tier.fill_min:
                reasons.append(f"fill={fill:.2f}<min{tier.fill_min}")
            verdict = "ACCEPT" if not reasons else "reject(" + ",".join(reasons) + ")"
            summary_lines.append(
                f"  c{i}: area={area_frac:.3%} rect={rw:.0f}x{rh:.0f} "
                f"@({rcx:.0f},{rcy:.0f}) aspect={aspect:.2f} fill={fill:.2f} → {verdict}"
            )
        summary_lines.append("")

    with (out_dir / f"multi_{ts}_summary.txt").open("w", encoding="utf-8") as f:
        f.write("\n".join(summary_lines))
    log.info("multi-pad debug → logs/multi_%s_*", ts)


def _dump_failure_debug(fused: np.ndarray, gray: np.ndarray, diag: dict[str, Any]) -> None:
    """When detection fails, write the fused frame + a mask per tier to logs/."""
    out_dir = Path("logs")
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    cv2.imwrite(str(out_dir / f"pad_fail_{ts}_fused.png"), fused)
    for tier in _TIERS:
        mask = _pad_mask(gray, tier=tier)
        cv2.imwrite(str(out_dir / f"pad_fail_{ts}_mask_{tier.name}.png"), mask)

    # Human-readable summary
    with (out_dir / f"pad_fail_{ts}_summary.txt").open("w", encoding="utf-8") as f:
        f.write(f"Pad detection failed at {ts}\n")
        f.write(f"Image: {gray.shape[1]}x{gray.shape[0]}  "
                f"min={int(gray.min())} max={int(gray.max())} mean={gray.mean():.1f}\n\n")
        for name, d in diag.items():
            f.write(f"Tier {name}: white_px={d['white_px']}  contours={d['contours']}\n")
            f.write(f"  rejections: {d['rejections']}\n")
            if d['accepted']:
                f.write(f"  accepted:   {d['accepted']}\n")
            f.write("\n")
    log.info("wrote debug files logs/pad_fail_%s_*", ts)


def debug_pad_overlay(fused: np.ndarray) -> np.ndarray:
    """Diagnostic view: all Otsu contours drawn, with the chosen pad highlighted.

    Yellow = rejected,  grey = outside valid size range,
    green fill + cyan bbox = chosen pad.  Red banner if nothing qualifies.
    """
    out = fused.copy()
    gray = cv2.cvtColor(fused, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape

    # Find which tier `_find_pad_contour` would pick, and visualise that tier's mask.
    pick = _find_pad_contour(gray)
    if pick is None:
        th = _pad_mask(gray, tier=_TIERS[0])
        tier_name_used = "none"
    else:
        _, _, tier_name_used = pick
        tier_used = next(t for t in _TIERS if t.name == tier_name_used)
        th = _pad_mask(gray, tier=tier_used)
    contours, _ = cv2.findContours(th, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    frame_area = float(w * h)
    tx, ty = w / 2.0, h / 2.0

    edge_margin = 12

    def score(c: np.ndarray) -> float:
        area = cv2.contourArea(c)
        if area < frame_area * 0.003 or area > frame_area * 0.30:
            return -1e9
        rect = cv2.minAreaRect(c)
        (rcx, rcy), (rw, rh), _ = rect
        if rw < 3 or rh < 3:
            return -1e9
        bx, by, bw, bh = cv2.boundingRect(c)
        if (bx < edge_margin or by < edge_margin
            or bx + bw > w - edge_margin or by + bh > h - edge_margin):
            return -1e9
        aspect = max(rw, rh) / max(1.0, min(rw, rh))
        if aspect > 3.0:
            return -1e9
        rect_area = rw * rh
        fill = area / max(1.0, rect_area)
        if fill < 0.4:
            return -1e9
        dist = np.hypot(rcx - tx, rcy - ty)
        return (area / frame_area) * (1.0 / (1.0 + dist / w)) * (1.0 / aspect) * fill

    scored = sorted([(score(c), c) for c in contours], key=lambda t: t[0], reverse=True)
    chosen: np.ndarray | None = scored[0][1] if scored and scored[0][0] > 0 else None

    for s, c in scored:
        if chosen is not None and c is chosen:
            continue
        if s <= -1e8:
            cv2.drawContours(out, [c], -1, (120, 120, 120), 1)
        else:
            cv2.drawContours(out, [c], -1, (0, 220, 220), 1)

    if chosen is not None:
        fill_layer = out.copy()
        cv2.drawContours(fill_layer, [chosen], -1, (0, 200, 0), thickness=cv2.FILLED)
        out = cv2.addWeighted(fill_layer, 0.30, out, 0.70, 0)
        cv2.drawContours(out, [chosen], -1, (0, 255, 0), 3)
        rect = cv2.minAreaRect(chosen)
        (rcx, rcy), (rw, rh), ang = rect
        box = cv2.boxPoints(rect).astype(np.int32)
        cv2.polylines(out, [box], True, (255, 200, 0), 2)
        area = cv2.contourArea(chosen)
        label = f"PAD  rot-rect {min(rw,rh):.0f}x{max(rw,rh):.0f} px   area={int(area)} px^2   {ang:+.1f} deg"
        tx_pos = int(min(p[0] for p in box))
        ty_pos = max(30, int(min(p[1] for p in box)) - 12)
        cv2.putText(out, label, (tx_pos, ty_pos),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 255, 0), 2, cv2.LINE_AA)
    else:
        cv2.putText(out, "PAD NOT FOUND", (20, 60),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 255), 2, cv2.LINE_AA)

    cv2.putText(
        out,
        f"Pad detection debug  ({len(scored)} contours, tier={tier_name_used})",
        (20, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2, cv2.LINE_AA,
    )
    cv2.putText(out, "green = chosen  yellow = rejected  grey = size/aspect/fill out of range",
                (20, out.shape[0] - 14),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1, cv2.LINE_AA)
    return out


# --------------------------------------------------------------------- convenience


def _build_pad_measurement(
    contour: np.ndarray,
    *,
    pixel_size_um: float,
    method: str,
    source_a_name: str,
    source_b_name: str,
    seeded: bool = False,
) -> PadMeasurement:
    """Build a PadMeasurement from a chosen contour."""
    rect = cv2.minAreaRect(contour)
    (rcx, rcy), (rw, rh), angle = rect
    corners = cv2.boxPoints(rect)
    corners_int = [(int(round(px)), int(round(py))) for (px, py) in corners]
    ax, ay, aw, ah = cv2.boundingRect(contour)

    pad_w = float(min(rw, rh))
    pad_h = float(max(rw, rh))
    area_px = float(cv2.contourArea(contour))
    rect_area = float(max(1.0, rw * rh))
    aspect = float(pad_h / max(1.0, pad_w))
    fill = float(area_px / rect_area)

    width_um = pad_w * pixel_size_um
    height_um = pad_h * pixel_size_um
    diagonal_um = float(np.hypot(width_um, height_um))
    area_um2 = area_px * pixel_size_um * pixel_size_um

    if fill >= 0.88:
        confidence = "high"
    elif fill >= 0.70:
        confidence = "medium"
    else:
        confidence = "low"

    return PadMeasurement(
        x_px=int(ax), y_px=int(ay),
        width_px=int(aw), height_px=int(ah),
        center_x_px=int(round(rcx)), center_y_px=int(round(rcy)),
        pad_w_px=pad_w, pad_h_px=pad_h,
        angle_deg=float(angle),
        corners_px=corners_int,
        width_um=float(width_um), height_um=float(height_um),
        diagonal_um=diagonal_um,
        area_px2=int(round(area_px)), area_um2=float(area_um2),
        aspect_ratio=aspect,
        fill_ratio=fill,
        confidence=confidence,
        method=method,
        pixel_size_um=float(pixel_size_um),
        source_a_name=source_a_name,
        source_b_name=source_b_name,
        seeded=seeded,
    )


def _try_merge_split_pad(
    contours: list[tuple[np.ndarray, float]],
    gray_ball: np.ndarray,
) -> list[tuple[np.ndarray, float]]:
    """Detect long pads that the threshold split into two halves because the
    ball is sitting on top of the pad's centre.

    A long pad with the ball obscuring the middle looks like two near-square
    bright halves with the ball as a dark gap between them. We merge such
    pairs into a single contour (the convex hull of both) when:
      * both halves have similar size + orientation
      * they're aligned along one axis (collinear centres)
      * the gap between them contains a circular dark feature (= the ball)
        — verified with HoughCircles on the focus-ball image

    The HoughCircles guard prevents over-merging genuinely separate pads in
    multi-pad arrays — there's no ball in the gap between adjacent pads.
    """
    if len(contours) < 2:
        return contours

    rects: list[tuple[tuple[float, float], tuple[float, float], float]] = []
    for c, _s in contours:
        rects.append(cv2.minAreaRect(c))

    used: set[int] = set()
    merged: list[tuple[np.ndarray, float]] = []

    for i in range(len(contours)):
        if i in used:
            continue
        ci, si = contours[i]
        (xi, yi), (wi, hi), ai = rects[i]
        min_i = min(wi, hi)
        max_i = max(wi, hi)

        for j in range(i + 1, len(contours)):
            if j in used:
                continue
            cj, sj = contours[j]
            (xj, yj), (wj, hj), aj = rects[j]
            min_j = min(wj, hj)
            max_j = max(wj, hj)

            # Size similarity — split halves should be near-equal.
            if abs(min_i - min_j) > max(min_i, min_j) * 0.25:
                continue
            if abs(max_i - max_j) > max(max_i, max_j) * 0.25:
                continue

            # Orientation similarity — angles wrap at 90°.
            angle_diff = abs(ai - aj) % 90.0
            angle_diff = min(angle_diff, 90.0 - angle_diff)
            if angle_diff > 12.0:
                continue

            # Centres should be reasonably close (gap < pad's longer side).
            cdist = float(np.hypot(xi - xj, yi - yj))
            mean_long = (max_i + max_j) / 2.0
            if cdist < mean_long * 0.5 or cdist > mean_long * 2.0:
                continue

            # Carve out the GAP (between contour edges, not centre-to-centre)
            # along the axis that connects the two centres. Centre-to-centre
            # would also enclose the two pads' own balls, leading to bogus
            # merges between genuinely separate pads.
            bx_i, by_i, bw_i, bh_i = cv2.boundingRect(ci)
            bx_j, by_j, bw_j, bh_j = cv2.boundingRect(cj)
            x_gap_lo = max(bx_i + bw_i, bx_j + bw_j)
            x_gap_hi = min(bx_i + bw_i, bx_j + bw_j)
            # Determine gap rectangle on the axis-aligned bbox (good enough
            # for nearly-axis-aligned pads — most production cases).
            if bx_j > bx_i + bw_i:           # j is to the RIGHT of i
                gx0 = bx_i + bw_i
                gx1 = bx_j
            elif bx_i > bx_j + bw_j:         # i is to the RIGHT of j
                gx0 = bx_j + bw_j
                gx1 = bx_i
            else:                             # overlap on x — gap is along y
                gx0 = max(bx_i, bx_j)
                gx1 = min(bx_i + bw_i, bx_j + bw_j)
            if by_j > by_i + bh_i:
                gy0 = by_i + bh_i
                gy1 = by_j
            elif by_i > by_j + bh_j:
                gy0 = by_j + bh_j
                gy1 = by_i
            else:
                gy0 = max(by_i, by_j)
                gy1 = min(by_i + bh_i, by_j + bh_j)
            # Pad the gap slightly so a ball whose edge brushes a pad still
            # lies in the cropped ROI.
            pad_pix = int(max(min_i, min_j) * 0.10)
            x0 = max(0, gx0 - pad_pix)
            y0 = max(0, gy0 - pad_pix)
            x1 = min(gray_ball.shape[1], gx1 + pad_pix)
            y1 = min(gray_ball.shape[0], gy1 + pad_pix)
            if x1 - x0 < 20 or y1 - y0 < 20:
                continue
            gap_roi = gray_ball[y0:y1, x0:x1]
            blurred = cv2.medianBlur(gap_roi, 5)
            blurred = cv2.GaussianBlur(blurred, (5, 5), 1.5)
            min_r = max(8, int(min(min_i, min_j) * 0.15))
            max_r = max(min_r + 5, int(min(min_i, min_j) * 0.6))
            circles = cv2.HoughCircles(
                blurred, cv2.HOUGH_GRADIENT,
                dp=1.2, minDist=20,
                param1=60, param2=20,
                minRadius=min_r, maxRadius=max_r,
            )
            if circles is None:
                continue
            # Validate: the circle must be DARKER than its surroundings.
            ball_found = False
            for cx, cy, r in circles[0]:
                inner_mask = np.zeros(gap_roi.shape, dtype=np.uint8)
                cv2.circle(inner_mask, (int(cx), int(cy)), int(r * 0.7), 255, -1)
                if not (inner_mask > 0).any():
                    continue
                inner_mean = float(gap_roi[inner_mask > 0].mean())
                outer_mask = np.zeros(gap_roi.shape, dtype=np.uint8)
                cv2.circle(outer_mask, (int(cx), int(cy)), int(r * 1.4), 255, -1)
                cv2.circle(outer_mask, (int(cx), int(cy)), int(r * 1.05), 0, -1)
                if not (outer_mask > 0).any():
                    continue
                outer_mean = float(gap_roi[outer_mask > 0].mean())
                if outer_mean - inner_mean >= 18.0:
                    ball_found = True
                    break
            if not ball_found:
                continue

            # All checks passed — merge ci+cj into the convex hull.
            combined = np.vstack([ci, cj])
            hull = cv2.convexHull(combined)
            hull_rect = cv2.minAreaRect(hull)
            (hcx, hcy), (hw, hh), _ = hull_rect
            hull_area = float(hw * hh)
            indiv_area = float(cv2.contourArea(ci) + cv2.contourArea(cj))
            # Sanity: the hull should be a clean rectangle once merged
            # (high fill of pad-pieces vs hull bbox).
            if indiv_area / max(1.0, hull_area) < 0.45:
                continue
            log.info(
                "merged split pad: contours %d+%d -> hull rect %dx%d",
                i, j, int(min(hw, hh)), int(max(hw, hh)),
            )
            merged.append((hull, max(si, sj)))
            used.add(i)
            used.add(j)
            break

    for k in range(len(contours)):
        if k not in used:
            merged.append(contours[k])

    return merged


def detect_pads_multi(
    fused_for_pad: np.ndarray,
    fused_for_ball: np.ndarray,
    *,
    pixel_size_um: float,
    source_a_name: str = "",
    source_b_name: str = "",
    debug_dump: bool = True,
) -> list[PadMeasurement]:
    """Detect ALL pads in the frame and run ball/gap detection on each.

    `fused_for_pad`  — image used for pad-edge detection (typically Focus-Pad)
    `fused_for_ball` — image used for ball-edge detection (typically Focus-Ball)

    Returns a list of PadMeasurement, sorted by score (best first). Empty list
    if no pad clears the filters.

    If `debug_dump` is True, writes per-tier masks + a summary text to logs/
    so the user can see why a particular pad was rejected.
    """
    gray_pad = cv2.cvtColor(fused_for_pad, cv2.COLOR_BGR2GRAY)
    accepted, tier_name = _find_all_pad_contours(gray_pad)

    # Long-pad recovery: when the ball sits on top of a long rectangular pad,
    # threshold splits the pad into two bright halves with a dark gap. Merge
    # such pairs back into a single contour, gated by HoughCircles seeing a
    # ball in the gap (so genuinely separate pads are NOT over-merged).
    if len(accepted) >= 2:
        gray_ball = cv2.cvtColor(fused_for_ball, cv2.COLOR_BGR2GRAY)
        accepted = _try_merge_split_pad(accepted, gray_ball)

    if debug_dump:
        try:
            _dump_multi_debug(fused_for_pad, gray_pad, accepted, tier_name)
        except Exception:
            log.exception("multi-pad debug dump failed")

    if not accepted:
        return []

    pads: list[PadMeasurement] = []
    for contour, _score in accepted:
        m = _build_pad_measurement(
            contour,
            pixel_size_um=pixel_size_um,
            method=f"otsu_rotrect_{tier_name}[FocusPad]",
            source_a_name=source_a_name,
            source_b_name=source_b_name,
        )
        # Ball detection inside this pad on the Focus-Ball frame.
        try:
            ball = detect_ball_in_pad(fused_for_ball, m, pixel_size_um=pixel_size_um)
            if ball is not None:
                ball.method = f"{ball.method}[FocusBall]"
            m.ball = ball
        except Exception:
            log.exception("ball-in-pad failed for pad center=(%d,%d)",
                          m.center_x_px, m.center_y_px)
            m.ball = None
        m.gap = compute_gap(m)
        pads.append(m)

    # Drop pads where ball detection failed when at least one other pad has a
    # ball. Pads without balls in a multi-pad frame are almost always false
    # positives — chip markings / metal traces / partial pads. When EVERY
    # candidate lacks a ball we keep them all (single-pad images shouldn't
    # silently return nothing).
    pads_with_ball = [m for m in pads if m.ball is not None]
    if pads_with_ball and len(pads_with_ball) < len(pads):
        dropped = len(pads) - len(pads_with_ball)
        log.info("dropping %d pad(s) without ball (likely false positives)", dropped)
        pads = pads_with_ball

    return pads


def detect_pad_best_of(
    candidates: list[tuple[str, np.ndarray]],
    *,
    pixel_size_um: float,
    source_a_name: str = "",
    source_b_name: str = "",
    seed_center: tuple[float, float] | None = None,
) -> tuple[PadMeasurement, str, np.ndarray]:
    """Try detecting on every candidate image and return the cleanest fit.

    Focus-stacking helps for ball detection but introduces micro-notches at the
    pad edge that lower fill_ratio. Running detection on each source frame and
    on the fused composite, then taking the result with the highest fill_ratio,
    consistently beats using any single image.

    Returns (measurement, winning_label, winning_image). The image is returned
    so callers can cache it for click-refinement against the same frame the
    measurement came from.
    """
    best: PadMeasurement | None = None
    best_label = ""
    best_image: np.ndarray | None = None
    errors: list[str] = []
    for label, img in candidates:
        try:
            m = detect_pad(
                img,
                pixel_size_um=pixel_size_um,
                source_a_name=source_a_name,
                source_b_name=source_b_name,
                seed_center=seed_center,
            )
        except ValueError as e:
            errors.append(f"{label}: {e}")
            continue
        if best is None or m.fill_ratio > best.fill_ratio:
            best = m
            best_label = label
            best_image = img
    if best is None or best_image is None:
        raise ValueError(
            "No pad contour found in any candidate image. Attempts:\n  "
            + "\n  ".join(errors)
        )
    best.method = f"{best.method}[{best_label}]"

    # Ball: run `detect_ball_in_pad` on every candidate using the chosen pad's
    # bbox, then pick the frame whose ball has the cleanest edge
    # (fill_ratio * circularity). Pad and ball may come from different frames,
    # which is the point — focus planes for pad surface and ball surface differ.
    best_ball: BallMeasurement | None = None
    best_ball_label = ""
    for label, img in candidates:
        try:
            ball = detect_ball_in_pad(img, best, pixel_size_um=pixel_size_um)
        except Exception:
            log.exception("ball detection error on %s", label)
            continue
        if ball is None:
            continue
        ball_score = ball.fill_ratio * ball.circularity
        if best_ball is None or ball_score > (best_ball.fill_ratio * best_ball.circularity):
            best_ball = ball
            best_ball_label = label
    if best_ball is not None:
        best_ball.method = f"{best_ball.method}[{best_ball_label}]"
    best.ball = best_ball
    best.gap = compute_gap(best)
    return best, best_label, best_image


def measure_pair(
    path_a: Path | str,
    path_b: Path | str,
    *,
    pixel_size_um: float,
    seed_center: tuple[float, float] | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, PadMeasurement]:
    """Load both frames, focus-stack, then detect pad. Returns (fused, img_a, img_b, m)."""
    img_a = load_as_bgr(path_a)
    img_b = load_as_bgr(path_b)
    fused = focus_stack(img_a, img_b)
    m = detect_pad(
        fused,
        pixel_size_um=pixel_size_um,
        source_a_name=Path(path_a).name,
        source_b_name=Path(path_b).name,
        seed_center=seed_center,
    )
    return fused, img_a, img_b, m


def redetect(
    fused: np.ndarray,
    previous: PadMeasurement,
    *,
    seed_center: tuple[float, float],
    img_a: np.ndarray | None = None,  # accepted for API compat; not used for pad
    img_b: np.ndarray | None = None,
) -> PadMeasurement:
    """Re-run pad detection on the same fused image with a new click seed."""
    return detect_pad(
        fused,
        pixel_size_um=previous.pixel_size_um,
        source_a_name=previous.source_a_name,
        source_b_name=previous.source_b_name,
        seed_center=seed_center,
    )
