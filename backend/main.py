from contextlib import asynccontextmanager
import os

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import uvicorn

import config
from brokers.fyers_broker import FyersBroker

current_broker = FyersBroker()


class TradeRequest(BaseModel):
    index: str
    option_type: str
    strike_price: int
    expiry: str
    entry_price: float | None = None
    lots: int = 1
    manual_sl: float | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("🚀 Scalping Tool Started (FYERS only)")
    print(f"📊 Lot Sizes: {config.LOT_SIZES}")
    yield
    print("🛑 Shutdown")


app = FastAPI(title="Scalping Tool", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])


@app.get("/api/config")
async def get_config():
    return {
        "lot_sizes": config.LOT_SIZES,
        "strike_steps": config.STRIKE_STEPS,
        "sl_points": config.SL_POINTS,
        "broker": "FYERS",
    }


@app.get("/")
async def root():
    return {
        "status": "running",
        "broker": current_broker.BROKER_NAME,
        "authenticated": current_broker.is_authenticated,
        "has_quote_api": current_broker.HAS_QUOTE_API,
    }


@app.get("/api/broker-status")
async def broker_status():
    return {
        "broker": current_broker.BROKER_NAME,
        "authenticated": current_broker.is_authenticated,
        "has_quote_api": current_broker.HAS_QUOTE_API,
        "instruments_count": len(current_broker.instruments_cache),
    }


@app.get("/auth/login")
async def login():
    return {"login_url": current_broker.get_login_url()}


@app.get("/auth/fyers/callback")
async def fyers_callback(auth_code: str = Query(None), code: str = Query(None), s: str = Query(None)):
    actual_code = auth_code or code
    if not actual_code:
        return {"error": "No auth code"}

    if current_broker.generate_session(actual_code):
        return HTMLResponse(SUCCESS_HTML)
    return HTMLResponse(ERROR_HTML)


@app.get("/auth/status")
async def auth_status():
    if not current_broker.is_authenticated:
        return {"authenticated": False}

    try:
        profile = current_broker.get_profile()
        return {
            "authenticated": True,
            "has_quote_api": current_broker.HAS_QUOTE_API,
            **profile,
        }
    except Exception:
        return {"authenticated": False}


@app.post("/auth/logout")
async def logout():
    if os.path.exists(current_broker.TOKEN_FILE):
        os.remove(current_broker.TOKEN_FILE)
    current_broker.is_authenticated = False
    current_broker.access_token = None
    return {"success": True}


@app.get("/api/expiries/{index}")
async def get_expiries(index: str):
    if not current_broker.is_authenticated:
        return {"expiries": []}
    return {"expiries": current_broker.get_expiry_dates(index)}


@app.get("/api/strikes/{index}")
async def get_strikes(index: str, expiry: str = Query(...)):
    if not current_broker.is_authenticated:
        return {"strikes": [], "atm": None}

    index = index.upper()
    all_strikes = current_broker.get_strikes(index, expiry)
    if not all_strikes:
        return {"strikes": [], "atm": None}

    atm = current_broker.get_atm_strike(index)
    closest_idx = min(range(len(all_strikes)), key=lambda i: abs(all_strikes[i] - atm))
    start = max(0, closest_idx - config.STRIKES_BELOW_ATM)
    end = min(len(all_strikes), closest_idx + config.STRIKES_ABOVE_ATM + 1)

    filtered = all_strikes[start:end]
    actual_atm = all_strikes[closest_idx]
    chain_map = current_broker.get_option_chain_ltp(index)

    strikes_data = []
    for strike in filtered:
        chain_info = chain_map.get(strike, {})
        ce_symbol = chain_info.get("ce_symbol") or current_broker.get_option_symbol(index, strike, "CE", expiry)
        pe_symbol = chain_info.get("pe_symbol") or current_broker.get_option_symbol(index, strike, "PE", expiry)

        ce_ltp = chain_info.get("ce_ltp")
        pe_ltp = chain_info.get("pe_ltp")

        if ce_ltp is None and ce_symbol:
            ce_ltp = current_broker.get_ltp(ce_symbol, current_broker.get_exchange(index))
        if pe_ltp is None and pe_symbol:
            pe_ltp = current_broker.get_ltp(pe_symbol, current_broker.get_exchange(index))

        strikes_data.append({
            "strike": strike,
            "is_atm": strike == actual_atm,
            "ce_ltp": ce_ltp,
            "pe_ltp": pe_ltp,
            "ce_symbol": ce_symbol,
            "pe_symbol": pe_symbol,
        })

    return {
        "strikes": strikes_data,
        "atm": actual_atm,
        "total": len(all_strikes),
        "has_ltp": True,
    }


@app.get("/api/index-quote/{index}")
async def get_index_quote(index: str):
    if not current_broker.is_authenticated:
        return {"price": None}

    quote = current_broker.get_index_quote(index)
    return quote if quote else {"price": None}


@app.get("/api/ltp")
async def get_ltp(index: str, strike: int, option_type: str, expiry: str):
    if not current_broker.is_authenticated:
        return {"ltp": None}

    symbol = current_broker.get_option_symbol(index, strike, option_type, expiry)
    exchange = current_broker.get_exchange(index)
    ltp = current_broker.get_ltp(symbol, exchange)

    return {"symbol": symbol, "ltp": ltp, "exchange": exchange}


@app.get("/api/sl-reference")
async def sl_reference(index: str, strike: int, option_type: str, expiry: str):
    if not current_broker.is_authenticated:
        return {"candles": [], "last_3_low": None, "last_close": None, "suggested_sl": None}

    symbol = current_broker.get_option_symbol(index, strike, option_type, expiry)
    candles = current_broker.get_recent_candles(symbol=symbol, resolution="5", count=3)

    if not candles:
        return {"candles": [], "last_3_low": None, "last_close": None, "suggested_sl": None}

    lows = [float(c["low"]) for c in candles if c.get("low") is not None]
    closes = [float(c["close"]) for c in candles if c.get("close") is not None]

    last_3_low = min(lows) if lows else None
    last_close = closes[-1] if closes else None
    suggested_sl = last_3_low if last_3_low is not None else last_close

    return {
        "symbol": symbol,
        "candles": candles,
        "last_3_low": last_3_low,
        "last_close": last_close,
        "suggested_sl": suggested_sl,
    }


@app.post("/api/trade")
async def place_trade(req: TradeRequest):
    if not current_broker.is_authenticated:
        return {"success": False, "error": "Not authenticated"}

    symbol = current_broker.get_option_symbol(req.index, req.strike_price, req.option_type, req.expiry)
    if not symbol:
        return {"success": False, "error": "Invalid symbol"}

    exchange = current_broker.get_exchange(req.index)
    live_ltp = current_broker.get_ltp(symbol, exchange)

    entry_price = req.entry_price
    if entry_price is None or entry_price <= 0:
        entry_price = live_ltp

    if entry_price is None or entry_price <= 0:
        return {"success": False, "error": "Unable to fetch LTP. Enter entry price manually."}

    sl_price = req.manual_sl
    if sl_price is None:
        candles = current_broker.get_recent_candles(symbol=symbol, resolution="5", count=3)
        lows = [float(c["low"]) for c in candles if c.get("low") is not None]
        sl_price = min(lows) if lows else (entry_price - config.SL_POINTS)

    lot_size = config.LOT_SIZES.get(req.index.upper(), 50)
    quantity = req.lots * lot_size

    order_id = current_broker.place_order(
        symbol=symbol,
        exchange=exchange,
        transaction_type="BUY",
        quantity=quantity,
        order_type="MARKET",
        price=0,
    )

    if order_id:
        return {
            "success": True,
            "order_id": order_id,
            "message": f"Order placed: {symbol} x {quantity}",
            "entry_price": entry_price,
            "live_ltp": live_ltp,
            "sl_price": sl_price,
        }

    return {"success": False, "error": "Order failed"}


SUCCESS_HTML = """<!DOCTYPE html>
<html><head><title>Success</title>
<style>body{font-family:system-ui;display:flex;justify-content:center;align-items:center;height:100vh;margin:0;background:#111;color:#fff}
.box{text-align:center;padding:40px;background:#1a1a1a;border-radius:12px}h1{color:#22c55e}</style></head>
<body><div class="box"><h1>✅ Fyers Connected</h1><p>Redirecting...</p></div>
<script>setTimeout(()=>location.href='http://127.0.0.1:5500/index.html',1500)</script></body></html>"""

ERROR_HTML = """<!DOCTYPE html>
<html><head><title>Error</title>
<style>body{font-family:system-ui;display:flex;justify-content:center;align-items:center;height:100vh;margin:0;background:#111;color:#fff}
.box{text-align:center;padding:40px;background:#1a1a1a;border-radius:12px}h1{color:#ef4444}</style></head>
<body><div class="box"><h1>❌ Fyers Login Failed</h1><a href="http://127.0.0.1:5500/index.html" style="color:#3b82f6">Try again</a></div></body></html>"""


if __name__ == "__main__":
    uvicorn.run("main:app", host=config.HOST, port=config.PORT, reload=True)
