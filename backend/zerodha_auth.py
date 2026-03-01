from kiteconnect import KiteConnect
import config
import json
import os

TOKEN_FILE = "access_token.json"


class ZerodhaAuth:
    def __init__(self):
        self.kite = KiteConnect(api_key=config.API_KEY)
        self.access_token = None
        self._load_token()

    def _load_token(self):
        """Load saved access token if exists"""
        if os.path.exists(TOKEN_FILE):
            try:
                with open(TOKEN_FILE, "r") as f:
                    data = json.load(f)
                    self.access_token = data.get("access_token")
                    self.kite.set_access_token(self.access_token)
                    # Verify token is still valid
                    self.kite.profile()
                    print("✅ Loaded saved access token")
            except Exception as e:
                print(f"⚠️ Saved token invalid: {e}")
                self.access_token = None

    def get_login_url(self):
        """Generate Zerodha login URL"""
        return self.kite.login_url()

    def generate_session(self, request_token: str):
        """Generate session from request token after login"""
        try:
            data = self.kite.generate_session(
                request_token, api_secret=config.API_SECRET
            )
            self.access_token = data["access_token"]
            self.kite.set_access_token(self.access_token)

            # Save token
            with open(TOKEN_FILE, "w") as f:
                json.dump({"access_token": self.access_token}, f)

            print("✅ Session generated successfully")
            return True
        except Exception as e:
            print(f"❌ Session generation failed: {e}")
            return False

    def is_authenticated(self):
        """Check if authenticated"""
        if not self.access_token:
            return False
        try:
            self.kite.profile()
            return True
        except:
            return False

    def get_kite(self) -> KiteConnect:
        """Get authenticated Kite instance"""
        return self.kite


# Singleton instance
auth = ZerodhaAuth()