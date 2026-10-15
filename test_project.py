"""실제 저장 HTML과 임시 DB로 핵심 동작을 검증한다."""
import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch
import database
import crawler

ROOT = Path(__file__).parent
HTML = (ROOT / 'tests/fixtures/list_page.html').read_text(encoding='utf-8')
EMPTY = (ROOT / 'tests/fixtures/empty_list.html').read_text(encoding='utf-8')

class Response:
    status_code = 200
    def __init__(self, html):
        self.text = html
    def raise_for_status(self):
        pass

class Client:
    def __init__(self, pages):
        self.pages = iter(pages)
        self.urls = []
    def get(self, url, **kwargs):
        self.urls.append(url)
        return Response(next(self.pages))

class ProjectTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(dir=ROOT)
        self.old_path = database.DB_PATH
        database.DB_PATH = Path(self.directory.name) / 'test.db'
        database.init_db()
        self.job = crawler.parse_page(HTML)[0]
        self.seen = datetime(2026, 10, 7, 9, 50, tzinfo=crawler.KST)
    def tearDown(self):
        database.DB_PATH = self.old_path
        self.directory.cleanup()
    def test_actual_fields(self):
        self.assertEqual(self.job['company'], '(주)화신이앤엘')
        self.assertEqual(self.job['title'], '[매쓰프로] 2026년 하반기 신입 및 경력사원 공개 채용')
        self.assertEqual(self.job['sectors'], ['Python', 'SaaS', '영업관리', '영업지원', '영업판촉'])
        self.assertEqual(self.job['location'], '서울 금천구 외')
        self.assertEqual(self.job['experience_employment'], '신입 · 경력 · 정규직')
        self.assertEqual(self.job['education'], '대학(2,3년)↑')
        self.assertEqual(self.job['salary'], '면접 후 협의')
        self.assertEqual(self.job['deadline'], '~10.19(월)')
        self.assertEqual(self.job['posted_text'], '17시간 전 등록')
        self.assertEqual(len(crawler.parse_page(HTML)), 20)
        self.assertFalse(crawler.is_target(crawler.parse_page(HTML)[1]))
        self.assertIsNone(crawler.estimate_posted_at('15시간 전 수정', self.seen))
        self.assertIsNone(crawler.estimate_posted_at('등록일 미표기', self.seen))
    def test_pagination_empty_and_repeated(self):
        client = Client([HTML, EMPTY])
        self.assertEqual(len(list(crawler.crawl(delay=0, session=client))), 12)
        self.assertTrue(client.urls[-1].endswith('page=2'))
        with self.assertRaisesRegex(ValueError, '반복'):
            list(crawler.crawl(delay=0, session=Client([HTML, HTML])))
        with self.assertRaisesRegex(ValueError, 'MAX_PAGE'):
            list(crawler.crawl(max_page=1, delay=0, session=Client([HTML])))
        with self.assertRaises(ValueError):
            crawler.parse_page('<html>access denied</html>')
    def test_duplicate_and_tag_delete(self):
        self.assertTrue(database.save_job(self.job, initial=True, seen_at=self.seen))
        self.assertFalse(database.save_job(self.job, seen_at=self.seen + timedelta(hours=1)))
        with database.connect() as db:
            row = db.execute('SELECT * FROM jobs').fetchone()
            self.assertEqual(db.execute('SELECT COUNT(*) FROM jobs').fetchone()[0], 1)
            self.assertEqual(row['stat_date'], '2026-10-06')
            self.assertEqual(row['first_seen_at'], self.seen.isoformat(timespec='seconds'))
            self.assertEqual(row['initial_import'], 1)
            self.assertNotEqual(row['last_seen_at'], row['first_seen_at'])
            db.execute("INSERT INTO tags(keyword,created_at) VALUES ('Python','now')")
            db.execute("INSERT INTO tags(keyword,created_at) VALUES ('LLM','now')")
        database.save_job(self.job, tag_id=1)
        database.save_job(self.job, tag_id=2)
        database.save_job(self.job, tag_id=1)
        with database.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM job_tags').fetchone()[0], 2)
            db.execute('DELETE FROM tags WHERE id=1')
        with database.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM jobs').fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM job_tags').fetchone()[0], 1)
    def test_tag_search_collects_all_pages_and_careers(self):
        second = HTML.replace('55211126', '99999997')
        client = Client([HTML, second, EMPTY])
        jobs = list(crawler.crawl(keyword='Python', delay=0, session=client))
        self.assertEqual(len(jobs), 40)
        self.assertTrue(any(not crawler.is_target(job) for job in jobs))
        self.assertTrue(client.urls[-1].endswith('searchword=Python&page=3'))
    def test_chip_count_and_filter_include_old_jobs(self):
        from app import app
        with database.connect() as db:
            db.execute("INSERT INTO tags(keyword,created_at) VALUES ('Python','now')")
        old = dict(self.job, title='OLDER_TAG_JOB')
        database.save_job(old, tag_id=1, stat_date='2020-01-01')
        # 같은 검색 결과를 다시 저장해도 링크 수는 늘어나지 않는다.
        database.save_job(old, tag_id=1)
        client = app.test_client()
        html = client.get('/?tag=1&period=30').get_data(as_text=True)
        self.assertIn('OLDER_TAG_JOB', html)
        self.assertIn('class="chip-count">1</span>', html)
        self.assertIn('tag-chip selected', html)
        self.assertIn('href="/?period=30" aria-current="true"', html)
        self.assertIn('<summary>+ ', html)
        self.assertNotIn('OLDER_TAG_JOB', client.get('/').get_data(as_text=True))
        self.assertEqual(client.get('/?tag=999').status_code, 404)
    def test_initial_and_scheduled_runs(self):
        with patch('crawler.crawl', return_value=iter([self.job])):
            self.assertEqual(database.run_import(initial=True, delay=0), 1)
        with patch('crawler.crawl', return_value=iter([self.job])):
            self.assertEqual(database.run_import(delay=0), 0)
        newer = dict(self.job, saramin_id='99999999')
        midnight = self.seen.replace(hour=0, minute=5)
        with patch('database.now_kst', return_value=midnight), patch('crawler.crawl', return_value=iter([newer])):
            self.assertEqual(database.run_import(delay=0), 1)
        morning_job = dict(self.job, saramin_id='99999998')
        with patch('database.now_kst', return_value=self.seen), patch('crawler.crawl', return_value=iter([morning_job])):
            self.assertEqual(database.run_import(delay=0), 1)
        with database.connect() as db:
            self.assertEqual(db.execute("SELECT stat_date FROM jobs WHERE saramin_id='99999999'").fetchone()[0], '2026-10-06')
            self.assertEqual(db.execute("SELECT stat_date FROM jobs WHERE saramin_id='99999998'").fetchone()[0], '2026-10-07')
        with self.assertRaises(ValueError):
            database.run_import(initial=True)
    def test_failed_initial_can_resume(self):
        def broken(*args):
            yield self.job
            raise ValueError('network failure')
        with patch('crawler.crawl', side_effect=broken), self.assertRaises(ValueError):
            database.run_import(initial=True, delay=0)
        self.assertFalse(database.initial_done())
        with patch('crawler.crawl', return_value=iter([self.job])):
            self.assertEqual(database.run_import(initial=True, delay=0), 0)
        self.assertTrue(database.initial_done())
    def test_flask_tag_lifecycle(self):
        from app import app
        client = app.test_client()
        response = client.get('/')
        self.assertEqual(response.status_code, 200)
        with client.session_transaction() as session:
            csrf = session['csrf']
        data = {'csrf': csrf, 'keyword': 'Python'}
        with patch('app.crawl', return_value=iter([self.job])):
            self.assertEqual(client.post('/tags', data=data).status_code, 302)
        client.post('/tags', data={'csrf': csrf, 'keyword': 'python'})
        with database.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM tags').fetchone()[0], 1)
        client.post('/tags/1/toggle', data={'csrf': csrf})
        with database.connect() as db:
            self.assertEqual(db.execute('SELECT alarm_enabled FROM tags').fetchone()[0], 0)
        self.assertEqual(client.get('/?period=30&tag=1').status_code, 200)
        self.assertEqual(client.post('/tags/1/delete', data={}).status_code, 400)
        client.post('/tags/1/delete', data={'csrf': csrf})
        with database.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM jobs').fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM job_tags').fetchone()[0], 0)

if __name__ == '__main__':
    unittest.main(verbosity=2)
