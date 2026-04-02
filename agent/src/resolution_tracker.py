import asyncio
import csv
import logging
import os
import tempfile

import aiohttp

from config import settings

log = logging.getLogger(__name__)

RESOLUTION_POLL_INTERVAL = 3600  # 1 hour


class ResolutionTracker:
    """
    Periodically checks the Gamma API for markets that have resolved,
    then back-fills resolved / resolution / pnl_usd in the signals CSV.
    """

    def __init__(self) -> None:
        self._csv_path = settings.csv_path

    async def run_loop(self) -> None:
        while True:
            try:
                await self._resolve_pending()
            except Exception as exc:
                log.error(f"ResolutionTracker error: {exc}")
            await asyncio.sleep(RESOLUTION_POLL_INTERVAL)

    async def _resolve_pending(self) -> None:
        rows = self._read_csv()
        if not rows:
            return
        pending_ids = {
            r["market_id"]
            for r in rows
            if r.get("market_id")
            and not r.get("resolved")
            and float(r.get("size_usd") or 0) > 0
        }
        if not pending_ids:
            log.debug("ResolutionTracker: no pending markets")
            return
        log.info(f"ResolutionTracker: checking {len(pending_ids)} markets")
        resolutions = await self._fetch_resolutions(list(pending_ids))
        if not resolutions:
            return
        updated = 0
        for row in rows:
            mid = row.get("market_id", "")
            if mid in resolutions and not row.get("resolved"):
                outcome = resolutions[mid]
                row["resolved"] = "true"
                row["resolution"] = outcome
                row["pnl_usd"] = str(self._calc_pnl(row, outcome))
                updated += 1
        if updated:
            self._write_csv(rows)
            log.info(f"ResolutionTracker: updated {updated} row(s)")

    async def _fetch_resolutions(self, market_ids: list[str]) -> dict[str, str]:
        results: dict[str, str] = {}
        ids_param = "&".join(f"id={mid}" for mid in market_ids)
        url = f"{settings.polymarket_gamma_url}/markets?{ids_param}&limit={len(market_ids)}"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status != 200:
                        log.warning(f"Gamma API returned {resp.status}")
                        return results
                    data = await resp.json()
                    markets = data if isinstance(data, list) else data.get("markets", [])
                    for m in markets:
                        mid = m.get("conditionId") or m.get("id", "")
                        if not m.get("resolved", False):
                            continue
                        raw = str(m.get("outcome", "")).strip().upper()
                        if raw in ("YES", "NO"):
                            results[mid] = raw
        except Exception as exc:
            log.error(f"ResolutionTracker fetch error: {exc}")
        return results

    def _calc_pnl(self, row: dict, outcome: str) -> float:
        try:
            size = float(row.get("size_usd") or 0)
            price = float(row.get("price") or 0)
            side = str(row.get("side", "")).upper()
            if size <= 0 or price <= 0:
                return 0.0
            if side == "BOTH":
                edge = 1.0 - price
                shares = size / (price / 2)
                return round(edge * shares, 4)
            if side == outcome:
                return round(size * (1.0 / price - 1.0), 4)
            return round(-size, 4)
        except (ValueError, ZeroDivisionError):
            return 0.0

    def _read_csv(self) -> list[dict]:
        if not os.path.exists(self._csv_path):
            return []
        with open(self._csv_path, newline="") as f:
            return list(csv.DictReader(f))

    def _write_csv(self, rows: list[dict]) -> None:
        if not rows:
            return
        fieldnames = list(rows[0].keys())
        dir_ = os.path.dirname(self._csv_path) or "."
        with tempfile.NamedTemporaryFile(
            "w", dir=dir_, delete=False, newline="", suffix=".tmp"
        ) as tmp:
            writer = csv.DictWriter(tmp, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
            tmp_path = tmp.name
        os.replace(tmp_path, self._csv_path)
