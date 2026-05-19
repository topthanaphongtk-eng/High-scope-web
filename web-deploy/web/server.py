"""Flask web monitor for High Scope Capture measurements.

Reads the SAME `measurements.db` the desktop app writes to, plus serves
TIFF/JSON files from the configured share folder so per-LOT detail pages
can show thumbnails. Fully read-only: the web layer never mutates the DB
(operators write through the desktop app).

Routes:
    /                    dashboard — recent LOTs + stats
    /lot/<lot_id>        per-LOT detail with all sessions
    /bonding/<num>       bonding × machine trend chart
    /image/<path>        serve a TIFF/PNG from share root (read-only)

API (JSON):
    /api/measurements    filterable list (since/until/bonding/machine/lot)
    /api/bondings        list of bonding × machine pairs with counts
    /api/lots            list of distinct LOTs (most recent first)
    /api/trend/<num>     trend series for one bonding (with machine filter)
"""

from __future__ import annotations

import io
import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import yaml
from flask import (
    Flask,
    Response,
    abort,
    jsonify,
    make_response,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from PIL import Image

import sys

# Allow importing `app.services.measurement_db` from a sibling package
# (the web app is shipped with the desktop project).
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.measurement_db import MeasurementDB  # noqa: E402

log = logging.getLogger(__name__)


# ------------------------------------------------------------------ config

def _load_settings() -> dict[str, Any]:
    """Load the desktop app's settings.yaml so the web reuses the same DB
    + share-root paths. Falls back to env vars + defaults."""
    here = Path(__file__).resolve().parent.parent / "config" / "settings.yaml"
    if here.exists():
        try:
            return yaml.safe_load(here.read_text(encoding="utf-8")) or {}
        except Exception:
            log.exception("failed to read settings.yaml")
    return {}


_settings = _load_settings()
_DB_PATH = Path(
    os.environ.get("MEASUREMENT_DB")
    or (ROOT / "logs" / "measurements.db")
).resolve()
_SHARE_ROOT = Path(
    os.environ.get("SHARE_ROOT")
    or _settings.get("storage", {}).get("shared_root")
    or "."
).resolve()

# ------------------------------------------------------------------ app


app = Flask(__name__)
app.config["JSON_SORT_KEYS"] = False
db = MeasurementDB(_DB_PATH)


# ------------------------------------------------------------------ unit handling

_MIL_PER_UM = 1.0 / 25.4


def _unit_choice() -> str:
    """Pick the active unit for this request: ?unit= overrides cookie."""
    candidate = (request.args.get("unit") or request.cookies.get("unit") or "um").lower()
    return "mil" if candidate == "mil" else "um"


def _unit_scale(unit: str) -> float:
    return _MIL_PER_UM if unit == "mil" else 1.0


@app.context_processor
def _inject_unit():
    """Make the active unit available to every template + JS payload."""
    unit = _unit_choice()
    return {
        "unit_choice": unit,
        "unit_scale": _unit_scale(unit),
        "unit_label": "mil" if unit == "mil" else "µm",
    }


@app.after_request
def _persist_unit_cookie(response: Response) -> Response:
    """Persist ?unit= → cookie so subsequent pages remember the choice."""
    requested = request.args.get("unit")
    if requested in ("um", "mil"):
        response.set_cookie(
            "unit", requested, max_age=60 * 60 * 24 * 90, samesite="Lax",
        )
    return response


# ------------------------------------------------------------------ helpers

def _parse_date(s: str | None) -> datetime | None:
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def _aggregate_per_lot(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse per-pad rows into per-LOT summaries: ball d avg / gap min avg
    across all locations, plus location coverage."""
    by_lot: dict[str, dict[str, Any]] = {}
    for r in rows:
        lid = r["lot_id"]
        bucket = by_lot.setdefault(lid, {
            "lot_id": lid,
            "bonding_number": r["bonding_number"],
            "lot_location": r.get("lot_location"),
            "mpc": r.get("mpc"),
            "package": r.get("package"),
            "operator_badge": r["operator_badge"],
            "confirmed_at": r["confirmed_at"],
            "session_id": r.get("session_id"),
            "ball_values": [],
            "gap_values": [],
            "locations": set(),
            "n_pads": 0,
        })
        if r.get("ball_d_um") is not None:
            bucket["ball_values"].append(float(r["ball_d_um"]))
        if r.get("gap_min_um") is not None:
            bucket["gap_values"].append(float(r["gap_min_um"]))
        bucket["locations"].add(r["location"])
        bucket["n_pads"] += 1
        # Keep the most recent confirmed_at for the LOT (rows can span
        # multiple sessions if re-measured).
        if r["confirmed_at"] > bucket["confirmed_at"]:
            bucket["confirmed_at"] = r["confirmed_at"]
            bucket["session_id"] = r.get("session_id")

    out: list[dict[str, Any]] = []
    for lid, b in by_lot.items():
        ball_v = b["ball_values"]
        gap_v = b["gap_values"]
        out.append({
            "lot_id": b["lot_id"],
            "bonding_number": b["bonding_number"],
            "lot_location": b["lot_location"],
            "mpc": b["mpc"],
            "package": b["package"],
            "operator_badge": b["operator_badge"],
            "confirmed_at": b["confirmed_at"],
            "session_id": b["session_id"],
            "ball_d_avg": (sum(ball_v) / len(ball_v)) if ball_v else None,
            "gap_min_avg": (sum(gap_v) / len(gap_v)) if gap_v else None,
            "locations": sorted(b["locations"]),
            "n_pads": b["n_pads"],
        })
    out.sort(key=lambda x: x["confirmed_at"], reverse=True)
    return out


def _trend_stats(values: list[float]) -> dict[str, float | None]:
    """3σ control limits computed from the leading values (oldest → before
    the latest). Latest is judged against prior variation, not itself."""
    base = values[:-1] if len(values) > 3 else values
    if len(base) < 3:
        return {"mean": None, "ucl": None, "lcl": None, "sigma": None}
    mean_v = sum(base) / len(base)
    var = sum((v - mean_v) ** 2 for v in base) / (len(base) - 1)
    sigma = var ** 0.5
    return {
        "mean": mean_v,
        "ucl": mean_v + 3 * sigma,
        "lcl": mean_v - 3 * sigma,
        "sigma": sigma,
    }


# ------------------------------------------------------------------ pages


@app.route("/")
def dashboard():
    """Landing page: hero stat cards + recent LOTs + bonding sidebar."""
    since = _parse_date(request.args.get("since"))
    until = _parse_date(request.args.get("until"))
    bonding = request.args.get("bonding") or None
    machine = request.args.get("machine") or None
    rows = db.export_json(
        since=since, until=until,
        bonding_number=bonding, lot_location=machine,
        limit=2000,
    )
    lots = _aggregate_per_lot(rows)

    # ---- Time buckets ----
    now = datetime.now()
    today      = now.replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday  = today - timedelta(days=1)
    week_start = today - timedelta(days=today.weekday())
    last_week_start = week_start - timedelta(days=7)
    month_start     = today.replace(day=1)
    last_month_end  = month_start
    last_month_start = (month_start - timedelta(days=1)).replace(day=1)

    def in_range(lo: datetime, hi: datetime) -> int:
        return sum(
            1 for l in lots
            if lo.isoformat() <= l["confirmed_at"] < hi.isoformat()
        )

    n_today        = in_range(today, today + timedelta(days=1))
    n_yesterday    = in_range(yesterday, today)
    n_week         = in_range(week_start, week_start + timedelta(days=7))
    n_last_week    = in_range(last_week_start, week_start)
    n_month        = in_range(month_start, today + timedelta(days=1))
    n_last_month   = in_range(last_month_start, last_month_end)

    def delta(curr: int, prev: int) -> dict:
        if prev == 0:
            return {"pct": None, "dir": "neutral", "abs": curr - prev}
        diff = curr - prev
        return {
            "pct": round(diff / prev * 100),
            "dir": "up" if diff > 0 else "down" if diff < 0 else "neutral",
            "abs": diff,
        }

    # ---- 14-day sparkline (one bar per day) ----
    spark = []
    for i in range(13, -1, -1):
        d = today - timedelta(days=i)
        n = in_range(d, d + timedelta(days=1))
        spark.append({"label": d.strftime("%m-%d"), "n": n})
    spark_max = max((s["n"] for s in spark), default=0) or 1

    # ---- Quality pulse (today's avg ball d / gap min, vs yesterday) ----
    def avg_metric(rows_in: list[dict], key: str) -> float | None:
        vals = [l[key] for l in rows_in if l.get(key) is not None]
        return (sum(vals) / len(vals)) if vals else None

    today_lots = [
        l for l in lots
        if today.isoformat() <= l["confirmed_at"] < (today + timedelta(days=1)).isoformat()
    ]
    yest_lots = [
        l for l in lots
        if yesterday.isoformat() <= l["confirmed_at"] < today.isoformat()
    ]
    pulse = {
        "ball_avg":     avg_metric(today_lots, "ball_d_avg"),
        "ball_avg_y":   avg_metric(yest_lots, "ball_d_avg"),
        "gap_avg":      avg_metric(today_lots, "gap_min_avg"),
        "gap_avg_y":    avg_metric(yest_lots, "gap_min_avg"),
        "operators":    len({l["operator_badge"] for l in today_lots}),
    }

    # ---- Bonding × machine summary for sidebar (with last-seen + count) ----
    bonding_acc: dict[tuple[str, str], dict] = {}
    for l in lots:
        key = (l["bonding_number"] or "—", l["lot_location"] or "—")
        b = bonding_acc.setdefault(key, {
            "bonding": key[0], "machine": key[1],
            "n": 0, "last_seen": l["confirmed_at"],
            "ball_avgs": [],
        })
        b["n"] += 1
        if l["confirmed_at"] > b["last_seen"]:
            b["last_seen"] = l["confirmed_at"]
        if l.get("ball_d_avg") is not None:
            b["ball_avgs"].append(l["ball_d_avg"])
    bondings_list: list[dict] = []
    for b in bonding_acc.values():
        ball_v = b.pop("ball_avgs")
        b["ball_avg"] = (sum(ball_v) / len(ball_v)) if ball_v else None
        bondings_list.append(b)
    bondings_list.sort(key=lambda b: b["last_seen"], reverse=True)

    return render_template(
        "dashboard.html",
        lots=lots[:200],
        n_today=n_today, n_week=n_week, n_month=n_month,
        n_total=len(lots),
        delta_today=delta(n_today, n_yesterday),
        delta_week=delta(n_week, n_last_week),
        delta_month=delta(n_month, n_last_month),
        spark=spark, spark_max=spark_max,
        pulse=pulse,
        bondings=bondings_list[:12],
        filter_since=request.args.get("since", ""),
        filter_until=request.args.get("until", ""),
        filter_bonding=bonding or "",
        filter_machine=machine or "",
        active_filter=bool(since or until or bonding or machine),
    )


@app.route("/lot/<path:lot_id>")
def lot_detail(lot_id: str):
    rows = db.export_json(limit=500)
    lot_rows = [r for r in rows if r["lot_id"] == lot_id]
    if not lot_rows:
        abort(404)
    # Pull all sessions for this LOT (chronological).
    sessions: dict[str, dict[str, Any]] = {}
    for r in lot_rows:
        sid = r.get("session_id") or "—"
        s = sessions.setdefault(sid, {
            "session_id": sid,
            "confirmed_at": r["confirmed_at"],
            "lot_location": r.get("lot_location"),
            "operator_badge": r["operator_badge"],
            "bonding_number": r["bonding_number"],
            "mpc": r.get("mpc"),
            "package": r.get("package"),
            "rows": [],
        })
        s["rows"].append(r)
    sessions_list = sorted(sessions.values(), key=lambda s: s["confirmed_at"], reverse=True)

    return render_template(
        "lot_detail.html",
        lot_id=lot_id,
        sessions=sessions_list,
        share_root=str(_SHARE_ROOT),
    )


@app.route("/bonding/<path:bonding>")
def bonding_view(bonding: str):
    machine = request.args.get("machine") or None
    rows = db.history_for_bonding(
        bonding, lot_location=machine, limit_lots=60,
    )
    lots = _aggregate_per_lot(rows)
    lots.sort(key=lambda x: x["confirmed_at"])  # oldest → newest for chart

    ball_series = [l["ball_d_avg"] for l in lots if l["ball_d_avg"] is not None]
    gap_series = [l["gap_min_avg"] for l in lots if l["gap_min_avg"] is not None]
    ball_stats = _trend_stats(ball_series)
    gap_stats = _trend_stats(gap_series)

    return render_template(
        "bonding.html",
        bonding=bonding,
        machine=machine or "—",
        lots=lots,
        ball_stats=ball_stats,
        gap_stats=gap_stats,
    )


# ------------------------------------------------------------------ image proxy


@app.route("/image")
def serve_image():
    """Serve a TIFF/PNG from inside `_SHARE_ROOT`. Refuses paths outside
    the share root (path-traversal guard). TIFFs are converted to JPEG
    on-the-fly so browsers can render them."""
    rel = request.args.get("path", "")
    if not rel:
        abort(400)
    target = (_SHARE_ROOT / rel).resolve()
    try:
        target.relative_to(_SHARE_ROOT)
    except ValueError:
        abort(403)
    if not target.exists() or not target.is_file():
        abort(404)
    if target.suffix.lower() in (".tif", ".tiff"):
        try:
            with Image.open(target) as im:
                rgb = im.convert("RGB")
                # Down-sample for the browser; full-res isn't needed.
                rgb.thumbnail((1200, 1200))
                buf = io.BytesIO()
                rgb.save(buf, format="JPEG", quality=85)
                buf.seek(0)
                return send_file(
                    buf, mimetype="image/jpeg",
                    download_name=target.with_suffix(".jpg").name,
                )
        except Exception:
            log.exception("TIFF preview failed for %s", target)
            abort(500)
    return send_file(target)


# ------------------------------------------------------------------ JSON API


@app.route("/api/measurements")
def api_measurements():
    since = _parse_date(request.args.get("since"))
    until = _parse_date(request.args.get("until"))
    bonding = request.args.get("bonding") or None
    machine = request.args.get("machine") or None
    limit = int(request.args.get("limit", "1000"))
    rows = db.export_json(
        since=since, until=until,
        bonding_number=bonding, lot_location=machine,
        limit=limit,
    )
    return jsonify({"count": len(rows), "rows": rows})


@app.route("/api/bondings")
def api_bondings():
    rows = db.export_json(limit=10000)
    counts: dict[tuple[str, str], dict[str, Any]] = {}
    for r in rows:
        key = (r["bonding_number"] or "", r["lot_location"] or "")
        c = counts.setdefault(key, {
            "bonding_number": key[0],
            "lot_location": key[1],
            "n_rows": 0,
            "n_lots": set(),
            "last_seen": r["confirmed_at"],
        })
        c["n_rows"] += 1
        c["n_lots"].add(r["lot_id"])
        if r["confirmed_at"] > c["last_seen"]:
            c["last_seen"] = r["confirmed_at"]
    out = []
    for c in counts.values():
        out.append({
            "bonding_number": c["bonding_number"],
            "lot_location": c["lot_location"],
            "n_rows": c["n_rows"],
            "n_lots": len(c["n_lots"]),
            "last_seen": c["last_seen"],
        })
    out.sort(key=lambda x: x["last_seen"], reverse=True)
    return jsonify(out)


@app.route("/api/lots")
def api_lots():
    rows = db.export_json(limit=int(request.args.get("limit", "1000")))
    return jsonify(_aggregate_per_lot(rows))


@app.route("/api/trend/<path:bonding>")
def api_trend(bonding: str):
    machine = request.args.get("machine") or None
    rows = db.history_for_bonding(
        bonding, lot_location=machine, limit_lots=60,
    )
    lots = _aggregate_per_lot(rows)
    lots.sort(key=lambda x: x["confirmed_at"])
    return jsonify({
        "bonding": bonding,
        "machine": machine,
        "points": [
            {
                "lot_id": l["lot_id"],
                "confirmed_at": l["confirmed_at"],
                "ball_d_avg": l["ball_d_avg"],
                "gap_min_avg": l["gap_min_avg"],
            }
            for l in lots
        ],
        "ball_stats": _trend_stats(
            [l["ball_d_avg"] for l in lots if l["ball_d_avg"] is not None]
        ),
        "gap_stats": _trend_stats(
            [l["gap_min_avg"] for l in lots if l["gap_min_avg"] is not None]
        ),
    })


# ------------------------------------------------------------------ misc


@app.template_filter("fmt_dt")
def _fmt_dt(s: str) -> str:
    try:
        dt = datetime.fromisoformat(s)
        return dt.strftime("%Y-%m-%d  %H:%M")
    except (TypeError, ValueError):
        return s or ""


@app.template_filter("fmt_num")
def _fmt_num(v: float | None, digits: int = 2) -> str:
    if v is None:
        return "—"
    return f"{v:.{digits}f}"


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()
    log.info("DB:   %s", _DB_PATH)
    log.info("Share: %s", _SHARE_ROOT)
    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
