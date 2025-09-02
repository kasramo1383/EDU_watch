NAMES: dict[str, str] = {
        'Name': '🪧 نام درس',
        'Lecturer': '👨‍🏫 استاد',
        'Capacity': '📊 ظرفیت',
        'Registered': '📈 ثبت نامی',
        'ExamDate': '📅 تاریخ آزمون',
        'ExamTime': '🕒 ساعت آزمون',
        'Sessions': '🗓️ برنامه هفتگی',
        'Info': '💬 توضیحات',
        # Unlikely to change:
        'Code': 'کد درس',
        'Group': 'گروه درس',
        'Units': 'واحد',
        'Year': 'سال',
        'Semester': 'ترم',
        'Units': 'واحد',
        'Department': 'دانشکده',
        'DepartmentCode': 'کد دانشکده',
        'Grade': 'مقطع',
    }


def parse_name(field: str) -> str:
        return NAMES.get(field, field)
    
def parse_value(field: str, value) -> str:
    def none(value: str) -> str:
        if value is None or value == '':
            return 'تعریف نشده'
        return value
    
    PARSERS = {
        'Sessions': _parse_sessions,
    }
    return PARSERS.get(field, none)(value)

def _parse_sessions(sessions: list) -> str:
    WEEKDAYS = ['شنبه', 'یکشنبه', 'دوشنبه', 'سه‌شنبه', 'چهارشنبه', 'پنجشنبه', 'جمعه']
    if not sessions:
        return 'تعریف نشده'
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