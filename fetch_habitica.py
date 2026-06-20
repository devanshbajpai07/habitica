import requests
import os
from datetime import datetime
from pymongo import MongoClient
from dotenv import load_dotenv

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
HABITICA_TASKS_URL = os.getenv("HABITICA_API_URL")
HABITICA_TAGS_URL = os.getenv("HABITICA_TAGS_URL")

MONGO_URI = os.getenv("MONGO_URL")

def fetch_and_update_history():
    print("Connecting to MongoDB Atlas...")
    client = MongoClient(MONGO_URI)
    db = client.pas_database
    history_col = db.history
    weights_col = db.weights

    # 1. Fetch Real Tag Names
    print("Fetching tags from Habitica...")
    tags_response = requests.get(HABITICA_TAGS_URL, headers=HEADERS)
    tag_map = {}
    if tags_response.status_code == 200:
        for t in tags_response.json().get("data", []):
            tag_map[t["id"]] = t["name"]

    # 2. Fetch Tasks
    print("Fetching tasks from Habitica...")
    response = requests.get(HABITICA_TASKS_URL, headers=HEADERS)
    if response.status_code != 200:
        print(f"Failed to fetch API. Status: {response.status_code}")
        return

    dailies = response.json().get("data", [])
    
    weights_doc = weights_col.find_one({"_id": "current_weights"})
    task_weights = weights_doc.get("weights", {}) if weights_doc else {}

    daily_score = 0
    tasks_log = []

    for task in dailies:
        task_id = task.get("id")
        completed = task.get("completed", False)
        is_due = task.get("isDue", False)
        
        # Translate UUIDs to Real Names using our tag_map
        raw_tags = task.get("tags", [])
        real_tag_names = [tag_map.get(tid, tid) for tid in raw_tags]
        
        weight = task_weights.get(task_id, 1) 
        
        if is_due:
            if completed:
                daily_score += weight
            else:
                daily_score -= weight
            
        tasks_log.append({
            "id": task_id,
            "title": task.get("text"),
            "completed": completed,
            "tags": real_tag_names, # Save the real names!
            "weight": weight,
            "is_due": is_due
        })

    today_str = datetime.now().strftime('%Y-%m-%d')
    record = {
        "date": today_str,
        "net_score": daily_score,
        "tasks": tasks_log
    }
    
    history_col.update_one({"date": today_str}, {"$set": record}, upsert=True)
    
    total_days = history_col.count_documents({})
    print(f"Saved data for {today_str}. Net Score: {daily_score}")
    print(f"Database currently holds {total_days} days of records.")

fetch_and_update_history()