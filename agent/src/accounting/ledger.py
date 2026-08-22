"""SQLite-backed append-only paper-trading ledger."""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from collections.abc import Mapping, Sequence
from decimal import Decimal
from pathlib import Path

from domain.orders import Fill, Position

ZERO = Decimal(0)


class Ledger:
    def __init__(self, path: str = ":memory:", *, initial_cash: Decimal | str = "1000"):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._db = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._init_schema(Decimal(str(initial_cash)))

    def close(self) -> None:
        self._db.close()

    def _init_schema(self, initial_cash: Decimal) -> None:
        self._db.executescript(
            """
            PRAGMA journal_mode=WAL;
            PRAGMA foreign_keys=ON;
            CREATE TABLE IF NOT EXISTS metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS ledger_entries (
                event_key TEXT PRIMARY KEY,
                entry_type TEXT NOT NULL,
                cash_delta TEXT NOT NULL,
                condition_id TEXT,
                token_id TEXT,
                side TEXT,
                shares TEXT,
                price TEXT,
                fee TEXT,
                source TEXT,
                timestamp_ms INTEGER
            );
            CREATE TABLE IF NOT EXISTS resolutions (
                condition_id TEXT PRIMARY KEY,
                event_key TEXT UNIQUE NOT NULL,
                winning_token_id TEXT NOT NULL,
                winning_outcome TEXT NOT NULL,
                timestamp_ms INTEGER
            );
            CREATE TABLE IF NOT EXISTS reservations (
                order_id TEXT PRIMARY KEY,
                amount TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1
            );
            """
        )
        self._db.execute(
            "INSERT OR IGNORE INTO metadata(key, value) VALUES('initial_cash', ?)",
            (str(initial_cash),),
        )

    @property
    def initial_cash(self) -> Decimal:
        row = self._db.execute(
            "SELECT value FROM metadata WHERE key='initial_cash'"
        ).fetchone()
        return Decimal(row["value"])

    @property
    def cash(self) -> Decimal:
        total = self.initial_cash
        for row in self._db.execute("SELECT cash_delta FROM ledger_entries"):
            total += Decimal(row["cash_delta"])
        return total

    @property
    def reserved_cash(self) -> Decimal:
        return sum(
            (
                Decimal(row["amount"])
                for row in self._db.execute(
                    "SELECT amount FROM reservations WHERE active=1"
                )
            ),
            ZERO,
        )

    @property
    def available_cash(self) -> Decimal:
        return self.cash - self.reserved_cash

    def reserve(self, order_id: str, amount: Decimal) -> bool:
        if not order_id or amount <= ZERO:
            return False
        self._db.execute("BEGIN IMMEDIATE")
        try:
            if self._db.execute(
                "SELECT 1 FROM reservations WHERE order_id=?", (order_id,)
            ).fetchone():
                self._db.execute("ROLLBACK")
                return False
            if self.available_cash < amount:
                self._db.execute("ROLLBACK")
                return False
            self._db.execute(
                "INSERT INTO reservations(order_id, amount, active) VALUES(?,?,1)",
                (order_id, str(amount)),
            )
            self._db.execute("COMMIT")
            return True
        except Exception:
            self._db.execute("ROLLBACK")
            raise

    def release(self, order_id: str) -> None:
        self._db.execute(
            "UPDATE reservations SET active=0 WHERE order_id=?", (order_id,)
        )

    @staticmethod
    def _fill_row(fill: Fill) -> tuple[object, ...]:
        return (
            f"fill:{fill.fill_id}",
            "BUY",
            str(-fill.total_cost),
            fill.condition_id,
            fill.token_id,
            fill.side,
            str(fill.filled_shares),
            str(fill.average_price),
            str(fill.fee),
            fill.source,
            fill.timestamp_ms,
        )

    def record_fill(self, fill: Fill) -> bool:
        return self.record_fills_atomic([fill])

    def record_fills_atomic(self, fills: Sequence[Fill]) -> bool:
        if not fills:
            return False
        keys = [f"fill:{fill.fill_id}" for fill in fills]
        if len(keys) != len(set(keys)):
            return False
        self._db.execute("BEGIN IMMEDIATE")
        try:
            placeholders = ",".join("?" for _ in keys)
            existing = self._db.execute(
                f"SELECT event_key FROM ledger_entries WHERE event_key IN ({placeholders})",
                keys,
            ).fetchall()
            if existing:
                self._db.execute("ROLLBACK")
                return False
            self._db.executemany(
                """INSERT INTO ledger_entries(
                    event_key, entry_type, cash_delta, condition_id, token_id,
                    side, shares, price, fee, source, timestamp_ms
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                [self._fill_row(fill) for fill in fills],
            )
            self._db.execute("COMMIT")
            return True
        except Exception:
            self._db.execute("ROLLBACK")
            raise

    def positions(self) -> list[Position]:
        resolved = {
            row["condition_id"]
            for row in self._db.execute("SELECT condition_id FROM resolutions")
        }
        grouped: dict[tuple[str, str, str], list[Decimal]] = defaultdict(
            lambda: [ZERO, ZERO]
        )
        for row in self._db.execute(
            """SELECT condition_id, token_id, side, shares, cash_delta
               FROM ledger_entries WHERE entry_type='BUY'"""
        ):
            if row["condition_id"] in resolved:
                continue
            key = (row["condition_id"], row["token_id"], row["side"])
            grouped[key][0] += Decimal(row["shares"])
            grouped[key][1] += -Decimal(row["cash_delta"])
        return [
            Position(k[0], k[1], k[2], v[0], v[1])
            for k, v in grouped.items()
            if v[0] > ZERO
        ]

    def settle(
        self,
        *,
        condition_id: str,
        winning_token_id: str,
        winning_outcome: str,
        timestamp_ms: int | None,
        event_key: str,
    ) -> bool:
        self._db.execute("BEGIN IMMEDIATE")
        try:
            if self._db.execute(
                "SELECT 1 FROM resolutions WHERE condition_id=?", (condition_id,)
            ).fetchone():
                self._db.execute("ROLLBACK")
                return False
            winning_shares = sum(
                (
                    Decimal(row["shares"])
                    for row in self._db.execute(
                        """SELECT token_id, shares FROM ledger_entries
                           WHERE entry_type='BUY' AND condition_id=?""",
                        (condition_id,),
                    )
                    if row["token_id"] == winning_token_id
                ),
                ZERO,
            )
            self._db.execute(
                """INSERT INTO resolutions(
                    condition_id,event_key,winning_token_id,winning_outcome,timestamp_ms
                ) VALUES(?,?,?,?,?)""",
                (
                    condition_id,
                    event_key,
                    winning_token_id,
                    winning_outcome,
                    timestamp_ms,
                ),
            )
            self._db.execute(
                """INSERT INTO ledger_entries(
                    event_key, entry_type, cash_delta, condition_id, token_id,
                    side, shares, price, fee, source, timestamp_ms
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    f"settlement:{event_key}",
                    "SETTLEMENT",
                    str(winning_shares),
                    condition_id,
                    winning_token_id,
                    winning_outcome,
                    str(winning_shares),
                    "1",
                    "0",
                    "RESOLUTION",
                    timestamp_ms,
                ),
            )
            self._db.execute("COMMIT")
            return True
        except Exception:
            self._db.execute("ROLLBACK")
            raise

    @property
    def realized_pnl(self) -> Decimal:
        pnl = ZERO
        for resolution in self._db.execute("SELECT condition_id FROM resolutions"):
            spent = ZERO
            payout = ZERO
            for row in self._db.execute(
                """SELECT entry_type,cash_delta FROM ledger_entries
                   WHERE condition_id=?""",
                (resolution["condition_id"],),
            ):
                delta = Decimal(row["cash_delta"])
                if row["entry_type"] == "BUY":
                    spent += -delta
                elif row["entry_type"] == "SETTLEMENT":
                    payout += delta
            pnl += payout - spent
        return pnl

    def equity(self, mark_prices: Mapping[str, Decimal]) -> Decimal:
        value = self.cash
        for position in self.positions():
            if position.token_id not in mark_prices:
                raise ValueError(
                    f"missing mark price for open token {position.token_id}"
                )
            value += position.shares * Decimal(str(mark_prices[position.token_id]))
        return value

    def snapshot(self, mark_prices: Mapping[str, Decimal]) -> dict[str, str]:
        return {
            "initial_cash": str(self.initial_cash),
            "cash": str(self.cash),
            "reserved_cash": str(self.reserved_cash),
            "available_cash": str(self.available_cash),
            "equity": str(self.equity(mark_prices)),
            "realized_pnl": str(self.realized_pnl),
        }
