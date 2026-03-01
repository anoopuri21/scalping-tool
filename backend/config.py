import os
from dotenv import load_dotenv

load_dotenv()

# ============ BROKER CREDENTIALS ============

# Zerodha
ZERODHA_API_KEY = os.getenv("ZERODHA_API_KEY", "")
ZERODHA_API_SECRET = os.getenv("ZERODHA_API_SECRET", "")

# Fyers
FYERS_APP_ID = os.getenv("FYERS_APP_ID", "")
FYERS_SECRET_KEY = os.getenv("FYERS_SECRET_KEY", "")
FYERS_REDIRECT_URL = os.getenv("FYERS_REDIRECT_URL", "http://127.0.0.1:8000/auth/fyers/callback")


# ============ LOT SIZES ============
# Update these when lot sizes change

LOT_SIZES = {
    "NIFTY": 65,
    "BANKNIFTY": 30,
    "SENSEX": 20,
}


# ============ STRIKE STEP SIZES ============
# Difference between consecutive strikes

STRIKE_STEPS = {
    "NIFTY": 50,
    "BANKNIFTY": 100,
    "SENSEX": 100,
}


# ============ DEFAULT ATM PRICES ============
# Fallback prices when live data unavailable

DEFAULT_ATM = {
    "NIFTY": 22500,
    "BANKNIFTY": 48000,
    "SENSEX": 73500,
}


# ============ TRADING CONFIG ============

SL_POINTS = 5  # Stop loss points below entry
STRIKES_ABOVE_ATM = 10  # Number of strikes to show above ATM
STRIKES_BELOW_ATM = 10  # Number of strikes to show below ATM


# ============ INDEX SYMBOLS (Fyers) ============

FYERS_INDEX_SYMBOLS = {
    "NIFTY": "NSE:NIFTY50-INDEX",
    "BANKNIFTY": "NSE:NIFTYBANK-INDEX",
    "SENSEX": "BSE:SENSEX-INDEX",
}


# ============ SERVER CONFIG ============

HOST = "127.0.0.1"
PORT = 8000
FRONTEND_URL = "http://127.0.0.1:5500/index.html"