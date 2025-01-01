from sqlalchemy import create_engine, MetaData, Table
from database import DATABASE_URL

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
)

metadata = MetaData()
metadata.reflect(bind=engine)

users_table = metadata.tables['users']
print("\nUsers table columns:")
for column in users_table.columns:
    print(f"- {column.name}: {column.type}")
