import json
import logging
import re
import signal
import threading
import time
from contextlib import suppress
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Tuple

import requests
from bs4 import BeautifulSoup
from decouple import config
import send_updates

WATCHED_DEPARTMENTS: Dict[int, str] = {
	20: "مهندسی_عمران",
	21: "مهندسی_صنایع",
	 22: "علوم_ریاضی",
	23: "شیمی",
	24: "فیزیک",
	 25: "مهندسی_برق",
	26: "مهندسی_شیمی_و_نفت",
	27: "مهندسی_و_علم_مواد",
	28: "مهندسی_مکانیک",
	29: "پژوهشکده_سیاست‏گذاری_علم،_فناوری_و_صنعت",
	30: "مرکز_تربیت_بدنی",
	31: "مرکز_زبان‌ها_و_زبان‌شناسی",
	33: "مرکز_آموزش_مهارت‌های_مهندسی",
	34: "پژوهشکده_علوم_و_فن‌آوری_انرژی،_آب_و_محیط_زیست",
	35: "مرکز_گرافیک_(مرکز_آموزش_مهارت‌های_مهندسی)",
	37: "مرکز_معارف_اسلامی_و_علوم_انسانی",
	38: "بیوشیمی",
	39: "پژوهشکده_الکترونيک",
	 40: "مهندسی_کامپیوتر",
	41: "گروه_برنامه‌ریزی_سیستم‌ها",
	42: "گروه_فلسفه_علم",
	43: "مهندسی_سیستم‌های_انرژی",
	44: "مدیریت_و_اقتصاد",
	45: "مهندسی_هوافضا",
	46: "مهندسی_انرژی",
	47: "پژوهشکده_فناوری_اطلاعات_و_ارتباطات_پیشرفته",
	48: "پژوهشکده_علوم_و_فن‌آوری_نانو",
	49: "طرح_مهمان_تکدرس",
	50: "دروس_پایه_و_عمومی_(پردیس_کیش)",
	51: "مهندسی_صنایع_(پردیس_کیش)",
	52: "مهندسی_کامپیوتر_(پردیس_کیش)",
	53: "مهندسی_عمران_(پردیس_کیش)",
	54: "مدیریت_(پردیس_کیش)",
	55: "مهندسی_برق_(پردیس_کیش)",
	56: "مهندسی_نانوفناوری_(پردیس_کیش)",
	57: "مهندسی_مواد_(پردیس_کیش)",
	58: "مهندسی_مکانیک_(پردیس_کیش)",
	59: "زبان‌ها_و_زبان‌شناسی_(پردیس_کیش)",
	61: "طرح_مهمان_تک_درس_(پردیس_کیش)",
	65: "مهندسی_هوافضا_(پردیس_کیش)",
	66: "مهندسی_شیمی_و_نفت_(پردیس_کیش)",
	70: "دروس_پایه_و_عمومی_(پردیس_تهران)",
	71: "طرح_مهمان_تک_درس_(پردیس_تهران)",
	73: "مهندسی_عمران_(پردیس_تهران)",
	76: "مهندسی_نفت_(پردیس_تهران)",
	77: "مهندسی_مواد_(پردیس_تهران)",
	78: "مهندسی_مکانیک_(پردیس_تهران)",
	79: "مهندسی_مکاترونیک_(پردیس_تهران)",
	80: "مهندسی_فناوری_اطلاعات_(پردیس_تهران)",
	81: "مهندسی_کامپیوتر(پردیس_تهران)",
}

DAY_OF_WEEK_MAP = {
    "شنبه": 0,
    "یکشنبه": 1,
    "دوشنبه": 2,
    "سه شنبه": 3,
    "چهارشنبه": 4,
    "پنجشنبه": 5,
    "جمعه": 6,
}

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36"
)

EDU_USERNAME = config('EDU_USERNAME')
EDU_PASSWORD = config('EDU_PASSWORD')
PERIOD = config('PERIOD')
OUTPUT_FILE = "courses_output.json"
ARCHIVE_PATH = "archive"

logger = logging.getLogger("edu_scraper")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")

# in-memory courses store: key -> Course
COURSES: Dict[str, "Course"] = {}

# HTTP session (requests.Session), created in login()
http_session: Optional[requests.Session] = None

stop_event = threading.Event()


# -----------------------
# Data classes & errors
# -----------------------
@dataclass
class CourseSession:
    day_of_week: int
    start_time: str
    end_time: str


@dataclass
class Course:
    Code: str = ""
    Group: int = 0
    Name: str = ""
    Lecturer: str = ""
    Capacity: int = 0
    Registered: int = 0
    Units: int = 0
    ExamDate: Optional[str] = None
    ExamTime: Optional[str] = None
    Sessions: List[CourseSession] = field(default_factory=list)
    Info: Optional[str] = None
    Department: str = ""
    DepartmentCode: int = 0
    Grade: str = ""
    Year: int = 0
    Semester: int = 0


class StatusCodeError(Exception):
    def __init__(self, code: int):
        super().__init__(f"unexpected status code {code}")
        self.code = code


def is_server_error(err: Exception) -> bool:
    return isinstance(err, StatusCodeError) and err.code >= 500


def trim_and_nil_if_empty(s: Optional[str]) -> Optional[str]:
    if s is None:
        return None
    t = s.strip()
    return t if t != "" else None


# -----------------------
# Parsers
# -----------------------
def fix_time_format(time_str: str) -> str:
    parts = time_str.split(":")
    if len(parts) == 2:
        h, m = parts
        if len(h) == 1:
            h = "0" + h
        if len(m) == 1:
            m = m + "0"
        return f"{h}:{m}"
    return time_str


def parse_exam_date_time(input_str: str) -> Tuple[Optional[str], Optional[str]]:
    # regex: date (non-space) followed by optional time HH:MM
    rexp = re.compile(r"(?P<date>\S+)\s*(?P<time>\d{2}:\d{2})")
    m = rexp.search(input_str or "")
    if not m:
        return None, None
    return m.group("date"), m.group("time")


def parse_course_session(input_str: str) -> List[CourseSession]:
    # Regex:
    # (?P<days>[^\d]+) از (?P<start>\d{1,2}:\d{1,2}) تا (?P<end>\d{1,2}:\d{1,2})
    pattern = re.compile(r"(?P<days>[^\d]+) از (?P<start>\d{1,2}:\d{1,2}) تا (?P<end>\d{1,2}:\d{1,2})")
    matches = pattern.finditer(input_str or "")
    sessions: List[CourseSession] = []
    for m in matches:
        days_raw = m.group("days")
        start = fix_time_format(m.group("start"))
        end = fix_time_format(m.group("end"))
        days = [d.strip() for d in days_raw.split(" و ")]
        for day in days:
            if day in DAY_OF_WEEK_MAP:
                sessions.append(CourseSession(day_of_week=DAY_OF_WEEK_MAP[day], start_time=start, end_time=end))
    return sessions


def is_login(body_bytes: bytes) -> bool:
    return b"https://accounts.sharif.edu/cas/login?service=https://edu.sharif.edu/login.jsp" in body_bytes


# -----------------------
# HTTP helpers & flows
# -----------------------
def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT})
    # do not verify SSL changes here; we rely on requests defaults
    return s


def get_with_ctx(session: requests.Session, url: str, method: str = "GET", data=None, allow_redirects: bool = True, timeout: int = 30) -> requests.Response:
    if method.upper() == "POST":
        return session.post(url, data=data, allow_redirects=allow_redirects, timeout=timeout)
    return session.get(url, allow_redirects=allow_redirects, timeout=timeout)


def login(ctx_stop: threading.Event) -> None:
    """
    Performs login flow and warmup. Raises exceptions on failure.
    On success: sets http_session global.
    """
    global http_session, EDU_USERNAME, EDU_PASSWORD

    s = make_session()
    logger.debug("Attempting initial GET to edu root")
    # initial GET
    resp = get_with_ctx(s, "https://edu.sharif.edu/", allow_redirects=True)
    if resp.status_code != 200:
        raise StatusCodeError(resp.status_code)
    # read body (ignored)
    _ = resp.content

    # do login POST
    payload = {
        "username": EDU_USERNAME,
        "password": EDU_PASSWORD,
        "jcaptcha": "ab",
        "command": "login",
        "captcha_key_name": "ab",
        "captchaStatus": "ab",
    }
    # small sleep to mimic Go's time.Sleep(time.Second)
    time.sleep(1)
    resp = get_with_ctx(s, "https://edu.sharif.edu/login.do", method="POST", data=payload, allow_redirects=True)
    body = resp.content
    if "خروج".encode('utf-8') not in body:
        raise RuntimeError("body is invalid (login probably failed)")
    # if login successful set global session
    http_session = s
    # run warmup
    warm_up(ctx_stop)


def warm_up(ctx_stop: threading.Event) -> None:
    """
    performs the sequence: action.do and register.do with changeMenu
    """
    if http_session is None:
        raise RuntimeError("http session not initialized")

    # Open the menu
    resp = get_with_ctx(http_session, "https://edu.sharif.edu/action.do",
                        method="POST",
                        data={"changeMenu": "OnlineRegistration", "isShowMenu": "", "commandMessage": "", "defaultCss": ""})
    if resp.status_code != 200:
        raise StatusCodeError(resp.status_code)
    if is_login(resp.content):
        raise RuntimeError("redirected to login page")

    # Change to courses
    resp = get_with_ctx(http_session, "https://edu.sharif.edu/register.do",
                        method="POST",
                        data={"changeMenu": "OnlineRegistration*OfficalLessonListShow", "isShowMenu": ""})
    if resp.status_code != 200:
        raise StatusCodeError(resp.status_code)
    if is_login(resp.content):
        raise RuntimeError("redirected to login page")


def check_diff(ctx_stop: threading.Event, department_id: int, department_name: str) -> int:
    """
    POST to register.do with depID and parse resulting HTML table(s)
    Returns number of courses parsed for that department.
    """
    global http_session, COURSES
    if http_session is None:
        raise RuntimeError("not logged in")

    # Build POST payload like Go
    payload = {
        "level": "0",
        "teacher_name": "",
        "sort_item": "1",
        "depID": str(department_id),
    }
    resp = get_with_ctx(http_session, "https://edu.sharif.edu/register.do", method="POST", data=payload)
    if resp.status_code != 200:
        raise StatusCodeError(resp.status_code)

    body = resp.content
    # check login page
    if is_login(body):
        raise RuntimeError("redirected to login page")

    soup = BeautifulSoup(body, "html.parser")

    # Find the header to extract semester/year
    year = 0
    semester = 0
    header_td = soup.select_one("td.header[colspan='13']")
    if header_td:
        text = header_td.get_text(strip=True)
        # Re: `نیمسال (\S+) (\d{4})-(\d{4})`
        m = re.search(r"نیمسال (\S+) (\d{4})-(\d{4})", text)
        if m:
            semester_text = m.group(1)
            # year is second group (end year in Go)
            year = int(m.group(3))
            if semester_text == "اول":
                semester = 1
            elif semester_text == "دوم":
                semester = 2
            else:
                semester = 3

    courses_got = 0

    # iterate .contentTable elements
    for table in soup.select(".contentTable"):
        # determine grade by checking first tr in tbody
        grade = "bs"
        tbody_first_tr = table.select_one("tbody tr")
        if tbody_first_tr:
            # combine td texts of first row to see keywords
            first_row_text = " ".join(td.get_text(strip=True) for td in tbody_first_tr.select("td"))
            if "کارشناسی ارشد" in first_row_text:
                grade = "ms"
            elif "دکترا" in first_row_text:
                grade = "phd"

        # iterate each row
        for row in table.select("tr"):
            # We'll collect columns; skip rows where first column is not an integer
            tds = row.select("td")
            if not tds:
                continue
            first_text = tds[0].get_text(strip=True)
            if not first_text.isdigit():
                continue

            c = Course()
            # ensure default values
            for i, td in enumerate(tds):
                text = td.get_text(strip=True)
                if i == 0:
                    c.Code = text
                elif i == 1:
                    with suppress(ValueError):
                        c.Group = int(text)
                elif i == 2:
                    with suppress(ValueError):
                        c.Units = int(text)
                elif i == 3:
                    c.Name = text
                elif i == 5:
                    with suppress(ValueError):
                        c.Capacity = int(text)
                elif i == 6:
                    with suppress(ValueError):
                        c.Registered = int(text)
                elif i == 7:
                    c.Lecturer = text
                elif i == 8:
                    exam_date, exam_time = parse_exam_date_time(text)
                    c.ExamDate = trim_and_nil_if_empty(exam_date)
                    c.ExamTime = trim_and_nil_if_empty(exam_time)
                elif i == 9:
                    c.Sessions = parse_course_session(text)
                elif i == 11:
                    c.Info = trim_and_nil_if_empty(text)

            c.Grade = grade
            c.Year = year
            c.Semester = semester
            c.Department = department_name.replace("_", " ")
            c.DepartmentCode = department_id

            key = f"{c.Code}-{c.Group}"
            COURSES[key] = c
            courses_got += 1

    return courses_got


# -----------------------
# Main Start loop
# -----------------------
def start_once(ctx_stop: threading.Event) -> None:
    """
    Performs a single scraping pass (Login -> WarmUp -> CheckDiff all departments).
    Returns normally on success; raises on fatal errors.
    """
    # Attempt login; keep single try (it breaks on any error)
    try:
        login(ctx_stop)
    except Exception as e:
        logger.error("cannot login: %s", e)
        raise

    logger.info("login done")

    # iterate departments
    for dep_id, dep_name in WATCHED_DEPARTMENTS.items():
        logger.info("getting courses of %d", dep_id)
        try:
            got_courses = check_diff(ctx_stop, dep_id, dep_name)
            logger.info("scraped department %d with %d courses", dep_id, got_courses)
        except Exception as e:
            logger.error("cannot get the courses for %d: %s", dep_id, e)
            raise
        # sleep 25 seconds
        for _ in range(25):
            if ctx_stop.is_set():
                raise RuntimeError("context cancelled")
            time.sleep(1)

    logger.info("currently have %d courses", len(COURSES))


def parse_duration_string(s: str) -> float:
    """
    Very small parser for durations like "30s", "1m", "2h" etc.
    Returns seconds as float.
    """
    s = s.strip()
    if s.endswith("ms"):
        return float(s[:-2]) / 1000.0
    if s.endswith("s"):
        return float(s[:-1])
    if s.endswith("m") and not s.endswith("ms"):
        return float(s[:-1]) * 60.0
    if s.endswith("h"):
        return float(s[:-1]) * 3600.0
    # fallback: assume seconds
    try:
        return float(s)
    except ValueError:
        raise ValueError(f"invalid period format: {s}")


import os

def save_courses_to_file():
    """Save the current COURSES data to a JSON file, keeping the previous file as '... - old.json'"""
    try:
        # If the output file already exists, rename it
        if os.path.exists(OUTPUT_FILE):
            old_file = OUTPUT_FILE.replace(".json", " - old.json")
            # Remove any existing old file to avoid errors
            if os.path.exists(old_file):
                os.remove(old_file)
            os.rename(OUTPUT_FILE, old_file)

        # Convert dataclasses to dictionaries
        out = {}
        for k, v in COURSES.items():
            course_dict = asdict(v)
            # Convert CourseSession objects to dictionaries
            course_dict["Sessions"] = [asdict(session) for session in v.Sessions]
            out[k] = course_dict

        # Make archive entry
        try:
            os.makedirs(ARCHIVE_PATH, exist_ok=True)
            timestamp = time.strftime("%Y-%m-%d_%H-%M-%S")
            archive_file = os.path.join(ARCHIVE_PATH, f"{timestamp}.json")

            with open(archive_file, 'w', encoding='utf-8') as f:
                json.dump(out, f, ensure_ascii=False, indent=2)

            logger.info("Archived snapshot saved as %s", archive_file)
        except Exception as e:
            logger.error("Failed to save archive snapshot: %s", e)

        # Write to file
        with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
            json.dump(out, f, ensure_ascii=False, indent=2)

        logger.info("Courses data saved to %s (previous file moved to '... - old.json')", OUTPUT_FILE)

        send_updates.main()
        logger.info("Invoked send_updates.main() to check for differences and call Telegram API")

        return True
    except Exception as e:
        logger.error("Failed to save courses to file: %s", e)
        return False


# -----------------------
# CLI / main
# -----------------------
def main():
    global EDU_USERNAME, EDU_PASSWORD, COURSES, OUTPUT_FILE

    # handle OS interrupt nicely
    def sigint_handler(sig, frame):
        logger.info("received interrupt, shutting down")
        stop_event.set()
        # Save courses before exiting
        # save_courses_to_file()

    signal.signal(signal.SIGINT, sigint_handler)
    signal.signal(signal.SIGTERM, sigint_handler)

    # run Start immediately
    logger.info("Running Start immediately")
    try:
        start_once(stop_event)
        save_courses_to_file()
    except Exception as e:
        logger.error("Start error: %s", e)
        # save_courses_to_file()

    logger.info("Shutting down")
    # save_courses_to_file()


if __name__ == "__main__":
    main()