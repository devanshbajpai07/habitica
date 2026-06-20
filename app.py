import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from pymongo import MongoClient
import os
from dotenv import load_dotenv
load_dotenv()

st.set_page_config(page_title="Personal Analytics System", layout="wide")

# --- MongoDB Configuration ---
# Must match the connection string in your fetch script
MONGO_URI = os.getenv("MONGO_URL") 

@st.cache_resource
def init_connection():
    return MongoClient(MONGO_URI)

client = init_connection()
db = client.pas_database
history_col = db.history
weights_col = db.weights

st.title("Personal Analytics System (PAS)")

# --- Load Data from MongoDB ---
data = list(history_col.find({}, {"_id": 0})) # Fetch all history, exclude the MongoDB ObjectId

if not data:
    st.warning("No data found in MongoDB. Please run fetch_habitica.py in your terminal first.")
    st.stop()

df = pd.DataFrame(data)
df['date'] = pd.to_datetime(df['date'])
df = df.sort_values('date').reset_index(drop=True)
df['cumulative_score'] = df['net_score'].cumsum()

# --- Weight Manager UI ---
with st.expander("⚙️ Manage Task Weights"):
    st.markdown("Adjust the Fibonacci weights for your dailies. Changes save directly to MongoDB and apply the **next time** you run your fetch script.")
    
    weights_doc = weights_col.find_one({"_id": "current_weights"})
    current_weights = weights_doc.get("weights", {}) if weights_doc else {}
            
    latest_tasks = df.iloc[-1]['tasks']
    new_weights = {}
    
    fibonacci_sequence = [1, 2, 3, 5, 8, 13, 21]
    
    col1, col2 = st.columns(2)
    
    for i, task in enumerate(latest_tasks):
        task_id = task['id']
        title = task['title']
        current_w = current_weights.get(task_id, 1)
        
        if current_w not in fibonacci_sequence:
            fibonacci_sequence.append(current_w)
            fibonacci_sequence.sort()
            
        with col1 if i % 2 == 0 else col2:
            new_w = st.selectbox(
                f"{title}", 
                options=fibonacci_sequence, 
                index=fibonacci_sequence.index(current_w),
                key=task_id
            )
            new_weights[task_id] = new_w
            
    if st.button("Save Weights to Cloud"):
        weights_col.update_one({"_id": "current_weights"}, {"$set": {"weights": new_weights}}, upsert=True)
        st.success("Weights saved to MongoDB successfully!")

st.markdown("---")

# --- Primary Trajectory Plotting ---
st.subheader("Primary Trajectory (Positive/Negative Dailies)")

fig = go.Figure()

if len(df) == 1:
    curr_row = df.iloc[0]
    curr_score = curr_row['cumulative_score']
    color = "#ff4b4b" if curr_score < 0 else "#00cc96"
    
    fig.add_trace(go.Scatter(
        x=[curr_row['date']], y=[curr_score], mode='markers',
        marker=dict(color=color, size=12), showlegend=False, hoverinfo="text",
        text=f"Date: {curr_row['date'].strftime('%Y-%m-%d')}<br>Net Daily Impact: {curr_row['net_score']}<br>Cumulative Total: {curr_score}"
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
            text=f"Date: {curr_row['date'].strftime('%Y-%m-%d')}<br>Net Daily Impact: {curr_row['net_score']}<br>Cumulative Total: {curr_score}"
        ))

fig.add_hline(y=0, line_dash="dash", line_color="white", opacity=0.3)

fig.update_layout(
    xaxis_title="Date", yaxis_title="Cumulative Score", template="plotly_dark", hovermode="x unified",
    xaxis=dict(type='date', tickformat='%Y-%m-%d')
)
st.plotly_chart(fig, use_container_width=True)

# --- Subcategory Plotting ---
st.markdown("---")
st.subheader("Subcategory Trajectories")

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
    fig_iso.update_layout(template="plotly_dark", xaxis=dict(type='date', tickformat='%Y-%m-%d'))
    st.plotly_chart(fig_iso, use_container_width=True)