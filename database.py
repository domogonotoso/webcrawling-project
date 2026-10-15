"""ORM 없이 sqlite3로 공고, 태그, 실행 기록을 관리한다."""
import json
import os
import sqlite3
from datetime import timedelta
from pathlib import Path
from crawler import now_kst, estimate_posted_at

DB_PATH = Path(os.environ.get('JOBS_DB_PATH', Path(__file__).with_name('jobs.db')))

class ClosingConnection(sqlite3.Connection):
    # sqlite3의 기본 with는 commit만 하고 연결은 닫지 않는다.
    # Windows 파일 잠금을 남기지 않도록 블록 종료 시 닫는다.
    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()

def connect():
    connection = sqlite3.connect(DB_PATH, timeout=30, factory=ClosingConnection)
    connection.row_factory = sqlite3.Row
    connection.execute('PRAGMA foreign_keys=ON')
    return connection

def init_db():
    with connect() as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS jobs (
          id INTEGER PRIMARY KEY, saramin_id TEXT UNIQUE NOT NULL,
          company TEXT, title TEXT, url TEXT, sectors TEXT, location TEXT,
          experience_employment TEXT, education TEXT, salary TEXT,
          deadline TEXT, posted_text TEXT, estimated_posted_at TEXT,
          first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL,
          stat_date TEXT, initial_import INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS tags (
          id INTEGER PRIMARY KEY, keyword TEXT UNIQUE COLLATE NOCASE NOT NULL,
          alarm_enabled INTEGER NOT NULL DEFAULT 1 CHECK(alarm_enabled IN (0,1)),
          created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS job_tags (
          job_id INTEGER REFERENCES jobs(id) ON DELETE CASCADE,
          tag_id INTEGER REFERENCES tags(id) ON DELETE CASCADE,
          PRIMARY KEY(job_id, tag_id));
        CREATE TABLE IF NOT EXISTS crawl_runs (
          id INTEGER PRIMARY KEY, mode TEXT, started_at TEXT,
          finished_at TEXT, status TEXT, new_count INTEGER DEFAULT 0, error TEXT);
        CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
        CREATE INDEX IF NOT EXISTS jobs_stat_date ON jobs(stat_date);
        ''')
        # 기존 연결을 신규 알림으로 오인하지 않도록 안전한 기본값으로 이관한다.
        db.execute('BEGIN IMMEDIATE')
        tag_columns = [row['name'] for row in db.execute('PRAGMA table_info(tags)')]
        if 'baseline_ready' not in tag_columns:
            db.execute('ALTER TABLE tags ADD COLUMN baseline_ready INTEGER NOT NULL DEFAULT 0')
            db.execute('UPDATE tags SET baseline_ready=1')
        link_columns = [row['name'] for row in db.execute('PRAGMA table_info(job_tags)')]
        if 'is_baseline' not in link_columns:
            db.execute('ALTER TABLE job_tags ADD COLUMN is_baseline INTEGER NOT NULL DEFAULT 1')
        if 'matched_at' not in link_columns:
            db.execute('ALTER TABLE job_tags ADD COLUMN matched_at TEXT')
            db.execute('''UPDATE job_tags SET matched_at=
                (SELECT first_seen_at FROM jobs WHERE jobs.id=job_tags.job_id)''')
        db.execute('''CREATE TABLE IF NOT EXISTS notification_batches (
            id INTEGER PRIMARY KEY, notification_date TEXT UNIQUE NOT NULL,
            notified_at TEXT NOT NULL, unique_job_count INTEGER NOT NULL)''')
        db.execute('''CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY, job_id INTEGER NOT NULL, tag_id INTEGER NOT NULL,
            notified_at TEXT NOT NULL, batch_id INTEGER REFERENCES notification_batches(id),
            UNIQUE(job_id, tag_id),
            FOREIGN KEY(job_id, tag_id) REFERENCES job_tags(job_id, tag_id) ON DELETE CASCADE)''')

def save_job(job, initial=False, tag_id=None, stat_date=None, seen_at=None, baseline=True):
    seen_at = seen_at or now_kst()
    stamp = seen_at.isoformat(timespec='seconds')
    estimated = estimate_posted_at(job['posted_text'], seen_at) if initial else None
    date = (estimated.date().isoformat() if estimated else None) if initial else (stat_date or seen_at.date().isoformat())
    fields = ['company', 'title', 'url', 'sectors', 'location',
              'experience_employment', 'education', 'salary', 'deadline', 'posted_text']
    values = [json.dumps(job[key], ensure_ascii=False) if key == 'sectors' else job[key] for key in fields]
    with connect() as db:
        cursor = db.execute('''INSERT OR IGNORE INTO jobs
        (saramin_id, company, title, url, sectors, location, experience_employment,
         education, salary, deadline, posted_text, estimated_posted_at,
         first_seen_at, last_seen_at, stat_date, initial_import)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
        [job['saramin_id']] + values + [estimated.isoformat() if estimated else None, stamp, stamp, date, int(initial)])
        inserted = cursor.rowcount == 1
        # 기존 공고의 최초 시각/통계 날짜/원문은 덮어쓰지 않는다.
        db.execute('UPDATE jobs SET last_seen_at=? WHERE saramin_id=?', (stamp, job['saramin_id']))
        row = db.execute('SELECT id FROM jobs WHERE saramin_id=?', (job['saramin_id'],)).fetchone()
        if tag_id is not None:
            db.execute('''INSERT OR IGNORE INTO job_tags
                (job_id,tag_id,matched_at,is_baseline) VALUES (?,?,?,?)''',
                (row['id'], tag_id, stamp, int(baseline or initial)))
    return inserted

def initial_done():
    with connect() as db:
        return db.execute("SELECT 1 FROM settings WHERE key='initial_done'").fetchone() is not None

def run_import(initial=False, slot='auto', max_page=300, delay=3):
    from crawler import crawl
    init_db()
    if initial and initial_done():
        raise ValueError('초기 적재가 이미 완료되었습니다. scheduled_crawl.py를 사용하세요.')
    if not initial and not initial_done():
        raise ValueError('먼저 initial_crawl.py를 완료하세요.')
    started = now_kst()
    # 자정 실행 구간(00시)은 전날, 오전 실행 및 수동 실행은 오늘.
    previous = slot == 'previous' or (slot == 'auto' and started.hour == 0)
    stat_date = (started.date() - timedelta(days=int(previous))).isoformat()
    with connect() as db:
        cursor = db.execute('INSERT INTO crawl_runs(mode,started_at,status) VALUES (?,?,?)',
                            ('initial' if initial else 'scheduled', started.isoformat(), 'running'))
        run_id = cursor.lastrowid
        tags = db.execute('SELECT * FROM tags ORDER BY id').fetchall()
    count = 0
    try:
        searches = [(None, None)] + [(tag['keyword'], tag['id']) for tag in tags]
        for keyword, tag_id in searches:
            baseline = True
            if tag_id is not None and not initial:
                tag = next(tag for tag in tags if tag['id'] == tag_id)
                baseline = not tag['baseline_ready']
            if keyword is not None:
                import time
                time.sleep(delay)
            for job in crawl(keyword, max_page, delay):
                count += save_job(job, initial, tag_id, stat_date, baseline=baseline)
            if tag_id is not None:
                with connect() as db:
                    db.execute('UPDATE tags SET baseline_ready=1 WHERE id=?', (tag_id,))
        with connect() as db:
            if initial:
                db.execute("INSERT OR REPLACE INTO settings VALUES ('initial_done',?)", (now_kst().isoformat(),))
            db.execute('UPDATE crawl_runs SET status=?,finished_at=?,new_count=? WHERE id=?',
                       ('success', now_kst().isoformat(), count, run_id))
    except Exception as error:
        with connect() as db:
            db.execute('UPDATE crawl_runs SET status=?,finished_at=?,new_count=?,error=? WHERE id=?',
                       ('failed', now_kst().isoformat(), count, str(error), run_id))
        raise
    return count
