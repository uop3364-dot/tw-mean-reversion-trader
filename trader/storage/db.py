from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from .models import Base
def database(url="sqlite:///trader.db"):
    engine=create_engine(url);Base.metadata.create_all(engine);return sessionmaker(engine,expire_on_commit=False)

