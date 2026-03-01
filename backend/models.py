from pydantic import BaseModel
from typing import Optional
from enum import Enum
from datetime import datetime


class OptionType(str, Enum):
    CE = "CE"
    PE = "PE"


class IndexName(str, Enum):
    NIFTY = "NIFTY"
    BANKNIFTY = "BANKNIFTY"
    SENSEX = "SENSEX"


class TradeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SL_HIT = "SL_HIT"
    WAITING_REENTRY = "WAITING_REENTRY"
    CLOSED = "CLOSED"


class TradeRequest(BaseModel):
    index: IndexName
    option_type: OptionType
    strike_price: int
    expiry: str  # Format: "2024-01-25"
    entry_price: float
    lots: int = 1


class CloseTradeRequest(BaseModel):
    trade_id: str


class TradeState(BaseModel):
    trade_id: str
    index: IndexName
    option_type: OptionType
    strike_price: int
    expiry: str
    trading_symbol: str
    entry_price: float  # Locked entry price
    current_price: float
    sl_price: float
    lots: int
    current_lots: int
    quantity: int
    status: TradeStatus
    reentry_count: int
    pnl: float
    order_ids: list
    created_at: str
    last_updated: str


class OrderResponse(BaseModel):
    success: bool
    message: str
    trade_id: Optional[str] = None
    order_id: Optional[str] = None