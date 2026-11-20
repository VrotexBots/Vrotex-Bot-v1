# VROTEX BOT V1 - SCALPING EDITION
# SMC • ICT • LIQUIDITY • PRECISION
# Python Only - No Flask

import time
import datetime

class VrotexBot:
    def __init__(self, balance=10000.00):
        self.balance = balance
        self.start_balance = balance
        self.equity = balance
        self.running = False
        self.open_trades = 0
        self.today_pnl = 0.0
        self.risk_per_trade = 0.01  # 1.00%
        self.daily_loss_limit = 0.02  # 2.00%
        self.max_consecutive_loss = 2
        self.consecutive_losses = 0
        self.mode = "A+ ONLY"
        self.journal = []

    def start(self):
        self.running = True
        print("=" * 40)
        print("🟢 VROTEX BOT V1 STARTED")
        print("Mode:", self.mode)
        print("Balance: $", self.balance)
        print("Risk Per Trade: 1.00%")
        print("=" * 40)
        return self.get_status()

    def stop(self):
        self.running = False
        print("=" * 40)
        print("🔴 VROTEX BOT STOPPED")
        print("Final Balance: $", self.balance)
        print("Today P/L: $", self.today_pnl)
        print("=" * 40)
        return self.get_status()

    def get_session(self):
        now = datetime.datetime.now().hour
        # Hours in SAST - simplified
        if 0 <= now < 8:
            return "ASIA"
        elif 8 <= now < 13:
            return "LONDON"
        elif 13 <= now < 21:
            return "NEW YORK"
        else:
            return "CLOSED"

    def analyze_1h_bias(self, price, prev_high, prev_low):
        # 1H - Market Bias - HH-HL = Bullish, LL-LH = Bearish
        if price > prev_high:
            return "BULLISH", "HH - HL"
        elif price < prev_low:
            return "BEARISH", "LL - LH"
        else:
            return "RANGING", "CHOP"

    def analyze_5m_setup(self, price, liquidity_low, liquidity_high):
        # 5M - Liquidity Sweep Detection
        if price < liquidity_low:
            return "SWEEP DETECTED", "Liquidity Sweep Below Low"
        elif price > liquidity_high:
            return "SWEEP DETECTED", "Liquidity Sweep Above High"
        else:
            return "PENDING", "Waiting For Sweep"

    def analyze_1m_entry(self, bias, setup):
        # 1M - Entry - Only A+ setups
        if bias == "BULLISH" and setup == "SWEEP DETECTED":
            return "READY", "BUY - A+ Setup"
        elif bias == "BEARISH" and setup == "SWEEP DETECTED":
            return "READY", "SELL - A+ Setup"
        else:
            return "WAIT", "Awaiting Confirmation"

    def check_quality(self, bias, setup, entry):
        # A+ Filter - Only trade A+ setups
        if entry == "READY":
            return "A+"
        elif setup == "SWEEP DETECTED":
            return "A"
        else:
            return "B - SKIP"

    def calculate_lot(self, price, stop_loss_pips):
        # Risk Management - 1% risk
        risk_amount = self.balance * self.risk_per_trade
        # Simplified lot calc for EURUSD
        lot = risk_amount / (stop_loss_pips * 10)
        lot = round(lot, 2)
        if lot < 0.01:
            lot = 0.01
        if lot > 1.0:
            lot = 1.0
        return lot

    def check_risk(self):
        # Daily Loss Limit Check
        daily_loss = self.start_balance - self.balance
        daily_loss_pct = daily_loss / self.start_balance
        if daily_loss_pct >= self.daily_loss_limit:
            print("
