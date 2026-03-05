from contextlib import asynccontextmanager
import asyncio
import os
import time
from datetime import datetime
from typing import Literal

from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
import uvicorn

import config
from brokers.fyers_broker import FyersBroker

current_broker = FyersBroker()
trade_book: dict[str, dict] = {}
instrument_refresh_task: asyncio.Task | None = None


class TradeRequest(BaseModel):
    index: str
    option_type: Literal["CE", "PE"]
    strike_price: int
    expiry: str
    lots: int = 1
    order_type: Literal["MARKET", "LIMIT", "STOP_LIMIT"] = "MARKET"
    entry_price: float | None = None
    trigger_price: float | None = None
    sl_mode: Literal["fixed", "candle"] = "candle"
    fixed_sl: float | None = None
    sl_offset: float = 0.0
    candle_resolution: Literal["1", "3"] = "1"
    candle_count: int = Field(default=5, ge=5, le=20)


async def refresh_instruments_job():
    while True:
        try:
            if current_broker.is_authenticated:
                current_broker.load_instruments()
                print(f"🔄 Instrument cache refresh complete at {datetime.now().isoformat()}")
        except Exception as e:
            print(f"⚠️ Instrument refresh failed: {e}")
        await asyncio.sleep(900)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global instrument_refresh_task
    print("🚀 Scalping Tool Started (FYERS only)")
    print(f"📊 Lot Sizes: {config.LOT_SIZES}")
    if current_broker.is_authenticated:
        current_broker.load_instruments()
    instrument_refresh_task = asyncio.create_task(refresh_instruments_job())
    yield
    if instrument_refresh_task:
        instrument_refresh_task.cancel()
    print("🛑 Shutdown")


app = FastAPI(title="Scalping Tool", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])


def retry_place_order(*, symbol: str, exchange: str, transaction_type: str, quantity: int,
                      order_type: str, price: float, trigger_price: float,
                      retries: int = 3, base_delay: float = 0.6) -> tuple[str | None, int]:
    for attempt in range(1, retries + 1):
        order_id = current_broker.place_order(
            symbol=symbol,
            exchange=exchange,
            transaction_type=transaction_type,
            quantity=quantity,
            order_type=order_type,
            price=price,
            trigger_price=trigger_price,
        )
        if order_id:
            return order_id, attempt
        if attempt < retries:
            delay = base_delay * (2 ** (attempt - 1))
            print(f"⏳ Retry order attempt {attempt + 1}/{retries} in {delay:.2f}s")
            time.sleep(delay)
    return None, retries


def compute_trade_metrics() -> dict:
    open_trades = [t for t in trade_book.values() if t["status"] == "OPEN"]
    total_pnl = sum(t.get("pnl", 0) for t in open_trades)
    total_positions = sum(t.get("quantity", 0) for t in open_trades)
    return {
        "open_trades": len(open_trades),
        "total_positions": total_positions,
        "total_pnl": total_pnl,
        "orders_with_retries": len([t for t in trade_book.values() if t.get("order_attempts", 1) > 1]),
    }


@app.get("/api/config")
async def get_config():
    return {
        "lot_sizes": config.LOT_SIZES,
        "strike_steps": config.STRIKE_STEPS,
        "sl_points": config.SL_POINTS,
        "broker": "FYERS",
        "order_types": ["MARKET", "LIMIT", "STOP_LIMIT"],
        "sl_modes": ["fixed", "candle"],
        "candle_resolutions": ["1", "3"],
        "default_candle_count": 5,
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
        strikes_data.append({
            "strike": strike,
            "is_atm": strike == actual_atm,
            "ce_ltp": chain_info.get("ce_ltp"),
            "pe_ltp": chain_info.get("pe_ltp"),
            "ce_symbol": ce_symbol,
            "pe_symbol": pe_symbol,
        })

    return {"strikes": strikes_data, "atm": actual_atm, "total": len(all_strikes), "has_ltp": True}


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
async def sl_reference(index: str, strike: int, option_type: str, expiry: str,
                       resolution: str = Query("1"), count: int = Query(5, ge=5, le=20),
                       offset: float = Query(0.0)):
    if not current_broker.is_authenticated:
        return {"candles": [], "min_low": None, "suggested_sl": None}

    symbol = current_broker.get_option_symbol(index, strike, option_type, expiry)
    candles = current_broker.get_recent_candles(symbol=symbol, resolution=resolution, count=count)

    lows = [float(c["low"]) for c in candles if c.get("low") is not None]
    min_low = min(lows) if lows else None
    suggested_sl = (min_low - offset) if min_low is not None else None

    return {
        "symbol": symbol,
        "candles": candles,
        "min_low": min_low,
        "suggested_sl": suggested_sl,
        "resolution": resolution,
        "count": count,
        "offset": offset,
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

    if req.order_type == "MARKET":
        entry_price = live_ltp
    else:
        entry_price = req.entry_price

    if entry_price is None or entry_price <= 0:
        return {"success": False, "error": "Entry price unavailable. Use LIMIT with manual entry or retry MARKET."}

    if req.sl_mode == "fixed" and req.fixed_sl and req.fixed_sl > 0:
        sl_price = req.fixed_sl
    elif req.sl_mode == "candle":
        candles = current_broker.get_recent_candles(symbol=symbol, resolution=req.candle_resolution, count=req.candle_count)
        lows = [float(c["low"]) for c in candles if c.get("low") is not None]
        sl_price = (min(lows) - req.sl_offset) if lows else (entry_price - config.SL_POINTS)
    else:
        sl_price = entry_price - config.SL_POINTS

    lot_size = config.LOT_SIZES.get(req.index.upper(), 50)
    quantity = req.lots * lot_size

    order_price = entry_price if req.order_type in ["LIMIT", "STOP_LIMIT"] else 0
    trigger_price = req.trigger_price if req.order_type == "STOP_LIMIT" else 0

    order_id, attempts = retry_place_order(
        symbol=symbol,
        exchange=exchange,
        transaction_type="BUY",
        quantity=quantity,
        order_type=req.order_type,
        price=order_price,
        trigger_price=trigger_price or 0,
    )

    if not order_id:
        return {"success": False, "error": "Order failed after retries"}

    trade_id = f"T{len(trade_book) + 1:04d}"
    trade_book[trade_id] = {
        "trade_id": trade_id,
        "symbol": symbol,
        "index": req.index,
        "option_type": req.option_type,
        "strike": req.strike_price,
        "expiry": req.expiry,
        "order_type": req.order_type,
        "entry_price": entry_price,
        "ltp": live_ltp or entry_price,
        "sl_price": sl_price,
        "quantity": quantity,
        "lots": req.lots,
        "status": "OPEN",
        "order_id": order_id,
        "order_attempts": attempts,
        "pnl": 0.0,
        "created_at": datetime.now().isoformat(),
    }

    return {
        "success": True,
        "order_id": order_id,
        "trade_id": trade_id,
        "message": f"Order placed: {symbol} x {quantity}",
        "entry_price": entry_price,
        "live_ltp": live_ltp,
        "sl_price": sl_price,
        "order_attempts": attempts,
    }


@app.get("/api/dashboard")
async def dashboard_data():
    if not current_broker.is_authenticated:
        return {"trades": [], "metrics": compute_trade_metrics()}

    for trade in trade_book.values():
        if trade["status"] != "OPEN":
            continue
        ltp = current_broker.get_ltp(trade["symbol"], current_broker.get_exchange(trade["index"]))
        if ltp is not None:
            trade["ltp"] = ltp
            trade["pnl"] = (ltp - trade["entry_price"]) * trade["quantity"]

    return {"trades": list(trade_book.values()), "metrics": compute_trade_metrics(), "updated_at": datetime.now().isoformat()}


@app.websocket("/ws/dashboard")
async def dashboard_ws(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            await websocket.send_json(await dashboard_data())
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        return


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
