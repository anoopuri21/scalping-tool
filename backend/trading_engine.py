import uuid
from datetime import datetime, date
from typing import Dict, Optional, List
from kiteconnect import KiteConnect

import config
from models import (
    TradeState, TradeStatus, TradeRequest,
    OptionType, IndexName
)
from zerodha_auth import auth


class TradingEngine:
    def __init__(self):
        # Active trades: trade_id -> TradeState
        self.trades: Dict[str, TradeState] = {}
        # Instrument cache
        self.instruments_cache: Dict[str, dict] = {}
        self.instruments_loaded = False

    def get_kite(self) -> KiteConnect:
        return auth.get_kite()

    def load_instruments(self):
        """Load and cache instrument list"""
        try:
            kite = self.get_kite()
            print("📥 Loading instruments from Zerodha...")

            # Load NSE F&O instruments for NIFTY and BANKNIFTY
            nfo_instruments = kite.instruments("NFO")
            nfo_count = 0
            for inst in nfo_instruments:
                if inst["name"] in ["NIFTY", "BANKNIFTY"] and inst["instrument_type"] in ["CE", "PE"]:
                    key = f"{inst['name']}_{int(inst['strike'])}_{inst['instrument_type']}_{inst['expiry']}"
                    self.instruments_cache[key] = inst
                    nfo_count += 1

            print(f"✅ Loaded {nfo_count} NFO instruments (NIFTY/BANKNIFTY)")

            # Load BSE F&O instruments for SENSEX
            try:
                bfo_instruments = kite.instruments("BFO")
                bfo_count = 0
                for inst in bfo_instruments:
                    if inst["name"] == "SENSEX" and inst["instrument_type"] in ["CE", "PE"]:
                        key = f"{inst['name']}_{int(inst['strike'])}_{inst['instrument_type']}_{inst['expiry']}"
                        self.instruments_cache[key] = inst
                        bfo_count += 1
                print(f"✅ Loaded {bfo_count} BFO instruments (SENSEX)")
            except Exception as e:
                print(f"⚠️ BFO instruments load failed: {e}")

            self.instruments_loaded = True
            print(f"✅ Total instruments cached: {len(self.instruments_cache)}")
            
            # Debug: Print sample expiries
            sample_expiries = self.get_expiry_dates(IndexName.NIFTY)
            print(f"📅 Sample NIFTY expiries: {sample_expiries[:3]}")
            
        except Exception as e:
            print(f"❌ Failed to load instruments: {e}")
            import traceback
            traceback.print_exc()

    def get_expiry_dates(self, index: IndexName) -> List[str]:
        """Get available expiry dates for an index"""
        if not self.instruments_loaded:
            print("⚠️ Instruments not loaded yet")
            return []
            
        expiries = set()
        for key, inst in self.instruments_cache.items():
            if inst["name"] == index.value:
                # Convert date to string if needed
                expiry = inst["expiry"]
                if isinstance(expiry, date):
                    expiry = expiry.strftime("%Y-%m-%d")
                expiries.add(expiry)
        
        sorted_expiries = sorted(list(expiries))[:8]  # Next 8 expiries
        print(f"📅 Expiries for {index.value}: {sorted_expiries}")
        return sorted_expiries

    def get_strikes(self, index: IndexName, expiry: str) -> List[int]:
        """Get available strike prices"""
        if not self.instruments_loaded:
            print("⚠️ Instruments not loaded yet")
            return []
            
        strikes = set()
        # Parse expiry string to date for comparison
        try:
            expiry_date = datetime.strptime(expiry, "%Y-%m-%d").date()
        except:
            print(f"⚠️ Invalid expiry format: {expiry}")
            return []
        
        for key, inst in self.instruments_cache.items():
            if inst["name"] == index.value:
                inst_expiry = inst["expiry"]
                if isinstance(inst_expiry, date):
                    if inst_expiry == expiry_date:
                        strikes.add(int(inst["strike"]))
                else:
                    if str(inst_expiry) == expiry:
                        strikes.add(int(inst["strike"]))
        
        sorted_strikes = sorted(list(strikes))
        print(f"🎯 Strikes for {index.value} {expiry}: {len(sorted_strikes)} found")
        return sorted_strikes

    def find_instrument(self, index: IndexName, strike: int,
                        option_type: OptionType, expiry: str) -> Optional[dict]:
        """Find instrument details"""
        try:
            expiry_date = datetime.strptime(expiry, "%Y-%m-%d").date()
        except:
            return None
            
        key = f"{index.value}_{strike}_{option_type.value}_{expiry_date}"
        instrument = self.instruments_cache.get(key)
        
        if not instrument:
            # Debug
            print(f"🔍 Looking for key: {key}")
            print(f"🔍 Sample keys: {list(self.instruments_cache.keys())[:5]}")
            
        return instrument

    def get_trading_symbol(self, index: IndexName, strike: int,
                           option_type: OptionType, expiry: str) -> Optional[str]:
        """Get trading symbol for the option"""
        instrument = self.find_instrument(index, strike, option_type, expiry)
        if instrument:
            return instrument["tradingsymbol"]
        return None

    def get_instrument_token(self, index: IndexName, strike: int,
                             option_type: OptionType, expiry: str) -> Optional[int]:
        """Get instrument token for live price"""
        instrument = self.find_instrument(index, strike, option_type, expiry)
        if instrument:
            return instrument["instrument_token"]
        return None

    def get_exchange(self, index: IndexName) -> str:
        """Get exchange for index"""
        if index == IndexName.SENSEX:
            return "BFO"
        return "NFO"

    def get_lot_size(self, index: IndexName) -> int:
        """Get lot size for index"""
        return config.DEFAULT_LOT_SIZE.get(index.value, 25)

    def get_ltp(self, trading_symbol: str, exchange: str) -> Optional[float]:
        """Get Last Traded Price"""
        try:
            kite = self.get_kite()
            full_symbol = f"{exchange}:{trading_symbol}"
            data = kite.ltp([full_symbol])
            return data[full_symbol]["last_price"]
        except Exception as e:
            print(f"❌ LTP fetch failed: {e}")
            return None

    # def get_ltp_from_websocket(self, instrument_token: int) -> float:
    # """Get LTP from WebSocket cache"""
    # from websocket_manager import ws_manager
    # return ws_manager.get_latest_price(instrument_token)

    def place_buy_order(self, trading_symbol: str, exchange: str,
                        quantity: int) -> Optional[str]:
        """Place a market buy order"""
        try:
            kite = self.get_kite()
            order_id = kite.place_order(
                variety=kite.VARIETY_REGULAR,
                exchange=exchange,
                tradingsymbol=trading_symbol,
                transaction_type=kite.TRANSACTION_TYPE_BUY,
                quantity=quantity,
                product=kite.PRODUCT_MIS,  # Intraday
                order_type=kite.ORDER_TYPE_MARKET,
            )
            print(f"✅ Buy order placed: {order_id}")
            return str(order_id)
        except Exception as e:
            print(f"❌ Buy order failed: {e}")
            return None

    def place_sell_order(self, trading_symbol: str, exchange: str,
                         quantity: int) -> Optional[str]:
        """Place a market sell order"""
        try:
            kite = self.get_kite()
            order_id = kite.place_order(
                variety=kite.VARIETY_REGULAR,
                exchange=exchange,
                tradingsymbol=trading_symbol,
                transaction_type=kite.TRANSACTION_TYPE_SELL,
                quantity=quantity,
                product=kite.PRODUCT_MIS,  # Intraday
                order_type=kite.ORDER_TYPE_MARKET,
            )
            print(f"✅ Sell order placed: {order_id}")
            return str(order_id)
        except Exception as e:
            print(f"❌ Sell order failed: {e}")
            return None

    def enter_trade(self, request: TradeRequest) -> dict:
        """Enter a new trade"""
        # Check if same option trade already active
        for tid, trade in self.trades.items():
            if (trade.index == request.index and
                trade.option_type == request.option_type and
                trade.strike_price == request.strike_price and
                trade.expiry == request.expiry and
                trade.status in [TradeStatus.ACTIVE, TradeStatus.WAITING_REENTRY]):
                return {
                    "success": False,
                    "message": f"Trade already active for this option. Trade ID: {tid}"
                }

        # Find instrument
        trading_symbol = self.get_trading_symbol(
            request.index, request.strike_price,
            request.option_type, request.expiry
        )
        if not trading_symbol:
            return {
                "success": False,
                "message": "Option instrument not found. Check strike/expiry."
            }

        exchange = self.get_exchange(request.index)
        lot_size = self.get_lot_size(request.index)
        quantity = request.lots * lot_size

        # Place buy order
        order_id = self.place_buy_order(trading_symbol, exchange, quantity)
        if not order_id:
            return {
                "success": False,
                "message": "Failed to place buy order with Zerodha"
            }

        # Create trade state
        trade_id = str(uuid.uuid4())[:8]
        sl_price = request.entry_price - config.SL_POINTS

        trade = TradeState(
            trade_id=trade_id,
            index=request.index,
            option_type=request.option_type,
            strike_price=request.strike_price,
            expiry=request.expiry,
            trading_symbol=trading_symbol,
            entry_price=request.entry_price,  # LOCKED
            current_price=request.entry_price,
            sl_price=sl_price,
            lots=request.lots,
            current_lots=request.lots,
            quantity=quantity,
            status=TradeStatus.ACTIVE,
            reentry_count=0,
            pnl=0.0,
            order_ids=[order_id],
            created_at=datetime.now().isoformat(),
            last_updated=datetime.now().isoformat(),
        )

        self.trades[trade_id] = trade

        return {
            "success": True,
            "message": f"Trade entered! SL at {sl_price}",
            "trade_id": trade_id,
            "order_id": order_id,
        }

    def check_and_execute_sl(self, trade_id: str, current_price: float):
        """Check if SL is hit and execute"""
        if trade_id not in self.trades:
            return

        trade = self.trades[trade_id]
        if trade.status != TradeStatus.ACTIVE:
            return

        trade.current_price = current_price
        trade.pnl = (current_price - trade.entry_price) * trade.quantity
        trade.last_updated = datetime.now().isoformat()

        # Check SL
        if current_price <= trade.sl_price:
            print(f"🔴 SL HIT for {trade_id} at {current_price}")

            exchange = self.get_exchange(trade.index)
            order_id = self.place_sell_order(
                trade.trading_symbol, exchange, trade.quantity
            )

            if order_id:
                trade.order_ids.append(order_id)

            trade.status = TradeStatus.WAITING_REENTRY
            trade.last_updated = datetime.now().isoformat()

            print(f"⏳ Waiting for price to reach {trade.entry_price} for re-entry")

    def check_and_execute_reentry(self, trade_id: str, current_price: float):
        """Check if price reached entry point for re-entry"""
        if trade_id not in self.trades:
            return

        trade = self.trades[trade_id]
        if trade.status != TradeStatus.WAITING_REENTRY:
            return

        trade.current_price = current_price
        trade.last_updated = datetime.now().isoformat()

        # Check if price touches locked entry price
        if current_price >= trade.entry_price:
            print(f"🟢 RE-ENTRY triggered for {trade_id} at {current_price}")

            # Increase lots by 1
            new_lots = trade.current_lots + 1
            lot_size = self.get_lot_size(trade.index)
            new_quantity = new_lots * lot_size

            exchange = self.get_exchange(trade.index)
            order_id = self.place_buy_order(
                trade.trading_symbol, exchange, new_quantity
            )

            if order_id:
                trade.order_ids.append(order_id)
                trade.current_lots = new_lots
                trade.quantity = new_quantity
                trade.reentry_count += 1
                trade.sl_price = trade.entry_price - config.SL_POINTS
                trade.status = TradeStatus.ACTIVE
                trade.pnl = 0.0  # Reset PnL for new entry
                trade.last_updated = datetime.now().isoformat()

                print(f"✅ Re-entered with {new_lots} lots. SL: {trade.sl_price}")

    def process_price_update(self, trade_id: str, current_price: float):
        """Process a price update for a trade"""
        if trade_id not in self.trades:
            return

        trade = self.trades[trade_id]

        if trade.status == TradeStatus.ACTIVE:
            self.check_and_execute_sl(trade_id, current_price)
        elif trade.status == TradeStatus.WAITING_REENTRY:
            self.check_and_execute_reentry(trade_id, current_price)

    def close_trade(self, trade_id: str) -> dict:
        """Manually close a trade"""
        if trade_id not in self.trades:
            return {"success": False, "message": "Trade not found"}

        trade = self.trades[trade_id]

        if trade.status == TradeStatus.ACTIVE:
            exchange = self.get_exchange(trade.index)
            order_id = self.place_sell_order(
                trade.trading_symbol, exchange, trade.quantity
            )
            if order_id:
                trade.order_ids.append(order_id)

        trade.status = TradeStatus.CLOSED
        trade.last_updated = datetime.now().isoformat()

        return {
            "success": True,
            "message": f"Trade {trade_id} closed",
            "final_pnl": trade.pnl,
        }

    def get_all_trades(self) -> list:
        """Get all trades"""
        return [trade.dict() for trade in self.trades.values()]

    def get_active_trades(self) -> list:
        """Get only active/waiting trades"""
        return [
            trade.dict() for trade in self.trades.values()
            if trade.status in [TradeStatus.ACTIVE, TradeStatus.WAITING_REENTRY]
        ]


# Singleton
engine = TradingEngine()