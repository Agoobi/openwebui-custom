"""Time handling. The server keeps UTC epoch seconds and never reads the host's local clock zone."""

import re
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

WEEKDAY_NAMES = {1: "Thứ 2", 2: "Thứ 3", 3: "Thứ 4", 4: "Thứ 5", 5: "Thứ 6", 6: "Thứ 7", 7: "Chủ nhật"}
_LOCAL_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})[T ](\d{1,2}):(\d{2})(?::(\d{2}))?$")


def now() -> int:
    return int(time.time())


def zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as error:
        raise ValueError(f"Múi giờ không hợp lệ: {name}") from error


def valid_zone(name: str) -> bool:
    try:
        zone(name)
        return True
    except ValueError:
        return False


def zone_names() -> list[str]:
    return sorted(name for name in available_timezones() if "/" in name and not name.startswith(("Etc/", "SystemV/", "posix/", "right/")))


def parse_moment(value: str, tz_name: str) -> int:
    """'2026-11-10 08:00' is read in tz_name; a value with Z or an offset keeps its own offset."""
    text = value.strip()
    match = _LOCAL_RE.match(text)
    if match:
        year, month, day, hour, minute = (int(part) for part in match.groups()[:5])
        second = int(match.group(6) or 0)
        local = datetime(year, month, day, hour, minute, second, tzinfo=zone(tz_name))
        # A wall time skipped by a DST jump does not survive a round trip; refuse it instead of guessing.
        back = local.astimezone(timezone.utc).astimezone(zone(tz_name))
        if (back.hour, back.minute) != (hour, minute):
            raise ValueError(f"{text} không có thật ở múi giờ {tz_name} (giờ bị nhảy khi đổi giờ mùa hè).")
        return int(local.timestamp())
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"Không đọc được thời điểm: {text}. Dùng dạng 2026-11-10 08:00.") from error
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=zone(tz_name))
    return int(parsed.timestamp())


def to_local(epoch: int, tz_name: str) -> datetime:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).astimezone(zone(tz_name))


def iso_utc(epoch: int | None) -> str | None:
    if epoch is None:
        return None
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def describe(epoch: int, tz_name: str) -> str:
    """'08:00 Thứ 2, 10/11/2026 (Asia/Ho_Chi_Minh, GMT+7)'"""
    local = to_local(epoch, tz_name)
    offset = local.utcoffset() or timedelta(0)
    minutes = int(offset.total_seconds() // 60)
    sign = "+" if minutes >= 0 else "-"
    hours, rest = divmod(abs(minutes), 60)
    gmt = f"GMT{sign}{hours}" + (f":{rest:02d}" if rest else "")
    return f"{local:%H:%M} {WEEKDAY_NAMES[local.isoweekday()]}, {local:%d/%m/%Y} ({tz_name}, {gmt})"


def slot_times(slots: list[dict], tz_name: str, start: int, days: int) -> list[int]:
    """Every slot occurrence from start for the given number of days, sorted."""
    tz = zone(tz_name)
    first = to_local(start, tz_name).date()
    found: list[int] = []
    for offset in range(days + 1):
        day = first + timedelta(days=offset)
        for slot in slots:
            if day.isoweekday() not in slot.get("days", []):
                continue
            hour, minute = (int(part) for part in str(slot["time"]).split(":"))
            moment = int(datetime(day.year, day.month, day.day, hour, minute, tzinfo=tz).timestamp())
            if moment >= start:
                found.append(moment)
    return sorted(set(found))
