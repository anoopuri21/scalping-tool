from abc import ABC, abstractmethod
from typing import Optional, List, Dict
import config


class BaseBroker(ABC):
    """Base broker interface"""
    
    BROKER_NAME = "BASE"
    HAS_QUOTE_API = False
    
    def __init__(self):
        self.access_token: Optional[str] = None
        self.is_authenticated: bool = False
        self.instruments_cache: Dict[str, dict] = {}
        self.instruments_loaded: bool = False
        self.index_prices: Dict[str, float] = {}
    
    @abstractmethod
    def get_login_url(self) -> str:
        pass
    
    @abstractmethod
    def generate_session(self, auth_code: str) -> bool:
        pass
    
    @abstractmethod
    def get_profile(self) -> dict:
        pass
    
    @abstractmethod
    def load_instruments(self) -> bool:
        pass
    
    @abstractmethod
    def get_expiry_dates(self, index: str) -> List[str]:
        pass
    
    @abstractmethod
    def get_strikes(self, index: str, expiry: str) -> List[int]:
        pass
    
    @abstractmethod
    def get_ltp(self, symbol: str, exchange: str) -> Optional[float]:
        pass
    
    @abstractmethod
    def get_index_quote(self, index: str) -> Optional[dict]:
        pass
    
    @abstractmethod
    def get_option_symbol(self, index: str, strike: int, option_type: str, expiry: str) -> Optional[str]:
        pass
    
    @abstractmethod
    def place_order(self, symbol: str, exchange: str, transaction_type: str,
                    quantity: int, order_type: str, price: float,
                    trigger_price: float = 0) -> Optional[str]:
        pass

    def get_recent_candles(self, symbol: str, resolution: str = "5", count: int = 3) -> List[dict]:
        """Return recent candles for a symbol as list of {timestamp, low, close}."""
        return []
    
    # ============ COMMON METHODS (Use Config) ============
    
    def get_lot_size(self, index: str) -> int:
        """Get lot size from config"""
        return config.LOT_SIZES.get(index.upper(), 50)
    
    def get_strike_step(self, index: str) -> int:
        """Get strike step from config"""
        return config.STRIKE_STEPS.get(index.upper(), 50)
    
    def get_exchange(self, index: str) -> str:
        """Get exchange for index"""
        return "BFO" if index.upper() == "SENSEX" else "NFO"
    
    def get_atm_strike(self, index: str) -> int:
        """Get ATM strike based on current price"""
        index = index.upper()
        
        # Try cached price first
        price = self.index_prices.get(index, 0)
        
        # If no cached price, try to fetch
        if price == 0 and self.HAS_QUOTE_API:
            quote = self.get_index_quote(index)
            if quote and quote.get("price"):
                price = quote["price"]
        
        # Fallback to default
        if price == 0:
            price = config.DEFAULT_ATM.get(index, 22500)
        
        step = self.get_strike_step(index)
        return int(round(price / step) * step)
