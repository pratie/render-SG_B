from sqlalchemy import create_engine, inspect

# Replace with your database URL
engine = create_engine('sqlite:///reddit_analysis.db')  # Modify for your DB type

inspector = inspect(engine)
tables = inspector.get_table_names()

print("Tables in database:")
for table in tables:
    print(f"- {table}")