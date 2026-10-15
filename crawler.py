"""수업의 requests + BeautifulSoup 방식으로 목록 페이지만 수집한다."""
import csv
import re
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode, urljoin, urlparse, parse_qs

import requests
from bs4 import BeautifulSoup

BASE_URL = 'https://www.saramin.co.kr'
MAX_PAGE = 300
KST = timezone(timedelta(hours=9))
HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.7922.174 Safari/537.36'}

def now_kst():
    return datetime.now(KST)

def build_url(page=1, keyword=None):
    params = {'type': 'all', 'cat_mcls': '2'}
    if keyword:
        params['searchword'] = keyword
    params['page'] = page
    return BASE_URL + '/zf_user/jobs/public/list?' + urlencode(params)

def text_of(parent, tag, class_name):
    node = parent.find(tag, class_=class_name) if parent else None
    return node.get_text(' ', strip=True) if node else ''

def parse_item(item):
    # 회사명은 반드시 company_nm 안에서 찾는다.
    company_area = item.find('div', class_='company_nm')
    title_area = item.find('div', class_='job_tit')
    link = title_area.find('a', class_='str_tit') if title_area else None
    if not link or not link.get('href'):
        raise ValueError('공고 제목/링크 구조가 변경되었습니다.')
    url = urljoin(BASE_URL, link['href'])
    if urlparse(url).hostname != 'www.saramin.co.kr':
        raise ValueError('사람인 외부 링크입니다.')
    ids = parse_qs(urlparse(url).query).get('rec_idx', [])
    match = re.fullmatch(r'rec_link_(\d+)', link.get('id', ''))
    saramin_id = ids[0] if ids else (match.group(1) if match else '')
    if not saramin_id.isdigit():
        raise ValueError('공고 ID를 찾을 수 없습니다.')
    sector_area = item.find('span', class_='job_sector')
    sectors = []
    if sector_area:
        for span in sector_area.find_all('span'):
            value = span.get_text(strip=True)
            if value and value not in sectors:
                sectors.append(value)
    recruit = item.find('div', class_='recruit_info')
    support = item.find('div', class_='support_info')
    if not company_area or not recruit or not support:
        raise ValueError('공고 필수 영역이 없습니다. HTML을 확인하세요.')
    return {'saramin_id': saramin_id,
            'company': text_of(company_area, 'a', 'str_tit'),
            'title': link.get_text(' ', strip=True), 'url': url,
            'sectors': sectors,
            'location': text_of(recruit, 'p', 'work_place'),
            'experience_employment': text_of(recruit, 'p', 'career'),
            'education': text_of(recruit, 'p', 'education'),
            'salary': text_of(recruit, 'p', 'salary'),
            'deadline': text_of(support, 'span', 'date'),
            'posted_text': text_of(support, 'span', 'deadlines')}

def parse_page(html):
    soup = BeautifulSoup(html, 'html.parser')
    items = soup.find_all('div', class_='list_item')
    # 차단/로그인 HTML을 마지막 페이지로 잘못 처리하지 않는다.
    if not items and not soup.find('div', class_='list_body'):
        raise ValueError('목록 영역이 없습니다. 차단 또는 HTML 변경 가능성이 있습니다.')
    return [parse_item(item) for item in items]

def is_target(job):
    career = job['experience_employment']
    return any(word in career for word in ('신입', '인턴', '경력무관', '경력 무관'))

def estimate_posted_at(posted_text, seen_at):
    if '수정' in posted_text:
        return None  # 수정 시각은 등록 시각이 아니므로 과거 등록 통계에 쓰지 않는다.
    match = re.search(r'(\d+)\s*(분|시간|일|주|개월|달)\s*전', posted_text)
    if match:
        units = {'분': 60, '시간': 3600, '일': 86400, '주': 604800,
                 '개월': 2592000, '달': 2592000}
        return seen_at - timedelta(seconds=int(match.group(1)) * units[match.group(2)])
    if '오늘' in posted_text or '방금' in posted_text:
        return seen_at
    if '어제' in posted_text:
        return seen_at - timedelta(days=1)
    return None  # 해석 불가능한 원문은 보존하고 날짜를 지어내지 않는다.

def crawl(keyword=None, max_page=MAX_PAGE, delay=3, session=None):
    if max_page < 1 or delay < 0:
        raise ValueError('max_page는 1 이상, delay는 0 이상이어야 합니다.')
    client = session or requests.Session()
    seen_pages = set()
    try:
        for page in range(1, max_page + 1):
            if page > 1:
                time.sleep(delay)
            response = client.get(build_url(page, keyword), headers=HEADERS, timeout=30)
            response.raise_for_status()
            if response.status_code != 200:
                raise ValueError(f'정상 응답이 아닙니다: {response.status_code}')
            response.encoding = 'utf-8'
            jobs = parse_page(response.text)
            print(f'{keyword or "IT 전체"} / page={page}: {len(jobs)}개', flush=True)
            if not jobs:
                return
            signature = tuple(sorted(job['saramin_id'] for job in jobs))
            if signature in seen_pages:
                raise ValueError('같은 페이지가 반복되었습니다. 수집을 중단합니다.')
            seen_pages.add(signature)
            for job in jobs:
                # 관심 검색은 기존/경력 공고도 포함해 검색 결과 전체를 연결한다.
                if keyword is not None or is_target(job):
                    yield job
        raise ValueError(f'MAX_PAGE={max_page}에 도달했습니다. 전체 적재 완료로 처리하지 않습니다.')
    finally:
        if session is None:
            client.close()

def export_csv(jobs, filename):
    import json
    jobs = list(jobs)
    if not jobs:
        return
    with open(filename, 'w', encoding='utf-8-sig', newline='') as file:
        writer = csv.DictWriter(file, fieldnames=list(jobs[0]))
        writer.writeheader()
        for job in jobs:
            row = dict(job)
            row['sectors'] = json.dumps(row['sectors'], ensure_ascii=False)
            writer.writerow(row)
