"""Canonical traffic units.

All new traffic reporting, wallet volume input and per-unit prices use IEC GiB.
Raw Xray counters and all historical SQLite consumption are always in bytes.
Old samples and pre-migration wallet pricing terms may have decimal-GB pricing:
the migration records their original divisor instead of rewriting history.
"""
BYTES_PER_KIB = 1024
BYTES_PER_MIB = 1024 ** 2
BYTES_PER_GIB = 1024 ** 3
LEGACY_BYTES_PER_GB = 10 ** 9
TRAFFIC_UNIT = "GiB"
