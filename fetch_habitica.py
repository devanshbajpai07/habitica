import requests
import os
from pymongo import MongoClient
from datetime import datetime
from dotenv import load_dotenv
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

# Load environment variables (for local testing)
load_dotenv()

# --- Configuration ---
USER_ID = os.getenv("USER_ID")
API_TOKEN = os.getenv("API_TOKEN")
CLIENT_ID = f"{USER_ID}-PAS"

HEADERS = {
    "x-api-user": USER_ID,
    "x-api-key": API_TOKEN,
    "x-client": CLIENT_ID
}

# Pulling URLs from the .env file with fallback defaults
HABITICA_TASKS_URL = os.getenv("HABITICA_API_URL")
HABITICA_TAGS_URL = os.getenv("HABITICA_TAGS_URL")

# Updated to match your GitHub Secret (MONGO_URL)
MONGO_URI = os.getenv("MONGO_URL", os.getenv("MONGO_URL"))

def fetch_and_update_history():
    print("Connecting to MongoDB Atlas...")
    client = MongoClient(MONGO_URI)
    db = client.pas_database
    history_col = db.history
    weights_col = db.weights

    # Fetch current weights
    weights_doc = weights_col.find_one({"_id": "current_weights"})
    task_weights = weights_doc.get("weights", {}) if weights_doc else {}

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
            
            raw_tags = task.get("tags", [])
            real_tag_names = [tag_map.get(tid, tid) for tid in raw_tags]
            
            # --- ASYMMETRIC WEIGHT LOGIC ---
            weight_data = task_weights.get(task_id, 1) 
            
            if isinstance(weight_data, dict):
                pos_weight = weight_data.get("pos", 1)
                neg_weight = weight_data.get("neg", 1)
            else:
                pos_weight = weight_data
                neg_weight = weight_data
            
            if is_due:
                if completed:
                    daily_score += pos_weight
                else:
                    daily_score -= neg_weight # <--- This is the exact line that caused the crash!
                
            tasks_log.append({
                "id": task_id,
                "title": task.get("text"),
                "completed": completed,
                "tags": real_tag_names,
                "pos_weight": pos_weight,
                "neg_weight": neg_weight,
                "is_due": is_due
            })

        today_str = datetime.now().strftime('%Y-%m-%d')
        history_col.update_one(
            {"date": today_str}, 
            {"$set": {"date": today_str, "net_score": daily_score, "tasks": tasks_log}}, 
            upsert=True
        )
        print(f"Successfully logged data for {today_str}. Net Score: {daily_score}")
        print("Generating widget graph...")
        all_data = list(history_col.find().sort("date", 1))
        
        if all_data:
            dates = [d['date'] for d in all_data]
            scores = [d['net_score'] for d in all_data]
            
            cumul = []
            current = 0
            for s in scores:
                current += s
                cumul.append(current)
                
            fig, ax = plt.subplots(figsize=(6, 3), facecolor='#0E1117')
            ax.set_facecolor('#0E1117')
            
            color = '#00cc96' if cumul[-1] >= 0 else '#ff4b4b'
            
            ax.plot(dates, cumul, color=color, linewidth=5)
            ax.axhline(y=0, color='white', alpha=0.15, linestyle='--')
            
            ax.axis('off')
            plt.tight_layout(pad=0)
            
            plt.savefig('widget.png', dpi=300, bbox_inches='tight', facecolor=fig.get_facecolor())
            print("Widget image saved to repository!")
    else:
        print(f"Failed to fetch data. Status code: {response.status_code}")
        response.raise_for_status()

if __name__ == "__main__":
    fetch_and_update_history()