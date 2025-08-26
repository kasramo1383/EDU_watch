import json
import requests
from decouple import config
import time

# Load Telegram bot token
TELEGRAM_TOKEN = config("TELEGRAM_TOKEN")
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

# Private channel numeric ID (note the negative and 100 prefix)
CHANNEL_ID = -1002910685507

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
                line = f"\n- {info.get('Name', 'Unnamed')} (ID: {k})"
                dept_lines.append(line)
                if "changes" in info:
                    for field, vals in info["changes"].items():
                        old_val = fields.parse_value(field, vals['old'])
                        new_val = fields.parse_value(field, vals['new'])
                        dept_lines.append(
                            f"    {fields.parse_name(field)}: {old_val} -> {new_val}"
                        )

        render_group(added, "Added Courses", "🟢")
        render_group(removed, "Removed Courses", "🔴")
        render_group(updated, "Updated Courses", "🟡")

        messages.append("\n".join(dept_lines))

    return messages

class fields:
    NAMES = {
        'Lecturer': '👨‍🏫 استاد',
        'Capacity': '📊 ظرفیت',
        'Registered': '📈 ثبت نامی',
        'ExamDate': '📅 تاریخ آزمون',
        'ExamTime': '🕒 ساعت آزمون',
        'Sessions': '🗓️ برنامه هفتگی',
        'Info': '💬 توضیحات',
    }
    def parse_name(field: str) -> str:
        return fields.NAMES.get(field, field)
    
    def parse_value(field: str, value) -> str:
        PARSERS = {
            'Sessions': fields._parse_sessions,
        }
        return PARSERS.get(field, str)(value)
    
    def _parse_sessions(sessions: list) -> str:
        WEEKDAYS = ['شنبه', 'یکشنبه', 'دوشنبه', 'سه‌شنبه', 'چهارشنبه', 'پنجشنبه', 'جمعه']
        if not sessions:
            return 'null'
        first_st = sessions[0].get('start_time')
        first_et = sessions[0].get('end_time')
        if all(s.get('start_time') == first_st and s.get('end_time') == first_et
               for s in sessions):
            days = [WEEKDAYS[s.get('day_of_week')] for s in sessions]
            return ' و '.join(days) + f" از {first_st} تا {first_et}"
        else:
            parsed = []
            for session in sessions:
                day = WEEKDAYS[session.get('day_of_week')]
                st = session.get('start_time'); et = session.get('end_time')
                parsed.append(day + f" از {st} تا {et}")
            return '، '.join(parsed)


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
        payload = {"chat_id": CHANNEL_ID, "text": chunk}
        response = requests.post(TELEGRAM_API_URL, json=payload)
        response.raise_for_status()

# ----- Main function -----
def main():
    old_data = load_json(OLD_FILE)
    new_data = load_json(CURRENT_FILE)

    added, removed, updated = compare_courses(old_data, new_data)
    if not (added or removed or updated):
        return  # No changes — do not send anything

    messages = format_messages(added, removed, updated)
    for msg in messages:
        send_telegram_message(msg)
        time.sleep(0.5)  # slight delay to avoid flooding


if __name__ == "__main__":
    main()