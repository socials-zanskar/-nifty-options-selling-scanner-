# NIFTY Options-Selling Scanner

Live dashboard that pulls the NIFTY option chain from Nubra, computes seller-focused
metrics (IV percentile, theta efficiency, OI change, breakeven distance, etc.), and
ranks eligible CE/PE contracts against each other.

## What this is (and isn't)

- Reads the option chain via REST (`option_chain()`), polled every 5s. No WebSocket
  streaming, no order placement -- this is a read-only scanner.
- Bid/ask spread and a liquidity score are **not included** -- Nubra's option chain
  has no bid/ask fields; that only exists via a separate per-contract order-book
  WebSocket stream, which was out of scope given the build timeline.
- The "Seller Opportunity Score" ranks contracts *against each other* under your
  chosen filters. It is not a probability of profit.

## Getting the code

```powershell
git clone https://github.com/<your-username>/<your-repo>.git
cd <your-repo>
```

## One-time setup

```powershell
# from the project root
python -m venv .venv
.venv\Scripts\Activate.ps1        # if the venv isn't already active
pip install -r requirements.txt
copy .env.example .env
notepad .env                      # fill in PHONE_NO and MPIN
```

`NUBRA_ENV` in `.env` defaults to `PROD`. Set it to `UAT` if you want to test
against the sandbox instead.

## Running it

```powershell
python -m uvicorn backend.app:app --host 127.0.0.1 --port 8000
```

**Do not add `--reload`.** Reload runs the app in a subprocess that doesn't reliably
forward terminal input, and the first login needs to read an OTP from the console.

Then open **http://127.0.0.1:8000** in a browser.

### First run vs. later runs

- **First run** (or whenever the cached session is invalid): the terminal will
  prompt for your **OTP** (sent by SMS -- this can't be pre-stored, so you'll type
  it every time it's actually needed). Phone number and MPIN are read automatically
  from `.env`.
- **Later runs**: Nubra's SDK caches the session in `auth_data.db*` in whatever
  folder you launched `uvicorn` from. As long as you always launch from the project
  root and don't delete that file, restarts should only silently re-verify the MPIN
  (from `.env`) -- no OTP prompt. Launch from a different folder and it'll look like
  login is being asked for again, because it's a fresh cache location.
- If you see an **IP address mismatch** warning on startup, that's Nubra checking
  your account's whitelisted static IP for *trading* access -- it does not block
  market-data reads, so the scanner should keep working regardless.

### Before the webinar

Run it once tonight, well before you're on stage, so:
1. The OTP prompt happens now, not live.
2. You can eyeball real numbers (spot, strikes, OI) and sanity-check they look right.
3. If the market's closed when you test, the chain should still return the last
   snapshot -- just double check the "updated Xs ago" indicator and `last_updated`
   aren't stuck if you leave it running into market hours.

## Running tests

```powershell
python -m pytest tests/ -v
```

These test the calculation layer (`backend/metrics.py`) and the API wiring against
synthetic data -- they never touch the real Nubra API, so they run offline.

## Project layout

```
backend/
  config.py       filter defaults, scoring weights
  nubra_client.py auth + option_chain() fetch, paise->rupee conversion boundary
  metrics.py       pure calculations: distance, breakeven, theta efficiency,
                   percentile scoring, eligibility filter, build_scan()
  poller.py        background thread polling the chain every 5s
  app.py           FastAPI app: GET /api/scan, serves frontend/
frontend/
  index.html / style.css / app.js   vanilla dashboard, no build step
tests/
  test_metrics.py  calculation unit tests
  test_app.py      API wiring smoke tests (fake snapshot, no live API)
```

## Security note

`.env` and `auth_data.db*` both hold live-login-adjacent material (credentials /
session tokens). Don't commit or share either. Both are already listed in
`.gitignore`.

## Disclaimer

**This project is for educational and informational purposes only. It is not
trading advice, investment advice, or a recommendation to buy, sell, or hold
any security or derivative.**

- Nothing produced by this dashboard -- scores, rankings, "opportunity"
  labels, IV percentiles, breakeven distances, or any other metric --
  constitutes a recommendation or solicitation to enter any trade.
- Options trading (including option selling/writing) carries substantial
  risk of loss, up to and including losses larger than the initial premium
  received, and is not suitable for everyone. Past performance of any
  strategy, metric, or backtest is not indicative of future results.
- The "Seller Opportunity Score" and similar derived metrics are simple,
  transparent heuristics built for a webinar demo. They rank contracts
  *relative to each other* under user-chosen filters -- they are **not**
  a probability of profit, a risk rating, or a substitute for your own
  due diligence.
- Market data is sourced from the Nubra API and may be delayed, incomplete,
  or inaccurate. Always verify prices and Greeks on your broker's official
  terminal before acting.
- The authors and contributors of this project accept no liability for any
  financial loss or damage arising from the use of this software. Use it
  entirely at your own risk, and consult a qualified, licensed financial
  advisor before making any trading or investment decisions.
