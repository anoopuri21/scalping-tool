from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse
from contextlib import asynccontextmanager
from pydantic import BaseModel
import uvicorn
import os

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


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("🚀 Scalping Tool Started")
    print(f"📊 Lot Sizes: {config.LOT_SIZES}")
    yield
    print("🛑 Shutdown")


app = FastAPI(title="Scalping Tool", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])


# ============ CONFIG ENDPOINT ============

@app.get("/api/config")
async def get_config():
    """Get trading config - lot sizes, etc."""
    return {
        "lot_sizes": config.LOT_SIZES,
        "strike_steps": config.STRIKE_STEPS,
        "sl_points": config.SL_POINTS,
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
async def get_strikes(index: str, expiry: str = Query(...), option_type: str = Query(None)):
    """Get strikes with LTP for each (10 above + ATM + 10 below)"""
    if not current_broker or not current_broker.is_authenticated:
        return {"strikes": [], "atm": None}
    
    index = index.upper()
    all_strikes = current_broker.get_strikes(index, expiry)
    
    if not all_strikes:
        return {"strikes": [], "atm": None}
    
    # Get ATM
    atm = current_broker.get_atm_strike(index)
    
    # Find closest strike to ATM
    closest_idx = 0
    min_diff = abs(all_strikes[0] - atm)
    
    for i, strike in enumerate(all_strikes):
        diff = abs(strike - atm)
        if diff < min_diff:
            min_diff = diff
            closest_idx = i
    
    # Get 10 below + ATM + 10 above
    start = max(0, closest_idx - config.STRIKES_BELOW_ATM)
    end = min(len(all_strikes), closest_idx + config.STRIKES_ABOVE_ATM + 1)
    
    filtered = all_strikes[start:end]
    actual_atm = all_strikes[closest_idx]
    
    # Build response with LTP if available (Fyers only)
    strikes_data = []
    
    for strike in filtered:
        strike_info = {
            "strike": strike,
            "is_atm": strike == actual_atm,
            "ce_ltp": None,
            "pe_ltp": None,
        }
        
        # Fetch LTP if broker has quote API
        if current_broker.HAS_QUOTE_API:
            # Get CE LTP
            ce_symbol = current_broker.get_option_symbol(index, strike, "CE", expiry)
            if ce_symbol:
                strike_info["ce_ltp"] = current_broker.get_ltp(ce_symbol, current_broker.get_exchange(index))
            
            # Get PE LTP
            pe_symbol = current_broker.get_option_symbol(index, strike, "PE", expiry)
            if pe_symbol:
                strike_info["pe_ltp"] = current_broker.get_ltp(pe_symbol, current_broker.get_exchange(index))
        
        strikes_data.append(strike_info)
    
    return {
        "strikes": strikes_data,
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
    
    quote = current_broker.get_index_quote(index)
    return quote if quote else {"price": None}


@app.get("/api/ltp")
async def get_ltp(index: str, strike: int, option_type: str, expiry: str):
    if not current_broker or not current_broker.is_authenticated:
        return {"ltp": None}
    
    symbol = current_broker.get_option_symbol(index, strike, option_type, expiry)
    
    if not current_broker.HAS_QUOTE_API:
        return {"symbol": symbol, "ltp": None, "message": "Enter price manually"}
    
    exchange = current_broker.get_exchange(index)
    ltp = current_broker.get_ltp(symbol, exchange)
    
    return {"symbol": symbol, "ltp": ltp, "exchange": exchange}


# ============ TRADE ============

@app.post("/api/trade")
async def place_trade(req: TradeRequest):
    if not current_broker or not current_broker.is_authenticated:
        return {"success": False, "error": "Not authenticated"}
    
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
        return {
            "success": True,
            "order_id": order_id,
            "message": f"Order placed: {symbol} x {quantity}",
            "sl_price": req.entry_price - config.SL_POINTS,
        }
    
    return {"success": False, "error": "Order failed"}


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