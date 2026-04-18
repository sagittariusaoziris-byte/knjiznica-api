"""
app/rate_limiter.py – WebSocket rate limiter
Verzija: 8.2 (ispravci)

ISPRAVCI v8.2:
  1. Produkcijski limiti: 10 msg / 10s je prestrogo za normalan rad
     (dashboard refresh, pretraga, notifikacije lako triggeritraju više poruka).
     Povećano na 30 msg / 30s za opći rate_limiter.
  2. Test bypass (`client_id.startswith("test_")`) uklonjen iz produkcijskog koda.
  3. CRLF → LF line endings.
"""

import time
from collections import defaultdict
from typing import Dict, Tuple


class RateLimiter:
    """Rate limiter s sliding window algoritmom."""

    def __init__(self, max_messages: int = 30, window_seconds: int = 30):
        """
        Args:
            max_messages:   Maksimalan broj poruka u prozoru
            window_seconds: Veličina prozora u sekundama
        """
        self.max_messages = max_messages
        self.window_seconds = window_seconds
        self.clients: Dict[str, list] = defaultdict(list)

    def is_allowed(self, client_id: str) -> Tuple[bool, int]:
        """
        Provjeri smije li klijent poslati poruku.

        Returns:
            (allowed: bool, retry_after_seconds: int)
        """
        now = time.time()
        window_start = now - self.window_seconds

        # Ukloni poruke izvan prozora
        self.clients[client_id] = [
            t for t in self.clients[client_id] if t > window_start
        ]

        if len(self.clients[client_id]) >= self.max_messages:
            oldest = min(self.clients[client_id])
            retry_after = int(oldest + self.window_seconds - now) + 1
            print(
                f"RATE LIMIT {client_id}: "
                f"{len(self.clients[client_id])}/{self.max_messages}, "
                f"retry za {retry_after}s"
            )
            return False, retry_after

        self.clients[client_id].append(now)
        return True, 0

    def get_remaining(self, client_id: str) -> int:
        """Broj preostalih poruka u trenutnom prozoru."""
        now = time.time()
        window_start = now - self.window_seconds
        self.clients[client_id] = [
            t for t in self.clients[client_id] if t > window_start
        ]
        return max(0, self.max_messages - len(self.clients[client_id]))

    def reset(self, client_id: str):
        """Resetiraj brojač za klijenta."""
        self.clients.pop(client_id, None)

    def get_stats(self) -> dict:
        """Vrati statistike rate limitera."""
        now = time.time()
        window_start = now - self.window_seconds

        active_clients = 0
        total_messages = 0

        for timestamps in self.clients.values():
            valid = [t for t in timestamps if t > window_start]
            if valid:
                active_clients += 1
                total_messages += len(valid)

        return {
            "active_clients": active_clients,
            "total_messages_in_window": total_messages,
            "max_messages_per_client": self.max_messages,
            "window_seconds": self.window_seconds,
        }


# ── Globalne instance ─────────────────────────────────────────────────────────
rate_limiter = RateLimiter(max_messages=30, window_seconds=30)
chat_rate_limiter = RateLimiter(max_messages=30, window_seconds=60)
sync_rate_limiter = RateLimiter(max_messages=50, window_seconds=60)
