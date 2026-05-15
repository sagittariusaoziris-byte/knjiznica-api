"""
app/rate_limiter.py – WebSocket rate limiter + Login brute-force zaštita
Verzija: 9.2.0

NOVO v9.2.0:
  - LoginRateLimiter: IP-based brute-force zaštita za /auth/token endpoint
    5 neuspjelih pokušaja → 15 minuta blokade po IP-u
    Uspješna prijava resetira brojač.

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


# ── Login brute-force zaštita ─────────────────────────────────────────────────

class LoginRateLimiter:
    """
    IP-based rate limiter za zaštitu login endpointa od brute-force napada.

    Pravila:
      - 5 uzastopnih neuspjelih pokušaja → blokada 15 minuta
      - Uspješna prijava resetira brojač za tu IP adresu
      - Pokušaji stariji od 15 minuta automatski se zaboravljaju
    """

    MAX_ATTEMPTS: int = 5
    BLOCK_SECONDS: int = 15 * 60  # 15 minuta

    def __init__(self):
        self._attempts: Dict[str, list] = defaultdict(list)  # ip → [timestamp, ...]
        self._blocked: Dict[str, float] = {}                 # ip → unblock_timestamp

    def _clean_attempts(self, ip: str) -> None:
        """Ukloni pokušaje starije od BLOCK_SECONDS."""
        cutoff = time.time() - self.BLOCK_SECONDS
        self._attempts[ip] = [t for t in self._attempts[ip] if t > cutoff]

    def is_blocked(self, ip: str) -> Tuple[bool, int]:
        """
        Provjeri je li IP adresa blokirana.

        Returns:
            (blocked: bool, seconds_remaining: int)
        """
        now = time.time()
        if ip in self._blocked:
            unblock_at = self._blocked[ip]
            if now < unblock_at:
                return True, int(unblock_at - now)
            # Blokada istekla – počisti
            del self._blocked[ip]
            self._attempts.pop(ip, None)
        return False, 0

    def record_failure(self, ip: str) -> Tuple[bool, int]:
        """
        Zabilježi neuspjeli pokušaj prijave.

        Returns:
            (just_blocked: bool, seconds_blocked: int)
              – just_blocked=True kad ovaj pokušaj aktivira blokadu
        """
        self._clean_attempts(ip)
        self._attempts[ip].append(time.time())

        if len(self._attempts[ip]) >= self.MAX_ATTEMPTS:
            unblock_at = time.time() + self.BLOCK_SECONDS
            self._blocked[ip] = unblock_at
            self._attempts.pop(ip, None)
            print(
                f"LOGIN BLOCKED {ip}: {self.MAX_ATTEMPTS} neuspjelih pokušaja, "
                f"blokada {self.BLOCK_SECONDS // 60} min"
            )
            return True, self.BLOCK_SECONDS

        remaining = self.MAX_ATTEMPTS - len(self._attempts[ip])
        print(f"LOGIN FAIL {ip}: preostalo pokušaja {remaining}/{self.MAX_ATTEMPTS}")
        return False, 0

    def record_success(self, ip: str) -> None:
        """Uspješna prijava – resetiraj brojač za ovu IP adresu."""
        self._attempts.pop(ip, None)
        self._blocked.pop(ip, None)

    def get_stats(self) -> dict:
        """Vrati statistike za monitoring."""
        return {
            "blocked_ips": len(self._blocked),
            "ips_with_attempts": len(self._attempts),
            "max_attempts": self.MAX_ATTEMPTS,
            "block_minutes": self.BLOCK_SECONDS // 60,
        }


login_rate_limiter = LoginRateLimiter()
