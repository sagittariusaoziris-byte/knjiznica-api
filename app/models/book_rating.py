"""
app/models/book_rating.py
VERZIJA: 9.1.0

Model premješten iz app/routes/ratings.py u ispravno mjesto — models/.
SQLAlchemy modeli ne smiju biti definirani u routes datotekama.
"""
from sqlalchemy import Column, DateTime, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.sql import func

from app.database import Base


class BookRating(Base):
    __tablename__ = "book_ratings"
    __table_args__ = (UniqueConstraint("book_id", "user_id", name="uq_book_user_rating"),)

    id         = Column(Integer, primary_key=True, index=True)
    book_id    = Column(Integer, ForeignKey("books.id",    ondelete="CASCADE"), nullable=False)
    user_id    = Column(Integer, ForeignKey("users.id",    ondelete="CASCADE"), nullable=False)
    library_id = Column(Integer, ForeignKey("libraries.id"), nullable=True, index=True)
    rating     = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
