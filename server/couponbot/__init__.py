"""Auto-redeem bot for the official KGC coupon site (kgc-coupon.awesomepiece.com).

Independent of the game-emulator server (`server.py`): it talks to the official
site, keeps its own SQLite store and runs either as a systemd worker cycle or
behind the small dashboard in `couponbot.web`.
"""

__all__ = ["state", "codes", "coupon_client"]
