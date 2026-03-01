import json
import threading
from kiteconnect import KiteTicker
from typing import Dict, Set, Callable, List
import asyncio

import config
from zerodha_auth import auth


class WebSocketManager:
    def __init__(self):
        self.ticker = None
        self.subscribed_tokens: Dict[int, str] = {}  # token -> trade_id
        self.index_tokens: Dict[str, int] = {}  # index_name -> token
        self.ws_clients: Set = set()
        self.running = False
        self._lock = threading.Lock()
        self.latest_prices: Dict[int, float] = {}  # token -> price
        self.price_callbacks: List[Callable] = []
        
        # Index instrument tokens (these are fixed)
        self.INDEX_TOKENS = {
            "NIFTY": 256265,      # NSE:NIFTY 50
            "BANKNIFTY": 260105,  # NSE:NIFTY BANK
            "SENSEX": 265,        # BSE:SENSEX (verify this token)
        }

    def start(self):
        """Start Kite WebSocket ticker"""
        if self.running:
            return

        if not auth.access_token:
            print("❌ Cannot start ticker: No access token")
            return

        try:
            self.ticker = KiteTicker(config.API_KEY, auth.access_token)

            self.ticker.on_ticks = self._on_ticks
            self.ticker.on_connect = self._on_connect
            self.ticker.on_close = self._on_close
            self.ticker.on_error = self._on_error

            # Run in background thread
            thread = threading.Thread(target=self._connect_ticker)
            thread.daemon = True
            thread.start()
            
            self.running = True
            print("✅ WebSocket ticker started")
        except Exception as e:
            print(f"❌ Failed to start ticker: {e}")

    def _connect_ticker(self):
        """Connect ticker in thread"""
        try:
            self.ticker.connect(threaded=True)
        except Exception as e:
            print(f"❌ Ticker connect error: {e}")
            self.running = False

    def _on_connect(self, ws, response):
        """On WebSocket connect"""
        print("✅ Ticker connected")
        
        # Subscribe to index tokens
        index_tokens = list(self.INDEX_TOKENS.values())
        if index_tokens:
            ws.subscribe(index_tokens)
            ws.set_mode(ws.MODE_LTP, index_tokens)
            print(f"✅ Subscribed to index tokens: {index_tokens}")
        
        # Subscribe to any existing trade tokens
        if self.subscribed_tokens:
            tokens = list(self.subscribed_tokens.keys())
            ws.subscribe(tokens)
            ws.set_mode(ws.MODE_LTP, tokens)

    def _on_ticks(self, ws, ticks):
        """Process incoming ticks"""
        for tick in ticks:
            token = tick["instrument_token"]
            ltp = tick["last_price"]
            
            # Store latest price
            self.latest_prices[token] = ltp
            
            # Check if it's a trade token
            if token in self.subscribed_tokens:
                trade_id = self.subscribed_tokens[token]
                # Import here to avoid circular import
                from trading_engine import engine
                engine.process_price_update(trade_id, ltp)

                # Broadcast to frontend
                self._broadcast({
                    "type": "tick",
                    "trade_id": trade_id,
                    "price": ltp,
                    "trade": engine.trades[trade_id].dict()
                    if trade_id in engine.trades else None
                })
            
            # Check if it's an index token
            for index_name, index_token in self.INDEX_TOKENS.items():
                if token == index_token:
                    self._broadcast({
                        "type": "index_tick",
                        "index": index_name,
                        "price": ltp
                    })
                    break

    def _on_close(self, ws, code, reason):
        print(f"⚠️ Ticker closed: {code} - {reason}")
        self.running = False
        # Try to reconnect after 5 seconds
        threading.Timer(5.0, self.start).start()

    def _on_error(self, ws, code, reason):
        print(f"❌ Ticker error: {code} - {reason}")

    def subscribe_trade(self, trade_id: str, instrument_token: int):
        """Subscribe to price updates for a trade"""
        with self._lock:
            self.subscribed_tokens[instrument_token] = trade_id
            if self.ticker and self.running:
                try:
                    self.ticker.subscribe([instrument_token])
                    self.ticker.set_mode(self.ticker.MODE_LTP, [instrument_token])
                    print(f"✅ Subscribed token {instrument_token} for trade {trade_id}")
                except Exception as e:
                    print(f"❌ Subscribe error: {e}")

    def unsubscribe_trade(self, instrument_token: int):
        """Unsubscribe from price updates"""
        with self._lock:
            if instrument_token in self.subscribed_tokens:
                del self.subscribed_tokens[instrument_token]
                if self.ticker and self.running:
                    try:
                        self.ticker.unsubscribe([instrument_token])
                    except:
                        pass

    def subscribe_option(self, instrument_token: int):
        """Subscribe to an option token for price updates"""
        with self._lock:
            if self.ticker and self.running:
                try:
                    self.ticker.subscribe([instrument_token])
                    self.ticker.set_mode(self.ticker.MODE_LTP, [instrument_token])
                except Exception as e:
                    print(f"❌ Option subscribe error: {e}")

    def get_latest_price(self, instrument_token: int) -> float:
        """Get latest price from cache"""
        return self.latest_prices.get(instrument_token, 0)

    def get_index_price(self, index_name: str) -> float:
        """Get latest index price"""
        token = self.INDEX_TOKENS.get(index_name)
        if token:
            return self.latest_prices.get(token, 0)
        return 0

    def _broadcast(self, data: dict):
        """Broadcast data to all frontend WS clients"""
        message = json.dumps(data, default=str)
        disconnected = set()
        
        for client in list(self.ws_clients):
            try:
                # Use asyncio for async send
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(client.send_text(message))
                loop.close()
            except Exception as e:
                disconnected.add(client)
        
        self.ws_clients -= disconnected

    def add_client(self, websocket):
        self.ws_clients.add(websocket)
        # Send current index prices to new client
        for index_name, token in self.INDEX_TOKENS.items():
            if token in self.latest_prices:
                try:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    loop.run_until_complete(websocket.send_text(json.dumps({
                        "type": "index_tick",
                        "index": index_name,
                        "price": self.latest_prices[token]
                    })))
                    loop.close()
                except:
                    pass

    def remove_client(self, websocket):
        self.ws_clients.discard(websocket)


# Singleton
ws_manager = WebSocketManager()