import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import os
from pymongo import MongoClient
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# --- Page Config ---
st.set_page_config(
    page_title="PAS Dashboard", 
    layout="wide", 
    page_icon="📈",
    initial_sidebar_state="collapsed" # <-- Add this parameter
)

# --- MongoDB Connection ---
MONGO_URI = os.getenv("MONGO_URL")

@st.cache_resource
def init_connection():
    return MongoClient(MONGO_URI)

client = init_connection()
db = client.pas_database
history_col = db.history
weights_col = db.weights

# --- Load Data ---
data = list(history_col.find({}, {"_id": 0}))
if not data:
    st.warning("No data found in MongoDB. Please run fetch_habitica.py first.")
    st.stop()

df = pd.DataFrame(data)
df['date'] = pd.to_datetime(df['date'])
df = df.sort_values('date').reset_index(drop=True)
df['cumulative_score'] = df['net_score'].cumsum()

latest_day = df.iloc[-1]
latest_tasks = latest_day['tasks']

# --- SIDEBAR: Weight Manager ---
with st.sidebar:
    st.header("⚙️ Task Weights")
    st.markdown("Adjust Fibonacci weights. Saves directly to Cloud.")
    
    weights_doc = weights_col.find_one({"_id": "current_weights"})
    current_weights = weights_doc.get("weights", {}) if weights_doc else {}
            
    new_weights = {}
    fibonacci_sequence = [1, 2, 3, 5, 8, 13, 21]
    
    with st.form("weights_form"):
        for task in latest_tasks:
            task_id = task['id']
            title = task['title']
            current_w = current_weights.get(task_id, 1)
            
            if current_w not in fibonacci_sequence:
                fibonacci_sequence.append(current_w)
                fibonacci_sequence.sort()
                
            new_w = st.selectbox(
                f"{title[:30]}..." if len(title) > 30 else title, 
                options=fibonacci_sequence, 
                index=fibonacci_sequence.index(current_w),
                key=task_id
            )
            new_weights[task_id] = new_w
            
        submitted = st.form_submit_button("Save Weights to Cloud")
        if submitted:
            weights_col.update_one({"_id": "current_weights"}, {"$set": {"weights": new_weights}}, upsert=True)
            st.success("Weights saved successfully!")

# --- MAIN DASHBOARD ---
st.title("Personal Analytics System 📈")

# --- KPIs ---
st.markdown("### Today's Overview")
col1, col2, col3 = st.columns(3)

# Calculate metrics for the cards
current_total = latest_day['cumulative_score']
today_net = latest_day['net_score']
due_tasks = [t for t in latest_tasks if t.get('is_due', True)]
completed_due = [t for t in due_tasks if t['completed']]
completion_rate = int((len(completed_due) / len(due_tasks) * 100)) if due_tasks else 0

# Calculate day-over-day changes if we have more than 1 day of data
delta_net = today_net - df.iloc[-2]['net_score'] if len(df) > 1 else None

col1.metric("Cumulative Score", f"{current_total}", help="Total accumulated score over time")
col2.metric("Today's Net Impact", f"{today_net > 0 and '+' or ''}{today_net}", delta=delta_net, delta_color="normal")
col3.metric("Daily Task Completion", f"{completion_rate}%", f"{len(completed_due)}/{len(due_tasks)} Tasks", delta_color="off")

st.markdown("---")

# --- TABS ---
tab1, tab2, tab3 = st.tabs(["📊 Primary Trajectory", "🏷️ Subcategories", "📋 Today's Breakdown"])

# --- TAB 1: Primary Chart ---
with tab1:
    fig = go.Figure()

    if len(df) == 1:
        curr_row = df.iloc[0]
        curr_score = curr_row['cumulative_score']
        color = "#ff4b4b" if curr_score < 0 else "#00cc96"
        
        fig.add_trace(go.Scatter(
            x=[curr_row['date']], y=[curr_score], mode='markers',
            marker=dict(color=color, size=12), showlegend=False, hoverinfo="text",
            text=f"Date: {curr_row['date'].strftime('%Y-%m-%d')}<br>Net: {curr_row['net_score']}<br>Total: {curr_score}"
        ))
    else:
        for i in range(1, len(df)):
            prev_row = df.iloc[i-1]
            curr_row = df.iloc[i]
            
            prev_score = prev_row['cumulative_score']
            curr_score = curr_row['cumulative_score']
            
            if curr_score < 0: color = "#ff4b4b" 
            elif curr_score >= 0 and curr_score < prev_score: color = "#ff4b4b" 
            else: color = "#00cc96" 
                
            fig.add_trace(go.Scatter(
                x=[prev_row['date'], curr_row['date']], y=[prev_score, curr_score],
                mode='lines+markers', line=dict(color=color, width=4), marker=dict(color=color, size=8),
                showlegend=False, hoverinfo="text",
                text=f"Date: {curr_row['date'].strftime('%Y-%m-%d')}<br>Net: {curr_row['net_score']}<br>Total: {curr_score}"
            ))

    fig.add_hline(y=0, line_dash="dash", line_color="white", opacity=0.3)
    fig.update_layout(xaxis_title="Date", yaxis_title="Cumulative Score", template="plotly_dark", hovermode="x unified", xaxis=dict(type='date', tickformat='%Y-%m-%d'), height=500)
    st.plotly_chart(fig, use_container_width=True)

# --- TAB 2: Subcategories ---
with tab2:
    all_tags = set()
    for tasks in df['tasks']:
        for task in tasks:
            for tag in task.get('tags', []):
                all_tags.add(tag)

    if not all_tags:
        st.info("No tags found in your fetched Habitica tasks.")
    else:
        selected_tag = st.selectbox("Select a Tag UUID to isolate:", list(all_tags))
        
        isolated_scores = []
        for index, row in df.iterrows():
            daily_iso = 0
            for task in row['tasks']:
                if selected_tag in task.get('tags', []) and task.get('is_due', True):
                    daily_iso += task['weight'] if task['completed'] else -task['weight']
            isolated_scores.append(daily_iso)
            
        iso_df = df[['date']].copy()
        iso_df['iso_net'] = isolated_scores
        iso_df['iso_cumulative'] = iso_df['iso_net'].cumsum()
        
        fig_iso = go.Figure()
        fig_iso.add_trace(go.Scatter(
            x=iso_df['date'], y=iso_df['iso_cumulative'], mode='lines+markers',
            line=dict(color="#ab63fa", width=3), name="Isolated Tag", hoverinfo="text",
            text=[f"Net Daily: {net}<br>Total: {cum}" for net, cum in zip(iso_df['iso_net'], iso_df['iso_cumulative'])]
        ))
        
        fig_iso.add_hline(y=0, line_dash="dash", line_color="white", opacity=0.3)
        fig_iso.update_layout(template="plotly_dark", xaxis=dict(type='date', tickformat='%Y-%m-%d'), height=500)
        st.plotly_chart(fig_iso, use_container_width=True)

# --- TAB 3: Today's Tasks Breakdown ---
with tab3:
    st.markdown(f"**Date:** {latest_day['date'].strftime('%A, %B %d, %Y')}")
    
    # Create a cleaner list for the dataframe
    display_tasks = []
    for t in latest_tasks:
        if t.get('is_due', True):
            display_tasks.append({
                "Status": "✅" if t['completed'] else "❌",
                "Task": t['title'],
                "Impact": f"+{t['weight']}" if t['completed'] else f"-{t['weight']}"
            })
            
    if display_tasks:
        task_df = pd.DataFrame(display_tasks)
        st.dataframe(task_df, use_container_width=True, hide_index=True)
    else:
        st.info("No tasks were due today!")