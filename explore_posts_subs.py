#!/usr/bin/env python3
"""
Streamlit application for analyzing Reddit cancer subreddit data.
"""

import os
import sys
import csv
import io
import psycopg2
import pandas as pd
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
import logging
from dotenv import load_dotenv

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
log = logging.getLogger("reddit_streamlit")

# Load environment variables
load_dotenv()

# PostgreSQL connection parameters from .env
PG_HOST = os.getenv("PG_HOST")
PG_PORT = os.getenv("PG_PORT")
PG_DBNAME = os.getenv("PG_DBNAME")
PG_USER = os.getenv("PG_USER")
PG_PASSWORD = os.getenv("PG_PASSWORD")

# Cancer-related subreddits
CANCER_SUBREDDITS = [
   "SaaS","microsaas","Entrepreneur","SideProject","Business_Ideas"]

def connect_to_db():
    """Connect to the PostgreSQL database."""
    try:
        conn = psycopg2.connect(
            host=PG_HOST,
            port=PG_PORT,
            dbname=PG_DBNAME,
            user=PG_USER,
            password=PG_PASSWORD
        )
        return conn
    except Exception as e:
        st.error(f"Error connecting to database: {e}")
        return None

@st.cache_data(ttl=3600)  # Cache for 1 hour
def get_subreddit_analysis(subreddit, limit=100):
    """Get detailed analysis for a specific subreddit including best posting times and top contributors."""
    conn = connect_to_db()
    if not conn:
        return None, None, None
    
    try:
        with conn.cursor() as cur:
            # Get posting time distribution
            cur.execute("""
                SELECT DATE_PART('hour', created_utc) AS hour,
                       COUNT(*) AS post_count,
                       AVG(score) AS avg_score
                FROM submissions
                WHERE subreddit = %s
                GROUP BY hour
                ORDER BY hour
            """, [subreddit])
            
            time_data = []
            for result in cur.fetchall():
                time_data.append({
                    'hour': int(result[0]),
                    'post_count': int(result[1]),
                    'avg_score': float(round(result[2], 2)) if result[2] else 0
                })
            
            # Get top contributors
            cur.execute("""
                SELECT author,
                       COUNT(*) AS post_count,
                       AVG(score) AS avg_score,
                       SUM(score) AS total_score,
                       MAX(score) AS max_score
                FROM submissions
                WHERE subreddit = %s AND author != '[deleted]'
                GROUP BY author
                ORDER BY post_count DESC
                LIMIT %s
            """, [subreddit, limit])
            
            contributors = []
            for result in cur.fetchall():
                contributors.append({
                    'author': result[0],
                    'post_count': result[1],
                    'avg_score': float(round(result[2], 2)) if result[2] else 0,
                    'total_score': float(result[3]) if result[3] else 0,
                    'max_score': float(result[4]) if result[4] else 0
                })
            
            # Get top posts in the subreddit
            cur.execute("""
                SELECT title, author, score, created_utc, num_comments, permalink
                FROM submissions
                WHERE subreddit = %s
                ORDER BY score DESC
                LIMIT 10
            """, [subreddit])
            
            top_posts = []
            for result in cur.fetchall():
                top_posts.append({
                    'title': result[0],
                    'author': result[1],
                    'score': result[2],
                    'created_utc': result[3],
                    'num_comments': result[4],
                    'permalink': result[5]
                })
            
            return time_data, contributors, top_posts
    finally:
        conn.close()

@st.cache_data(ttl=3600)  # Cache for 1 hour
def search_posts(query, subreddit=None, limit=100, offset=0):
    """Search for posts containing the query string using full text search when possible."""
    conn = connect_to_db()
    if not conn:
        return []
    
    try:
        with conn.cursor() as cur:
            # Check if the table exists
            cur.execute("SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'submissions')")
            if not cur.fetchone()[0]:
                st.error("Submissions table does not exist")
                return []
            
            # Check if we have full text search index
            cur.execute("""
                SELECT EXISTS (
                    SELECT FROM pg_indexes 
                    WHERE tablename = 'submissions'
                    AND indexdef LIKE '%to_tsvector%title%'
                )
            """)
            has_fts = cur.fetchone()[0]
            
            # Define display fields
            display_fields = ['id', 'author', 'title', 'score', 'created_utc', 'subreddit', 'num_comments', 'permalink']
            
            # Build the WHERE clause
            where_clauses = []
            params = []
            
            # Use full text search if available, otherwise use ILIKE
            if has_fts and ' ' in query.strip():
                # Convert query to tsquery format (replace spaces with & for AND search)
                ts_query = ' & '.join(query.split())
                where_clauses.append("to_tsvector('english', title) @@ to_tsquery('english', %s)")
                params.append(ts_query)
            else:
                # Fall back to ILIKE for simple searches
                where_clauses.append("title ILIKE %s")
                params.append(f"%{query}%")
            
            # Add subreddit filter if specified
            if subreddit:
                where_clauses.append("subreddit = %s")
                params.append(subreddit)
            
            # Build the final query
            sql_query = f"""
                SELECT {', '.join(display_fields)}
                FROM submissions
                WHERE {' AND '.join(where_clauses)}
                ORDER BY score DESC
                LIMIT %s OFFSET %s
            """
            params.extend([limit, offset])
            
            cur.execute(sql_query, params)
            results = cur.fetchall()
            
            # Convert to list of dicts
            posts = []
            for result in results:
                post = {}
                for i, field in enumerate(display_fields):
                    post[field] = result[i]
                posts.append(post)
            
            return posts
    finally:
        conn.close()

@st.cache_data(ttl=3600)  # Cache for 1 hour
def export_to_csv(data):
    """Export data to a CSV string."""
    if not data:
        return None
    
    try:
        csv_buffer = io.StringIO()
        writer = csv.DictWriter(csv_buffer, fieldnames=data[0].keys())
        writer.writeheader()
        writer.writerows(data)
        
        return csv_buffer.getvalue()
    except Exception as e:
        st.error(f"Error exporting data: {e}")
        return None

def main():
    st.set_page_config(
        page_title="Reddit Insights - SneakyGuy ",
        page_icon="📊",
        layout="wide"
    )
    
    st.title("📊 Reddit Insights - SneakyGuy")
    st.write("Search and explore posts from Reddit")
    
    # Add back navigation but with only two options
    st.sidebar.title("Navigation")
    page = st.sidebar.radio(
        "Choose a page:",
        ["Post Search", "Subreddit Analysis"]
    )
    
    if page == "Post Search":
        # Post Search page
        st.header("Search Posts")
        
        col1, col2 = st.columns(2)
        with col1:
            search_query = st.text_input("Search for", placeholder="Enter keywords...")
        
        with col2:
            # Add option to select from predefined list or enter custom subreddit
            subreddit_option = st.radio("Subreddit selection", ["Choose from list", "Enter manually"], horizontal=True)
            
            if subreddit_option == "Choose from list":
                search_subreddit = st.selectbox("Select subreddit", options=["All Subreddits"] + CANCER_SUBREDDITS)
            else:
                search_subreddit = st.text_input("Enter subreddit name", placeholder="e.g. AskReddit (without r/)")
                if not search_subreddit:
                    search_subreddit = "All Subreddits"
        
        limit = st.slider("Number of results", min_value=10, max_value=100, value=25)
        
        if search_query:
            subreddit_filter = None if search_subreddit == "All Subreddits" else search_subreddit
            results = search_posts(search_query, subreddit_filter, limit)
            
            if results:
                # Format results as DataFrame
                df = pd.DataFrame(results)
                
                # Format created time
                if 'created_utc' in df.columns:
                    df['created_utc'] = pd.to_datetime(df['created_utc'])
                    df['created_date'] = df['created_utc'].dt.strftime('%Y-%m-%d')
                
                # Show results
                st.subheader(f"Search Results for '{search_query}'")
                
                # Create post list display
                for i, post in enumerate(results):
                    with st.container():
                        st.markdown(f"#### {i+1}. {post['title']}")
                        col1, col2, col3 = st.columns([2, 1, 1])
                        with col1:
                            st.markdown(f"**Subreddit:** r/{post['subreddit']} | **Author:** u/{post['author']}")
                        with col2:
                            st.markdown(f"**Score:** {post['score']}")
                        with col3:
                            st.markdown(f"**Comments:** {post['num_comments']}")
                        
                        if 'permalink' in post and post['permalink']:
                            st.markdown(f"[View on Reddit]({post['permalink']})")
                        
                        st.divider()
                
                # Export data
                csv_data = export_to_csv(results)
                if csv_data:
                    st.download_button(
                        label="Download CSV",
                        data=csv_data,
                        file_name="search_results.csv",
                        mime="text/csv"
                    )
            else:
                st.warning(f"No results found for '{search_query}'")
        else:
            st.info("Enter a search term above to find relevant posts.")
    
    elif page == "Subreddit Analysis":
        st.header("Subreddit Analysis")
        
        # Add option to select from predefined list or enter custom subreddit
        subreddit_option = st.radio("Subreddit selection", ["Choose from list", "Enter manually"], horizontal=True)
        
        if subreddit_option == "Choose from list":
            selected_subreddit = st.selectbox("Select a subreddit to analyze", options=CANCER_SUBREDDITS)
        else:
            selected_subreddit = st.text_input("Enter subreddit name", placeholder="e.g. AskReddit (without r/)")
        
        if selected_subreddit:
            # Get subreddit analysis data
            time_data, contributors, top_posts = get_subreddit_analysis(selected_subreddit)
            
            if time_data and contributors and top_posts:
                # Create tabs for different analysis views
                tab1, tab2, tab3 = st.tabs(["Best Time to Post", "Top Contributors", "Top Posts"])
                
                with tab1:
                    st.subheader(f"Best Time to Post in r/{selected_subreddit}")
                    
                    # Create DataFrame from time data
                    time_df = pd.DataFrame(time_data)
                    
                    # Add hour labels for display
                    time_df['hour_label'] = time_df['hour'].apply(lambda x: f"{x}:00-{(x+1) % 24}:00")
                    
                    # Find the best hour to post based on average score
                    best_score_hour = time_df.loc[time_df['avg_score'].idxmax()]
                    best_count_hour = time_df.loc[time_df['post_count'].idxmax()]
                    
                    col1, col2 = st.columns(2)
                    
                    with col1:
                        st.metric("Best Hour by Avg Score", f"{int(best_score_hour['hour'])}:00", f"Score: {best_score_hour['avg_score']}")
                    
                    with col2:
                        st.metric("Most Active Hour", f"{int(best_count_hour['hour'])}:00", f"Posts: {best_count_hour['post_count']}")
                    
                    # Create hourly distribution chart
                    fig1 = px.bar(
                        time_df,
                        x='hour_label',
                        y='post_count',
                        labels={'post_count': 'Number of Posts', 'hour_label': 'Hour (UTC)'},
                        title=f"Posting Activity by Hour in r/{selected_subreddit}"
                    )
                    
                    # Add average score line on secondary axis
                    fig1.add_trace(
                        go.Scatter(
                            x=time_df['hour_label'],
                            y=time_df['avg_score'],
                            name='Average Score',
                            yaxis='y2',
                            line=dict(color='red')
                        )
                    )
                    
                    # Configure second y-axis
                    fig1.update_layout(
                        yaxis2=dict(
                            title='Average Score',
                            overlaying='y',
                            side='right'
                        )
                    )
                    
                    st.plotly_chart(fig1, use_container_width=True)
                    
                    st.info("💡 **Tip:** The best time to post for maximum visibility and engagement is when the average score (red line) is highest while still having a reasonable number of posts. This often represents a sweet spot of active users who are more likely to upvote content.")
                
                with tab2:
                    st.subheader(f"Top Contributors in r/{selected_subreddit}")
                    
                    # Create DataFrame from contributors data
                    contrib_df = pd.DataFrame(contributors)
                    
                    # Display top 10 contributors with metrics
                    for i, contributor in enumerate(contributors[:10]):
                        with st.container():
                            col1, col2, col3, col4 = st.columns([2, 1, 1, 1])
                            
                            with col1:
                                st.markdown(f"**{i+1}. u/{contributor['author']}**")
                            
                            with col2:
                                st.metric("Posts", contributor['post_count'])
                            
                            with col3:
                                st.metric("Avg Score", contributor['avg_score'])
                            
                            with col4:
                                st.metric("Max Score", contributor['max_score'])
                    
                    # Create contributor chart
                    fig2 = px.bar(
                        contrib_df.head(20),
                        x='author',
                        y='post_count',
                        color='avg_score',
                        labels={'post_count': 'Number of Posts', 'author': 'Author', 'avg_score': 'Average Score'},
                        title=f"Top 20 Contributors in r/{selected_subreddit} by Post Count",
                        color_continuous_scale=px.colors.sequential.Viridis
                    )
                    
                    st.plotly_chart(fig2, use_container_width=True)
                    
                    # Show full data table with more contributors
                    with st.expander("View All Contributors Data"):
                        st.dataframe(contrib_df, use_container_width=True)
                
                with tab3:
                    st.subheader(f"Top Posts in r/{selected_subreddit}")
                    
                    # Format and display top posts
                    for i, post in enumerate(top_posts):
                        with st.container():
                            st.markdown(f"#### {i+1}. {post['title']}")
                            
                            col1, col2, col3 = st.columns([2, 1, 1])
                            
                            with col1:
                                created_date = post['created_utc'].strftime('%Y-%m-%d') if isinstance(post['created_utc'], datetime) else 'Unknown'
                                st.markdown(f"**Posted by:** u/{post['author']} | **Date:** {created_date}")
                            
                            with col2:
                                st.markdown(f"**Score:** {post['score']}")
                            
                            with col3:
                                st.markdown(f"**Comments:** {post['num_comments']}")
                            
                            if post['permalink']:
                                st.markdown(f"[View on Reddit]({post['permalink']})")
                            
                            st.divider()
                
                # Add export options
                st.subheader("Export Data")
                col1, col2 = st.columns(2)
                
                with col1:
                    # Export time data
                    csv_time_data = export_to_csv(time_data)
                    if csv_time_data:
                        st.download_button(
                            label="Download Posting Time Data",
                            data=csv_time_data,
                            file_name=f"{selected_subreddit}_posting_times.csv",
                            mime="text/csv"
                        )
                
                with col2:
                    # Export contributor data
                    csv_contrib_data = export_to_csv(contributors)
                    if csv_contrib_data:
                        st.download_button(
                            label="Download Contributors Data",
                            data=csv_contrib_data,
                            file_name=f"{selected_subreddit}_contributors.csv",
                            mime="text/csv"
                        )
            else:
                st.warning(f"No analysis data available for r/{selected_subreddit}")
        else:
            st.info("Please select a subreddit to analyze")

if __name__ == "__main__":
    main()