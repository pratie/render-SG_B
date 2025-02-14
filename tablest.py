import streamlit as st
import pandas as pd
import sqlite3
from datetime import datetime
import re

# Initialize connection string
DB_PATH = 'reddit_analysis_feb141.db'

def validate_email(email):
    """Validate email format using regex pattern."""
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None

def get_db_connection():
    """Create database connection with context manager."""
    return sqlite3.connect(DB_PATH)

def add_user(email, has_paid=False, stripe_payment_id=None):
    """Add a new user to the database with improved validation."""
    if not validate_email(email):
        return False, "Invalid email format"
        
    with get_db_connection() as conn:
        cursor = conn.cursor()
        try:
            # Check if user exists
            cursor.execute("SELECT * FROM users WHERE email = ?", (email,))
            if cursor.fetchone():
                return False, "User already exists"
            
            # Add new user
            created_at = datetime.now()
            cursor.execute("""
                INSERT INTO users (
                    email, created_at, last_login, has_paid, 
                    payment_date, stripe_payment_id
                ) VALUES (?, ?, ?, ?, ?, ?)
            """, (email, created_at, created_at if has_paid else None, 
                  has_paid, created_at if has_paid else None, stripe_payment_id))
            return True, "User added successfully"
        except sqlite3.Error as e:
            return False, f"Database error: {str(e)}"

def update_user_paid_status(email, has_paid, stripe_payment_id=None):
    """Update user's paid status with improved error handling."""
    if not validate_email(email):
        return False, "Invalid email format"
        
    with get_db_connection() as conn:
        cursor = conn.cursor()
        try:
            current_time = datetime.now()
            cursor.execute("""
                UPDATE users 
                SET has_paid = ?, 
                    payment_date = ?,
                    stripe_payment_id = ?
                WHERE email = ?
            """, (has_paid, current_time if has_paid else None, 
                  stripe_payment_id, email))
            
            if cursor.rowcount == 0:
                return False, "User not found"
            return True, "User paid status updated successfully"
        except sqlite3.Error as e:
            return False, f"Database error: {str(e)}"

def load_table_data(table_name, search_term=None):
    """Safely load data from specified table with optional search."""
    try:
        with get_db_connection() as conn:
            query = f"SELECT * FROM {table_name}"
            
            if search_term and table_name == "users":
                query += f" WHERE email LIKE '%{search_term}%'"
            elif search_term and table_name == "brands":
                query += f" WHERE name LIKE '%{search_term}%' OR description LIKE '%{search_term}%'"
            
            df = pd.read_sql_query(query, conn)
            
            # Convert datetime columns with ISO format
            datetime_columns = ['created_at', 'last_login', 'payment_date', 'updated_at']
            for col in datetime_columns:
                if col in df.columns:
                    df[col] = pd.to_datetime(df[col], format='ISO8601', errors='coerce')
            
            return df
    except sqlite3.Error as e:
        st.error(f"Error loading {table_name}: {str(e)}")
        return pd.DataFrame()

def show_data():
    st.set_page_config(page_title="Reddit Analysis Dashboard", layout="wide")
    
    st.markdown("""
        <style>
        .stButton>button {
            width: 100%;
        }
        .user-management {
            background-color: #f0f2f6;
            padding: 20px;
            border-radius: 10px;
            margin-bottom: 20px;
        }
        .stDataFrame {
            padding: 10px;
        }
        </style>
    """, unsafe_allow_html=True)

    st.title("Reddit Analysis Dashboard")

    # User Management Section
    with st.container():
        st.markdown("<div class='user-management'>", unsafe_allow_html=True)
        
        # Add User Section
        st.subheader("Add New User")
        col1, col2, col3 = st.columns([3, 1, 2])
        with col1:
            email = st.text_input("New User Email", key="new_email")
        with col2:
            has_paid = st.checkbox("Has Paid", key="new_paid")
        with col3:
            stripe_id = st.text_input("Stripe Payment ID", key="new_stripe_id")
        
        if st.button("Add User", use_container_width=True):
            if not email:
                st.error("Email is required")
            else:
                success, message = add_user(email, has_paid, stripe_id if stripe_id else None)
                if success:
                    st.success(message)
                else:
                    st.error(message)

        # Update User Section
        st.subheader("Update User Payment Status")
        col1, col2, col3 = st.columns([3, 1, 2])
        with col1:
            update_email = st.text_input("Update User Email", key="update_email")
        with col2:
            update_has_paid = st.checkbox("Mark as Paid", key="update_paid")
        with col3:
            update_stripe_id = st.text_input("Update Stripe ID", key="update_stripe_id")
        
        if st.button("Update Status", use_container_width=True):
            if not update_email:
                st.error("Email is required")
            else:
                success, message = update_user_paid_status(
                    update_email, update_has_paid, 
                    update_stripe_id if update_stripe_id else None
                )
                if success:
                    st.success(message)
                else:
                    st.error(message)
        
        st.markdown("</div>", unsafe_allow_html=True)

    # Data Display Sections
    tab1, tab2, tab3 = st.tabs(["Users", "Reddit Mentions", "Brands"])
    
    with tab1:
        st.subheader("Users")
        search_term = st.text_input("Search Users (by email)", key="user_search")
        users_df = load_table_data("users", search_term)
        
        if not users_df.empty:
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Total Users", len(users_df))
            with col2:    
                st.metric("Paid Users", len(users_df[users_df['has_paid'] == True]))
            with col3:
                st.metric("Free Users", len(users_df[users_df['has_paid'] == False]))
            
            st.dataframe(users_df, use_container_width=True)

    with tab2:
        st.subheader("Reddit Mentions")
        mentions_df = load_table_data("reddit_mentions")
        if not mentions_df.empty:
            # Add some analytics for mentions
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Total Mentions", len(mentions_df))
            with col2:
                avg_score = mentions_df['score'].mean()
                st.metric("Average Score", f"{avg_score:.1f}")
            with col3:
                avg_comments = mentions_df['num_comments'].mean()
                st.metric("Avg Comments", f"{avg_comments:.1f}")
            
            st.dataframe(mentions_df, use_container_width=True)

    with tab3:
        st.subheader("Brands")
        search_term = st.text_input("Search Brands", key="brand_search")
        brands_df = load_table_data("brands", search_term)
        if not brands_df.empty:
            st.metric("Total Brands", len(brands_df))
            st.dataframe(brands_df, use_container_width=True)

if __name__ == '__main__':
    show_data()