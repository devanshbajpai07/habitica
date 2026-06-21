import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import os
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()

st.set_page_config(page_title="PAS Dashboard", layout="wide", page_icon="📈")

# --- Custom CSS for UI Tweaks ---
st.markdown("""
    <style>
        /* 1. Force tabs to expand and distribute evenly across the screen */
        button[data-baseweb="tab"] {
            flex: 1 !important;
            padding-top: 1rem !important;
            padding-bottom: 1rem !important;
        }
        
        /* 2. Target the specific text inside the tabs to make it massive and bold */
        button[data-baseweb="tab"] p {
            font-size: 22px !important;
            font-weight: 600 !important;
        }
        
        /* 3. Slightly reduce the invisible gap above the tabs */
        div[data-testid="stTabs"] {
            margin-top: -10px !important;
        }
    </style>
""", unsafe_allow_html=True)
MONGO_URI = os.getenv("MONGO_URL")
TAGS_URL=os.getenv("HABITICA_TAGS_URL")
API_URL=os.getenv("HABITICA_API_URL")

@st.cache_resource
def init_connection():
    return MongoClient(MONGO_URI)

client = init_connection()
db = client.pas_database
history_col = db.history
weights_col = db.weights

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

# --- Group Tasks by Primary Tag for UI ---
tasks_by_tag = {}
for task in latest_tasks:
    tags = task.get('tags', [])
    if not tags:
        primary_tag = "📁 Uncategorized"
    else:
        # Place the task only in its FIRST tag folder to prevent UI duplicates
        primary_tag = f"📁 {tags[0]}" 
        
    tasks_by_tag.setdefault(primary_tag, []).append(task)

# --- TOP CONTROL BAR ---
# Creates 3 columns: Left (popover), Middle (empty space), Right (sync button)
col_left, col_spacer, col_right = st.columns([2, 6, 2], vertical_alignment="bottom")

with col_left:
    with st.popover(" Edit Task Weights", use_container_width=True):
        st.markdown("Adjust weights by Subcategory. Saves to Cloud.")
        
        weights_doc = weights_col.find_one({"_id": "current_weights"})
        current_weights = weights_doc.get("weights", {}) if weights_doc else {}
                
        new_weights = {}
        fibonacci_sequence = [1, 2, 3, 5, 8, 13, 21]
        
        with st.form("weights_form"):
            for tag_name, tasks_in_tag in tasks_by_tag.items():
                with st.expander(tag_name):
                    for task in tasks_in_tag:
                        task_id = task['id']
                        title = task['title']
                        current_w = current_weights.get(task_id, 1)
                        
                        if current_w not in fibonacci_sequence:
                            fibonacci_sequence.append(current_w)
                            fibonacci_sequence.sort()
                            
                        new_w = st.selectbox(
                            f"{title[:40]}..." if len(title) > 40 else title, 
                            options=fibonacci_sequence, 
                            index=fibonacci_sequence.index(current_w),
                            key=task_id
                        )
                        new_weights[task_id] = new_w
                        
            if st.form_submit_button("Save Weights to Cloud"):
                weights_col.update_one({"_id": "current_weights"}, {"$set": {"weights": new_weights}}, upsert=True)
                st.rerun()

with col_right:
    # (The <br> tag that was here has been removed!)
    if st.button(" Sync Live Data", use_container_width=True):
        with st.spinner("Fetching latest tasks..."):
            import requests
            USER_ID = os.getenv("USER_ID")
            API_TOKEN = os.getenv("API_TOKEN")
            HEADERS = {"x-api-user": USER_ID, "x-api-key": API_TOKEN, "x-client": f"{USER_ID}-PAS"}
            
            tags_response = requests.get(TAGS_URL, headers=HEADERS)
            tag_map = {t["id"]: t["name"] for t in tags_response.json().get("data", [])} if tags_response.status_code == 200 else {}

            response = requests.get(API_URL, headers=HEADERS)
            
            if response.status_code == 200:
                dailies = response.json().get("data", [])
                weights_doc = weights_col.find_one({"_id": "current_weights"})
                task_weights = weights_doc.get("weights", {}) if weights_doc else {}
                
                daily_score = 0
                tasks_log = []
                
                for task in dailies:
                    task_id = task.get("id")
                    completed = task.get("completed", False)
                    is_due = task.get("isDue", False)
                    real_tag_names = [tag_map.get(tid, tid) for tid in task.get("tags", [])]
                    weight = task_weights.get(task_id, 1) 
                    
                    if is_due:
                        if completed: daily_score += weight
                        else: daily_score -= weight
                        
                    tasks_log.append({
                        "id": task_id, "title": task.get("text"), "completed": completed,
                        "tags": real_tag_names, "weight": weight, "is_due": is_due
                    })

                from datetime import datetime
                today_str = datetime.now().strftime('%Y-%m-%d')
                history_col.update_one(
                    {"date": today_str}, 
                    {"$set": {"date": today_str, "net_score": daily_score, "tasks": tasks_log}}, 
                    upsert=True
                )
                st.success("Synced successfully!")
                st.rerun()
            else:
                st.error("Failed to connect to Habitica.")

st.title("Personal Analytics System ")


st.markdown("### Today's Overview")
col1, col2, col3 = st.columns(3)

current_total = latest_day['cumulative_score']
today_net = latest_day['net_score']
due_tasks = [t for t in latest_tasks if t.get('is_due', True)]
completed_due = [t for t in due_tasks if t['completed']]
completion_rate = int((len(completed_due) / len(due_tasks) * 100)) if due_tasks else 0
delta_net = today_net - df.iloc[-2]['net_score'] if len(df) > 1 else None

col1.metric("Cumulative Score", f"{current_total}")
col2.metric("Today's Net Impact", f"{today_net > 0 and '+' or ''}{today_net}", delta=delta_net, delta_color="normal")
col3.metric("Daily Task Completion", f"{completion_rate}%", f"{len(completed_due)}/{len(due_tasks)} Tasks", delta_color="off")

st.markdown("---")
tab1, tab2, tab3 = st.tabs([" Primary Trajectory", " Subcategories", " Today's Breakdown"])

# --- TAB 1: Primary Chart (Daily Net Score) ---
with tab1:
    fig = go.Figure()

    first_date = df.iloc[0]['date']
    # Create a dynamic, short baseline just 2 days in the past so it draws beautifully from off-screen
    origin_date = first_date - pd.Timedelta(days=2) 
    yesterday_anchor = first_date - pd.Timedelta(days=1)
    
    # Draw the dashed baseline
    fig.add_trace(go.Scatter(
        x=[origin_date, yesterday_anchor], y=[0, 0], mode='lines',
        line=dict(color="#ff4b4b", width=2, dash="dot"), showlegend=False, hoverinfo="skip"
    ))
    
    first_score = df.iloc[0]['net_score'] 
    first_color = "#ff4b4b" if first_score < 0 else "#00cc96"
    fig.add_trace(go.Scatter(
        x=[yesterday_anchor, first_date], y=[0, first_score], mode='lines',
        line=dict(color=first_color, width=4), showlegend=False, hoverinfo="skip"
    ))

    fig.add_trace(go.Scatter(
        x=[first_date], y=[first_score], mode='markers',
        marker=dict(color=first_color, size=8), showlegend=False, hoverinfo="text",
        text=f"Date: {first_date.strftime('%Y-%m-%d')}<br>Daily Score: {first_score}"
    ))

    for i in range(1, len(df)):
        prev_row = df.iloc[i-1]
        curr_row = df.iloc[i]
        
        prev_score = prev_row['net_score'] 
        curr_score = curr_row['net_score'] 
        
        color = "#ff4b4b" if curr_score < 0 else "#00cc96"
            
        fig.add_trace(go.Scatter(
            x=[prev_row['date'], curr_row['date']], y=[prev_score, curr_score],
            mode='lines+markers', line=dict(color=color, width=4), marker=dict(color=color, size=8),
            showlegend=False, hoverinfo="text",
            text=f"Date: {curr_row['date'].strftime('%Y-%m-%d')}<br>Daily Score: {curr_score}"
        ))

    fig.add_hline(y=0, line_dash="solid", line_color="white", opacity=0.1)
    
    fig.update_layout(
        xaxis_title="Trajectory Trend", 
        yaxis_title="Daily Net Score", 
        template="plotly_dark", 
        hovermode="x unified", 
        height=500,
        xaxis=dict(
            type='date', 
            # REMOVED the hardcoded range so it auto-scales naturally!
            showticklabels=False, 
            showgrid=False 
        )
    )
    st.plotly_chart(fig, use_container_width=True)

# --- TAB 2: Subcategories (Daily Net Score) ---
with tab2:
    all_tags = set()
    for tasks in df['tasks']:
        for task in tasks:
            for tag in task.get('tags', []):
                all_tags.add(tag)

    if not all_tags:
        st.info("No tags found in your fetched Habitica tasks.")
    else:
        selected_tag = st.selectbox("Select a Subcategory to isolate:", list(all_tags))
        
        isolated_scores = []
        for index, row in df.iterrows():
            daily_iso = 0
            for task in row['tasks']:
                if selected_tag in task.get('tags', []) and task.get('is_due', True):
                    daily_iso += task['weight'] if task['completed'] else -task['weight']
            isolated_scores.append(daily_iso)
            
        iso_df = df[['date']].copy()
        iso_df['iso_net'] = isolated_scores
        
        fig_iso = go.Figure()
        
        iso_first_score = iso_df.iloc[0]['iso_net']
        
        # Dynamic baseline for subcategories too
        first_date = iso_df.iloc[0]['date']
        origin_date = first_date - pd.Timedelta(days=2)
        yesterday_anchor = first_date - pd.Timedelta(days=1)
        
        fig_iso.add_trace(go.Scatter(
            x=[origin_date, yesterday_anchor], y=[0, 0], mode='lines',
            line=dict(color="#ab63fa", width=2, dash="dot"), showlegend=False, hoverinfo="skip"
        ))
        
        fig_iso.add_trace(go.Scatter(
            x=[yesterday_anchor, first_date], y=[0, iso_first_score], mode='lines',
            line=dict(color="#ab63fa", width=3), showlegend=False, hoverinfo="skip"
        ))
        
        fig_iso.add_trace(go.Scatter(
            x=iso_df['date'], y=iso_df['iso_net'], mode='lines+markers',
            line=dict(color="#ab63fa", width=3), name="Isolated Tag", hoverinfo="text",
            text=[f"Date: {date.strftime('%Y-%m-%d')}<br>Daily Score: {net}" for date, net in zip(iso_df['date'], iso_df['iso_net'])]
        ))
        
        fig_iso.add_hline(y=0, line_dash="solid", line_color="white", opacity=0.1)
        
        fig_iso.update_layout(
            xaxis_title="Subcategory Trend", 
            yaxis_title="Daily Isolated Score", 
            template="plotly_dark", 
            height=500,
            xaxis=dict(
                type='date', 
                showticklabels=False, 
                showgrid=False
            )
        )
        st.plotly_chart(fig_iso, use_container_width=True)

# --- TAB 3: Today's Tasks Breakdown ---
with tab3:
    st.markdown(f"**Date:** {latest_day['date'].strftime('%A, %B %d, %Y')}")
    
    display_tasks = []
    for t in latest_tasks:
        if t.get('is_due', True):
            display_tasks.append({
                "Status": "✅" if t['completed'] else "❌",
                "Task": t['title'],
                "Impact": f"+{t['weight']}" if t['completed'] else f"-{t['weight']}",
                "Tags": ", ".join(t.get('tags', [])) # Show real tags in the table too!
            })
            
    if display_tasks:
        task_df = pd.DataFrame(display_tasks)
        st.dataframe(task_df, use_container_width=True, hide_index=True)
    else:
        st.info("No tasks were due today!")