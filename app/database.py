from sqlmodel import Session, SQLModel, create_engine
from .config import DATABASE_URL

# SQLModel database engine
engine = create_engine(DATABASE_URL)

def create_db_and_tables():
    SQLModel.metadata.create_all(engine)

def get_session():
    with Session(engine) as session:
        yield session