from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class LotDetail(BaseModel):
    """Subset of DetailLotModel fields we surface in the GUI, plus raw payload."""

    lot_id: str
    mpc: str | None = None
    lot_location: str | None = None
    package: str | None = None
    qs: str | None = None
    bonding_running: str | None = None

    reply_code: int
    reply_desc: str | None = None

    raw: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_soap(cls, obj: Any) -> LotDetail:
        """Convert a zeep response object into a LotDetail.

        zeep returns objects with attributes matching the WSDL schema.
        """
        raw: dict[str, Any] = {}
        for k in (
            "Reply_Code", "Reply_Des", "LotLocation", "LotClass", "LotID",
            "WaferLotID", "MPC", "Package", "BondingRunning", "PadSize",
            "LFRunning", "Dapsize", "MaskRunning", "QS", "Wire", "WireType",
            "Automotive", "ReqQty", "Cap", "ProductType", "SpecialType",
            "ESD", "Mask2", "AssyLevel", "CarteringDesc",
        ):
            v = getattr(obj, k, None)
            raw[k] = v

        return cls(
            lot_id=raw.get("LotID") or "",
            mpc=raw.get("MPC"),
            lot_location=raw.get("LotLocation"),
            package=raw.get("Package"),
            qs=raw.get("QS"),
            bonding_running=raw.get("BondingRunning"),
            reply_code=int(raw.get("Reply_Code") or 0),
            reply_desc=raw.get("Reply_Des"),
            raw=raw,
        )

    def is_ok(self) -> bool:
        return (self.reply_desc or "").strip().upper() == "SUCCESS"
