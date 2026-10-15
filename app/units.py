"""Canonical global units for the independent monitor (never per provider/port).

All raw Xray traffic remains bytes. The chosen unit is persisted at installation
and is immutable for the lifetime of this monitor database.
"""
BYTES_PER_KIB=1024
BYTES_PER_MIB=1024**2
BYTES_PER_GIB=1024**3
LEGACY_BYTES_PER_GB=10**9
UNITS={'GB':LEGACY_BYTES_PER_GB, 'GiB':BYTES_PER_GIB}

def check_unit(unit):
    if unit not in UNITS:
        raise ValueError('Traffic unit must be GB (1000) or GiB (1024)')
    return unit

def bytes_per_unit(unit):
    return UNITS[check_unit(unit)]

def selected_unit(db):
    row=db.execute("SELECT value FROM settings WHERE key='traffic_unit'").fetchone()
    if row is None:
        raise ValueError('Traffic unit has not been initialized for this monitor database')
    return check_unit(row[0])

def selected_bytes_per_unit(db):
    return bytes_per_unit(selected_unit(db))
