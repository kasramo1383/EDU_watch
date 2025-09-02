import json
import os
from datetime import datetime
import requests
from decouple import config
import time
from fields import parse_name, parse_value

# Load Telegram bot token
TELEGRAM_TOKEN = config("TELEGRAM_TOKEN")
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

# Private channel numeric ID
CHANNEL_ID = -1002910685507
# Test channel:
# CHANNEL_ID = -1002914784215

# Files
CURRENT_FILE = "courses_output.json"
OLD_FILE = "courses_output - old.json"

# ----- JSON comparison -----
def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def compare_courses(old_data, new_data):
    old_keys = set(old_data.keys())
    new_keys = set(new_data.keys())

    added_keys = new_keys - old_keys
    removed_keys = old_keys - new_keys
    common_keys = old_keys & new_keys

    def group_by_department(keys, source_data):
        grouped = {}
        for k in keys:
            dept = source_data[k].get("Department", "Unknown")
            if dept not in grouped:
                grouped[dept] = {}
            grouped[dept][k] = source_data[k]
        return grouped

    added = group_by_department(added_keys, new_data)
    removed = group_by_department(removed_keys, old_data)

    # For updated, only store the changed fields
    updated_temp = {}
    for k in common_keys:
        if new_data[k] != old_data[k]:
            changes = {}
            for field in new_data[k]:
                if field in old_data[k] and new_data[k][field] != old_data[k][field]:
                    changes[field] = {"old": old_data[k][field], "new": new_data[k][field]}
            if changes:
                updated_temp[k] = {"changes": changes, "Department": new_data[k].get("Department", "Unknown"), "name": new_data[k].get('Name', 'Unknown')}

    # Group updates by department
    updated = {}
    for k, val in updated_temp.items():
        dept = val["Department"]
        if dept not in updated:
            updated[dept] = {}
        updated[dept][k] = {
            "Name": val["name"],
            "changes": val["changes"]
        }

    return added, removed, updated

def format_messages(added, removed, updated):
    messages = []

    # collect all departments across all groups
    departments = set(added.keys()) | set(removed.keys()) | set(updated.keys())

    for dept in sorted(departments):
        dept_lines = [f"🏛️ {dept}:"]  # Department header

        # helper to render a single group inside a dept
        def render_group(group, title, emoji):
            courses = group.get(dept, {})
            if not courses:
                return
            dept_lines.append(f"{emoji} {title}:")
            for k, info in courses.items():
                line = f"- {info.get('Name', 'Unnamed')} (ID: {k})"
                dept_lines.append(line)
                if "changes" in info:
                    for field, vals in info["changes"].items():
                        old_val = parse_value(field, vals['old'])
                        new_val = parse_value(field, vals['new'])
                        dept_lines.append(
                            f"    {parse_name(field)}: {old_val} ◀️ {new_val}"
                        )
                dept_lines.append('')

        render_group(added, "Added Courses", "🟢")
        render_group(removed, "Removed Courses", "🔴")
        render_group(updated, "Updated Courses", "🟡")

        messages.append("\n".join(dept_lines))

    return messages

# ----- Telegram sending -----
MAX_LENGTH = 4000  # safe margin below 4096

def send_telegram_message(text):
    # Split text into chunks if too long
    chunks = []
    while text:
        if len(text) <= MAX_LENGTH:
            chunks.append(text)
            break
        # try to split at newline for readability
        split_pos = text.rfind("\n", 0, MAX_LENGTH)
        if split_pos == -1:
            split_pos = MAX_LENGTH
        chunks.append(text[:split_pos])
        text = text[split_pos:].lstrip("\n")
    
    for chunk in chunks:
        payload = {"chat_id": CHANNEL_ID, "text": chunk, "parse_mode": "HTML"}
        response = requests.post(TELEGRAM_API_URL, json=payload)
        response.raise_for_status()

def send_markdown(text):
    payload = {"chat_id": CHANNEL_ID, "text": text, "parse_mode": "MarkdownV2"}
    response = requests.post(TELEGRAM_API_URL, json=payload)
    response.raise_for_status()

# ----- Main function -----
def main(logger=None):
    if not logger:
        import logging
        logger = logging.getLogger("edu_scraper")
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
    # Get modification times before loading files
    try:
        old_mtime = os.path.getmtime(OLD_FILE)
        old_time_str = datetime.fromtimestamp(old_mtime).strftime("%Y-%m-%d %H:%M:%S")
    except FileNotFoundError:
        old_time_str = "N/A (file not found)"
    
    try:
        new_mtime = os.path.getmtime(CURRENT_FILE)
        new_time_str = datetime.fromtimestamp(new_mtime).strftime("%Y-%m-%d %H:%M:%S")
    except FileNotFoundError:
        new_time_str = "N/A (file not found)"
    
    # Load the data
    old_data = load_json(OLD_FILE)
    new_data = load_json(CURRENT_FILE)

    added, removed, updated = compare_courses(old_data, new_data)

    if not (added or removed or updated):
        logger.info("No changes detected between this session and the previous one. Will not send any message")
        return  # No changes — do not send anything
    logger.info("Detected updates, sending messages via Telegram API")
    # Send time range message first
    time_range_msg = f"```Time [{old_time_str}] ➡️ [{new_time_str}] ```"
    send_markdown(time_range_msg)
    time.sleep(0.5)
    
    # Send the actual update messages
    messages = format_messages(added, removed, updated)
    for msg in messages:
        send_telegram_message(msg)
        time.sleep(0.5)  # slight delay to avoid flooding

if __name__ == "__main__":
    main()