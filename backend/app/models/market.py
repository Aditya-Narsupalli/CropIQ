"""
SQLAlchemy model for daily crop commodity prices.

Every time the app fetches "today's" live prices from Agmarknet, one row is
saved per (crop, location, price_date). Rows older than
`settings.PRICE_HISTORY_RETENTION_DAYS` (default 30) are periodically purged,
so this table always holds a rolling ~30-day window that both the
`/market/trends/{crop}` endpoint and the frontend's "last 30 days" chart read
from.
"""
from datetime import datetime

from sqlalchemy import Column, Date, DateTime, Float, Integer, String, UniqueConstraint, Index

from app.core.db import Base


class MarketPriceHistory(Base):
    __tablename__ = "market_price_history"

    id = Column(Integer, primary_key=True, autoincrement=True)

    crop = Column(String(255), nullable=False)
    commodity_group = Column(String(255), nullable=True)
    location = Column(String(255), nullable=False, default="All India (Agmarknet)")

    price_per_quintal = Column(Float, nullable=True)
    msp_price = Column(Float, nullable=True)
    arrival_metric_tonnes = Column(Float, nullable=True)
    price_change_pct = Column(Float, nullable=True)
    trend = Column(String(50), nullable=True)
    source = Column(String(100), nullable=True, default="Agmarknet (Live)")

    # The calendar date the price is quoted for (used for the 30-day window
    # and for charting). Distinct from `recorded_at`, which is when our
    # scraper actually wrote the row.
    price_date = Column(Date, nullable=False)
    recorded_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        # One row per crop/location/day - re-fetching "today's" price just
        # updates the existing row instead of creating duplicates.
        UniqueConstraint("crop", "location", "price_date", name="uq_market_price_crop_location_date"),
        Index("ix_market_price_crop", "crop"),
        Index("ix_market_price_price_date", "price_date"),
    )

    def to_history_point(self) -> dict:
        """Shape consumed by the frontend's 30-day trend chart."""
        return {
            "date": self.price_date.isoformat(),
            "price": self.price_per_quintal,
        }
