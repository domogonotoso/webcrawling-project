"""실제 DB 대신 임시 DB에서 baseline/중복/실패 조건을 검사한다."""
import sqlite3
import sys
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import Mock, patch

import database
import notify
import test_project

class NotificationTests(unittest.TestCase):
    setUp = test_project.ProjectTests.setUp
    tearDown = test_project.ProjectTests.tearDown

    def add_tag(self, keyword='Python', enabled=1, ready=1):
        with database.connect() as db:
            return db.execute('''INSERT INTO tags(keyword,alarm_enabled,created_at,baseline_ready)
                VALUES (?,?,?,?)''', (keyword, enabled, self.seen.isoformat(), ready)).lastrowid

    def test_a_no_new_links(self):
        tag = self.add_tag()
        database.save_job(self.job, tag_id=tag, baseline=True)
        sender = Mock()
        self.assertEqual(notify.send_notifications(sender, self.seen), 0)
        sender.assert_not_called()

    def test_b_c_summary_and_repeat(self):
        tag = self.add_tag()
        database.save_job(self.job, tag_id=tag, baseline=False)
        sender = Mock()
        self.assertEqual(notify.send_notifications(sender, self.seen), 1)
        self.assertIn('Python 1건', sender.call_args.args[1])
        self.assertEqual(notify.send_notifications(sender, self.seen), 0)
        self.assertEqual(sender.call_count, 1)

    def test_d_off_and_unique_total(self):
        for word, enabled in [('Python', 1), ('LLM', 1), ('RAG', 0)]:
            database.save_job(self.job, tag_id=self.add_tag(word, enabled), baseline=False)
        sender = Mock()
        notify.send_notifications(sender, self.seen)
        message = sender.call_args.args[1]
        self.assertIn('Python 1건', message)
        self.assertIn('LLM 1건', message)
        self.assertIn('총 1건', message)
        self.assertNotIn('RAG', message)
        with database.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM notifications').fetchone()[0], 2)

    def test_e_web_baseline_then_scheduled_match(self):
        from app import app
        client = app.test_client()
        client.get('/')
        with client.session_transaction() as session:
            csrf = session['csrf']
        with patch('app.crawl', return_value=iter([self.job])):
            client.post('/tags', data={'csrf': csrf, 'keyword': 'Python'})
        sender = Mock()
        self.assertEqual(notify.send_notifications(sender, self.seen), 0)
        with database.connect() as db:
            db.execute("INSERT INTO settings VALUES ('initial_done','yes')")
        newer = dict(self.job, saramin_id='99999990')
        with patch('crawler.crawl', side_effect=[iter([self.job, newer]), iter([self.job, newer])]):
            database.run_import(delay=0)
        self.assertEqual(notify.send_notifications(sender, self.seen), 1)
        with database.connect() as db:
            self.assertEqual(db.execute('SELECT is_baseline FROM job_tags WHERE job_id=1').fetchone()[0], 1)

    def test_failure_does_not_mark_and_day_limit(self):
        tag = self.add_tag()
        database.save_job(self.job, tag_id=tag, baseline=False)
        with self.assertRaises(RuntimeError):
            notify.send_notifications(Mock(side_effect=RuntimeError('toast failed')), self.seen)
        with database.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM notifications').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM notification_batches').fetchone()[0], 0)
        sender = Mock()
        notify.send_notifications(sender, self.seen)
        database.save_job(dict(self.job, saramin_id='99999991'), tag_id=tag, baseline=False)
        self.assertEqual(notify.send_notifications(sender, self.seen), 0)
        self.assertEqual(notify.send_notifications(sender, self.seen + timedelta(days=1)), 1)

    def test_failed_first_web_crawl_remains_baseline_on_retry(self):
        from app import app
        tag = self.add_tag(ready=0)
        def broken(*args, **kwargs):
            yield self.job
            raise RuntimeError('connection lost')
        with patch('app.crawl', side_effect=broken), self.assertRaises(RuntimeError):
            from app import crawl_tag
            crawl_tag({'id': tag, 'keyword': 'Python'})
        with database.connect() as db:
            db.execute("INSERT INTO settings VALUES ('initial_done','yes')")
        newer = dict(self.job, saramin_id='99999992')
        with patch('crawler.crawl', side_effect=[iter([]), iter([self.job, newer])]):
            database.run_import(delay=0)
        self.assertEqual(notify.send_notifications(Mock(), self.seen), 0)

    def test_migrate_old_links_safely_and_idempotently(self):
        legacy = Path(self.directory.name) / 'legacy.db'
        with sqlite3.connect(legacy) as db:
            db.executescript('''CREATE TABLE jobs(id INTEGER PRIMARY KEY, first_seen_at TEXT,stat_date TEXT);
            CREATE TABLE tags(id INTEGER PRIMARY KEY,keyword TEXT,alarm_enabled INTEGER,created_at TEXT);
            CREATE TABLE job_tags(job_id INTEGER,tag_id INTEGER,PRIMARY KEY(job_id,tag_id));
            INSERT INTO jobs VALUES (1,'2026-10-07',NULL);
            INSERT INTO tags VALUES (1,'Python',1,'2026-10-07');
            INSERT INTO job_tags VALUES (1,1);''')
        db.close()
        with patch.object(database, 'DB_PATH', legacy):
            database.init_db()
            database.init_db()
            with database.connect() as db:
                self.assertEqual(db.execute('SELECT is_baseline FROM job_tags').fetchone()[0], 1)
                self.assertEqual(db.execute('SELECT baseline_ready FROM tags').fetchone()[0], 1)
                self.assertEqual(len(notify.pending_links(db)), 0)

def native_smoke_test():
    # B/C: Windows 호출도 확인하되 사용자 DB에 가짜 공고를 저장하지 않는다.
    fixture = NotificationTests()
    fixture.setUp()
    try:
        tag = fixture.add_tag()
        database.save_job(fixture.job, tag_id=tag, baseline=False)
        assert notify.send_notifications() == 1
        assert notify.send_notifications() == 0
        print('실제 Windows 호출 및 재실행 중복 방지 확인 완료 (임시 DB)')
    finally:
        fixture.tearDown()

if __name__ == '__main__':
    if '--native' in sys.argv:
        native_smoke_test()
    else:
        unittest.main(verbosity=2)
