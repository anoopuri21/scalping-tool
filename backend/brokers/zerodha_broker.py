from kiteconnect import KiteConnect
from typing import Optional, List
from datetime import date
import json
import os
from .base_broker import BaseBroker
import config


class ZerodhaBroker(BaseBroker):
    """Zerodha - No Quote API"""
    
    BROKER_NAME = "ZERODHA"
    HAS_QUOTE_API = False
    TOKEN_FILE = "zerodha_token.json"
    
    def __init__(self):
        super().__init__()
        self.kite = KiteConnect(api_key=config.ZERODHA_API_KEY)
        self._load_token()
    
    def _load_token(self):
        if os.path.exists(self.TOKEN_FILE):
            try:
                with open(self.TOKEN_FILE, "r") as f:
                    self.access_token = json.load(f).get("access_token")
                    self.kite.set_access_token(self.access_token)
                    self.kite.profile()
                    self.is_authenticated = True
                    print("✅ Zerodha: Token loaded")
                    self.load_instruments()
            except Exception as e:
                print(f"⚠️ Zerodha: Token invalid - {e}")
                self.access_token = None
                self.is_authenticated = False
    
    def get_login_url(self) -> str:
        return self.kite.login_url()
    
    def generate_session(self, request_token: str) -> bool:
        try:
            data = self.kite.generate_session(request_token, api_secret=config.ZERODHA_API_SECRET)
            self.access_token = data["access_token"]
            self.kite.set_access_token(self.access_token)
            
            with open(self.TOKEN_FILE, "w") as f:
                json.dump({"access_token": self.access_token}, f)
            
            self.is_authenticated = True
            self.load_instruments()
            print("✅ Zerodha: Session created")
            return True
        except Exception as e:
            print(f"❌ Zerodha: Session failed - {e}")
            return False
    
    def get_profile(self) -> dict:
        profile = self.kite.profile()
        return {
            "broker": "ZERODHA",
            "user_name": profile.get("user_name", ""),
            "user_id": profile.get("user_id", ""),
        }
    
    def load_instruments(self) -> bool:
        try:
            print("📥 Zerodha: Loading instruments...")
            self.instruments_cache.clear()
            
            # NFO
            for inst in self.kite.instruments("NFO"):
                if inst["name"] in ["NIFTY", "BANKNIFTY"] and inst["instrument_type"] in ["CE", "PE"]:
                    expiry = inst["expiry"].strftime("%Y-%m-%d") if isinstance(inst["expiry"], date) else str(inst["expiry"])
                    key = f"{inst['name']}_{int(inst['strike'])}_{inst['instrument_type']}_{expiry}"
                    self.instruments_cache[key] = {
                        "symbol": inst["tradingsymbol"],
                        "token": inst["instrument_token"],
                        "name": inst["name"],
                        "strike": inst["strike"],
                        "type": inst["instrument_type"],
                        "expiry": expiry,
                        "exchange": "NFO",
                    }
            
            # BFO
            try:
                for inst in self.kite.instruments("BFO"):
                    if inst["name"] == "SENSEX" and inst["instrument_type"] in ["CE", "PE"]:
                        expiry = inst["expiry"].strftime("%Y-%m-%d") if isinstance(inst["expiry"], date) else str(inst["expiry"])
                        key = f"{inst['name']}_{int(inst['strike'])}_{inst['instrument_type']}_{expiry}"
                        self.instruments_cache[key] = {
                            "symbol": inst["tradingsymbol"],
                            "token": inst["instrument_token"],
                            "name": inst["name"],
                            "strike": inst["strike"],
                            "type": inst["instrument_type"],
                            "expiry": expiry,
                            "exchange": "BFO",
                        }
            except:
                pass
            
            self.instruments_loaded = True
            print(f"✅ Zerodha: {len(self.instruments_cache)} instruments loaded")
            return True
        except Exception as e:
            print(f"❌ Zerodha: Load failed - {e}")
            return False
    
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
        return inst["symbol"] if inst else None
    
    def get_ltp(self, symbol: str, exchange: str) -> Optional[float]:
        return None  # No Quote API
    
    def get_index_quote(self, index: str) -> Optional[dict]:
        return None  # No Quote API
    
    def place_order(self, symbol: str, exchange: str, transaction_type: str,
                    quantity: int, order_type: str = "MARKET", price: float = 0) -> Optional[str]:
        try:
            txn = self.kite.TRANSACTION_TYPE_BUY if transaction_type == "BUY" else self.kite.TRANSACTION_TYPE_SELL
            
            order_id = self.kite.place_order(
                variety=self.kite.VARIETY_REGULAR,
                exchange=exchange,
                tradingsymbol=symbol,
                transaction_type=txn,
                quantity=quantity,
                product=self.kite.PRODUCT_MIS,
                order_type=self.kite.ORDER_TYPE_MARKET,
            )
            print(f"✅ Zerodha: Order {order_id}")
            return str(order_id)
        except Exception as e:
            print(f"❌ Zerodha: Order failed - {e}")
            return None