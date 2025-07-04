import re
import sqlite3
import streamlit as st
import pandas as pd
from datetime import datetime
import plotly.express as px
import plotly.graph_objects as go

# Initialize connection string and page config
DB_PATH = 'reddit_analysis_jun9.db'
st.set_page_config(layout="wide", page_title="Brand Mentions Analytics")

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
                INSERT INTO users (email, created_at, last_login, has_paid, stripe_payment_id)
                VALUES (?, ?, ?, ?, ?)
            """, (email, created_at, created_at, has_paid, stripe_payment_id))
            conn.commit()
            return True, "User added successfully"
        except Exception as e:
            return False, f"Error: {str(e)}"

def update_user_payment(email, has_paid, stripe_payment_id=None):
    """Update user payment status in the database."""
    if not validate_email(email):
        return False, "Invalid email format"
        
    with get_db_connection() as conn:
        cursor = conn.cursor()
        try:
            # Check if user exists
            cursor.execute("SELECT * FROM users WHERE email = ?", (email,))
            if not cursor.fetchone():
                return False, "User does not exist"
            
            # Update user payment status
            cursor.execute("""
                UPDATE users 
                SET has_paid = ?, 
                    stripe_payment_id = ?,
                    payment_date = CASE WHEN ? = 1 THEN CURRENT_TIMESTAMP ELSE NULL END
                WHERE email = ?
            """, (has_paid, stripe_payment_id, has_paid, email))
            conn.commit()
            return True, "Payment status updated successfully"
        except Exception as e:
            return False, f"Error: {str(e)}"

def get_mentions_by_email(email):
    """Get all Reddit mentions for a user's brands by email."""
    with get_db_connection() as conn:
        query = """
            SELECT 
                m.id, m.title, m.subreddit, m.score, m.num_comments,
                m.relevance_score, m.created_at, m.url, 
                b.name as brand_name, m.intent, m.suggested_comment
            FROM reddit_mentions m
            JOIN brands b ON m.brand_id = b.id
            WHERE b.user_email = ?
            ORDER BY m.created_at DESC
        """
        df = pd.read_sql_query(query, conn, params=(email,))
        return df

def get_user_preferences(email):
    """Get user preferences from database."""
    with get_db_connection() as conn:
        df = pd.read_sql_query("""
            SELECT tone, response_style, created_at, updated_at 
            FROM user_preferences 
            WHERE user_email = ?
        """, conn, params=(email,))
        return df

def get_reddit_auth_status(email):
    """Get Reddit authentication status for user."""
    with get_db_connection() as conn:
        df = pd.read_sql_query("""
            SELECT reddit_username, created_at, updated_at, expires_at 
            FROM reddit_tokens 
            WHERE user_email = ?
        """, conn, params=(email,))
        return df

def get_alert_settings_data():
    """Get all alert settings data from the database."""
    with get_db_connection() as conn:
        df = pd.read_sql_query("SELECT * FROM alert_settings", conn)
        return df

def get_user_stats(email):
    """Get comprehensive user statistics"""
    with get_db_connection() as conn:
        # Get user info
        user_df = pd.read_sql("""
            SELECT email, created_at, last_login, has_paid
            FROM users WHERE email = ?
        """, conn, params=(email,))
        
        # Get brand stats
        brand_stats = pd.read_sql("""
            SELECT 
                b.id, b.name,
                COUNT(DISTINCT m.id) as mention_count,
                COUNT(DISTINCT c.id) as comment_count,
                b.created_at
            FROM brands b
            LEFT JOIN reddit_mentions m ON b.id = m.brand_id
            LEFT JOIN reddit_comments c ON b.id = c.brand_id
            WHERE b.user_email = ?
            GROUP BY b.id
        """, conn, params=(email,))
        
        return user_df, brand_stats

def get_brand_details(brand_id):
    """Get detailed brand analytics"""
    with get_db_connection() as conn:
        # Get mentions over time
        mentions_df = pd.read_sql("""
            SELECT 
                created_at,
                subreddit,
                score,
                num_comments,
                relevance_score
            FROM reddit_mentions
            WHERE brand_id = ?
            ORDER BY created_at
        """, conn, params=(brand_id,))
        
        # Get comments
        comments_df = pd.read_sql("""
            SELECT created_at, comment_text, post_url
            FROM reddit_comments
            WHERE brand_id = ?
            ORDER BY created_at DESC
        """, conn, params=(brand_id,))
        
        return mentions_df, comments_df

def show_admin_dashboard():
    st.title("Admin Dashboard")
    
    # Add new user form
    with st.expander("Add New User"):
        with st.form("add_user_form"):
            email = st.text_input("Email")
            has_paid = st.checkbox("Has Paid")
            stripe_id = st.text_input("Stripe Payment ID (optional)")
            submitted = st.form_submit_button("Add User")
            
            if submitted:
                success, message = add_user(email, has_paid, stripe_id)
                if success:
                    st.success(message)
                else:
                    st.error(message)

    # Update user payment form
    with st.expander("Update User Payment"):
        with st.form("update_payment_form"):
            update_email = st.text_input("User Email")
            update_has_paid = st.checkbox("Has Paid")
            update_stripe_id = st.text_input("Stripe Payment ID (optional)")
            update_submitted = st.form_submit_button("Update Payment Status")
            
            if update_submitted:
                success, message = update_user_payment(update_email, update_has_paid, update_stripe_id)
                if success:
                    st.success(message)
                else:
                    st.error(message)

    # Main content tabs
    tabs = st.tabs(["Users", "Reddit Mentions", "Brands", "Reddit Comments", "User Preferences", "Reddit Auth Status", "Alert Settings", "Mentions by Email"])
    
    with tabs[0]:
        st.subheader("Users")
        search_term = st.text_input("Search Users (by email)", key="user_search")
        
        # Restore search functionality
        with get_db_connection() as conn:
            if search_term:
                query = "SELECT * FROM users WHERE email LIKE ?"
                users_df = pd.read_sql_query(query, conn, params=(f"%{search_term}%",))
            else:
                users_df = pd.read_sql_query("SELECT * FROM users", conn)
        
        if not users_df.empty:
            # Convert datetime columns with ISO format
            datetime_cols = ['created_at', 'last_login', 'payment_date']
            for col in datetime_cols:
                if col in users_df.columns:
                    users_df[col] = pd.to_datetime(users_df[col], format='ISO8601', errors='coerce')
            
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Total Users", len(users_df))
            with col2:
                st.metric("Paid Users", len(users_df[users_df['has_paid'] == True]))
            with col3:
                st.metric("Free Users", len(users_df[users_df['has_paid'] == False]))
            
            st.dataframe(users_df, use_container_width=True)
        else:
            st.info("No users found")

    with tabs[1]:
        st.subheader("Reddit Mentions")
        mentions_df = pd.read_sql_query("SELECT * FROM reddit_mentions", get_db_connection())
        if not mentions_df.empty:
            # Convert datetime columns
            datetime_cols = ['created_at']
            for col in datetime_cols:
                if col in mentions_df.columns:
                    mentions_df[col] = pd.to_datetime(mentions_df[col], format='ISO8601', errors='coerce')

            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Total Mentions", len(mentions_df))
            with col2:
                st.metric("Average Score", round(mentions_df['score'].mean(), 2))
            with col3:
                st.metric("Total Comments", mentions_df['num_comments'].sum())
            st.dataframe(mentions_df, use_container_width=True)

    with tabs[2]:
        st.subheader("Brands")
        brands_df = pd.read_sql_query("SELECT * FROM brands", get_db_connection())
        if not brands_df.empty:
            # Convert datetime columns
            datetime_cols = ['created_at', 'updated_at']
            for col in datetime_cols:
                if col in brands_df.columns:
                    brands_df[col] = pd.to_datetime(brands_df[col], format='ISO8601', errors='coerce')

            st.metric("Total Brands", len(brands_df))
            st.dataframe(brands_df, use_container_width=True)

    with tabs[3]:
        st.subheader("Reddit Comments")
        comments_df = pd.read_sql_query("SELECT * FROM reddit_comments", get_db_connection())
        if not comments_df.empty:
            # Convert datetime columns
            datetime_cols = ['created_at']
            for col in datetime_cols:
                if col in comments_df.columns:
                    comments_df[col] = pd.to_datetime(comments_df[col], format='ISO8601', errors='coerce')

            st.metric("Total Comments", len(comments_df))
            st.dataframe(comments_df, use_container_width=True)

    with tabs[4]:
        st.subheader("User Preferences")
        pref_email = st.text_input("Enter user email to view preferences", key="pref_email")
        if pref_email:
            prefs_df = get_user_preferences(pref_email)
            if not prefs_df.empty:
                # Convert datetime columns
                datetime_cols = ['created_at', 'updated_at']
                for col in datetime_cols:
                    if col in prefs_df.columns:
                        prefs_df[col] = pd.to_datetime(prefs_df[col], format='ISO8601', errors='coerce')

                st.dataframe(prefs_df, use_container_width=True)
                
                # Display preferences details
                st.subheader("Preferences Details")
                col1, col2 = st.columns(2)
                with col1:
                    st.write("Tone:", prefs_df.iloc[0]['tone'])
                with col2:
                    st.write("Response Style:", prefs_df.iloc[0]['response_style'])
            else:
                st.info("No preferences found for this user")

    with tabs[5]:
        st.subheader("Reddit Authentication Status")
        auth_email = st.text_input("Enter user email to view Reddit auth status", key="auth_email")
        if auth_email:
            auth_df = get_reddit_auth_status(auth_email)
            if not auth_df.empty:
                # Convert datetime columns
                datetime_cols = ['created_at', 'updated_at']
                for col in datetime_cols:
                    if col in auth_df.columns:
                        auth_df[col] = pd.to_datetime(auth_df[col], format='ISO8601', errors='coerce')

                st.dataframe(auth_df, use_container_width=True)
                
                # Display auth details
                st.subheader("Authentication Details")
                col1, col2 = st.columns(2)
                with col1:
                    st.write("Reddit Username:", auth_df.iloc[0]['reddit_username'])
                with col2:
                    expires_at = auth_df.iloc[0]['expires_at']
                    st.write("Token Expires At:", datetime.fromtimestamp(expires_at) if expires_at else "N/A")
            else:
                st.warning("No Reddit authentication found for this user")
                
    with tabs[6]:
        st.subheader("Alert Settings")
        alert_settings_df = get_alert_settings_data()
        if not alert_settings_df.empty:
            # Convert datetime columns
            datetime_cols = ['created_at', 'updated_at']
            for col in datetime_cols:
                if col in alert_settings_df.columns:
                    alert_settings_df[col] = pd.to_datetime(alert_settings_df[col], errors='coerce').dt.strftime('%Y-%m-%d %H:%M:%S')
        st.dataframe(alert_settings_df, use_container_width=True)
        
    with tabs[7]:
        st.subheader("View Mentions by Email")
        email_to_search = st.text_input("Enter user email to view their brand mentions:")
        
        if email_to_search:
            if not validate_email(email_to_search):
                st.error("Please enter a valid email address")
            else:
                mentions_df = get_mentions_by_email(email_to_search)
                if not mentions_df.empty:
                    st.write(f"### Found {len(mentions_df)} mentions for {email_to_search}")
                    
                    # Convert datetime for display
                    if 'created_at' in mentions_df.columns:
                        mentions_df['created_at'] = pd.to_datetime(mentions_df['created_at'])
                    
                    # Show summary stats
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        st.metric("Total Mentions", len(mentions_df))
                    with col2:
                        st.metric("Unique Subreddits", mentions_df['subreddit'].nunique())
                    with col3:
                        st.metric("Avg. Relevance Score", 
                                f"{mentions_df['relevance_score'].mean():.1f}" if 'relevance_score' in mentions_df.columns else "N/A")
                    
                    # Show the data in an expandable section
                    with st.expander("View All Mentions", expanded=True):
                        st.dataframe(
                            mentions_df[[
                                'created_at', 'brand_name', 'subreddit', 
                                'title', 'relevance_score', 'intent', 'suggested_comment', 'url'
                            ]],
                            column_config={
                                "url": st.column_config.LinkColumn("Post Link"),
                                "created_at": "Date",
                                "relevance_score": st.column_config.NumberColumn(
                                    "Relevance",
                                    format="%d",
                                    min_value=0,
                                    max_value=100
                                ),
                                "suggested_comment": st.column_config.TextColumn(
                                    "Suggested Comment",
                                    width="large"
                                ),
                                "title": st.column_config.TextColumn(
                                    "Title",
                                    width="medium"
                                )
                            },
                            hide_index=True,
                            use_container_width=True,
                            height=min(400, 50 + (len(mentions_df) * 35))  # Dynamic height based on number of rows
                        )
                    
                    # Add a section to view individual mentions with more details
                    if not mentions_df.empty:
                        st.subheader("View Detailed Mention")
                        mention_idx = st.selectbox(
                            "Select a mention to view details:",
                            range(len(mentions_df)),
                            format_func=lambda i: f"{mentions_df.iloc[i]['title'][:50]}..."
                        )
                        
                        mention = mentions_df.iloc[mention_idx]
                        with st.container(border=True):
                            st.markdown(f"**Brand:** {mention['brand_name']}")
                            st.markdown(f"**Subreddit:** r/{mention['subreddit']}")
                            st.markdown(f"**Title:** {mention['title']}")
                            st.markdown(f"**Date:** {mention['created_at'].strftime('%Y-%m-%d %H:%M')}")
                            st.markdown(f"**Relevance Score:** {int(mention['relevance_score'])}/100")
                            st.markdown(f"**Intent:** {mention['intent'] or 'N/A'}")
                            st.markdown("**Suggested Comment:**")
                            st.markdown(f"```\n{mention['suggested_comment'] or 'No suggested comment available.'}\n```")
                            st.markdown(f"[View on Reddit]({mention['url']})")
                            
                            # Add a button to copy the suggested comment
                            if pd.notna(mention['suggested_comment']) and mention['suggested_comment']:
                                st.download_button(
                                    "Copy Comment to Clipboard",
                                    data=mention['suggested_comment'],
                                    file_name=f"comment_{mention_idx}.txt",
                                    mime="text/plain"
                                )
                    
                    # Download button
                    csv = mentions_df.to_csv(index=False).encode('utf-8')
                    st.download_button(
                        "Download as CSV",
                        data=csv,
                        file_name=f"mentions_{email_to_search}_{datetime.now().strftime('%Y%m%d')}.csv",
                        mime="text/csv"
                    )
                else:
                    st.info(f"No mentions found for {email_to_search}")
            # Display metrics
            col1, col2 = st.columns(2)
            with col1:
                st.metric("Total Alert Settings", len(alert_settings_df))
            with col2:
                telegram_enabled = len(alert_settings_df[alert_settings_df['enable_telegram_alerts'] == True])
                st.metric("Telegram Alerts Enabled", telegram_enabled)
            
            # Display the full dataframe
            st.dataframe(alert_settings_df, use_container_width=True)
        else:
            st.info("No alert settings found")

def show_user_dashboard(email):
    """Display the user-specific dashboard with brand analytics"""
    user_df, brand_stats = get_user_stats(email)
    
    if not user_df.empty:
        st.success(f"Welcome back!")
        
        # User Overview
        st.header("Your Overview")
        col1, col2 = st.columns(2)
        with col1:
            st.metric("Total Brands", len(brand_stats))
        with col2:
            st.metric("Total Mentions", brand_stats['mention_count'].sum())
        
        if not brand_stats.empty:
            # Brand Selection
            selected_brand = st.selectbox(
                "Select Brand to Analyze",
                options=brand_stats['name'].tolist(),
                index=0
            )
            
            # Get selected brand info
            brand_row = brand_stats[brand_stats['name'] == selected_brand].iloc[0]
            brand_id = brand_row['id']
            mentions_df, comments_df = get_brand_details(brand_id)
            
            # Brand Overview
            st.header(f"Brand: {selected_brand}")
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Total Mentions", brand_row['mention_count'])
            with col2:
                st.metric("Total Comments", brand_row['comment_count'])
            with col3:
                st.metric("Created", brand_row['created_at'].split()[0])
            
            # Tabs for different views
            tab1, tab2, tab3 = st.tabs(["Mentions Timeline", "Subreddit Analysis", "Recent Comments"])
            
            with tab1:
                if not mentions_df.empty:
                    mentions_df['date'] = pd.to_datetime(mentions_df['created_at'])
                    mentions_by_date = mentions_df.groupby('date').size().reset_index(name='count')
                    
                    fig = px.line(mentions_by_date, x='date', y='count',
                                title='Mentions Over Time')
                    st.plotly_chart(fig, use_container_width=True)
                else:
                    st.info("No mentions data available yet")
            
            with tab2:
                if not mentions_df.empty:
                    subreddit_stats = mentions_df.groupby('subreddit').agg({
                        'score': ['count', 'mean'],
                        'num_comments': 'mean',
                        'relevance_score': 'mean'
                    }).reset_index()
                    
                    subreddit_stats.columns = ['subreddit', 'mentions', 'avg_score', 
                                             'avg_comments', 'avg_relevance']
                    
                    fig = px.scatter(subreddit_stats, 
                                   x='avg_score', y='mentions',
                                   size='avg_comments',
                                   hover_data=['subreddit', 'avg_relevance'],
                                   title='Subreddit Performance')
                    st.plotly_chart(fig, use_container_width=True)
                    
                    st.dataframe(subreddit_stats)
                else:
                    st.info("No subreddit data available yet")
            
            with tab3:
                if not comments_df.empty:
                    for _, row in comments_df.head(5).iterrows():
                        with st.expander(f"Comment from {row['created_at'].split()[0]}", expanded=False):
                            st.write(row['comment_text'])
                            st.markdown(f"[View Post]({row['post_url']})")
                else:
                    st.info("No comments available yet")
        else:
            st.info("You haven't created any brands yet.")
    else:
        st.error("User not found!")

def show_user_preferences(email):
    """Display user preferences"""
    prefs_df = get_user_preferences(email)
    if not prefs_df.empty:
        st.dataframe(prefs_df)
        
        # Display preferences details
        st.subheader("Preferences Details")
        col1, col2 = st.columns(2)
        with col1:
            st.write("Tone:", prefs_df.iloc[0]['tone'])
        with col2:
            st.write("Response Style:", prefs_df.iloc[0]['response_style'])
    else:
        st.info("No preferences found for this user")

def show_reddit_auth_status(email):
    """Display Reddit authentication status"""
    auth_df = get_reddit_auth_status(email)
    if not auth_df.empty:
        st.dataframe(auth_df)
        
        # Display auth details
        st.subheader("Authentication Details")
        col1, col2 = st.columns(2)
        with col1:
            st.write("Reddit Username:", auth_df.iloc[0]['reddit_username'])
        with col2:
            expires_at = auth_df.iloc[0]['expires_at']
            st.write("Token Expires At:", datetime.fromtimestamp(expires_at) if expires_at else "N/A")
    else:
        st.warning("No Reddit authentication found for this user")

def main():
    st.sidebar.title("Navigation")
    app_mode = st.sidebar.selectbox("Choose Mode", ["User Dashboard", "Admin Dashboard"])
    
    if app_mode == "Admin Dashboard":
        show_admin_dashboard()
    else:
        st.title("Brand Mentions Analytics Dashboard")
        email = st.sidebar.text_input("Enter your email:")
        if email and validate_email(email):
            show_user_dashboard(email)
        else:
            st.warning("Please enter a valid email to continue")

if __name__ == "__main__":
    main()