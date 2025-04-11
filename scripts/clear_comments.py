from database import SessionLocal
from models import RedditComment

def clear_reddit_comments():
    db = SessionLocal()
    try:
        # Delete all records from reddit_comments table
        num_deleted = db.query(RedditComment).delete()
        db.commit()
        print(f"Successfully deleted {num_deleted} records from reddit_comments table")
    except Exception as e:
        db.rollback()
        print(f"Error deleting records: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    clear_reddit_comments()
