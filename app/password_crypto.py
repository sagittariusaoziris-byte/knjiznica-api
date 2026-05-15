"""
app/password_crypto.py
VERZIJA: 9.2.0 — Simetrična enkripcija plain_password kolone

Koristi Fernet (AES-128-CBC + HMAC-SHA256) iz cryptography paketa.
Ključ se izvodi iz KNJIZNICA_SECRET_KEY env varijable kako ne bi
trebao poseban env var — ako je SECRET_KEY promijenjen, lozinke
treba re-enkriptirati (vidi migrate_encrypt_passwords.py).

VIDLJIVOST:
  - Super admin (role=admin, library_id=None) → vidi sve dešifrirane lozinke
  - Library admin (role=admin, library_id=X)  → vidi samo lozinke svoje knjižnice
  - Ostali                                    → None
"""
import base64
import hashlib
import logging
import os

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)

_DEFAULT_SECRET = "knjiznica-super-tajni-kljuc-2024-promijeniti-u-produkciji"
_SECRET_KEY = os.environ.get("KNJIZNICA_SECRET_KEY", _DEFAULT_SECRET)


def _get_fernet() -> Fernet:
    """
    Izvodi Fernet ključ iz SECRET_KEY pomoću SHA-256.
    SHA-256 daje 32 bajta → base64url enkodiranje daje valjani Fernet ključ.
    """
    key_bytes = hashlib.sha256(_SECRET_KEY.encode("utf-8")).digest()
    fernet_key = base64.urlsafe_b64encode(key_bytes)
    return Fernet(fernet_key)


def encrypt_password(plain: str | None) -> str | None:
    """
    Enkriptira lozinku za pohranu u bazu.
    Vraća None ako je ulaz None ili prazan string.
    """
    if not plain:
        return plain
    try:
        return _get_fernet().encrypt(plain.encode("utf-8")).decode("utf-8")
    except Exception as exc:
        logger.error("Greška pri enkripciji lozinke: %s", exc)
        return None


def decrypt_password(encrypted: str | None) -> str | None:
    """
    Dekriptira lozinku iz baze.
    Ako dekriptiranje ne uspije (npr. stari plain-text unos), vraća original
    kako bi migracija mogla raditi inkrementalno.
    """
    if not encrypted:
        return encrypted
    try:
        return _get_fernet().decrypt(encrypted.encode("utf-8")).decode("utf-8")
    except (InvalidToken, Exception):
        # Vjerojatno još nije enkriptiran (stari unos) — vrati kako jest
        logger.debug("decrypt_password: token nije Fernet, vraćam original")
        return encrypted


def is_encrypted(value: str | None) -> bool:
    """Provjeri je li vrijednost već Fernet enkriptirana."""
    if not value:
        return False
    try:
        _get_fernet().decrypt(value.encode("utf-8"))
        return True
    except (InvalidToken, Exception):
        return False
