"""
Canadian Forest Fire Weather Index (FWI) System — Van Wagner (1987) equations.

This is the real multi-component fire danger system (not a single-shot heuristic):
  FFMC — Fine Fuel Moisture Code   (fast-drying surface litter, hours)
  DMC  — Duff Moisture Code        (loosely compacted organic layer, days-weeks)
  DC   — Drought Code              (deep compact organic layer, weeks-months)
  ISI  — Initial Spread Index      (from FFMC + wind)
  BUI  — Buildup Index             (from DMC + DC)
  FWI  — Fire Weather Index        (overall intensity, from ISI + BUI)

Each day's codes are computed FROM YESTERDAY'S codes plus today's noon weather —
this is why it needs a backend with persistent state; a static webpage can't
carry "yesterday" forward.

DAY-LENGTH FACTORS: Great Smoky Mountains NP sits at ~35.6° N, a mid-latitude
site with real seasonal day-length swings (unlike a near-equatorial site).
We use the standard Van Wagner (1987) monthly Le/Lf lookup tables for this
latitude band rather than a fixed constant.
"""
import math

# Standard system startup defaults (used when there's no "yesterday" yet —
# e.g. first ever run of the station).
STARTUP_FFMC = 85.0
STARTUP_DMC = 6.0
STARTUP_DC = 15.0

# Van Wagner (1987) standard monthly day-length adjustment tables,
# valid for the ~20-50°N band that covers Great Smoky Mountains NP (35.6°N).
LE_BY_MONTH = [6.5, 7.5, 9.0, 12.8, 13.9, 13.9, 12.4, 10.9, 9.4, 8.0, 7.0, 6.0]   # DMC
LF_BY_MONTH = [-1.6, -1.6, -1.6, 0.9, 3.8, 5.8, 6.4, 5.0, 2.4, 0.4, -1.6, -1.6]   # DC


def calc_ffmc(ffmc_prev, temp, rh, wind_kmh, rain_mm):
    mo = 147.2 * (101.0 - ffmc_prev) / (59.5 + ffmc_prev)

    if rain_mm > 0.5:
        rf = rain_mm - 0.5
        if mo <= 150.0:
            mr = mo + 42.5 * rf * math.exp(-100.0 / (251.0 - mo)) * (1 - math.exp(-6.93 / rf))
        else:
            mr = (mo + 42.5 * rf * math.exp(-100.0 / (251.0 - mo)) * (1 - math.exp(-6.93 / rf))
                  + 0.0015 * (mo - 150.0) ** 2 * math.sqrt(rf))
        mo = min(mr, 250.0)

    ed = (0.942 * rh ** 0.679 + 11 * math.exp((rh - 100) / 10.0)
          + 0.18 * (21.1 - temp) * (1 - math.exp(-0.115 * rh)))

    if mo > ed:
        ko = 0.424 * (1 - (rh / 100.0) ** 1.7) + 0.0694 * math.sqrt(wind_kmh) * (1 - (rh / 100.0) ** 8)
        kd = ko * 0.581 * math.exp(0.0365 * temp)
        m = ed + (mo - ed) * (10 ** (-kd))
    else:
        ew = (0.618 * rh ** 0.753 + 10 * math.exp((rh - 100) / 10.0)
              + 0.18 * (21.1 - temp) * (1 - math.exp(-0.115 * rh)))
        if mo < ew:
            k1 = 0.424 * (1 - ((100 - rh) / 100.0) ** 1.7) + 0.0694 * math.sqrt(wind_kmh) * (1 - ((100 - rh) / 100.0) ** 8)
            kw = k1 * 0.581 * math.exp(0.0365 * temp)
            m = ew - (ew - mo) * (10 ** (-kw))
        else:
            m = mo

    ffmc = 59.5 * (250.0 - m) / (147.2 + m)
    return max(0.0, min(101.0, ffmc))


def calc_dmc(dmc_prev, temp, rh, rain_mm, le):
    dmc_o = dmc_prev
    if rain_mm > 1.5:
        re = 0.92 * rain_mm - 1.27
        mo = 20.0 + math.exp(5.6348 - dmc_prev / 43.43)
        if dmc_prev <= 33:
            b = 100.0 / (0.5 + 0.3 * dmc_prev)
        elif dmc_prev <= 65:
            b = 14.0 - 1.3 * math.log(dmc_prev)
        else:
            b = 6.2 * math.log(dmc_prev) - 17.2
        mr = mo + 1000.0 * re / (48.77 + b * re)
        dmc_r = 244.72 - 43.43 * math.log(mr - 20.0)
        dmc_o = max(0.0, dmc_r)

    temp_eff = max(temp, -1.1)
    k = 1.894 * (temp_eff + 1.1) * (100.0 - rh) * le * 1e-4
    dmc = dmc_o + k
    return max(0.0, dmc)


def calc_dc(dc_prev, temp, rain_mm, lf):
    dc_o = dc_prev
    if rain_mm > 2.8:
        rd = 0.83 * rain_mm - 1.27
        qo = 800.0 * math.exp(-dc_prev / 400.0)
        qr = qo + 3.937 * rd
        dc_r = 400.0 * math.log(800.0 / qr)
        dc_o = max(0.0, dc_r)

    temp_eff = max(temp, -2.8)
    v = 0.36 * (temp_eff + 2.8) + lf
    v = max(0.0, v)
    dc = dc_o + 0.5 * v
    return max(0.0, dc)


def calc_isi(ffmc, wind_kmh):
    m = 147.2 * (101.0 - ffmc) / (59.5 + ffmc)
    ff = 91.9 * math.exp(-0.1386 * m) * (1 + (m ** 5.31) / (4.93e7))
    fw = math.exp(0.05039 * wind_kmh)
    return 0.208 * fw * ff


def calc_bui(dmc, dc):
    if dmc <= 0.4 * dc:
        bui = 0.8 * dmc * dc / (dmc + 0.4 * dc) if (dmc + 0.4 * dc) > 0 else 0.0
    else:
        denom = dmc + 0.4 * dc
        bui = dmc - (1 - 0.8 * dc / denom) * (0.92 + (0.0114 * dmc) ** 1.7) if denom > 0 else dmc
    return max(0.0, bui)


def calc_fwi(isi, bui):
    if bui <= 80:
        fd = 0.626 * bui ** 0.809 + 2.0
    else:
        fd = 1000.0 / (25 + 108.64 * math.exp(-0.023 * bui))
    b = 0.1 * isi * fd
    if b > 1:
        s = math.exp(2.72 * (0.434 * math.log(b)) ** 0.647)
    else:
        s = b
    return s


def risk_level(fwi):
    if fwi < 5:
        return "LOW", "var(--accent-green)"
    if fwi < 12:
        return "MODERATE", "var(--accent-amber)"
    if fwi < 21:
        return "HIGH", "var(--accent-fire)"
    return "EXTREME", "var(--accent-red)"


def compute_daily(prev_codes, temp, rh, wind_kmh, rain_mm, month=None):
    """
    prev_codes: dict with ffmc, dmc, dc from the previous day (or startup defaults).
    month: 1-12 (defaults to current UTC month) — selects the seasonal day-length factor.
    Returns dict with all components for today.
    """
    import datetime
    if month is None:
        month = datetime.datetime.utcnow().month
    le = LE_BY_MONTH[month - 1]
    lf = LF_BY_MONTH[month - 1]

    ffmc = calc_ffmc(prev_codes["ffmc"], temp, rh, wind_kmh, rain_mm)
    dmc = calc_dmc(prev_codes["dmc"], temp, rh, rain_mm, le)
    dc = calc_dc(prev_codes["dc"], temp, rain_mm, lf)
    isi = calc_isi(ffmc, wind_kmh)
    bui = calc_bui(dmc, dc)
    fwi = calc_fwi(isi, bui)
    level, color = risk_level(fwi)
    return {
        "ffmc": round(ffmc, 2), "dmc": round(dmc, 2), "dc": round(dc, 2),
        "isi": round(isi, 2), "bui": round(bui, 2), "fwi": round(fwi, 2),
        "risk_level": level, "risk_color": color,
    }
