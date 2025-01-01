import sqlite3

def clear_tables():
   conn = sqlite3.connect('reddit_analysis.db')
   cursor = conn.cursor()
   
   tables = ['users', 'reddit_mentions', 'brands']
   
   try:
       for table in tables:
           cursor.execute(f"DELETE FROM {table}")
       conn.commit()
       print("All data cleared successfully")
   except Exception as e:
       print(f"Error: {e}")
   finally:
       conn.close()

if __name__ == "__main__":
   clear_tables()