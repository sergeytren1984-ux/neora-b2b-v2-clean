from datetime import datetime, timedelta, timezone
import hashlib
from availability_ledger import asof, validate

raw = b"archived official release bytes"
t = datetime(2026, 10, 2, 12, 30, tzinfo=timezone.utc)
row = {"event": "NFP", "observation_period": "2026-09", "revision_id": "first",
       "source_url": "https://www.bls.gov/news.release/empsit.htm",
       "scheduled_utc": t.isoformat(), "published_utc": t.isoformat(),
       "first_seen_utc": (t + timedelta(seconds=4)).isoformat(),
       "capture_utc": (t + timedelta(seconds=5)).isoformat(),
       "raw_sha256": hashlib.sha256(raw).hexdigest(), "value_status": "RAW_CAPTURED"}
assert asof(row, raw, (t + timedelta(seconds=4)).isoformat()) is None
assert asof(row, raw, (t + timedelta(seconds=5)).isoformat())["numeric_admission"] is False
for change in ({"capture_utc": (t - timedelta(seconds=1)).isoformat()},
               {"source_url": "https://example.com/fake"},
               {"raw_sha256": "0" * 64}):
    try:
        validate({**row, **change}, raw)
    except ValueError:
        pass
    else:
        raise AssertionError("invalid record accepted")
print("availability-time ledger tests OK")
