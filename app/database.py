from sqlmodel import create_engine
from .config import DATABASE_URL

# SQLAlchemy database engine
engine = create_engine(DATABASE_URL)