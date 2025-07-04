from sqlalchemy import create_engine, inspect
from database import DATABASE_URL

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
)
inspector = inspect(engine)

print("Users table columns:")
for column in inspector.get_columns('users'):
    print(f"- {column['name']}: {column['type']}")

print("\nBrands table columns:")
for column in inspector.get_columns('brands'):
    print(f"- {column['name']}: {column['type']}")

# print("User auth table columns:")
# for column in inspector.get_columns('reddit_tokens'):
#     print(f"- {column['name']}: {column['type']}")
