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
        # --- WIDGET IMAGE GENERATOR ---
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
            score_str = f"+{cumul[-1]}" if cumul[-1] > 0 else f"{cumul[-1]}"
            
            # 1. Draw the thick main line
            ax.plot(dates, cumul, color=color, linewidth=4)
            
            # 2. Add the subtle fill/gradient under the line
            y_min, y_max = min(cumul), max(cumul)
            y_range = y_max - y_min if y_max != y_min else 10
            y_bottom = y_min - y_range * 0.1
            ax.fill_between(dates, cumul, y_bottom, color=color, alpha=0.15)
            
            # 3. Draw the zero-baseline
            ax.axhline(y=0, color='white', alpha=0.15, linestyle='--')
            
            # 4. Expand the top of the graph so the line doesn't crash into our text
            ax.set_ylim(y_bottom, y_max + y_range * 0.6)
            
            # 5. Large Top-Left Score Text
            ax.text(0.04, 0.90, score_str, transform=ax.transAxes, color='white', 
                    fontsize=34, fontweight='bold', va='top', ha='left')
                    
            # 6. Subtitle "CURRENT TRAJECTORY"
            ax.text(0.04, 0.70, "CURRENT TRAJECTORY", transform=ax.transAxes, color='#A0A0A0', 
                    fontsize=10, va='top', ha='left')
            
            # 7. Add the glowing dot at the very end of the line
            ax.plot(dates[-1], cumul[-1], marker='o', color=color, markersize=6)
            
            # 8. Add the rounded dark badge tooltip at the end
            ax.annotate(score_str, 
                        xy=(len(dates)-1, cumul[-1]), 
                        xytext=(0, 12), # Push it slightly above the dot
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

if __name__ == "__main__":
    fetch_and_update_history()