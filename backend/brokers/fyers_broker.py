from fyers_apiv3 import fyersModel
from typing import Optional, List, Dict
from datetime import datetime, timedelta
import json
import os
from .base_broker import BaseBroker
import config


class FyersBroker(BaseBroker):
    """Fyers - Full Quote API"""
    
    BROKER_NAME = "FYERS"
    HAS_QUOTE_API = True
    TOKEN_FILE = "fyers_token.json"
    
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
            
            # Fetch index prices first
            self._fetch_all_index_prices()
            
            expiries = self._get_expiries()
            
            for index in ["NIFTY", "BANKNIFTY", "SENSEX"]:
                exp_list = expiries.get(index, [])
                step = config.STRIKE_STEPS.get(index, 50)
                lot = config.LOT_SIZES.get(index, 50)
                exchange = "BFO" if index == "SENSEX" else "NFO"
                
                # Get base price
                base = self.index_prices.get(index) or config.DEFAULT_ATM.get(index, 22500)
                base = round(base / step) * step
                
                for expiry in exp_list[:4]:
                    for offset in range(-40, 41):
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
            return True
        except Exception as e:
            print(f"❌ Fyers: Load failed - {e}")
            return False
    
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
                            print(f"  {name}: {price}")
                            break
        except Exception as e:
            print(f"⚠️ Fyers: Index price fetch failed - {e}")
    
    def _get_expiries(self) -> dict:
        today = datetime.now().date()
        expiries = {"NIFTY": [], "BANKNIFTY": [], "SENSEX": []}
        
        current = today
        while len(expiries["NIFTY"]) < 8:
            days_ahead = (3 - current.weekday()) % 7
            if days_ahead == 0 and current != today:
                days_ahead = 7
            next_thu = current + timedelta(days=days_ahead)
            
            if next_thu >= today:
                exp_str = next_thu.strftime("%Y-%m-%d")
                if exp_str not in expiries["NIFTY"]:
                    expiries["NIFTY"].append(exp_str)
                    expiries["BANKNIFTY"].append(exp_str)
            
            current = next_thu + timedelta(days=1)
        
        current = today
        while len(expiries["SENSEX"]) < 8:
            days_ahead = (4 - current.weekday()) % 7
            if days_ahead == 0 and current != today:
                days_ahead = 7
            next_fri = current + timedelta(days=days_ahead)
            
            if next_fri >= today:
                exp_str = next_fri.strftime("%Y-%m-%d")
                if exp_str not in expiries["SENSEX"]:
                    expiries["SENSEX"].append(exp_str)
            
            current = next_fri + timedelta(days=1)
        
        return expiries
    
    def _make_symbol(self, index: str, strike: int, opt_type: str, expiry: str) -> str:
        d = datetime.strptime(expiry, "%Y-%m-%d")
        month_str = d.strftime("%y%b").upper()
        exchange = "BFO" if index == "SENSEX" else "NFO"
        return f"{exchange}:{index}{month_str}{strike}{opt_type}"
    
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
        return self._make_symbol(index, strike, option_type, expiry)
    
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
            
            # Return cached
            if index.upper() in self.index_prices:
                return {"price": self.index_prices[index.upper()], "change": 0, "change_percent": 0}
            
            return None
        except Exception as e:
            print(f"❌ Fyers: Index quote failed - {e}")
            if index.upper() in self.index_prices:
                return {"price": self.index_prices[index.upper()], "change": 0, "change_percent": 0}
            return None
    
    def get_ltp(self, symbol: str, exchange: str = None) -> Optional[float]:
        try:
            if not symbol.startswith(("NSE:", "NFO:", "BSE:", "BFO:")):
                symbol = f"{exchange or 'NFO'}:{symbol}"
            
            response = self.fyers.quotes({"symbols": symbol})
            
            if response.get("s") == "ok" and "d" in response and len(response["d"]) > 0:
                return response["d"][0].get("v", {}).get("lp")
            return None
        except Exception as e:
            print(f"❌ Fyers: LTP failed - {e}")
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