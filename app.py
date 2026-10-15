import json
import secrets
import sqlite3
from datetime import timedelta

from flask import Flask, render_template, request, redirect, url_for, flash, session, abort
import database
from crawler import crawl, now_kst

app = Flask(__name__)
app.secret_key = secrets.token_hex(32)
app.config['MAX_CONTENT_LENGTH'] = 4096
database.init_db()

@app.before_request
def protect_forms():
    if 'csrf' not in session:
        session['csrf'] = secrets.token_hex(24)
    if request.method == 'POST' and not secrets.compare_digest(request.form.get('csrf', ''), session['csrf']):
        abort(400)

@app.get('/')
def index():
    today = now_kst().date()
    period = request.args.get('period', '1')
    days = {'1': 1, '7': 7, '30': 30}.get(period, 1)
    start = (today - timedelta(days=days - 1)).isoformat()
    tag_id = request.args.get('tag', type=int)
    with database.connect() as db:
        counts = []
        for length in (1, 7, 30):
            since = (today - timedelta(days=length - 1)).isoformat()
            counts.append(db.execute('SELECT COUNT(*) FROM jobs WHERE stat_date BETWEEN ? AND ?',
                                     (since, today.isoformat())).fetchone()[0])
        tags = db.execute('''SELECT tags.*, COUNT(job_tags.job_id) AS job_count FROM tags
        LEFT JOIN job_tags ON tags.id=job_tags.tag_id
        GROUP BY tags.id ORDER BY tags.id''').fetchall()
        selected_tag = None
        if tag_id:
            selected_tag = next((tag for tag in tags if tag['id'] == tag_id), None)
            if selected_tag is None:
                abort(404)
            # 칩의 숫자와 목록이 같도록 해당 태그의 전체 공고를 조회한다.
            sql = 'SELECT * FROM jobs WHERE id IN (SELECT job_id FROM job_tags WHERE tag_id=?)'
            values = [tag_id]
        else:
            sql = 'SELECT * FROM jobs WHERE stat_date BETWEEN ? AND ?'
            values = [start, today.isoformat()]
        rows = db.execute(sql + ' ORDER BY stat_date DESC, first_seen_at DESC, id DESC', values).fetchall()
        run = db.execute('SELECT * FROM crawl_runs ORDER BY id DESC LIMIT 1').fetchone()
        unknown = db.execute('SELECT COUNT(*) FROM jobs WHERE stat_date IS NULL').fetchone()[0]
    jobs = []
    for row in rows:
        job = dict(row)
        job['sectors'] = json.loads(job['sectors'])
        jobs.append(job)
    return render_template('index.html', jobs=jobs, counts=counts, tags=tags,
                           today=today, period=str(days), tag_id=tag_id, run=run,
                           ready=database.initial_done(), unknown=unknown, selected_tag=selected_tag)

def crawl_tag(tag):
    for job in crawl(keyword=tag['keyword']):
        # 웹 추가/재수집은 기존 결과를 적재한다. 알림 대상은 정기 수집만 만든다.
        database.save_job(job, initial=not database.initial_done(), tag_id=tag['id'], baseline=True)
    with database.connect() as db:
        db.execute('UPDATE tags SET baseline_ready=1 WHERE id=?', (tag['id'],))

@app.post('/tags')
def add_tag():
    keyword = request.form.get('keyword', '').strip()
    if not keyword or len(keyword) > 50:
        flash('태그는 1~50자로 입력하세요.', 'error')
        return redirect(url_for('index'))
    try:
        with database.connect() as db:
            cursor = db.execute('INSERT INTO tags(keyword,created_at) VALUES (?,?)',
                                (keyword, now_kst().isoformat()))
            tag_id = cursor.lastrowid
    except sqlite3.IntegrityError:
        flash('이미 등록한 태그입니다.', 'error')
        return redirect(url_for('index'))
    try:
        crawl_tag({'id': tag_id, 'keyword': keyword})
        flash(f'{keyword} 태그를 추가하고 검색 결과를 저장했습니다.', 'success')
    except Exception as error:
        flash(f'태그는 저장했으나 수집이 완료되지 않았습니다: {error}. 재수집 버튼을 이용하세요.', 'error')
    return redirect(url_for('index', tag=tag_id))

@app.post('/tags/<int:tag_id>/<action>')
def update_tag(tag_id, action):
    with database.connect() as db:
        tag = db.execute('SELECT * FROM tags WHERE id=?', (tag_id,)).fetchone()
        if not tag:
            abort(404)
        if action == 'delete':
            db.execute('DELETE FROM tags WHERE id=?', (tag_id,))
        elif action == 'toggle':
            db.execute('UPDATE tags SET alarm_enabled=1-alarm_enabled WHERE id=?', (tag_id,))
        elif action != 'refresh':
            abort(404)
    if action == 'refresh':
        try:
            crawl_tag(tag)
            flash('태그 검색 결과를 갱신했습니다.', 'success')
        except Exception as error:
            flash(f'수집 실패: {error}', 'error')
    return redirect(url_for('index', tag=tag_id) if action != 'delete' else url_for('index'))

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5000, debug=False)
