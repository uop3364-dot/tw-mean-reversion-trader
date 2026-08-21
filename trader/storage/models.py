from sqlalchemy.orm import DeclarativeBase,Mapped,mapped_column
from sqlalchemy import String,Float,Integer,DateTime,Text,UniqueConstraint
from datetime import datetime
class Base(DeclarativeBase):pass
class Order(Base):
    __tablename__="orders";__table_args__=(UniqueConstraint("client_order_id"),)
    id:Mapped[int]=mapped_column(primary_key=True);client_order_id:Mapped[str]=mapped_column(String(64));symbol:Mapped[str]=mapped_column(String(16));side:Mapped[str]=mapped_column(String(8));status:Mapped[str]=mapped_column(String(20),default="NEW");created_at:Mapped[datetime]=mapped_column(DateTime,default=datetime.utcnow)
class Fill(Base):
    __tablename__="fills";id:Mapped[int]=mapped_column(primary_key=True);order_id:Mapped[int]=mapped_column(Integer);price:Mapped[float]=mapped_column(Float);quantity:Mapped[int]=mapped_column(Integer)
class PositionRecord(Base):
    __tablename__="positions";id:Mapped[int]=mapped_column(primary_key=True);symbol:Mapped[str]=mapped_column(String(16),unique=True);quantity:Mapped[int]=mapped_column(Integer);avg_price:Mapped[float]=mapped_column(Float)
class EventRecord(Base):
    __tablename__="events";id:Mapped[int]=mapped_column(primary_key=True);kind:Mapped[str]=mapped_column(String(30));payload:Mapped[str]=mapped_column(Text);created_at:Mapped[datetime]=mapped_column(DateTime,default=datetime.utcnow)

