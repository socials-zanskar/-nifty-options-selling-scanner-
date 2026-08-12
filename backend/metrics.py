"""Pure calculation functions for the options-selling scanner.

Nothing here talks to the network -- it only transforms a normalized option
chain snapshot into ranked, scored rows. That keeps it trivially unit-testable
and keeps a slow/flaky Nubra API call from ever being on the hot path of a
scoring bug.
"""

from datetime import date

from backend.config import PAISE_TO_RUPEE, SCORE_WEIGHTS


def _rupees(paise_value):
    """Nubra returns strike_price/last_traded_price in paise; convert to rupees."""
    if paise_value is None:
        return None
    return round(paise_value / PAISE_TO_RUPEE, 2)


def _normalize_option(opt, option_type):
    return {
        "type": option_type,
        "ref_id": opt.ref_id,
        "strike": _rupees(opt.strike_price),
        "lot_size": opt.lot_size,
        "ltp": _rupees(opt.last_traded_price),
        "ltp_change": _rupees(opt.last_traded_price_change),
        "iv": opt.iv,
        "delta": opt.delta,
        "gamma": opt.gamma,
        "theta": opt.theta,
        "vega": opt.vega,
        "oi": opt.open_interest,
        "prev_oi": opt.previous_open_interest,
        "volume": opt.volume,
        "timestamp": opt.timestamp,
    }


def normalize_chain(wrapper):
    """Convert the SDK's OptionChainWrapper (pydantic model) into plain dicts,
    with all price fields converted from paise to rupees."""
    chain = wrapper.chain
    return {
        "asset": chain.asset,
        "expiry": chain.expiry,
        "current_price": _rupees(chain.current_price),
        "atm_strike": _rupees(chain.at_the_money_strike),
        "all_expiries": list(chain.all_expiries or []),
        "ce": [_normalize_option(o, "CE") for o in chain.ce],
        "pe": [_normalize_option(o, "PE") for o in chain.pe],
    }


def is_eligible(row, filters):
    """Stage-1 filter: does this contract even qualify for scoring/ranking?"""
    if row["ltp"] is None or row["ltp"] <= 0:
        return False
    if row["iv"] is None or row["theta"] is None or row["delta"] is None:
        return False
    if row["oi"] is None or row["oi"] < filters["min_oi"]:
        return False
    if row["volume"] is None or row["volume"] < filters["min_volume"]:
        return False
    d = abs(row["delta"])
    if d < filters["delta_min"] or d > filters["delta_max"]:
        return False
    return True


def percentile_scores(values):
    """Cross-sectional percentile rank (0-100) for each value, ties averaged.
    Higher input value -> higher percentile. Single-value input scores 100
    (nothing to compare against, so it can't be penalized)."""
    n = len(values)
    if n == 0:
        return []
    if n == 1:
        return [100.0]

    order = sorted(range(n), key=lambda i: values[i])
    scores = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg_rank = (i + j) / 2
        pct = avg_rank / (n - 1) * 100
        for k in range(i, j + 1):
            scores[order[k]] = pct
        i = j + 1
    return scores


def _days_to_expiry(expiry_str):
    if not expiry_str or len(expiry_str) < 8:
        return None
    try:
        d = date(int(expiry_str[0:4]), int(expiry_str[4:6]), int(expiry_str[6:8]))
        return (d - date.today()).days
    except (ValueError, TypeError):
        return None


def compute_rows(normalized, filters):
    """Attach every per-contract derived metric. Returns (rows, atm_iv)."""
    spot = normalized["current_price"]
    atm_strike = normalized["atm_strike"]

    rows = [dict(r) for r in normalized["ce"]] + [dict(r) for r in normalized["pe"]]

    atm_ivs = [r["iv"] for r in rows if r["strike"] == atm_strike and r["iv"] is not None]
    atm_iv = sum(atm_ivs) / len(atm_ivs) if atm_ivs else None

    for r in rows:
        strike, ltp, side = r["strike"], r["ltp"], r["type"]

        if spot and strike is not None:
            r["distance_pct"] = round(
                (strike - spot) / spot * 100 if side == "CE" else (spot - strike) / spot * 100, 2
            )
        else:
            r["distance_pct"] = None

        if ltp is not None and strike is not None:
            r["breakeven"] = round(strike + ltp if side == "CE" else strike - ltp, 2)
        else:
            r["breakeven"] = None

        if r["breakeven"] is not None and spot:
            r["breakeven_distance_pct"] = round(
                (r["breakeven"] - spot) / spot * 100
                if side == "CE"
                else (spot - r["breakeven"]) / spot * 100,
                2,
            )
        else:
            r["breakeven_distance_pct"] = None

        r["iv_vs_atm"] = (
            round(r["iv"] - atm_iv, 2) if (r["iv"] is not None and atm_iv is not None) else None
        )

        r["theta_efficiency_pct"] = (
            round(abs(r["theta"]) / ltp * 100, 2) if (r["theta"] is not None and ltp) else None
        )

        if r["oi"] is not None and r["prev_oi"] is not None:
            r["oi_change_abs"] = r["oi"] - r["prev_oi"]
            r["oi_change_pct"] = round(r["oi_change_abs"] / r["prev_oi"] * 100, 2) if r["prev_oi"] else None
        else:
            r["oi_change_abs"] = None
            r["oi_change_pct"] = None

        r["eligible"] = is_eligible(r, filters)
        for key in ("iv_percentile", "theta_percentile", "oi_percentile", "oi_activity_percentile", "score"):
            r[key] = None

    return rows, atm_iv


def score_rows(rows):
    """Percentile-rank and weight-score eligible rows, separately per side
    (CE vs PE), since IV/OI skew differs by side and comparing across sides
    would be meaningless for a seller picking one side)."""
    for side in ("CE", "PE"):
        side_rows = [r for r in rows if r["type"] == side and r["eligible"]]
        if not side_rows:
            continue

        iv_pct = percentile_scores([r["iv"] for r in side_rows])
        theta_pct = percentile_scores([r["theta_efficiency_pct"] for r in side_rows])
        oi_pct = percentile_scores([r["oi"] for r in side_rows])
        oiact_pct = percentile_scores([r["oi_change_abs"] if r["oi_change_abs"] is not None else 0 for r in side_rows])

        for i, r in enumerate(side_rows):
            r["iv_percentile"] = round(iv_pct[i], 1)
            r["theta_percentile"] = round(theta_pct[i], 1)
            r["oi_percentile"] = round(oi_pct[i], 1)
            r["oi_activity_percentile"] = round(oiact_pct[i], 1)
            r["score"] = round(
                SCORE_WEIGHTS["iv"] * iv_pct[i]
                + SCORE_WEIGHTS["theta"] * theta_pct[i]
                + SCORE_WEIGHTS["oi"] * oi_pct[i]
                + SCORE_WEIGHTS["oi_activity"] * oiact_pct[i],
                1,
            )
    return rows


def build_scan(normalized, filters):
    """Top-level entry point: normalized chain + filters -> full scanner payload."""
    rows, atm_iv = compute_rows(normalized, filters)
    score_rows(rows)

    side_filter = filters.get("side", "ALL")
    visible = [r for r in rows if side_filter in ("ALL",) or r["type"] == side_filter]

    eligible_sorted = sorted(
        (r for r in visible if r["eligible"]), key=lambda r: r["score"] or 0, reverse=True
    )
    ineligible = [r for r in visible if not r["eligible"]]

    total_call_oi = sum(r["oi"] for r in rows if r["type"] == "CE" and r["oi"] is not None)
    total_put_oi = sum(r["oi"] for r in rows if r["type"] == "PE" and r["oi"] is not None)
    pcr = round(total_put_oi / total_call_oi, 2) if total_call_oi else None

    top_call = next((r for r in eligible_sorted if r["type"] == "CE"), None)
    top_put = next((r for r in eligible_sorted if r["type"] == "PE"), None)

    return {
        "asset": normalized["asset"],
        "expiry": normalized["expiry"],
        "all_expiries": normalized["all_expiries"],
        "spot": normalized["current_price"],
        "atm_strike": normalized["atm_strike"],
        "atm_iv": round(atm_iv, 2) if atm_iv is not None else None,
        "days_to_expiry": _days_to_expiry(normalized["expiry"]),
        "total_call_oi": total_call_oi,
        "total_put_oi": total_put_oi,
        "pcr": pcr,
        "rows": eligible_sorted + ineligible,
        "top_call": top_call,
        "top_put": top_put,
        "filters": filters,
        "weights": SCORE_WEIGHTS,
    }
