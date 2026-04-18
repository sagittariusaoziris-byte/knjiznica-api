"""
app/models/license_record.py  —  v8.6.0

PROMJENE v8.6.0:
  - Dodano: hostname, os_platform, os_version, app_version (info o računalu)
  - Dodano: activated_at (datum prve aktivacije)
  - Dodano: last_seen (datum zadnje provjere)
  - Dodano: activation_count (broj aktivacijskih pokušaja)
  - Dodano: notes (admin bilješka)
  - Zadržano: UniqueConstraint na license_key
"""

from datetime import datetime

from app.database import Base
from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text, UniqueConstraint


class LicenseRecord(Base):
    __tablename__ = "licenses"

    __table_args__ = (UniqueConstraint("license_key", name="uq_licenses_license_key"),)

    id          = Column(Integer, primary_key=True, index=True)
    email       = Column(String(255), nullable=False, index=True)
    license_key = Column(Text, nullable=False)

    issued      = Column(DateTime, default=datetime.utcnow, nullable=False)
    expiry      = Column(DateTime, nullable=False)
    activated_at = Column(DateTime, nullable=True)   # NEW v8.6.0
    last_seen   = Column(DateTime, nullable=True)    # NEW v8.6.0

    machine_id  = Column(String(128), nullable=True)
    # NEW v8.6.0 — info o računalu koje je aktiviralo licencu
    hostname    = Column(String(255), nullable=True)
    os_platform = Column(String(64),  nullable=True)
    os_version  = Column(String(128), nullable=True)
    app_version = Column(String(32),  nullable=True)

    activation_count = Column(Integer, default=0, nullable=False)  # NEW v8.6.0
    notes       = Column(Text, nullable=True)   # NEW v8.6.0 — admin bilješka

    created_by  = Column(String(64), nullable=True)
    is_active   = Column(Boolean, default=True, nullable=False)

    def to_dict(self) -> dict:
        now = datetime.utcnow()
        expired = self.expiry < now if self.expiry else True
        days_remaining = max((self.expiry - now).days, 0) if self.expiry and not expired else 0

        if not self.is_active:
            status = "revoked"
        elif expired:
            status = "expired"
        else:
            status = "active"

        return {
            "id":               self.id,
            "email":            self.email,
            "license_key":      self.license_key,
            "issued":           self.issued.strftime("%Y-%m-%d")       if self.issued       else None,
            "expiry":           self.expiry.strftime("%Y-%m-%d")       if self.expiry       else None,
            "activated_at":     self.activated_at.strftime("%Y-%m-%d %H:%M") if self.activated_at else None,
            "last_seen":        self.last_seen.strftime("%Y-%m-%d %H:%M")    if self.last_seen    else None,
            "days_remaining":   days_remaining,
            "machine_id":       self.machine_id,
            "hostname":         self.hostname,
            "os_platform":      self.os_platform,
            "os_version":       self.os_version,
            "app_version":      self.app_version,
            "activation_count": self.activation_count or 0,
            "notes":            self.notes,
            "created_by":       self.created_by,
            "is_active":        self.is_active,
            "status":           status,
        }
