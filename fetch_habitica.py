import requests
import os
from pymongo import MongoClient
from datetime import datetime
from dotenv import load_dotenv
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

load_dotenv()

USER_ID = os.getenv("USER_ID")
API_TOKEN = os.getenv("API_TOKEN")
CLIENT_ID = f"{USER_ID}-PAS"

HEADERS = {
    "x-api-user": USER_ID,
    "x-api-key": API_TOKEN,
    "x-client": CLIENT_ID
}

HABITICA_TASKS_URL = os.getenv("HABITICA_API_URL")
HABITICA_TAGS_URL = os.getenv("HABITICA_TAGS_URL")
MONGO_URI = os.getenv("MONGO_URL")

print("Connecting to MongoDB Atlas...")
client = MongoClient(MONGO_URI)
db = client.pas_database
history_col = db.history
misc_col = db.misc

print("Extracting custom weights from historical data...")
current_weights = {}
all_history = list(history_col.find().sort("date", 1))

for h in all_history:
    if 'tasks' in h and isinstance(h['tasks'], list):
        for t in h['tasks']:
            t_id = t.get('id')
            pw = t.get('pos_weight', 1)
            nw = t.get('neg_weight', 1)
            if pw != 1 or nw != 1:
                current_weights[t_id] = {'pos': pw, 'neg': nw}

print("Fetching tags from Habitica...")
tags_response = requests.get(HABITICA_TAGS_URL, headers=HEADERS)
tag_map = {t["id"]: t["name"] for t in tags_response.json().get("data", [])} if tags_response.status_code == 200 else {}

print("Fetching tasks from Habitica...")
response = requests.get(HABITICA_TASKS_URL, headers=HEADERS)

if response.status_code == 200:
    dailies = response.json().get("data", [])
    daily_score = 0
    tasks_log = []
    
    for task in dailies:
        task_id = task.get("id")
        completed = task.get("completed", False)
        is_due = task.get("isDue", False)
        
        real_tag_names = [tag_map.get(tid, tid) for tid in task.get("tags", [])]
        
        weight_data = current_weights.get(task_id, {'pos': 1, 'neg': 1})
        pos_w = weight_data.get("pos", 1)
        neg_w = weight_data.get("neg", 1)
        
        # is_due LOGIC RESTORED: Only alter score if the task is due today
        if is_due:
            if completed: 
                daily_score += pos_w
            else: 
                daily_score -= neg_w
            
        tasks_log.append({
            "id": task_id, 
            "title": task.get("text"), 
            "completed": completed,
            "pos_weight": pos_w, 
            "neg_weight": neg_w, 
            "is_due": is_due,
            "tags": real_tag_names
        })

    today_str = datetime.now().strftime('%Y-%m-%d')
    
    history_col.update_one(
        {"date": today_str}, 
        {"$set": {"date": today_str, "net_score": daily_score, "tasks": tasks_log}}, 
        upsert=True
    )
    print(f"Successfully logged data for {today_str}. Net Score: {daily_score}")

    print("Generating widget graph...")
    all_history = list(history_col.find().sort("date", 1))
    all_misc = list(misc_col.find().sort("date", 1))
    
    combined_data = {}
    
    for h in all_history:
        h_score = 0
        if 'tasks' in h and isinstance(h['tasks'], list):
            for t in h['tasks']:
                # is_due LOGIC RESTORED for historical calculations
                if t.get('is_due', True):
                    tw_data = current_weights.get(t.get('id'), {'pos': 1, 'neg': 1})
                    pw = tw_data.get('pos', t.get('pos_weight', 1))
                    nw = tw_data.get('neg', t.get('neg_weight', 1))
                    
                    if t.get('completed'): 
                        h_score += pw
                    else: 
                        h_score -= nw
            combined_data[h['date']] = h_score
        else:
            combined_data[h['date']] = h.get('net_score', 0)
            
    for m in all_misc:
        d = m['date']
        combined_data[d] = combined_data.get(d, 0) + m.get('score', 0)
        
    if combined_data:
        dates = sorted(list(combined_data.keys()))
        cumul = []
        current = 0
        for d in dates:
            current += combined_data[d]
            cumul.append(current)
            
        fig, ax = plt.subplots(figsize=(6, 3), facecolor='#0E1117')
        ax.set_facecolor('#0E1117')
        
        color = '#00cc96' if cumul[-1] >= 0 else '#ff4b4b'
        score_str = f"+{cumul[-1]}" if cumul[-1] > 0 else f"{cumul[-1]}"
        
        ax.plot(dates, cumul, color=color, linewidth=4)
        ax.fill_between(dates, cumul, 0, color=color, alpha=0.15)
        ax.axhline(y=0, color='white', alpha=0.15, linestyle='--')
        
        y_min, y_max = min(cumul + [0]), max(cumul + [0])
        y_range = y_max - y_min if y_max != y_min else 10
        ax.set_ylim(y_min - y_range * 0.15, y_max + y_range * 0.6)
        
        ax.text(0.04, 0.90, score_str, transform=ax.transAxes, color='white', 
                fontsize=34, fontweight='bold', va='top', ha='left')
        ax.text(0.04, 0.70, "CURRENT TRAJECTORY", transform=ax.transAxes, color='#A0A0A0', 
                fontsize=10, va='top', ha='left')
        
        ax.plot(dates[-1], cumul[-1], marker='o', color=color, markersize=6)
        ax.annotate(score_str, 
                    xy=(dates[-1], cumul[-1]), 
                    xytext=(0, 12),
                    textcoords="offset points",
                    ha='center', va='bottom',
                    color='white', fontsize=10, fontweight='bold',
                    bbox=dict(boxstyle="round,pad=0.4", fc="#2A2D35", ec="none", alpha=0.9))
        
        ax.axis('off')
        plt.tight_layout(pad=0)
        plt.savefig('widget.png', dpi=300, bbox_inches='tight', facecolor=fig.get_facecolor())
        print("Widget image saved to repository!")
else:
    print(f"Failed to fetch data. Status code: {response.status_code}")
    response.raise_for_status()
