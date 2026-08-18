"""Month ledger: monthly peaks, their history and the 12-month rolling average.

A month is identified by ``"YYYY-MM"`` in the *local* timezone (Europe/Brussels for
Fluvius). A quarter belongs to the month in which it **starts** — the 23:45–00:00
quarter of the last day of a month still counts for that month.

For every month up to three peak values may be known, in decreasing precedence:

* ``manual`` — set by the user via a service call (correction after a desync);
* ``meter``  — reported by the meter itself (OBIS ``1-0:1.6.0`` / ``0-0:98.1.0``);
* ``calc``   — the highest :class:`QuarterResult` recorded by this integration.

:meth:`MonthLedger.month_peak` resolves them in that order and applies the billing floor.
"""

from __future__ import annotations

from datetime import datetime, tzinfo

from .model import DEFAULT_FLOOR_KW, MonthPeak, PeakEntry, QuarterResult, Source, as_utc


def month_key_for(ts: datetime, tz: tzinfo) -> str:
    """``YYYY-MM`` of ``ts`` in timezone ``tz``."""
    return as_utc(ts).astimezone(tz).strftime("%Y-%m")


def shift_month(key: str, delta: int) -> str:
    """Return the month key ``delta`` months away from ``key`` (negative = earlier)."""
    year, month = (int(p) for p in key.split("-"))
    idx = year * 12 + (month - 1) + delta
    return f"{idx // 12:04d}-{idx % 12 + 1:02d}"


def _validate_key(key: str) -> str:
    year, month = key.split("-")
    if len(year) != 4 or not (1 <= int(month) <= 12):
        raise ValueError(f"invalid month key {key!r}, expected YYYY-MM")
    return key


class MonthLedger:
    """Bookkeeping of monthly peaks. Pure Python; see module docstring."""

    def __init__(
        self,
        *,
        tz: tzinfo,
        floor_kw: float = DEFAULT_FLOOR_KW,
        keep_months: int = 13,
        top_n: int = 5,
        min_coverage: float = 0.9,
    ) -> None:
        self.tz = tz
        self.floor_kw = floor_kw
        self.keep_months = keep_months
        self.top_n = top_n
        self.min_coverage = min_coverage
        # month -> {"calc": PeakEntry|None, "meter": PeakEntry|None, "manual": PeakEntry|None,
        #           "top": list[PeakEntry]}
        self._months: dict[str, dict] = {}

    # ------------------------------------------------------------------ helpers

    def month_key(self, ts: datetime) -> str:
        return month_key_for(ts, self.tz)

    def months(self) -> list[str]:
        """Known month keys, oldest first."""
        return sorted(self._months)

    def _rec(self, key: str) -> dict:
        return self._months.setdefault(
            _validate_key(key), {"calc": None, "meter": None, "manual": None, "top": []}
        )

    # ------------------------------------------------------------------ writes

    def record(self, result: QuarterResult) -> bool:
        """Record a closed quarter. Returns True when it raised the month's *calculated* peak.

        Results with insufficient coverage or without data are ignored for peak purposes: we
        would rather miss a peak than invent one (the meter's own 1.6.0 catches it anyway)."""
        if result.source is Source.NONE or result.coverage < self.min_coverage:
            return False
        key = self.month_key(result.start)
        rec = self._rec(key)
        entry = PeakEntry(kw=result.average_kw, at=result.end, source=result.source)

        top: list[PeakEntry] = rec["top"]
        top.append(entry)
        top.sort(key=lambda e: e.kw, reverse=True)
        del top[self.top_n :]

        current: PeakEntry | None = rec["calc"]
        if current is None or entry.kw > current.kw:
            rec["calc"] = entry
            return True
        return False

    def set_meter_peak(self, key: str, kw: float, at: datetime | None) -> bool:
        """Store the peak the meter reports for ``key``. Only ever raises the stored value within
        a month (1.6.0 is monotonic within a month). Returns True when it changed."""
        rec = self._rec(key)
        current: PeakEntry | None = rec["meter"]
        if current is not None and kw <= current.kw:
            return False
        rec["meter"] = PeakEntry(kw=float(kw), at=as_utc(at) if at else None, source=Source.METER)
        return True

    def set_manual_peak(self, key: str, kw: float, at: datetime | None) -> None:
        """User correction; overrides meter and calculated values for that month."""
        rec = self._rec(key)
        rec["manual"] = PeakEntry(kw=float(kw), at=as_utc(at) if at else None, source=Source.MANUAL)

    def clear_manual_peak(self, key: str) -> None:
        if key in self._months:
            self._months[key]["manual"] = None

    def reset_month(self, key: str) -> None:
        """Forget everything about a month (calculated, meter and manual values)."""
        self._months.pop(key, None)

    def prune(self, current_key: str) -> None:
        """Drop months older than ``keep_months`` (counting the current month)."""
        oldest = shift_month(current_key, -(self.keep_months - 1))
        for key in [k for k in self._months if k < oldest]:
            del self._months[key]

    # ------------------------------------------------------------------ reads

    def month_peak(self, key: str) -> MonthPeak:
        rec = self._months.get(key)
        entry: PeakEntry | None = None
        if rec is not None:
            entry = rec["manual"] or rec["meter"] or rec["calc"]
        raw = entry.kw if entry else None
        return MonthPeak(
            month=key,
            peak_kw=max(self.floor_kw, raw or 0.0),
            raw_kw=raw,
            at=entry.at if entry else None,
            source=entry.source if entry else Source.NONE,
            top=tuple(rec["top"]) if rec else (),
        )

    def rolling_average(self, key: str, months: int = 12) -> float:
        """Average billed peak over the ``months`` months ending at ``key`` (inclusive).
        Months without data count at the floor, exactly like the first year of a new meter."""
        total = 0.0
        for i in range(months):
            total += self.month_peak(shift_month(key, -i)).peak_kw
        return total / months

    def has_data(self, key: str) -> bool:
        return key in self._months

    # ------------------------------------------------------------------ persistence

    def to_dict(self) -> dict:
        return {
            "months": {
                key: {
                    "calc": _entry_to_dict(rec["calc"]),
                    "meter": _entry_to_dict(rec["meter"]),
                    "manual": _entry_to_dict(rec["manual"]),
                    "top": [_entry_to_dict(e) for e in rec["top"]],
                }
                for key, rec in sorted(self._months.items())
            }
        }

    @classmethod
    def from_dict(cls, data: dict, *, tz: tzinfo, **kwargs) -> MonthLedger:
        ledger = cls(tz=tz, **kwargs)
        for key, rec in (data.get("months") or {}).items():
            ledger._months[_validate_key(key)] = {
                "calc": _entry_from_dict(rec.get("calc")),
                "meter": _entry_from_dict(rec.get("meter")),
                "manual": _entry_from_dict(rec.get("manual")),
                "top": [e for e in (_entry_from_dict(d) for d in rec.get("top") or []) if e],
            }
        return ledger


def _entry_to_dict(entry: PeakEntry | None) -> dict | None:
    if entry is None:
        return None
    return {
        "kw": entry.kw,
        "at": as_utc(entry.at).isoformat() if entry.at else None,
        "source": str(entry.source),
    }


def _entry_from_dict(data: dict | None) -> PeakEntry | None:
    if not data:
        return None
    at = data.get("at")
    return PeakEntry(
        kw=float(data["kw"]),
        at=as_utc(datetime.fromisoformat(at)) if at else None,
        source=Source(data.get("source", "power")),
    )


__all__ = ["MonthLedger", "month_key_for", "shift_month"]
