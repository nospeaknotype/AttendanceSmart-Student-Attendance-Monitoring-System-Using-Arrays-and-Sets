"""AttendanceSmart: school attendance dashboard with rule-based attendance insights.

Flask backend + SQLite database. No machine learning claims: insights use clear rules.
Student rows are handled as arrays/lists; attendance status groups use Python sets.
"""

from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
import os
import re
import sqlite3

from flask import Flask, g, jsonify, render_template, request

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get('ATTENDANCESMART_DB', str(BASE_DIR / 'attendancesmart.db')))
app = Flask(__name__)
app.json.sort_keys = False
STATUSES = {'Present', 'Late', 'Absent', 'Excused'}
DAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']


def get_db():
    if 'db' not in g:
        db = sqlite3.connect(DB_PATH)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        g.db = db
    return g.db


@app.teardown_appcontext
def close_db(_error=None):
    db = g.pop('db', None)
    if db is not None:
        db.close()


def initialize_database():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with app.app_context():
        db = get_db()
        db.executescript('''
          CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_no TEXT UNIQUE NOT NULL COLLATE NOCASE,
            name TEXT NOT NULL,
            section TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (date('now'))
          );
          CREATE TABLE IF NOT EXISTS attendance (
            student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
            attendance_date TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('Present','Late','Absent','Excused')),
            checkin_time TEXT,
            PRIMARY KEY (student_id, attendance_date)
          );
          CREATE TABLE IF NOT EXISTS schedule (
            weekday INTEGER PRIMARY KEY CHECK (weekday BETWEEN 0 AND 6),
            enabled INTEGER NOT NULL DEFAULT 0,
            start_time TEXT NOT NULL DEFAULT '08:00'
          );
          CREATE TABLE IF NOT EXISTS config (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
          );
        ''')
        for wd in range(7):
            db.execute('INSERT OR IGNORE INTO schedule(weekday,enabled,start_time) VALUES(?,?,?)',
                       (wd, 1 if wd < 5 else 0, '08:00'))
        db.execute("INSERT OR IGNORE INTO config(key,value) VALUES('grace_minutes','10')")
        db.commit()


def api_error(message, code=400):
    return jsonify({'error': message}), code


def parse_date(text):
    if not isinstance(text, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', text):
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def parse_time(text):
    if text is None or text == '':
        return None
    if not isinstance(text, str) or not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', text):
        raise ValueError('Enter a valid time (HH:MM).')
    return text


def payload():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def clean_text(value, title, limit=80, required=True):
    if not isinstance(value, str):
        raise ValueError(f'{title} must be text.')
    cleaned = ' '.join(value.split())
    if required and not cleaned:
        raise ValueError(f'Enter {title.lower()}.')
    if len(cleaned) > limit:
        raise ValueError(f'{title} must be {limit} characters or fewer.')
    return cleaned


def schedule_settings(db):
    items = [dict(x) for x in db.execute('SELECT weekday, enabled, start_time FROM schedule ORDER BY weekday')]
    grace = int(db.execute("SELECT value FROM config WHERE key='grace_minutes'").fetchone()['value'])
    return {'days': [{**item, 'name': DAYS[item['weekday']], 'enabled': bool(item['enabled'])} for item in items], 'grace_minutes': grace}


def normalize_attendance_status(db, day, status, time):
    # Present check-ins after the class start plus the grace period are automatically late.
    if status == 'Present' and time:
        settings = schedule_settings(db)
        sched = settings['days'][day.weekday()]
        if sched['enabled']:
            start = datetime.strptime(sched['start_time'], '%H:%M')
            limit = start + timedelta(minutes=settings['grace_minutes'])
            actual = datetime.strptime(time, '%H:%M')
            if actual > limit:
                return 'Late'
    return status


def rows_for_day(db, day):
    return [dict(row) for row in db.execute('''
        SELECT s.id, s.student_no, s.name, s.section, a.status, a.checkin_time
        FROM students s LEFT JOIN attendance a
          ON a.student_id=s.id AND a.attendance_date=?
        ORDER BY s.name COLLATE NOCASE, s.id
    ''', (day,))]


def daily_summary(rows):
    # Python sets apply the Arrays and Sets project concept directly.
    roster = {row['id'] for row in rows}
    present_set = {row['id'] for row in rows if row['status'] == 'Present'}
    late_set = {row['id'] for row in rows if row['status'] == 'Late'}
    absent_set = {row['id'] for row in rows if row['status'] == 'Absent'}
    excused_set = {row['id'] for row in rows if row['status'] == 'Excused'}
    marked_set = present_set | late_set | absent_set | excused_set
    unmarked_set = roster - marked_set
    assert not (present_set & absent_set)
    # Excused and unmarked rows are not treated as attended classes or absent classes.
    counted = len(present_set | late_set | absent_set)
    rate = round(100 * len(present_set | late_set) / counted, 1) if counted else None
    return {'total': len(roster), 'present': len(present_set), 'late': len(late_set),
            'absent': len(absent_set), 'excused': len(excused_set),
            'unmarked': len(unmarked_set), 'attendance_rate': rate,
            'marked': len(marked_set)}


def week_data(db, target):
    start = target - timedelta(days=target.weekday())
    result = []
    for i in range(5):
        day = start + timedelta(days=i)
        rows = rows_for_day(db, day.isoformat())
        summary = daily_summary(rows)
        result.append({'date': day.isoformat(), 'label': day.strftime('%a'),
                       'rate': summary['attendance_rate'] if day <= target else None,
                       'marked': summary['marked'] if day <= target else 0})
    return result


def reports_data(db, target):
    since = (target - timedelta(days=29)).isoformat()
    until = target.isoformat()
    students = [dict(x) for x in db.execute('SELECT id,student_no,name,section FROM students ORDER BY name COLLATE NOCASE')]
    data = db.execute('''
        SELECT student_id, attendance_date, status FROM attendance
        WHERE attendance_date BETWEEN ? AND ? ORDER BY attendance_date
    ''', (since, until)).fetchall()
    by_student = defaultdict(list)
    for row in data:
        by_student[row['student_id']].append(dict(row))
    report_rows = []
    for student in students:
        records = by_student[student['id']]
        counts = {s: sum(1 for r in records if r['status'] == s) for s in STATUSES}
        counted = counts['Present'] + counts['Late'] + counts['Absent']
        rate = round(100 * (counts['Present'] + counts['Late']) / counted, 1) if counted else None
        report_rows.append({**student, 'present': counts['Present'], 'late': counts['Late'],
                            'absent': counts['Absent'], 'excused': counts['Excused'],
                            'rate': rate, 'sessions': counted})
    return report_rows


def insight_data(db, target):
    reports = reports_data(db, target)
    warnings = [s for s in reports if s['absent'] >= 3]
    since7 = (target - timedelta(days=6)).isoformat()
    late7 = db.execute('''
        SELECT student_id, COUNT(*) count FROM attendance
        WHERE attendance_date BETWEEN ? AND ? AND status='Late'
        GROUP BY student_id HAVING COUNT(*) >= 2
    ''', (since7, target.isoformat())).fetchall()
    late_names = {r['student_id'] for r in late7}
    repeats = [s for s in reports if s['id'] in late_names]

    insights = []
    if warnings:
        insights.append({'type': 'danger', 'icon': 'alert', 'title': f"{len(warnings)} student{'s' if len(warnings) != 1 else ''} with 3+ absences",
                         'detail': 'Review attendance and follow up with the students.',
                         'names': [s['name'] for s in warnings[:4]]})
    if repeats:
        insights.append({'type': 'warning', 'icon': 'clock', 'title': f"{len(repeats)} student{'s' if len(repeats) != 1 else ''} repeatedly late",
                         'detail': 'At least 2 late arrivals in the last 7 days.',
                         'names': [s['name'] for s in repeats[:4]]})
    week = week_data(db, target)
    known = [entry for entry in week if entry['rate'] is not None]
    if len(known) > 1:
        change = round(known[-1]['rate'] - known[0]['rate'], 1)
        mood = 'success' if change >= 0 else 'info'
        direction = 'up' if change > 0 else 'down' if change < 0 else 'unchanged'
        detail = f"{abs(change):g} percentage points {direction} from the first recorded day this week." if change else 'No change from the first recorded day this week.'
        insights.append({'type': mood, 'icon': 'trend', 'title': 'Weekly attendance trend', 'detail': detail, 'names': []})
    if not insights:
        insights.append({'type': 'success', 'icon': 'check', 'title': 'No attendance warnings yet',
                         'detail': 'Insights appear as you record attendance over time.', 'names': []})
    return insights


@app.get('/')
def home():
    return render_template('index.html')


@app.get('/api/students')
def get_students():
    return jsonify({'students': [dict(x) for x in get_db().execute('''
        SELECT id,student_no,name,section,created_at FROM students ORDER BY name COLLATE NOCASE
    ''')]})


@app.post('/api/students')
def add_student():
    data = payload()
    try:
        name = clean_text(data.get('name'), 'Student name')
        section = clean_text(data.get('section'), 'Course / section', 45)
        number = clean_text(data.get('student_no', ''), 'Student ID', 30, required=False)
    except ValueError as exc:
        return api_error(str(exc))
    db = get_db()
    try:
        if not number:
            # Unique generated ID; do not reuse an old ID when students are deleted.
            next_id = db.execute('SELECT seq FROM sqlite_sequence WHERE name=?', ('students',)).fetchone()
            candidate = (next_id['seq'] if next_id else 0) + 1
            number = f'STU-{candidate:04d}'
            while db.execute('SELECT 1 FROM students WHERE student_no=?', (number,)).fetchone():
                candidate += 1
                number = f'STU-{candidate:04d}'
        cur = db.execute('INSERT INTO students (student_no, name, section) VALUES (?,?,?)',
                         (number, name, section))
        db.commit()
    except sqlite3.IntegrityError:
        return api_error('Student ID already exists. Try a different ID.', 409)
    student = db.execute('SELECT * FROM students WHERE id=?', (cur.lastrowid,)).fetchone()
    return jsonify({'student': dict(student)}), 201


@app.patch('/api/students/<int:student_id>')
def update_student(student_id):
    data = payload()
    try:
        name = clean_text(data.get('name'), 'Student name')
        section = clean_text(data.get('section'), 'Course / section', 45)
        number = clean_text(data.get('student_no'), 'Student ID', 30)
    except ValueError as exc:
        return api_error(str(exc))
    db = get_db()
    try:
        cur = db.execute('UPDATE students SET student_no=?, name=?, section=? WHERE id=?',
                         (number, name, section, student_id))
        db.commit()
    except sqlite3.IntegrityError:
        return api_error('Student ID already exists.', 409)
    if not cur.rowcount:
        return api_error('Student not found.', 404)
    return jsonify({'message': 'Student updated.'})


@app.delete('/api/students/<int:student_id>')
def remove_student(student_id):
    db = get_db()
    cur = db.execute('DELETE FROM students WHERE id=?', (student_id,))
    db.commit()
    if not cur.rowcount:
        return api_error('Student not found.', 404)
    return jsonify({'message': 'Student and attendance records deleted.'})


@app.get('/api/attendance')
def get_attendance():
    target = parse_date(request.args.get('date', ''))
    if target is None:
        return api_error('Choose a valid attendance date (YYYY-MM-DD).')
    rows = rows_for_day(get_db(), target.isoformat())
    return jsonify({'date': target.isoformat(), 'students': rows, 'summary': daily_summary(rows)})


@app.put('/api/attendance/<int:student_id>')
def update_attendance(student_id):
    data = payload()
    target = parse_date(data.get('date'))
    if not target:
        return api_error('Choose a valid attendance date.')
    status = data.get('status')
    if status not in STATUSES | {'Unmarked'}:
        return api_error('Select Present, Late, Absent, Excused, or Unmarked.')
    try:
        checkin = parse_time(data.get('checkin_time'))
    except ValueError as exc:
        return api_error(str(exc))
    db = get_db()
    if db.execute('SELECT 1 FROM students WHERE id=?', (student_id,)).fetchone() is None:
        return api_error('Student not found.', 404)
    if status == 'Unmarked':
        db.execute('DELETE FROM attendance WHERE student_id=? AND attendance_date=?', (student_id, target.isoformat()))
    else:
        if status in {'Absent', 'Excused'}:
            checkin = None
        status = normalize_attendance_status(db, target, status, checkin)
        db.execute('''
            INSERT INTO attendance (student_id,attendance_date,status,checkin_time)
            VALUES (?,?,?,?) ON CONFLICT(student_id,attendance_date)
            DO UPDATE SET status=excluded.status, checkin_time=excluded.checkin_time
        ''', (student_id, target.isoformat(), status, checkin))
    db.commit()
    return jsonify({'message': 'Attendance saved.', 'status': status, 'checkin_time': checkin})


@app.get('/api/overview')
def overview():
    target = parse_date(request.args.get('date', ''))
    if not target:
        return api_error('Choose a valid date.')
    db = get_db()
    rows = rows_for_day(db, target.isoformat())
    return jsonify({'date': target.isoformat(), 'summary': daily_summary(rows),
                    'students': rows, 'week': week_data(db, target),
                    'insights': insight_data(db, target)})


@app.get('/api/reports')
def reports():
    target = parse_date(request.args.get('date', ''))
    if not target:
        return api_error('Choose a valid date.')
    db = get_db()
    return jsonify({'students': reports_data(db, target),
                    'insights': insight_data(db, target), 'week': week_data(db, target),
                    'end_date': target.isoformat(),
                    'start_date': (target - timedelta(days=29)).isoformat()})


@app.get('/api/schedule')
def get_schedule():
    return jsonify(schedule_settings(get_db()))


@app.put('/api/schedule')
def update_schedule():
    data = payload()
    if not isinstance(data.get('days'), list) or len(data['days']) != 7:
        return api_error('Please provide all 7 schedule days.')
    try:
        grace = int(data.get('grace_minutes'))
        if str(data.get('grace_minutes')).strip() != str(grace) or not (0 <= grace <= 60):
            raise ValueError('Grace period must be 0–60 minutes.')
        seen = set()
        updates = []
        for item in data['days']:
            if not isinstance(item, dict) or type(item.get('weekday')) is not int:
                raise ValueError('Invalid schedule entry.')
            wd = item['weekday']
            if wd < 0 or wd > 6 or wd in seen or type(item.get('enabled')) is not bool:
                raise ValueError('Invalid schedule entry.')
            seen.add(wd)
            start = parse_time(item.get('start_time'))
            if start is None:
                raise ValueError('Every day needs a start time.')
            updates.append((int(item['enabled']), start, wd))
    except (TypeError, ValueError) as exc:
        return api_error(str(exc))
    db = get_db()
    db.executemany('UPDATE schedule SET enabled=?, start_time=? WHERE weekday=?', updates)
    db.execute("UPDATE config SET value=? WHERE key='grace_minutes'", (str(grace),))
    db.commit()
    return jsonify({'message': 'Schedule saved.', **schedule_settings(db)})


@app.post('/api/demo')
def demo_data():
    """Optional sample records for presentations. Never replace an existing roster."""
    db = get_db()
    if db.execute('SELECT COUNT(*) AS n FROM students').fetchone()['n']:
        return api_error('Demo data can only be loaded into an empty student list.', 409)
    samples = [
        ('2026-001', 'Sarah Mitchell', 'BSCS - 3A'),
        ('2026-002', 'James Carter', 'BSIT - 3B'),
        ('2026-003', 'Priya Nair', 'BSIS - 3A'),
        ('2026-004', 'Daniel Brooks', 'BSCS - 3B'),
        ('2026-005', 'Elena Rossi', 'BSIT - 3A'),
        ('2026-006', 'Miguel Santos', 'BSCS - 3A'),
        ('2026-007', 'Anna Reyes', 'BSIT - 3B'),
        ('2026-008', 'Mark Lopez', 'BSIS - 3A'),
        ('2026-009', 'Nicole Cruz', 'BSCS - 3B'),
        ('2026-010', 'Ivan Garcia', 'BSIT - 3A')
    ]
    target = date.today()
    weekdays = []
    cursor = target
    while len(weekdays) < 10:
        if cursor.weekday() < 5:
            weekdays.append(cursor)
        cursor -= timedelta(days=1)
    weekdays.reverse()
    try:
        db.executemany('INSERT INTO students(student_no,name,section) VALUES (?,?,?)', samples)
        ids = [r['id'] for r in db.execute('SELECT id FROM students ORDER BY id')]
        for idx, day in enumerate(weekdays):
            for j, student_id in enumerate(ids):
                status = 'Present'
                if j == 3 and idx in (1, 4, 8):
                    status = 'Absent'
                elif j == 7 and idx in (2, 5, 9):
                    status = 'Absent'
                elif j == 1 and idx in (5, 7, 9):
                    status = 'Late'
                elif j == 4 and idx == 6:
                    status = 'Excused'
                elif (idx + j) % 18 == 0:
                    status = 'Late'
                time = None if status in {'Absent', 'Excused'} else ('08:19' if status == 'Late' else f'08:{(j * 3 + idx) % 10:02d}')
                db.execute('INSERT INTO attendance (student_id,attendance_date,status,checkin_time) VALUES (?,?,?,?)',
                           (student_id, day.isoformat(), status, time))
        db.commit()
    except sqlite3.IntegrityError:
        db.rollback()
        return api_error('Could not create demo data.', 409)
    return jsonify({'message': '10 sample students and 10 school days loaded.', 'is_demo': True}), 201


@app.post('/api/reset')
def reset_data():
    if payload().get('confirm') != 'DELETE ALL':
        return api_error('Confirmation is required.')
    db = get_db()
    db.execute('DELETE FROM attendance')
    db.execute('DELETE FROM students')
    db.commit()
    return jsonify({'message': 'All student and attendance records removed.'})


initialize_database()

if __name__ == '__main__':
    app.run(debug=False, host='127.0.0.1', port=5000)
