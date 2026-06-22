import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import os
from pymongo import MongoClient
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()

st.set_page_config(page_title="PAS Dashboard", layout="wide", page_icon="📈")

# --- Custom CSS for Elite UI Tweaks ---
# --- Custom CSS for Elite UI Tweaks ---
st.markdown("""
    <style>
        /* 1. Large Premium Navigation Dropdown */
        div[data-testid="stSelectbox"] label {
            font-size: 20px !important;
            font-weight: 600 !important;
            color: white !important;
        }
        
        /* 2. Enhanced Glassmorphism for KPI Metric Cards */
        div[data-testid="stMetric"] {
            /* Diagonal gradient to simulate light hitting glass */
            background: linear-gradient(135deg, rgba(255, 255, 255, 0.08), rgba(255, 255, 255, 0.01)) !important;
            backdrop-filter: blur(15px) !important;
            -webkit-backdrop-filter: blur(15px) !important;
            border-radius: 20px !important;
            padding: 20px !important;
            
            /* Brighter top/left borders create a 3D edge reflection */
            border: 1px solid rgba(255, 255, 255, 0.05) !important;
            border-top: 1px solid rgba(255, 255, 255, 0.2) !important;
            border-left: 1px solid rgba(255, 255, 255, 0.2) !important;
            
            /* Deep shadow to lift it off the page */
            box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.3) !important;
        }
    </style>
""", unsafe_allow_html=True)

# --- MongoDB Connection ---
MONGO_URI = os.getenv("MONGO_URL")

@st.cache_resource
def init_connection():
    return MongoClient(MONGO_URI)

client = init_connection()
db = client.pas_database
history_col = db.history
weights_col = db.weights
misc_col = db.misc 

# --- Load Data & Recalculate ---
data = list(history_col.find({}, {"_id": 0}))
if not data:
    st.warning("No data found in MongoDB. Please run fetch_habitica.py first.")
    st.stop()

weights_doc = weights_col.find_one({"_id": "current_weights"})
current_weights = weights_doc.get("weights", {}) if weights_doc else {}

df = pd.DataFrame(data)
df['date'] = pd.to_datetime(df['date'])
df = df.sort_values('date').reset_index(drop=True)

# Dynamic Recalculation Engine
recalculated_scores = []
for index, row in df.iterrows():
    daily_recalc = 0
    for task in row['tasks']:
        if task.get('is_due', True):
            task_id = task['id']
            if task_id in current_weights:
                weight_data = current_weights[task_id]
                if isinstance(weight_data, dict):
                    pos_w = weight_data.get("pos", 1)
                    neg_w = weight_data.get("neg", 1)
                else:
                    pos_w = weight_data
                    neg_w = weight_data
            else:
                pos_w = task.get('pos_weight', task.get('weight', 1))
                neg_w = task.get('neg_weight', task.get('weight', 1))
            
            if task['completed']:
                daily_recalc += pos_w
            else:
                daily_recalc -= neg_w
                
    recalculated_scores.append(daily_recalc)

df['net_score'] = recalculated_scores 
df['cumulative_score'] = df['net_score'].cumsum()

latest_day = df.iloc[-1]
latest_tasks = latest_day['tasks']

# Extract all unique tags
all_tags = set()
for tasks in df['tasks']:
    for task in tasks:
        for tag in task.get('tags', []):
            all_tags.add(tag)

tasks_by_tag = {}
for task in latest_tasks:
    tags = task.get('tags', [])
    if not tags:
        tasks_by_tag.setdefault("📁 Uncategorized", []).append(task)
    else:
        for tag in tags:
            tasks_by_tag.setdefault(f"📁 {tag}", []).append(task)

# --- TOP CONTROL BAR ---
col_left, col_spacer, col_right1, col_right2 = st.columns([2.5, 4.5, 2.5, 2.5], vertical_alignment="bottom")

with col_left:
    with st.popover("Edit Task Weights", use_container_width=True):
        st.markdown("Adjust weights by Subcategory.")
        new_weights = {}
        fibonacci_sequence = [1, 2, 3, 5, 8, 13, 21]
        
        with st.form("weights_form"):
            for tag_name, tasks_in_tag in tasks_by_tag.items():
                with st.expander(tag_name):
                    for task in tasks_in_tag:
                        task_id = task['id']
                        title = task['title']
                        
                        weight_data = current_weights.get(task_id, 1)
                        if isinstance(weight_data, dict):
                            curr_pos = weight_data.get("pos", 1)
                            curr_neg = weight_data.get("neg", 1)
                        else:
                            curr_pos = weight_data
                            curr_neg = weight_data
                        
                        for w in [curr_pos, curr_neg]:
                            if w not in fibonacci_sequence:
                                fibonacci_sequence.append(w)
                        fibonacci_sequence.sort()
                        
                        st.markdown(f"**{title[:40]}...**" if len(title) > 40 else f"**{title}**")
                        
                        c1, c2 = st.columns(2)
                        with c1:
                            new_pos = st.selectbox("Reward (+)", options=fibonacci_sequence, index=fibonacci_sequence.index(curr_pos), key=f"pos_{task_id}_{tag_name}")
                        with c2:
                            new_neg = st.selectbox("Penalty (-)", options=fibonacci_sequence, index=fibonacci_sequence.index(curr_neg), key=f"neg_{task_id}_{tag_name}")
                            
                        if new_pos != curr_pos or new_neg != curr_neg:
                            new_weights[task_id] = {"pos": new_pos, "neg": new_neg}
                        elif task_id not in new_weights:
                            new_weights[task_id] = {"pos": curr_pos, "neg": curr_neg}
                            
                        st.markdown("---")
                        
            if st.form_submit_button("Save Weights to Cloud"):
                weights_col.update_one({"_id": "current_weights"}, {"$set": {"weights": new_weights}}, upsert=True)
                st.rerun()

with col_right1:
    with st.popover("Today's Breakdown", use_container_width=True):
        st.markdown(f"**Date:** {latest_day['date'].strftime('%A, %B %d, %Y')}")
        st.markdown("---")
        
        has_due_tasks = False
        for t in latest_tasks:
            if t.get('is_due', True):
                has_due_tasks = True
                task_id = t['id']
                if task_id in current_weights:
                    weight_data = current_weights[task_id]
                    if isinstance(weight_data, dict):
                        pos_w = weight_data.get("pos", 1)
                        neg_w = weight_data.get("neg", 1)
                    else:
                        pos_w = weight_data
                        neg_w = weight_data
                else:
                    pos_w = t.get('pos_weight', t.get('weight', 1))
                    neg_w = t.get('neg_weight', t.get('weight', 1))
                
                # Native Markdown natively wraps text, completely eliminating horizontal scrolling
                status = "✅" if t['completed'] else "❌"
                impact = f"+{pos_w}" if t['completed'] else f"-{neg_w}"
                color = "green" if t['completed'] else "red"
                
                st.markdown(f"{status} **:{color}[{impact}]** &nbsp; | &nbsp; {t['title']}")
                
        if not has_due_tasks:
            st.info("No tasks were due today!")

with col_right2:
    # We simply capture the button click into a variable here
    run_sync = st.button("Sync Live Data", use_container_width=True)

# --- Run the sync OUTSIDE the columns so it doesn't stretch the UI ---
if run_sync:
    with st.spinner("Fetching latest tasks..."):
        import requests
        USER_ID = os.getenv("USER_ID")
        API_TOKEN = os.getenv("API_TOKEN")
        HABITICA_API_URL = os.getenv("HABITICA_API_URL")
        HABITICA_TAGS_URL = os.getenv("HABITICA_TAGS_URL")
        
        HEADERS = {"x-api-user": USER_ID, "x-api-key": API_TOKEN, "x-client": f"{USER_ID}-PAS"}
        
        tags_response = requests.get(HABITICA_TAGS_URL, headers=HEADERS)
        tag_map = {t["id"]: t["name"] for t in tags_response.json().get("data", [])} if tags_response.status_code == 200 else {}

        response = requests.get(HABITICA_API_URL, headers=HEADERS)
        
        if response.status_code == 200:
            dailies = response.json().get("data", [])
            daily_score = 0
            tasks_log = []
            
            for task in dailies:
                task_id = task.get("id")
                completed = task.get("completed", False)
                is_due = task.get("isDue", False)
                real_tag_names = [tag_map.get(tid, tid) for tid in task.get("tags", [])]
                
                weight_data = current_weights.get(task_id, 1)
                if isinstance(weight_data, dict):
                    pos_w = weight_data.get("pos", 1)
                    neg_w = weight_data.get("neg", 1)
                else:
                    pos_w = weight_data
                    neg_w = weight_data
                
                if is_due:
                    if completed: daily_score += pos_w
                    else: daily_score -= neg_w
                    
                tasks_log.append({
                    "id": task_id, "title": task.get("text"), "completed": completed,
                    "tags": real_tag_names, "pos_weight": pos_w, "neg_weight": neg_w, "is_due": is_due
                })

            today_str = datetime.now().strftime('%Y-%m-%d')
            history_col.update_one(
                {"date": today_str}, 
                {"$set": {"date": today_str, "net_score": daily_score, "tasks": tasks_log}}, 
                upsert=True
            )
            st.rerun() # We removed st.success because the instant page refresh is enough feedback
        else:
            st.error("Failed to connect to Habitica.")

st.title("Personal Analytics System")

# --- KPIs ---
st.markdown("### Today's Overview")

current_total = latest_day['cumulative_score']
today_net = latest_day['net_score']
due_tasks = [t for t in latest_tasks if t.get('is_due', True)]
completed_due = [t for t in due_tasks if t['completed']]
completion_rate = int((len(completed_due) / len(due_tasks) * 100)) if due_tasks else 0
delta_net = today_net - df.iloc[-2]['net_score'] if len(df) > 1 else None

# --- NEW: Calculate Earned vs Total Possible Points ---
earned_points = 0
total_possible_points = 0
for t in due_tasks:
    task_id = t['id']
    if task_id in current_weights:
        weight_data = current_weights[task_id]
        pos_w = weight_data.get("pos", 1) if isinstance(weight_data, dict) else weight_data
    else:
        pos_w = t.get('pos_weight', t.get('weight', 1))
    
    total_possible_points += pos_w
    if t['completed']:
        earned_points += pos_w

col1, col2, col3 = st.columns([1, 1, 1.2])

with col1:
    st.metric("Cumulative Score", f"{current_total}")
with col2:
    st.metric("Today's Net Impact", f"{today_net > 0 and '+' or ''}{today_net}", delta=delta_net, delta_color="normal")
with col3:
    fig_gauge = go.Figure(go.Indicator(
        mode = "gauge+number",
        value = completion_rate,
        domain = {'x': [0, 1], 'y': [0, 1]},
        title = {'text': f"{len(completed_due)}/{len(due_tasks)} Tasks Completed", 'font': {'size': 14, 'color': "gray"}},
        number = {'suffix': "%", 'font': {'size': 36, 'color': "white"}},
        gauge = {
            'axis': {'range': [None, 100], 'visible': False},
            'bar': {'color': "#00cc96", 'thickness': 0.25},
            'bgcolor': "rgba(255, 255, 255, 0.05)",
            'borderwidth': 0
        }
    ))
    
    fig_gauge.update_layout(
        height=150, 
        margin=dict(l=10, r=10, t=30, b=10), 
        paper_bgcolor="rgba(0,0,0,0)", 
        font={'color': "white"}
    )
    st.plotly_chart(fig_gauge, use_container_width=True)
    
    # Inject the points sub-metric directly below the gauge, centered cleanly
    st.markdown(f"<div style='text-align: center; color: #a0a0a0; font-size: 15px; margin-top: -15px;'><strong>{earned_points} / {total_possible_points}</strong> Points</div>", unsafe_allow_html=True)

st.markdown("---")

# --- VIEW ROUTER (MAIN NAVIGATION) ---
view_options = [
    "Cumulative Graph", 
    "Daily Trajectory", 
    "Miscellaneous Graph"
]
selected_view = st.selectbox("Select View", view_options, label_visibility="collapsed")

# ---------------------------------------------------------
# VIEW 1: CUMULATIVE GRAPH
# ---------------------------------------------------------
if selected_view == "Cumulative Graph":
    cumul_target = st.selectbox("Select Target:", ["Overall (All Data)"] + list(all_tags), key="cumul_sel")
    
    fig = go.Figure()
    
    if cumul_target == "Overall (All Data)":
        plot_df = df[['date', 'cumulative_score']].copy()
        plot_df.rename(columns={'cumulative_score': 'score'}, inplace=True)
    else:
        isolated_scores = []
        for index, row in df.iterrows():
            daily_iso = 0
            for task in row['tasks']:
                if cumul_target in task.get('tags', []) and task.get('is_due', True):
                    task_id = task['id']
                    if task_id in current_weights:
                        weight_data = current_weights[task_id]
                        if isinstance(weight_data, dict):
                            pos_w = weight_data.get("pos", 1)
                            neg_w = weight_data.get("neg", 1)
                        else:
                            pos_w = weight_data
                            neg_w = weight_data
                    else:
                        pos_w = task.get('pos_weight', task.get('weight', 1))
                        neg_w = task.get('neg_weight', task.get('weight', 1))
                    daily_iso += pos_w if task['completed'] else -neg_w
            isolated_scores.append(daily_iso)
            
        plot_df = df[['date']].copy()
        plot_df['iso_net'] = isolated_scores
        plot_df['score'] = plot_df['iso_net'].cumsum()
        
    first_date = plot_df.iloc[0]['date']
    origin_date = first_date - pd.Timedelta(days=2)
    yesterday_anchor = first_date - pd.Timedelta(days=1)
    
    # 1. INVISIBLE HOVER LAYER (Perfect alignment, no big dots)
    fig.add_trace(go.Scatter(
        x=plot_df['date'], y=plot_df['score'], mode='markers',
        marker=dict(color='rgba(0,0,0,0)', size=10), # Invisible
        showlegend=False, hoverinfo="text",
        text=[f"Date: {d.strftime('%Y-%m-%d')}<br>Cumul Score: {s}" for d, s in zip(plot_df['date'], plot_df['score'])]
    ))

    # 2. VISUAL LINE LAYER
    fig.add_trace(go.Scatter(
        x=[origin_date, yesterday_anchor], y=[0, 0], mode='lines',
        line=dict(color="#ff4b4b", width=2, dash="dot"), showlegend=False, hoverinfo="skip"
    ))
    
    first_score = plot_df.iloc[0]['score']
    first_color = "#00cc96" if first_score >= 0 else "#ff4b4b"
    fig.add_trace(go.Scatter(x=[yesterday_anchor, first_date], y=[0, first_score], mode='lines', line=dict(color=first_color, width=4), showlegend=False, hoverinfo="skip"))

    # Draw color-coded segments without overriding hover text or adding markers
    for i in range(1, len(plot_df)):
        prev_row = plot_df.iloc[i-1]
        curr_row = plot_df.iloc[i]
        color = "#00cc96" if curr_row['score'] >= 0 else "#ff4b4b"
            
        fig.add_trace(go.Scatter(
            x=[prev_row['date'], curr_row['date']], y=[prev_row['score'], curr_row['score']],
            mode='lines', line=dict(color=color, width=4), showlegend=False, hoverinfo="skip"
        ))

    fig.add_hline(y=0, line_dash="solid", line_color="white", opacity=0.1)
    fig.update_layout(xaxis_title="Timeline", yaxis_title="Cumulative Score", template="plotly_dark", showlegend=False, xaxis=dict(type='date', showticklabels=False, showgrid=False), height=500)
    st.plotly_chart(fig, use_container_width=True)

# ---------------------------------------------------------
# VIEW 2: DAILY TRAJECTORY
# ---------------------------------------------------------
elif selected_view == "Daily Trajectory":
    daily_target = st.selectbox("Select Target:", ["Overall (All Data)"] + list(all_tags), key="daily_sel")
    
    fig = go.Figure()
    
    if daily_target == "Overall (All Data)":
        plot_df = df[['date', 'net_score']].copy()
        plot_df.rename(columns={'net_score': 'score'}, inplace=True)
        base_color_positive = "#00cc96"
    else:
        isolated_scores = []
        for index, row in df.iterrows():
            daily_iso = 0
            for task in row['tasks']:
                if daily_target in task.get('tags', []) and task.get('is_due', True):
                    task_id = task['id']
                    if task_id in current_weights:
                        weight_data = current_weights[task_id]
                        if isinstance(weight_data, dict):
                            pos_w = weight_data.get("pos", 1)
                            neg_w = weight_data.get("neg", 1)
                        else:
                            pos_w = weight_data
                            neg_w = weight_data
                    else:
                        pos_w = task.get('pos_weight', task.get('weight', 1))
                        neg_w = task.get('neg_weight', task.get('weight', 1))
                    
                    daily_iso += pos_w if task['completed'] else -neg_w
            isolated_scores.append(daily_iso)
            
        plot_df = df[['date']].copy()
        plot_df['score'] = isolated_scores
        base_color_positive = "#ab63fa"
        
    first_date = plot_df.iloc[0]['date']
    origin_date = first_date - pd.Timedelta(days=2)
    yesterday_anchor = first_date - pd.Timedelta(days=1)
    first_score = plot_df.iloc[0]['score']
    
    # INVISIBLE HOVER LAYER
    fig.add_trace(go.Scatter(
        x=plot_df['date'], y=plot_df['score'], mode='markers',
        marker=dict(color='rgba(0,0,0,0)', size=10), 
        showlegend=False, hoverinfo="text",
        text=[f"Date: {d.strftime('%Y-%m-%d')}<br>Score: {s}" for d, s in zip(plot_df['date'], plot_df['score'])]
    ))
    
    baseline_color = "#ff4b4b" if daily_target == "Overall (All Data)" else "#ab63fa"
    first_color = base_color_positive if first_score >= 0 else "#ff4b4b"
    
    fig.add_trace(go.Scatter(x=[origin_date, yesterday_anchor], y=[0, 0], mode='lines', line=dict(color=baseline_color, width=2, dash="dot"), showlegend=False, hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=[yesterday_anchor, first_date], y=[0, first_score], mode='lines', line=dict(color=first_color, width=3), showlegend=False, hoverinfo="skip"))
    
    for i in range(1, len(plot_df)):
        prev_row = plot_df.iloc[i-1]
        curr_row = plot_df.iloc[i]
        color = base_color_positive if curr_row['score'] >= 0 else "#ff4b4b"
        fig.add_trace(go.Scatter(
            x=[prev_row['date'], curr_row['date']], y=[prev_row['score'], curr_row['score']],
            mode='lines', line=dict(color=color, width=3), showlegend=False, hoverinfo="skip"
        ))
    
    fig.add_hline(y=0, line_dash="solid", line_color="white", opacity=0.1)
    fig.update_layout(xaxis_title="Trajectory Trend", yaxis_title="Daily Score", template="plotly_dark", height=500, xaxis=dict(type='date', showticklabels=False, showgrid=False))
    st.plotly_chart(fig, use_container_width=True)

# ---------------------------------------------------------
# VIEW 3: MISCELLANEOUS GRAPH
# ---------------------------------------------------------
elif selected_view == "Miscellaneous Graph":
    today_str = datetime.now().strftime('%Y-%m-%d')
    
    today_misc_doc = misc_col.find_one({"date": today_str})
    current_misc_score = today_misc_doc.get("score", 0) if today_misc_doc else 0
    
    st.markdown("### Log Unregistered Wins")
    col_input, col_add, col_sub, _ = st.columns([2, 2, 2, 6], vertical_alignment="bottom")
    
    with col_input:
        val = st.number_input("Points", min_value=1, max_value=50, value=1, step=1)
        
    with col_add:
        if st.button("➕ Increment", use_container_width=True):
            misc_col.update_one({"date": today_str}, {"$inc": {"score": val}}, upsert=True)
            st.rerun()
            
    with col_sub:
        if st.button("➖ Decrement", use_container_width=True, disabled=(current_misc_score <= 0)):
            deduct_val = min(val, current_misc_score)
            misc_col.update_one({"date": today_str}, {"$inc": {"score": -deduct_val}}, upsert=True)
            st.rerun()

    misc_data = list(misc_col.find({}, {"_id": 0}))
    if not misc_data:
        st.info("No miscellaneous points logged yet. Add some above to start your trajectory!")
    else:
        misc_df = pd.DataFrame(misc_data)
        misc_df['date'] = pd.to_datetime(misc_df['date'])
        
        master_dates = df[['date']].copy()
        plot_misc_df = pd.merge(master_dates, misc_df, on='date', how='left').fillna({'score': 0})
        plot_misc_df = plot_misc_df.sort_values('date').reset_index(drop=True)
        
        fig_misc = go.Figure()
        first_date = plot_misc_df.iloc[0]['date']
        origin_date = first_date - pd.Timedelta(days=2)
        yesterday_anchor = first_date - pd.Timedelta(days=1)
        
        # INVISIBLE HOVER LAYER
        fig_misc.add_trace(go.Scatter(
            x=plot_misc_df['date'], y=plot_misc_df['score'], mode='markers',
            marker=dict(color='rgba(0,0,0,0)', size=10), showlegend=False, hoverinfo="text",
            text=[f"Date: {date.strftime('%Y-%m-%d')}<br>Misc Score: {score}" for date, score in zip(plot_misc_df['date'], plot_misc_df['score'])]
        ))
        
        fig_misc.add_trace(go.Scatter(x=[origin_date, yesterday_anchor], y=[0, 0], mode='lines', line=dict(color="#00cc96", width=2, dash="dot"), showlegend=False, hoverinfo="skip"))
        fig_misc.add_trace(go.Scatter(x=[yesterday_anchor, first_date], y=[0, plot_misc_df.iloc[0]['score']], mode='lines', line=dict(color="#00cc96", width=4), showlegend=False, hoverinfo="skip"))
        
        # Draw smooth line with no markers
        fig_misc.add_trace(go.Scatter(
            x=plot_misc_df['date'], y=plot_misc_df['score'], mode='lines',
            line=dict(color="#00cc96", width=4), showlegend=False, hoverinfo="skip"
        ))
        
        fig_misc.add_hline(y=0, line_dash="solid", line_color="white", opacity=0.1)
        fig_misc.update_layout(xaxis_title="Miscellaneous Wins", yaxis_title="Points", template="plotly_dark", height=500, xaxis=dict(type='date', showticklabels=False, showgrid=False))
        st.plotly_chart(fig_misc, use_container_width=True)