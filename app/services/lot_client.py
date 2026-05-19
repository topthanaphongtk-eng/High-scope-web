from __future__ import annotations

import logging
from pathlib import Path

from requests import Session
from requests.adapters import HTTPAdapter
from zeep import Client, Settings as ZeepSettings
from zeep.cache import SqliteCache
from zeep.exceptions import Fault, TransportError
from zeep.transports import Transport

from app.models.lot import LotDetail

log = logging.getLogger(__name__)


class _InsecureAdapter(HTTPAdapter):
    """Forces verify=False on every request — used only when verify_ssl is disabled.

    Corporate SSL-intercepting proxies re-sign outbound TLS with a private CA, which
    breaks cert validation for zeep's external schema downloads (schemas.xmlsoap.org).
    Setting Session.verify=False alone isn't enough because requests/urllib3 may have
    already resolved verify before the Session flag takes effect, so we short-circuit
    at the adapter level.
    """

    def send(self, request, **kwargs):  # type: ignore[override]
        kwargs["verify"] = False
        return super().send(request, **kwargs)


class LotClientError(Exception):
    """Base class for LOT service errors surfaced to the GUI."""


class ServerUnreachable(LotClientError):
    """Network-level failure — timeout, DNS, or HTTP transport error."""


class ServerFault(LotClientError):
    """Server accepted the request but responded with a SOAP Fault."""


class LotNotFound(LotClientError):
    def __init__(self, lot_id: str, reply_code: int, reply_desc: str | None) -> None:
        self.lot_id = lot_id
        self.reply_code = reply_code
        self.reply_desc = reply_desc
        super().__init__(f"LOT {lot_id!r}: code={reply_code} desc={reply_desc!r}")


class LotClient:
    """SOAP client for the MES RecordService.getDetailLotMES operation.

    The WSDL is cached to SQLite so repeated startups are fast even though
    the WSDL itself is ~1 MB with many unrelated operations.
    """

    def __init__(
        self,
        wsdl_url: str,
        *,
        timeout: int = 5,
        cache_dir: Path | None = None,
        verify_ssl: bool = True,
    ) -> None:
        session = Session()
        if not verify_ssl:
            session.verify = False
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            adapter = _InsecureAdapter()
            session.mount("https://", adapter)
            session.mount("http://", adapter)

        cache = None
        if cache_dir is not None:
            cache_dir.mkdir(parents=True, exist_ok=True)
            cache = SqliteCache(path=str(cache_dir / "wsdl_cache.db"), timeout=86400)

        transport = Transport(
            session=session,
            timeout=timeout,
            operation_timeout=timeout,
            cache=cache,
        )
        zeep_settings = ZeepSettings(strict=False, xml_huge_tree=True)

        try:
            self._client = Client(
                wsdl=wsdl_url, transport=transport, settings=zeep_settings,
            )
        except TransportError as e:
            raise ServerUnreachable(f"Cannot load WSDL from {wsdl_url}: {e}") from e

    def get_lot_detail(self, lot_id: str) -> LotDetail:
        """Call getDetailLotMES. Raises LotNotFound if the server reports no LOT."""
        if not lot_id:
            raise ValueError("lot_id is required")

        try:
            raw = self._client.service.getDetailLotMES(lot=lot_id)
        except Fault as e:
            raise ServerFault(str(e)) from e
        except TransportError as e:
            raise ServerUnreachable(str(e)) from e

        detail = LotDetail.from_soap(raw)
        if not detail.is_ok():
            raise LotNotFound(lot_id, detail.reply_code, detail.reply_desc)
        return detail
