from fyers_apiv3 import fyersModel
from typing import Optional, List, Dict
from datetime import datetime, timedelta
import json
import os
import time
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
        self.quote_cache: Dict[str, tuple[float, float]] = {}
        self.quote_cache_ttl = 1.5
        self._load_token()

    @staticmethod
    def _extract_quote_records(response: dict) -> List[dict]:
        if not isinstance(response, dict):
            return []
        records = response.get("d")
        if isinstance(records, list):
            return records
        data = response.get("data")
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and isinstance(data.get("d"), list):
            return data.get("d")
        return []

    @staticmethod
    def _extract_ltp(record: dict) -> Optional[float]:
        if not isinstance(record, dict):
            return None
        v = record.get("v", {})
        for key in ("lp", "ltp", "last_price"):
            value = v.get(key) if isinstance(v, dict) else None
            if value is None:
                value = record.get(key)
            if value is not None:
                try:
                    return float(value)
                except (TypeError, ValueError):
                    continue
        return None

    def get_quotes_batch(self, symbols: List[str]) -> Dict[str, float]:
        now = time.time()
        result: Dict[str, float] = {}
        pending: List[str] = []

        for symbol in symbols:
            cached = self.quote_cache.get(symbol)
            if cached and (now - cached[1]) <= self.quote_cache_ttl:
                result[symbol] = cached[0]
            else:
                pending.append(symbol)

        if not pending:
            return result

        response = self.fyers.quotes({"symbols": ",".join(pending)})
        for item in self._extract_quote_records(response):
            symbol = item.get("n") or item.get("symbol")
            ltp = self._extract_ltp(item)
            if symbol and ltp is not None and ltp > 0:
                result[symbol] = ltp
                self.quote_cache[symbol] = (ltp, now)

        return result
    
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
            
            for item in self._extract_quote_records(response):
                symbol = item.get("n", "")
                price = self._extract_ltp(item) or 0

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
            records = self._extract_quote_records(response)

            if records:
                first = records[0]
                v = first.get("v", {}) if isinstance(first.get("v"), dict) else {}
                price = self._extract_ltp(first) or 0

                if price > 0:
                    self.index_prices[index.upper()] = price
                    self.quote_cache[symbol] = (price, time.time())

                return {
                    "price": price,
                    "change": float(v.get("ch") or first.get("ch") or 0),
                    "change_percent": float(v.get("chp") or first.get("chp") or 0),
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
            return self.get_quotes_batch([symbol]).get(symbol)
        except Exception as e:
            print(f"❌ Fyers: LTP failed - {e}")
            return None

    def get_option_ltp_for_strikes(self, index: str, expiry: str, strikes: List[int]) -> Dict[int, dict]:
        chain_map: Dict[int, dict] = {}
        symbols: List[str] = []

        for strike in strikes:
            ce_symbol = self.get_option_symbol(index, strike, "CE", expiry)
            pe_symbol = self.get_option_symbol(index, strike, "PE", expiry)
            chain_map[strike] = {
                "ce_ltp": None,
                "pe_ltp": None,
                "ce_symbol": ce_symbol,
                "pe_symbol": pe_symbol,
            }
            if ce_symbol:
                symbols.append(ce_symbol)
            if pe_symbol:
                symbols.append(pe_symbol)

        if not symbols:
            return chain_map

        ltp_map = self.get_quotes_batch(symbols)
        for strike, info in chain_map.items():
            ce_symbol = info.get("ce_symbol")
            pe_symbol = info.get("pe_symbol")
            if ce_symbol in ltp_map:
                info["ce_ltp"] = ltp_map[ce_symbol]
            if pe_symbol in ltp_map:
                info["pe_ltp"] = ltp_map[pe_symbol]
        return chain_map

    def get_option_chain_ltp(self, index: str) -> Dict[int, dict]:
        """Fetch option chain and map strike -> {ce_ltp, pe_ltp, ce_symbol, pe_symbol}."""
        chain_map: Dict[int, dict] = {}
        try:
            symbol = config.FYERS_INDEX_SYMBOLS.get(index.upper())
            if not symbol:
                return chain_map

            response = self.fyers.optionchain({"symbol": symbol, "strikecount": 30, "timestamp": ""})
            if response.get("s") != "ok":
                return chain_map

            for item in response.get("data", {}).get("optionsChain", []):
                strike = item.get("strike_price")
                option_type = item.get("option_type")
                if strike is None or option_type not in ["CE", "PE"]:
                    continue

                if strike not in chain_map:
                    chain_map[strike] = {
                        "ce_ltp": None,
                        "pe_ltp": None,
                        "ce_symbol": None,
                        "pe_symbol": None,
                    }

                chain_map[strike][f"{option_type.lower()}_ltp"] = item.get("ltp")
                chain_map[strike][f"{option_type.lower()}_symbol"] = item.get("symbol")

            return chain_map
        except Exception as e:
            print(f"⚠️ Fyers: Option chain fetch failed - {e}")
            return chain_map

    def get_recent_candles(self, symbol: str, resolution: str = "5", count: int = 3) -> List[dict]:
        try:
            if not symbol:
                return []

            to_date = datetime.now().date()
            from_date = to_date - timedelta(days=5)

            response = self.fyers.history({
                "symbol": symbol,
                "resolution": resolution,
                "date_format": "1",
                "range_from": from_date.strftime("%Y-%m-%d"),
                "range_to": to_date.strftime("%Y-%m-%d"),
                "cont_flag": "1",
            })

            candles = response.get("candles", []) if isinstance(response, dict) else []
            if not candles:
                return []

            recent = candles[-count:]
            result = []
            for candle in recent:
                # [timestamp, open, high, low, close, volume]
                result.append({
                    "timestamp": candle[0],
                    "low": candle[3],
                    "close": candle[4],
                })
            return result
        except Exception as e:
            print(f"⚠️ Fyers: Candle fetch failed - {e}")
            return []
    
    def place_order(self, symbol: str, exchange: str, transaction_type: str,
                    quantity: int, order_type: str = "MARKET", price: float = 0,
                    trigger_price: float = 0) -> Optional[str]:
        try:
            if not symbol.startswith(("NSE:", "NFO:", "BSE:", "BFO:")):
                symbol = f"{exchange}:{symbol}"
            
            fyers_type = 2 if order_type == "MARKET" else (3 if order_type == "STOP_LIMIT" else 1)
            data = {
                "symbol": symbol,
                "qty": quantity,
                "type": fyers_type,
                "side": 1 if transaction_type == "BUY" else -1,
                "productType": "INTRADAY",
                "limitPrice": price if order_type in ["LIMIT", "STOP_LIMIT"] else 0,
                "stopPrice": trigger_price if order_type == "STOP_LIMIT" else 0,
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
