
import streamlit as st
import pandas as pd
import sqlite3

def show_data():
    conn = sqlite3.connect('reddit_analysis_backup.db')
    
    st.title("Database Data")

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