from sqlalchemy import create_engine, text
from models import Base
from database import engine

# Create database engine
# engine = create_engine('sqlite:///./sql_app.db')

def migrate_database():
    """
    Migrate the database schema
    """
    try:
        # Drop existing tables
        Base.metadata.drop_all(bind=engine)
        print("Dropped existing tables")
        
        # Create tables with new schema
        Base.metadata.create_all(bind=engine)
        print("Created new tables")
        
        # Add last_analyzed column to brands table
        with engine.begin() as conn:
            try:
                conn.execute(text("ALTER TABLE brands ADD COLUMN last_analyzed TIMESTAMP"))
                print("Added last_analyzed column to brands table")
            except Exception as e:
                print(f"Note: last_analyzed column might already exist: {e}")
        
        print("Database migration completed successfully!")
        
    except Exception as e:
        print(f"Error during migration: {e}")
        raise

if __name__ == "__main__":
    migrate_database()
