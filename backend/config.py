DEFAULT_INSTRUMENT = "NIFTY"
PAISE_TO_RUPEE = 100
POLL_INTERVAL_SEC = 5

DEFAULT_FILTERS = {
    "side": "ALL",       # ALL | CE | PE
    "delta_min": 0.10,
    "delta_max": 0.35,
    "min_oi": 50_000,
    "min_volume": 0,
}

# Renormalized from the original 5-component design (IV 35 / Theta 25 / OI 20 /
# OI-activity 10 / Liquidity 10) after dropping Liquidity for V1 -- bid/ask isn't
# available from the option-chain endpoint, only from a per-contract orderbook
# stream, which is out of scope for this build.
SCORE_WEIGHTS = {
    "iv": 0.40,
    "theta": 0.30,
    "oi": 0.20,
    "oi_activity": 0.10,
}
