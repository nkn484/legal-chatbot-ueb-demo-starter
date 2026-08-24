"""SQLAlchemy declarative base; domain tables are intentionally not defined here."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class for future migration-managed database models."""
