import requests
from datetime import datetime
from pymongo import MongoClient
import os
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
HABITICA_API_URL = os.getenv("HABITICA_API_URL")

# --- MongoDB Configuration ---
# Replace with your actual MongoDB Atlas connection string
MONGO_URI = os.getenv("MONGO_URL") 

def fetch_and_update_history():
    print("Connecting to MongoDB Atlas...")
    client = MongoClient(MONGO_URI)
    db = client.pas_database
    history_col = db.history
    weights_col = db.weights

    print("Fetching tasks from Habitica...")
    response = requests.get(HABITICA_API_URL, headers=HEADERS)
    if response.status_code != 200:
        print(f"Failed to fetch API. Status: {response.status_code}")
        print(f"Error Details: {response.text}")
        return

    dailies = response.json().get("data", [])
    
    # Load dynamically assigned weights from MongoDB
    weights_doc = weights_col.find_one({"_id": "current_weights"})
    task_weights = weights_doc.get("weights", {}) if weights_doc else {}

    daily_score = 0
    tasks_log = []

    for task in dailies:
        task_id = task.get("id")
        completed = task.get("completed", False)
        tags = task.get("tags", [])
        is_due = task.get("isDue", False)
        
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
            "tags": tags,
            "weight": weight,
            "is_due": is_due
        })

    today_str = datetime.now().strftime('%Y-%m-%d')
    
    record = {
        "date": today_str,
        "net_score": daily_score,
        "tasks": tasks_log
    }
    
    # Upsert ensures that if you run the script twice today, it updates today's entry instead of duplicating it
    history_col.update_one({"date": today_str}, {"$set": record}, upsert=True)
    
    total_days = history_col.count_documents({})
    print(f"Saved data for {today_str}. Net Score: {daily_score}")
    print(f"Database currently holds {total_days} days of records.")

fetch_and_update_history()