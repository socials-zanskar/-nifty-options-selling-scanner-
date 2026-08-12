import types

from backend.metrics import (
    build_scan,
    compute_rows,
    is_eligible,
    normalize_chain,
    percentile_scores,
    score_rows,
)

DEFAULT_FILTERS = {
    "side": "ALL",
    "delta_min": 0.10,
    "delta_max": 0.35,
    "min_oi": 50_000,
    "min_volume": 0,
}


def make_option(**kwargs):
    defaults = dict(
        ref_id=1,
        timestamp=1234567890,
        strike_price=2540000,   # paise -> 25400.00
        lot_size=25,
        last_traded_price=8200,  # paise -> 82.00
        last_traded_price_change=150,
        iv=17.8,
        delta=0.21,
        gamma=0.001,
        theta=-6.2,
        vega=8.5,
        open_interest=1_800_000,
        previous_open_interest=1_500_000,
        volume=480_000,
    )
    defaults.update(kwargs)
    return types.SimpleNamespace(**defaults)


def make_wrapper(ce, pe, current_price=2542050, at_the_money_strike=2540000, expiry="20260814"):
    chain = types.SimpleNamespace(
        asset="NIFTY",
        expiry=expiry,
        ce=ce,
        pe=pe,
        at_the_money_strike=at_the_money_strike,
        current_price=current_price,
        all_expiries=[expiry],
    )
    return types.SimpleNamespace(chain=chain, message="ok", exchange="NSE")


def test_normalize_chain_converts_paise_to_rupees():
    wrapper = make_wrapper(ce=[make_option()], pe=[])
    normalized = normalize_chain(wrapper)

    assert normalized["current_price"] == 25420.50
    assert normalized["atm_strike"] == 25400.0
    assert normalized["ce"][0]["strike"] == 25400.0
    assert normalized["ce"][0]["ltp"] == 82.0


def test_percentile_scores_single_value_scores_100():
    assert percentile_scores([42]) == [100.0]


def test_percentile_scores_ties_get_averaged_rank():
    # three equal values -> all should land on the same (middle) percentile
    scores = percentile_scores([10, 10, 10])
    assert scores == [50.0, 50.0, 50.0]


def test_percentile_scores_ascending_order():
    scores = percentile_scores([10, 20, 30])
    assert scores == [0.0, 50.0, 100.0]


def test_distance_and_breakeven_for_call():
    wrapper = make_wrapper(ce=[make_option(strike_price=2580000, last_traded_price=8200)], pe=[])
    normalized = normalize_chain(wrapper)
    rows, _ = compute_rows(normalized, DEFAULT_FILTERS)
    row = rows[0]

    # strike 25800, spot 25420.50 -> distance = (25800-25420.5)/25420.5*100
    assert row["distance_pct"] == round((25800 - 25420.50) / 25420.50 * 100, 2)
    assert row["breakeven"] == 25800 + 82.0
    assert row["breakeven_distance_pct"] == round((row["breakeven"] - 25420.50) / 25420.50 * 100, 2)


def test_distance_and_breakeven_for_put():
    wrapper = make_wrapper(ce=[], pe=[make_option(strike_price=2500000, last_traded_price=7600, delta=-0.20)])
    normalized = normalize_chain(wrapper)
    rows, _ = compute_rows(normalized, DEFAULT_FILTERS)
    row = rows[0]

    assert row["distance_pct"] == round((25420.50 - 25000) / 25420.50 * 100, 2)
    assert row["breakeven"] == 25000 - 76.0
    assert row["breakeven_distance_pct"] == round((25420.50 - row["breakeven"]) / 25420.50 * 100, 2)


def test_theta_efficiency_pct():
    wrapper = make_wrapper(ce=[make_option(last_traded_price=8000, theta=-6.0)], pe=[])
    normalized = normalize_chain(wrapper)
    rows, _ = compute_rows(normalized, DEFAULT_FILTERS)
    assert rows[0]["theta_efficiency_pct"] == round(6.0 / 80.0 * 100, 2)


def test_oi_change_uses_previous_open_interest_field():
    wrapper = make_wrapper(ce=[make_option(open_interest=1_800_000, previous_open_interest=1_500_000)], pe=[])
    normalized = normalize_chain(wrapper)
    rows, _ = compute_rows(normalized, DEFAULT_FILTERS)
    row = rows[0]
    assert row["oi_change_abs"] == 300_000
    assert row["oi_change_pct"] == round(300_000 / 1_500_000 * 100, 2)


def test_eligibility_rejects_out_of_range_delta():
    row = {"ltp": 82.0, "iv": 17.8, "theta": -6.2, "delta": 0.55, "oi": 1_800_000, "volume": 480_000}
    assert is_eligible(row, DEFAULT_FILTERS) is False


def test_eligibility_rejects_low_oi():
    row = {"ltp": 82.0, "iv": 17.8, "theta": -6.2, "delta": 0.21, "oi": 1_000, "volume": 480_000}
    assert is_eligible(row, DEFAULT_FILTERS) is False


def test_eligibility_accepts_within_range():
    row = {"ltp": 82.0, "iv": 17.8, "theta": -6.2, "delta": 0.21, "oi": 1_800_000, "volume": 480_000}
    assert is_eligible(row, DEFAULT_FILTERS) is True


def test_build_scan_ranks_eligible_rows_and_picks_top_candidates():
    ce_rows = [
        make_option(ref_id=1, strike_price=2580000, last_traded_price=8200, iv=17.8, theta=-6.2,
                    delta=0.21, open_interest=1_800_000, previous_open_interest=1_500_000, volume=480_000),
        make_option(ref_id=2, strike_price=2590000, last_traded_price=6100, iv=18.4, theta=-5.5,
                    delta=0.16, open_interest=1_200_000, previous_open_interest=1_100_000, volume=310_000),
        # ineligible: delta out of range
        make_option(ref_id=3, strike_price=2560000, last_traded_price=15000, iv=16.0, theta=-9.0,
                    delta=0.52, open_interest=2_000_000, previous_open_interest=1_900_000, volume=600_000),
    ]
    pe_rows = [
        make_option(ref_id=4, strike_price=2500000, last_traded_price=7600, iv=18.1, theta=-6.0,
                    delta=-0.20, open_interest=1_600_000, previous_open_interest=1_390_000, volume=520_000),
    ]
    wrapper = make_wrapper(ce=ce_rows, pe=pe_rows)
    normalized = normalize_chain(wrapper)

    result = build_scan(normalized, DEFAULT_FILTERS)

    # ref_id=2 has higher IV and higher theta-efficiency than ref_id=1 (ref_id=1 only
    # wins on OI/OI-activity, which carry less combined weight) -> ref_id=2 should rank first
    assert result["top_call"]["ref_id"] == 2
    assert result["top_put"]["ref_id"] == 4
    assert result["top_call"]["score"] is not None
    assert result["pcr"] == round(1_600_000 / (1_800_000 + 1_200_000 + 2_000_000), 2)

    eligible = [r for r in result["rows"] if r["eligible"]]
    ineligible = [r for r in result["rows"] if not r["eligible"]]
    assert len(eligible) == 3
    assert len(ineligible) == 1
    assert ineligible[0]["ref_id"] == 3
    # eligible rows must be ranked before ineligible ones
    assert result["rows"].index(eligible[-1]) < result["rows"].index(ineligible[0])
