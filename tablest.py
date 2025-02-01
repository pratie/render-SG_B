import streamlit as st
import pandas as pd
import sqlite3
from datetime import datetime

def add_user(email, has_paid=False):
    conn = sqlite3.connect('reddit_analysis_backup1.db')
    cursor = conn.cursor()
    try:
        # Check if user already exists
        cursor.execute("SELECT * FROM users WHERE email = ?", (email,))
        if cursor.fetchone():
            return False, "User already exists"
        
        # Add new user
        created_at = datetime.now().isoformat()
        cursor.execute(
            "INSERT INTO users (email, has_paid, created_at) VALUES (?, ?, ?)",
            (email, has_paid, created_at)
        )
        conn.commit()
        return True, "User added successfully"
    except Exception as e:
        return False, f"Error adding user: {str(e)}"
    finally:
        conn.close()

def update_user_paid_status(email, has_paid):
    conn = sqlite3.connect('reddit_analysis_backup1.db')
    cursor = conn.cursor()
    try:
        # Update user's paid status
        cursor.execute(
            "UPDATE users SET has_paid = ? WHERE email = ?",
            (has_paid, email)
        )
        if cursor.rowcount == 0:
            return False, "User not found"
        conn.commit()
        return True, "User paid status updated successfully"
    except Exception as e:
        return False, f"Error updating user: {str(e)}"
    finally:
        conn.close()

def show_data():
    conn = sqlite3.connect('reddit_analysis_backup1.db')
    
    st.title("Database Management Dashboard")

    # Add User Section
    st.header("Add New User")
    col1, col2 = st.columns([3, 1])
    with col1:
        email = st.text_input("User Email")
    with col2:
        has_paid = st.checkbox("Has Paid")
    
    if st.button("Add User"):
        if not email:
            st.error("Email is required")
        else:
            success, message = add_user(email, has_paid)
            if success:
                st.success(message)
            else:
                st.error(message)

    # Update User Paid Status Section
    st.header("Update User Paid Status")
    update_col1, update_col2 = st.columns([3, 1])
    with update_col1:
        update_email = st.text_input("User Email to Update")
    with update_col2:
        update_has_paid = st.checkbox("Mark as Paid", key="update_paid")
    
    if st.button("Update Paid Status"):
        if not update_email:
            st.error("Email is required")
        else:
            success, message = update_user_paid_status(update_email, update_has_paid)
            if success:
                st.success(message)
            else:
                st.error(message)
    
    # Display Data Section
    try:
        # Users table
        users_df = pd.read_sql_query("SELECT * FROM users", conn)
        st.header("Users")
        st.dataframe(users_df)
        col1, col2 = st.columns(2)
        with col1:
            st.metric("Total Users", len(users_df))
        with col2:    
            st.metric("Paid Users", len(users_df[users_df['has_paid'] == True]))
        
        # Reddit mentions table
        mentions_df = pd.read_sql_query("SELECT * FROM reddit_mentions", conn)
        st.header("Reddit Mentions") 
        st.dataframe(mentions_df)
        
        # Brands table
        brands_df = pd.read_sql_query("SELECT * FROM brands", conn)
        st.header("Brands")
        st.dataframe(brands_df)
            
    except Exception as e:
        st.error(f"Error reading data: {str(e)}")
    
    conn.close()

if __name__ == '__main__':
    show_data()