from fyers_apiv3 import fyersModel
from typing import Optional, List, Dict
from datetime import datetime, timedelta, date
import json
import os
from .base_broker import BaseBroker
import config


class FyersBroker(BaseBroker):
    """Fyers - Full Quote API"""
    
    BROKER_NAME = "FYERS"
    HAS_QUOTE_API = True
    TOKEN_FILE = "fyers_token.json"
    
    # Month codes for weekly options (Fyers specific)
    MONTH_CODES = {
        1: '1', 2: '2', 3: '3', 4: '4', 5: '5', 6: '6',
        7: '7', 8: '8', 9: '9', 10: 'O', 11: 'N', 12: 'D'
    }
    
    def get_candle_data(self, symbol: str, timeframe: int) -> Optional[dict]:
        """
        Get previous candle close/low for the given timeframe.  The argument may
        be an underlying index (e.g. "NIFTY") or a fully‑qualified symbol
        ("NFO:NIFTY23FEB15000CE").
        """
        try:
            # normalize to Fyers format; if the caller passed a raw index name
            # look it up in the config table.  Otherwise assume the symbol is
            # already valid.
            if ":" not in symbol:
                symbol = config.FYERS_INDEX_SYMBOLS.get(symbol.upper(), symbol)
            if not symbol:
                return None
            
            # Fyers resolution format
            resolution_map = {
                5: "5",
                15: "15",
                30: "30",
                60: "60",
            }
            resolution = resolution_map.get(timeframe, "5")
            
            # Get last 2 candles
            from datetime import datetime, timedelta
            
            now = datetime.now()
            # Go back enough time to get at least 2 candles
            range_from = now - timedelta(minutes=timeframe * 3)
            range_to = now
            
            data = {
                "symbol": symbol,
                "resolution": resolution,
                "date_format": "1",  # epoch
                "range_from": int(range_from.timestamp()),
                "range_to": int(range_to.timestamp()),
                "cont_flag": "1",
            }
            
            response = self.fyers.history(data)
            
            if response.get("s") == "ok" and "candles" in response:
                candles = response["candles"]
                
                if len(candles) >= 2:
                    # Previous completed candle (second to last)
                    prev_candle = candles[-2]
                    # Format: [timestamp, open, high, low, close, volume]
                    return {
                        "timeframe": f"{timeframe}min" if timeframe < 60 else "1hr",
                        "timestamp": prev_candle[0],
                        "open": prev_candle[1],
                        "high": prev_candle[2],
                        "low": prev_candle[3],
                        "close": prev_candle[4],
                        "volume": prev_candle[5],
                    }
                elif len(candles) == 1:
                    candle = candles[0]
                    return {
                        "timeframe": f"{timeframe}min" if timeframe < 60 else "1hr",
                        "timestamp": candle[0],
                        "open": candle[1],
                        "high": candle[2],
                        "low": candle[3],
                        "close": candle[4],
                        "volume": candle[5],
                    }
            
            print(f"⚠️ Candle data not found: {response}")
            return None
            
        except Exception as e:
            print(f"❌ Fyers candle data error: {e}")
            return None
    
    def __init__(self):
        super().__init__()
        self.fyers = None
        self._load_token()
    
    def _load_token(self):
        if os.path.exists(self.TOKEN_FILE):
            try:
                with open(self.TOKEN_FILE, "r") as f:
                    self.access_token = json.load(f).get("access_token")
                    self._init_client()
                    self.get_profile()
                    self.is_authenticated = True
                    print("✅ Fyers: Token loaded")
                    self.load_instruments()
            except Exception as e:
                print(f"⚠️ Fyers: Token invalid - {e}")
                self.access_token = None
                self.is_authenticated = False
    
    def _init_client(self):
        if self.access_token:
            self.fyers = fyersModel.FyersModel(
                client_id=config.FYERS_APP_ID,
                token=self.access_token,
                log_path=""
            )
    
    def get_login_url(self) -> str:
        session = fyersModel.SessionModel(
            client_id=config.FYERS_APP_ID,
            secret_key=config.FYERS_SECRET_KEY,
            redirect_uri=config.FYERS_REDIRECT_URL,
            response_type="code",
            grant_type="authorization_code"
        )
        return session.generate_authcode()
    
    def generate_session(self, auth_code: str) -> bool:
        try:
            session = fyersModel.SessionModel(
                client_id=config.FYERS_APP_ID,
                secret_key=config.FYERS_SECRET_KEY,
                redirect_uri=config.FYERS_REDIRECT_URL,
                response_type="code",
                grant_type="authorization_code"
            )
            session.set_token(auth_code)
            response = session.generate_token()
            
            if "access_token" in response:
                self.access_token = response["access_token"]
                self._init_client()
                
                with open(self.TOKEN_FILE, "w") as f:
                    json.dump({"access_token": self.access_token}, f)
                
                self.is_authenticated = True
                self.load_instruments()
                print("✅ Fyers: Session created")
                return True
            
            print(f"❌ Fyers: No access_token")
            return False
        except Exception as e:
            print(f"❌ Fyers: Session failed - {e}")
            return False
    
    def get_profile(self) -> dict:
        response = self.fyers.get_profile()
        data = response.get("data", response)
        return {
            "broker": "FYERS",
            "user_name": data.get("name", ""),
            "user_id": data.get("fy_id", ""),
        }
    
    def load_instruments(self) -> bool:
        try:
            print("📥 Fyers: Loading instruments...")
            self.instruments_cache.clear()
            
            # Fetch index prices
            self._fetch_all_index_prices()
            
            # Get expiries
            expiries = self._get_expiries()
            
            for index in ["NIFTY", "BANKNIFTY", "SENSEX"]:
                exp_list = expiries.get(index, [])
                step = config.STRIKE_STEPS.get(index, 50)
                lot = config.LOT_SIZES.get(index, 50)
                exchange = "BFO" if index == "SENSEX" else "NFO"
                
                # Get current price
                base = self.index_prices.get(index) or config.DEFAULT_ATM.get(index, 22500)
                base = round(base / step) * step
                
                for expiry in exp_list[:4]:
                    for offset in range(-30, 31):
                        strike = int(base + (offset * step))
                        if strike <= 0:
                            continue
                        
                        for opt in ["CE", "PE"]:
                            key = f"{index}_{strike}_{opt}_{expiry}"
                            symbol = self._make_symbol(index, strike, opt, expiry)
                            self.instruments_cache[key] = {
                                "symbol": symbol,
                                "name": index,
                                "strike": strike,
                                "type": opt,
                                "expiry": expiry,
                                "lot": lot,
                                "exchange": exchange,
                            }
            
            self.instruments_loaded = True
            print(f"✅ Fyers: {len(self.instruments_cache)} instruments")
            
            # Test a symbol
            self._test_symbol()
            
            return True
        except Exception as e:
            print(f"❌ Fyers: Load failed - {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def _test_symbol(self):
        """Test symbol with actual Fyers API"""
        try:
            nifty_price = self.index_prices.get("NIFTY", 25000)
            atm = round(nifty_price / 50) * 50
            
            expiries = self._get_expiries()
            if expiries.get("NIFTY"):
                expiry = expiries["NIFTY"][0]
                symbol = self._make_symbol("NIFTY", atm, "CE", expiry)
                
                print(f"🧪 Testing symbol: {symbol}")
                response = self.fyers.quotes({"symbols": symbol})
                
                if response.get("s") == "ok" and "d" in response:
                    ltp = response["d"][0].get("v", {}).get("lp") if response["d"] else None
                    print(f"🧪 Response: Status={response.get('s')}, LTP={ltp}")
                else:
                    print(f"🧪 Response: {response}")
        except Exception as e:
            print(f"🧪 Symbol test error: {e}")
    
    def _fetch_all_index_prices(self):
        try:
            symbols = ",".join(config.FYERS_INDEX_SYMBOLS.values())
            response = self.fyers.quotes({"symbols": symbols})
            
            if response.get("s") == "ok" and "d" in response:
                for item in response["d"]:
                    symbol = item.get("n", "")
                    price = item.get("v", {}).get("lp", 0)
                    
                    for name, sym in config.FYERS_INDEX_SYMBOLS.items():
                        if symbol == sym and price > 0:
                            self.index_prices[name] = price
                            print(f"  📊 {name}: {price}")
                            break
        except Exception as e:
            print(f"⚠️ Fyers: Index price fetch failed - {e}")
    
    def _get_expiries(self) -> dict:
        """Get upcoming expiry dates - FIXED VERSION"""
        today = datetime.now().date()
        expiries = {"NIFTY": [], "BANKNIFTY": [], "SENSEX": []}
        
        print(f"📅 Today is: {today} (Weekday: {today.weekday()})")
        
        # Find next 8 Thursdays for NIFTY/BANKNIFTY
        current_date = today
        
        for _ in range(60):  # Check next 60 days
            # Thursday is weekday 3
            if current_date.weekday() == 3 and current_date >= today:
                exp_str = current_date.strftime("%Y-%m-%d")
                if exp_str not in expiries["NIFTY"]:
                    expiries["NIFTY"].append(exp_str)
                    expiries["BANKNIFTY"].append(exp_str)
                    
                if len(expiries["NIFTY"]) >= 8:
                    break
            
            current_date += timedelta(days=1)
        
        # Find next 8 Fridays for SENSEX
        current_date = today
        
        for _ in range(60):
            # Friday is weekday 4
            if current_date.weekday() == 4 and current_date >= today:
                exp_str = current_date.strftime("%Y-%m-%d")
                if exp_str not in expiries["SENSEX"]:
                    expiries["SENSEX"].append(exp_str)
                    
                if len(expiries["SENSEX"]) >= 8:
                    break
            
            current_date += timedelta(days=1)
        
        print(f"📅 NIFTY expiries: {expiries['NIFTY'][:3]}")
        print(f"📅 SENSEX expiries: {expiries['SENSEX'][:3]}")
        
        return expiries
    
    def _make_symbol(self, index: str, strike: int, opt_type: str, expiry: str) -> str:
        """
        Construct Fyers option symbol
        Format: NFO:NIFTY2530525200CE
        """
        d = datetime.strptime(expiry, "%Y-%m-%d")
        year = d.strftime("%y")
        day = d.strftime("%d")
        month_num = d.month
        month_name = d.strftime("%b").upper()
        
        exchange = "BFO" if index == "SENSEX" else "NFO"
        
        # Check if monthly expiry (last Thursday/Friday)
        is_monthly = self._is_monthly_expiry(d)
        
        if is_monthly:
            # Monthly: NIFTY25MAR25200CE
            symbol = f"{exchange}:{index}{year}{month_name}{strike}{opt_type}"
        else:
            # Weekly: NIFTY2530525200CE (YY + MonthCode + DD + Strike)
            month_code = self.MONTH_CODES.get(month_num, str(month_num))
            symbol = f"{exchange}:{index}{year}{month_code}{day}{strike}{opt_type}"
        
        return symbol
    
    def _is_monthly_expiry(self, expiry_date: datetime) -> bool:
        """Check if expiry is monthly (last Thursday/Friday of month)"""
        next_week = expiry_date + timedelta(days=7)
        return next_week.month != expiry_date.month
    
    def get_expiry_dates(self, index: str) -> List[str]:
        expiries = set()
        for inst in self.instruments_cache.values():
            if inst["name"] == index.upper():
                expiries.add(inst["expiry"])
        return sorted(list(expiries))[:8]
    
    def get_strikes(self, index: str, expiry: str) -> List[int]:
        strikes = set()
        for inst in self.instruments_cache.values():
            if inst["name"] == index.upper() and inst["expiry"] == expiry:
                strikes.add(int(inst["strike"]))
        return sorted(list(strikes))
    
    def get_option_symbol(self, index: str, strike: int, option_type: str, expiry: str) -> Optional[str]:
        key = f"{index.upper()}_{strike}_{option_type.upper()}_{expiry}"
        inst = self.instruments_cache.get(key)
        if inst:
            return inst["symbol"]
        return self._make_symbol(index.upper(), strike, option_type.upper(), expiry)
    
    def get_index_quote(self, index: str) -> Optional[dict]:
        try:
            symbol = config.FYERS_INDEX_SYMBOLS.get(index.upper())
            if not symbol:
                return None
            
            response = self.fyers.quotes({"symbols": symbol})
            
            if response.get("s") == "ok" and "d" in response and len(response["d"]) > 0:
                v = response["d"][0].get("v", {})
                price = v.get("lp", 0)
                
                if price > 0:
                    self.index_prices[index.upper()] = price
                
                return {
                    "price": price,
                    "change": v.get("ch", 0),
                    "change_percent": v.get("chp", 0),
                }
            
            if index.upper() in self.index_prices:
                return {"price": self.index_prices[index.upper()], "change": 0, "change_percent": 0}
            
            return None
        except Exception as e:
            print(f"❌ Fyers: Index quote failed - {e}")
            if index.upper() in self.index_prices:
                return {"price": self.index_prices[index.upper()], "change": 0, "change_percent": 0}
            return None
    
    def get_ltp(self, symbol: str, exchange: str = None) -> Optional[float]:
        """Get LTP for an option or index.

        The broker sometimes requires different prefixing, so if the first
        request returns nothing we try a couple of reasonable alternatives
        before giving up.
        """
        try:
            if not symbol.startswith(("NSE:", "NFO:", "BSE:", "BFO:")):
                symbol = f"{exchange or 'NFO'}:{symbol}"
            
            print(f"📡 Fetching LTP: {symbol}")
            
            response = self.fyers.quotes({"symbols": symbol})
            
            print(f"📡 Response: {response}")
            
            if response.get("s") == "ok" and "d" in response and len(response["d"]) > 0:
                ltp = response["d"][0].get("v", {}).get("lp")
                if ltp:
                    print(f"✅ LTP: {ltp}")
                    return ltp
            
            # try alternate prefixes if nothing came back
            if symbol.startswith("NFO:"):
                alt = symbol.replace("NFO:", "NSE:")
            elif symbol.startswith("NSE:"):
                alt = symbol.replace("NSE:", "NFO:")
            else:
                alt = None
            if alt:
                print(f"📡 retrying LTP with alternate prefix {alt}")
                response = self.fyers.quotes({"symbols": alt})
                if response.get("s") == "ok" and "d" in response and len(response["d"]) > 0:
                    ltp = response["d"][0].get("v", {}).get("lp")
                    if ltp:
                        print(f"✅ LTP (alt): {ltp}")
                        return ltp
            
            print(f"⚠️ No LTP in response")
            return None
        except Exception as e:
            print(f"❌ Fyers LTP failed: {e}")
            return None
    
    def place_order(self, symbol: str, exchange: str, transaction_type: str,
                    quantity: int, order_type: str = "MARKET", price: float = 0) -> Optional[str]:
        try:
            if not symbol.startswith(("NSE:", "NFO:", "BSE:", "BFO:")):
                symbol = f"{exchange}:{symbol}"
            
            data = {
                "symbol": symbol,
                "qty": quantity,
                "type": 2 if order_type == "MARKET" else 1,
                "side": 1 if transaction_type == "BUY" else -1,
                "productType": "INTRADAY",
                "limitPrice": 0,
                "stopPrice": 0,
                "validity": "DAY",
                "disclosedQty": 0,
                "offlineOrder": False,
            }
            
            response = self.fyers.place_order(data)
            
            if response.get("s") == "ok":
                order_id = response.get("id")
                print(f"✅ Fyers: Order {order_id}")
                return str(order_id)
            
            print(f"❌ Fyers: Order failed - {response}")
            return None
        except Exception as e:
            print(f"❌ Fyers: Order failed - {e}")
            return None