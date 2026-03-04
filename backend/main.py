from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse
from contextlib import asynccontextmanager
from pydantic import BaseModel
from typing import Optional  # used for query parameters
from datetime import datetime
import uvicorn
import os
import traceback

import config
from brokers.zerodha_broker import ZerodhaBroker
from brokers.fyers_broker import FyersBroker

current_broker = None


class BrokerRequest(BaseModel):
    broker_name: str


class TradeRequest(BaseModel):
    index: str
    option_type: str
    strike_price: int
    expiry: str
    entry_price: float
    lots: int = 1
    sl_points: float = 5.0  # User defined SL


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("🚀 Scalping Tool Started")
    print(f"📊 Lot Sizes: {config.LOT_SIZES}")
    yield
    print("🛑 Shutdown")


app = FastAPI(title="Scalping Tool", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])


# ============ CONFIG ============

@app.get("/api/config")
async def get_config():
    return {
        "lot_sizes": config.LOT_SIZES,
        "strike_steps": config.STRIKE_STEPS,
        "default_sl_points": config.DEFAULT_SL_POINTS,
        "candle_timeframes": list(config.CANDLE_TIMEFRAMES.keys()),
    }


# ============ BROKER ============

@app.get("/")
async def root():
    if not current_broker:
        return {"status": "running", "broker": None}
    return {
        "status": "running",
        "broker": current_broker.BROKER_NAME,
        "authenticated": current_broker.is_authenticated,
        "has_quote_api": current_broker.HAS_QUOTE_API,
    }


@app.post("/api/select-broker")
async def select_broker(req: BrokerRequest):
    global current_broker
    name = req.broker_name.upper()
    
    try:
        if name == "ZERODHA":
            current_broker = ZerodhaBroker()
        elif name == "FYERS":
            current_broker = FyersBroker()
        else:
            return {"success": False, "error": "Invalid broker"}
        
        return {
            "success": True,
            "broker": current_broker.BROKER_NAME,
            "authenticated": current_broker.is_authenticated,
            "has_quote_api": current_broker.HAS_QUOTE_API,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.get("/api/broker-status")
async def broker_status():
    if not current_broker:
        return {"broker": None, "authenticated": False}
    
    return {
        "broker": current_broker.BROKER_NAME,
        "authenticated": current_broker.is_authenticated,
        "has_quote_api": current_broker.HAS_QUOTE_API,
        "instruments_count": len(current_broker.instruments_cache),
    }


# ============ AUTH ============

@app.get("/auth/login")
async def login():
    if not current_broker:
        return {"error": "No broker selected"}
    return {"login_url": current_broker.get_login_url()}


@app.get("/auth/callback")
async def zerodha_callback(request_token: str = Query(None)):
    if not isinstance(current_broker, ZerodhaBroker):
        return JSONResponse(status_code=400, content={"error": "Wrong broker"})
    if current_broker.generate_session(request_token):
        return HTMLResponse(SUCCESS_HTML.format(broker="Zerodha"))
    return HTMLResponse(ERROR_HTML.format(broker="Zerodha"))


@app.get("/auth/fyers/callback")
async def fyers_callback(auth_code: str = Query(None), code: str = Query(None), s: str = Query(None)):
    if not isinstance(current_broker, FyersBroker):
        return JSONResponse(status_code=400, content={"error": "Wrong broker"})
    
    actual_code = auth_code or code
    if not actual_code:
        return JSONResponse(status_code=400, content={"error": "No auth code"})
    
    if current_broker.generate_session(actual_code):
        return HTMLResponse(SUCCESS_HTML.format(broker="Fyers"))
    return HTMLResponse(ERROR_HTML.format(broker="Fyers"))


@app.get("/auth/status")
async def auth_status():
    if not current_broker or not current_broker.is_authenticated:
        return {"authenticated": False}
    
    try:
        profile = current_broker.get_profile()
        return {
            "authenticated": True,
            "has_quote_api": current_broker.HAS_QUOTE_API,
            **profile
        }
    except:
        return {"authenticated": False}


@app.post("/auth/logout")
async def logout():
    global current_broker
    if current_broker:
        token_file = f"{current_broker.BROKER_NAME.lower()}_token.json"
        if os.path.exists(token_file):
            os.remove(token_file)
        current_broker = None
    return {"success": True}


# ============ DATA ============

@app.get("/api/expiries/{index}")
async def get_expiries(index: str):
    if not current_broker or not current_broker.is_authenticated:
        return {"expiries": []}
    return {"expiries": current_broker.get_expiry_dates(index)}


@app.get("/api/strikes/{index}")
async def get_strikes(index: str, expiry: str = Query(...)):
    if not current_broker or not current_broker.is_authenticated:
        return {"strikes": [], "atm": None}
    
    index = index.upper()
    all_strikes = current_broker.get_strikes(index, expiry)
    
    if not all_strikes:
        return {"strikes": [], "atm": None}
    
    atm = current_broker.get_atm_strike(index)
    
    closest_idx = 0
    min_diff = abs(all_strikes[0] - atm)
    
    for i, strike in enumerate(all_strikes):
        diff = abs(strike - atm)
        if diff < min_diff:
            min_diff = diff
            closest_idx = i
    
    start = max(0, closest_idx - config.STRIKES_BELOW_ATM)
    end = min(len(all_strikes), closest_idx + config.STRIKES_ABOVE_ATM + 1)
    
    filtered = all_strikes[start:end]
    actual_atm = all_strikes[closest_idx]
    
    return {
        "strikes": filtered,
        "atm": actual_atm,
        "total": len(all_strikes),
        "has_ltp": current_broker.HAS_QUOTE_API,
    }


@app.get("/api/index-quote/{index}")
async def get_index_quote(index: str):
    if not current_broker or not current_broker.is_authenticated:
        return {"price": None}
    
    if not current_broker.HAS_QUOTE_API:
        return {"price": None, "message": "No quote API"}
    
    try:
        quote = current_broker.get_index_quote(index)
        return quote if quote else {"price": None}
    except Exception as e:
        return {"price": None, "error": str(e)}


@app.get("/api/ltp")
async def get_ltp(index: str, strike: int, option_type: str, expiry: str):
    if not current_broker or not current_broker.is_authenticated:
        return {"ltp": None, "symbol": None}
    
    try:
        symbol = current_broker.get_option_symbol(index, strike, option_type, expiry)
        
        if not symbol:
            return {"ltp": None, "symbol": None, "error": "Symbol not found"}
        
        if not current_broker.HAS_QUOTE_API:
            return {
                "symbol": symbol, 
                "ltp": None, 
                "message": "No quote API - enter price manually"
            }
        
        exchange = current_broker.get_exchange(index)
        ltp = current_broker.get_ltp(symbol, exchange)
        
        return {
            "symbol": symbol,
            "ltp": ltp,
            "exchange": exchange,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        print(f"❌ LTP error: {e}")
        return {"symbol": None, "ltp": None, "error": str(e)}


# ============ CANDLE DATA ============

@app.get("/api/candles/{index}")
async def get_candles(
    index: str,
    timeframe: int = Query(5),
    strike: Optional[int] = Query(None),
    option_type: Optional[str] = Query(None),
    expiry: Optional[str] = Query(None),
):
    """Get previous candle data for an index or a specific option symbol.

    If a strike price (with option_type and expiry) is supplied the broker will
    fetch candles for that option contract. Otherwise it defaults to the
    underlying index symbol.
    """
    if not current_broker or not current_broker.is_authenticated:
        return {"error": "Not authenticated"}
    
    if not current_broker.HAS_QUOTE_API:
        return {"error": "No quote API available"}
    
    if not hasattr(current_broker, 'get_candle_data'):
        return {"error": "Candle data not supported for this broker"}
    
    try:
        # determine which symbol to ask the broker for
        symbol = index
        if strike is not None and option_type and expiry:
            symbol = current_broker.get_option_symbol(index, strike, option_type, expiry)
            if not symbol:
                return {"error": "Invalid option symbol"}
        candle = current_broker.get_candle_data(symbol, timeframe)
        if candle:
            return {"candle": candle}
        return {"error": "No candle data available"}
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/candles-all/{index}")
async def get_all_candles(index: str):
    """Get candles for all timeframes"""
    if not current_broker or not current_broker.is_authenticated:
        return {"error": "Not authenticated"}
    
    if not current_broker.HAS_QUOTE_API:
        return {"error": "No quote API available"}
    
    if not hasattr(current_broker, 'get_candle_data'):
        return {"error": "Candle data not supported"}
    
    try:
        result = {}
        for name, minutes in config.CANDLE_TIMEFRAMES.items():
            candle = current_broker.get_candle_data(index, minutes)
            result[name] = candle
        
        return {"index": index, "candles": result}
    except Exception as e:
        return {"error": str(e)}


# ============ TRADE ============

@app.post("/api/trade")
async def place_trade(req: TradeRequest):
    if not current_broker or not current_broker.is_authenticated:
        return {"success": False, "error": "Not authenticated"}
    
    try:
        symbol = current_broker.get_option_symbol(req.index, req.strike_price, req.option_type, req.expiry)
        if not symbol:
            return {"success": False, "error": "Invalid symbol"}
        
        exchange = current_broker.get_exchange(req.index)
        lot_size = config.LOT_SIZES.get(req.index.upper(), 50)
        quantity = req.lots * lot_size
        
        order_id = current_broker.place_order(
            symbol=symbol,
            exchange=exchange,
            transaction_type="BUY",
            quantity=quantity,
            order_type="MARKET",
            price=0
        )
        
        if order_id:
            sl_price = req.entry_price - req.sl_points
            return {
                "success": True,
                "order_id": order_id,
                "message": f"Order placed: {symbol} x {quantity}",
                "entry_price": req.entry_price,
                "sl_price": sl_price,
                "sl_points": req.sl_points,
            }
        
        return {"success": False, "error": "Order failed"}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ============ DEBUG ============

@app.get("/api/debug/info")
async def debug_info():
    try:
        return {
            "broker": current_broker.BROKER_NAME if current_broker else None,
            "authenticated": current_broker.is_authenticated if current_broker else False,
            "has_quote_api": current_broker.HAS_QUOTE_API if current_broker else False,
            "instruments_count": len(current_broker.instruments_cache) if current_broker else 0,
            "index_prices": dict(current_broker.index_prices) if current_broker and hasattr(current_broker, 'index_prices') else {},
            "current_time": datetime.now().isoformat(),
        }
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/debug/symbol-test")
async def debug_symbol_test(index: str = "NIFTY"):
    if not current_broker:
        return {"error": "No broker"}
    
    if not isinstance(current_broker, FyersBroker):
        return {"error": "Fyers only"}
    
    try:
        expiries = current_broker.get_expiry_dates(index)
        if not expiries:
            return {"error": "No expiries"}
        
        expiry = expiries[0]
        atm = current_broker.get_atm_strike(index)
        
        d = datetime.strptime(expiry, "%Y-%m-%d")
        year = d.strftime("%y")
        month_name = d.strftime("%b").upper()
        month_num = d.month
        day = d.strftime("%d")
        
        month_codes = {1:'1', 2:'2', 3:'3', 4:'4', 5:'5', 6:'6',
                       7:'7', 8:'8', 9:'9', 10:'O', 11:'N', 12:'D'}
        month_code = month_codes.get(month_num, str(month_num))
        
        exchange = "BFO" if index.upper() == "SENSEX" else "NFO"
        
        formats = [
            f"{exchange}:{index}{year}{month_code}{day}{atm}CE",
            f"{exchange}:{index}{year}{month_name}{atm}CE",
        ]
        
        results = []
        for symbol in formats:
            try:
                response = current_broker.fyers.quotes({"symbols": symbol})
                ltp = None
                if response.get("s") == "ok" and "d" in response and len(response["d"]) > 0:
                    ltp = response["d"][0].get("v", {}).get("lp")
                results.append({"symbol": symbol, "ltp": ltp, "works": ltp is not None})
            except Exception as e:
                results.append({"symbol": symbol, "error": str(e)})
        
        return {
            "expiry": expiry,
            "atm": atm,
            "results": results,
            "current_date": datetime.now().strftime("%Y-%m-%d"),
        }
    except Exception as e:
        return {"error": str(e), "traceback": traceback.format_exc()}


# ============ HTML ============

SUCCESS_HTML = """<!DOCTYPE html>
<html><head><title>Success</title>
<style>body{{font-family:system-ui;display:flex;justify-content:center;align-items:center;height:100vh;margin:0;background:#111;color:#fff}}
.box{{text-align:center;padding:40px;background:#1a1a1a;border-radius:12px}}h1{{color:#22c55e}}</style></head>
<body><div class="box"><h1>✅ {broker} Connected</h1><p>Redirecting...</p></div>
<script>setTimeout(()=>location.href='http://127.0.0.1:5500/index.html',1500)</script></body></html>"""

ERROR_HTML = """<!DOCTYPE html>
<html><head><title>Error</title>
<style>body{{font-family:system-ui;display:flex;justify-content:center;align-items:center;height:100vh;margin:0;background:#111;color:#fff}}
.box{{text-align:center;padding:40px;background:#1a1a1a;border-radius:12px}}h1{{color:#ef4444}}</style></head>
<body><div class="box"><h1>❌ {broker} Login Failed</h1><a href="http://127.0.0.1:5500/index.html" style="color:#3b82f6">Try again</a></div></body></html>"""


if __name__ == "__main__":
    uvicorn.run("main:app", host=config.HOST, port=config.PORT, reload=True)