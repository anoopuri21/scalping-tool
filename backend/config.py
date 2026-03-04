import os
from dotenv import load_dotenv

load_dotenv()

# ============ BROKER CREDENTIALS ============

ZERODHA_API_KEY = os.getenv("ZERODHA_API_KEY", "")
ZERODHA_API_SECRET = os.getenv("ZERODHA_API_SECRET", "")

FYERS_APP_ID = os.getenv("FYERS_APP_ID", "")
FYERS_SECRET_KEY = os.getenv("FYERS_SECRET_KEY", "")
FYERS_REDIRECT_URL = os.getenv("FYERS_REDIRECT_URL", "http://127.0.0.1:8000/auth/fyers/callback")


# ============ LOT SIZES ============

LOT_SIZES = {
    "NIFTY": 65,
    "BANKNIFTY": 30,
    "SENSEX": 20,
}


# ============ STRIKE SETTINGS ============

STRIKE_STEPS = {
    "NIFTY": 50,
    "BANKNIFTY": 100,
    "SENSEX": 100,
}

DEFAULT_ATM = {
    "NIFTY": 25000,
    "BANKNIFTY": 50000,
    "SENSEX": 75000,
}

STRIKES_ABOVE_ATM = 10
STRIKES_BELOW_ATM = 10


# ============ DEFAULT SL (User can change in UI) ============

DEFAULT_SL_POINTS = 5


# ============ FYERS INDEX SYMBOLS ============

FYERS_INDEX_SYMBOLS = {
    "NIFTY": "NSE:NIFTY50-INDEX",
    "BANKNIFTY": "NSE:NIFTYBANK-INDEX",
    "SENSEX": "BSE:SENSEX-INDEX",
}


# ============ CANDLE TIMEFRAMES ============

CANDLE_TIMEFRAMES = {
    "5min": 5,
    "15min": 15,
    "30min": 30,
    "1hr": 60,
}


# ============ SERVER ============

HOST = "127.0.0.1"
PORT = 8000
FRONTEND_URL = "http://127.0.0.1:5500/index.html"