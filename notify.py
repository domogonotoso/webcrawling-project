"""매일 10:00 실행: 알림 ON 태그의 새 연결을 한 번의 toast로 요약한다."""
import argparse
import base64
import html
import os
import subprocess
from collections import Counter
from unittest.mock import patch

import database
from crawler import now_kst

def checked_powershell(*, command='', file=''):
    # winotify 기본 실행은 오류를 숨기므로 완료를 기다리고 종료 코드를 검사한다.
    if file or not command:
        raise ValueError('알림 명령이 비어 있습니다.')
    script = "$ErrorActionPreference = 'Stop';\n" + command
    encoded = base64.b64encode(script.encode('utf-16-le')).decode('ascii')
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive',
                             '-EncodedCommand', encoded], capture_output=True,
                            startupinfo=startup, timeout=30)
    if result.returncode:
        detail = result.stderr.decode('utf-8', errors='replace')
        raise RuntimeError(f'Windows 알림 호출 실패 ({result.returncode}): {detail}')

def safe_text(value):
    # 태그 텍스트가 PowerShell 변수/명령 또는 XML로 해석되지 않도록 한다.
    return html.escape(value).replace('`', '``').replace('$', '`$')

def show_toast(title, message):
    if os.name != 'nt':
        raise RuntimeError('Windows에서 실행하세요.')
    try:
        import winotify
    except ImportError as error:
        raise RuntimeError('python -m pip install winotify==1.1.0 를 실행하세요.') from error
    toast = winotify.Notification(app_id='Job Tracker', title=safe_text(title),
                                 msg=safe_text(message), duration='long')
    toast.add_actions(label='공고 보기', launch='http://127.0.0.1:5000')
    with patch('winotify._run_ps', checked_powershell):
        toast.show()

def pending_links(db):
    return db.execute('''SELECT jt.job_id,jt.tag_id,t.keyword FROM job_tags jt
        JOIN tags t ON t.id=jt.tag_id
        WHERE t.alarm_enabled=1 AND t.baseline_ready=1 AND jt.is_baseline=0
        AND NOT EXISTS (SELECT 1 FROM notifications n
            WHERE n.job_id=jt.job_id AND n.tag_id=jt.tag_id)
        ORDER BY t.id,jt.job_id''').fetchall()

def summary(rows):
    counts = Counter(row['keyword'] for row in rows)
    lines = [f'{keyword} {count}건' for keyword, count in counts.items()]
    # 태그가 많을 때 toast가 너무 길어지지 않게 요약한다.
    if len(lines) > 5:
        lines = lines[:5] + [f'외 {len(counts)-5}개 태그']
    total = len({row['job_id'] for row in rows})
    return '\n'.join(lines) + f'\n\n고유 신규 공고 총 {total}건'

def send_notifications(sender=None, at=None):
    sender = sender or show_toast
    database.init_db()
    at = at or now_kst()
    day = at.date().isoformat()
    stamp = at.isoformat(timespec='seconds')
    with database.connect() as db:
        # 조회부터 기록까지 잠가 동시에 실행해도 중복 toast가 나오지 않게 한다.
        db.execute('BEGIN IMMEDIATE')
        rows = pending_links(db)
        if not rows:
            print('새로운 관심 공고가 없습니다.')
            return 0
        if db.execute('SELECT 1 FROM notification_batches WHERE notification_date=?', (day,)).fetchone():
            print('오늘 요약 알림은 이미 발송했습니다. 남은 공고는 다음 알림에 포함합니다.')
            return 0
        message = summary(rows)
        sender('사람인 관심 공고', message)  # 실패하면 with 블록에서 rollback
        total = len({row['job_id'] for row in rows})
        cursor = db.execute('''INSERT INTO notification_batches
            (notification_date,notified_at,unique_job_count) VALUES (?,?,?)''', (day, stamp, total))
        db.executemany('''INSERT INTO notifications(job_id,tag_id,notified_at,batch_id)
            VALUES (?,?,?,?)''', [(row['job_id'], row['tag_id'], stamp, cursor.lastrowid) for row in rows])
    print(message)
    return total

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='관심 공고 Windows 요약 알림')
    parser.add_argument('--test', action='store_true', help='DB를 변경하지 않는 테스트 toast')
    args = parser.parse_args()
    try:
        if args.test:
            show_toast('Job Tracker 알림 테스트', 'Windows 알림이 정상적으로 동작합니다.')
            print('테스트 알림을 Windows에 전달했습니다.')
        else:
            send_notifications()
    except Exception as error:
        parser.exit(1, f'알림 실패: {error}\n')
