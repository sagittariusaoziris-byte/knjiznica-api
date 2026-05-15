#!/usr/bin/env python3
"""
migrate_encrypt_passwords.py
VERZIJA: 9.2.0

Skript za jednokratnu migraciju: enkriptira sve plain_password vrijednosti
koje su još uvijek u čistom tekstu (plain-text) u bazi podataka.

POKRETANJE:
    cd api/
    python migrate_encrypt_passwords.py

Skript je siguran za višestruko pokretanje — preskače već enkriptirane vrijednosti.
"""
import os
import sys

# Dodaj api/ direktorij u Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

from app.database import SessionLocal
from app.models.user import User
from app.password_crypto import encrypt_password, is_encrypted


def migrate():
    db = SessionLocal()
    try:
        users = db.query(User).all()
        total = len(users)
        already_encrypted = 0
        migrated = 0
        skipped_empty = 0

        print(f"Pronađeno {total} korisnika u bazi.\n")

        for user in users:
            if not user.plain_password:
                skipped_empty += 1
                continue

            if is_encrypted(user.plain_password):
                already_encrypted += 1
                continue

            # Plain text — enkriptiraj
            old_value = user.plain_password
            user.plain_password = encrypt_password(old_value)
            migrated += 1
            print(f"  Enkriptiran: korisnik '{user.username}' (id={user.id})")

        if migrated > 0:
            db.commit()
            print(f"\n✅ Migracija završena:")
        else:
            print(f"\n✅ Migracija završena (bez promjena):")

        print(f"   Enkriptirano:       {migrated}")
        print(f"   Već enkriptirano:   {already_encrypted}")
        print(f"   Bez lozinke:        {skipped_empty}")
        print(f"   Ukupno korisnika:   {total}")

    except Exception as exc:
        db.rollback()
        print(f"\n❌ Greška pri migraciji: {exc}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    migrate()
