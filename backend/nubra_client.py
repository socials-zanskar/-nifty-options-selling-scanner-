"""Nubra SDK auth + option-chain fetch, isolated behind a tiny wrapper so the
rest of the app never touches the SDK's pydantic models directly.

Authentication is interactive on first run: with PHONE_NO and MPIN set in
.env, the SDK still prompts for the OTP sent to that phone (OTP can't be
pre-stored -- it's a one-time SMS code). After a successful login, the SDK
caches its session in an `auth_data.db*` shelve file in the current working
directory, so restarts only re-verify the MPIN (from .env, no prompt) rather
than repeating the full OTP flow -- as long as the app is always launched
from the same working directory and that file isn't deleted.
"""

import os
import threading

from dotenv import load_dotenv
from nubra_python_sdk.marketdata.market_data import MarketData
from nubra_python_sdk.start_sdk import InitNubraSdk, NubraEnv

load_dotenv()

_lock = threading.Lock()
_market_data = None


def get_market_data():
    global _market_data
    if _market_data is None:
        with _lock:
            if _market_data is None:
                env_name = os.getenv("NUBRA_ENV", "PROD").upper()
                env = NubraEnv.UAT if env_name == "UAT" else NubraEnv.PROD
                client = InitNubraSdk(env, env_creds=True)
                _market_data = MarketData(client)
    return _market_data


def fetch_raw_option_chain(instrument, expiry=None):
    """Returns the SDK's OptionChainWrapper (pydantic model) as-is."""
    market_data = get_market_data()
    return market_data.option_chain(instrument, expiry=expiry or "")
