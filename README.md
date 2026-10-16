
```markdown
# 채용공고 자동 수집 및 관심 기술 알림 시스템

사람인 IT·개발/데이터 채용공고를 자동으로 수집하고,  
관심 기술 키워드별 공고를 관리하며 신규 공고 발생 시 Windows 알림을 제공하는 프로젝트입니다.

반복적으로 채용공고를 검색하고 확인하는 과정을 줄이기 위해  
수집 → 파싱 → 저장 → 중복 확인 → 신규 공고 탐지 → 알림까지 하나의 자동화 흐름으로 구현했습니다.

---

## 주요 기능

- 사람인 IT·개발/데이터 채용공고 자동 수집
- Requests + BeautifulSoup4 기반 HTML 파싱
- 회사명, 공고명, 직무, 지역, 경력, 학력, 마감일 등 추출
- SQLite 기반 공고 저장 및 `saramin_id` 기준 중복 방지
- Python, Java, LLM 등 관심 기술 태그별 공고 관리
- Flask 기반 채용공고 조회 대시보드
- 신규 관심 공고 탐지 및 Windows 알림
- Windows Task Scheduler를 이용한 정기 실행 지원

---

## System Flow

```text
Windows Task Scheduler
        ↓
     Collect
  채용공고 페이지 요청
        ↓
      Parse
 BeautifulSoup HTML 파싱
        ↓
      SQLite
 저장 / 중복 확인 / 이력 관리
        ↓
    New Job?
     ↙    ↘
   No      Yes
   ↓        ↓
 종료   Notification
             ↓
       Flask Dashboard
```

---

## Tech Stack

| Category | Stack |
|---|---|
| Language | Python |
| Crawling | Requests, BeautifulSoup4 |
| Backend | Flask, Jinja2 |
| Frontend | HTML, CSS, JavaScript |
| Database | SQLite |
| Notification | winotify |
| Automation | Windows Task Scheduler, Batch Script |

---

## Crawling

사람인 검색 조건을 이용해 IT·개발/데이터 채용공고 페이지를 요청합니다.

```python
response = requests.get(url, headers=headers)
soup = BeautifulSoup(response.text, "html.parser")
```

BeautifulSoup으로 각 공고의 HTML 구조를 탐색한 뒤 필요한 데이터를 추출합니다.

```python
company_area = item.find("div", class_="company_nm")

company = text_of(
    company_area,
    "a",
    "str_tit"
)
```

수집하는 주요 데이터:

```text
공고 ID
회사명
공고 제목
상세 URL
직무
근무 지역
경력 / 고용 형태
학력
급여
마감일
등록 시점
```

---

## 관심 기술 태그

사용자가 관심 기술을 등록하면 해당 키워드의 검색 결과를 별도로 수집합니다.

예시:

```text
Python
Java
LLM
FastAPI
```

태그별 공고 수를 확인할 수 있으며, 새로운 관심 공고가 발견되면 Windows 알림 대상으로 처리합니다.

---

## Notification

`winotify`를 이용해 신규 관심 공고를 Windows 알림으로 제공합니다.

```text
사람인 관심 공고

Python 3건
LLM 2건
RAG 1건

[공고 보기]
```

기존 공고는 baseline으로 관리하여 처음 알림 기능을 실행했을 때  
과거 공고가 한꺼번에 알림으로 표시되지 않도록 구성했습니다.

---

## 실행 방법

### 1. 패키지 설치

```bash
pip install -r requirements.txt
```

### 2. 최초 공고 수집

```bash
python initial_crawl.py
```

### 3. 정기 수집

```bash
python scheduled_crawl.py --slot today
```

### 4. 웹 서버 실행

```bash
python app.py
```

브라우저:

```text
http://127.0.0.1:5000
```

### 5. 알림 실행

```bash
python notify.py
```

---

## Project Structure

```text
WebCrawler/
├─ crawler.py
├─ database.py
├─ initial_crawl.py
├─ scheduled_crawl.py
├─ notify.py
├─ app.py
│
├─ templates/
│  └─ index.html
│
├─ static/
│  ├─ style.css
│  └─ script.js
│
├─ run_scheduled_crawl.bat
├─ run_notify.bat
├─ requirements.txt
└─ README.md
```

---

## Test

크롤링 파싱, 중복 방지, 태그 연결, 알림 중복 방지,
Flask 화면 및 기존 DB migration 등을 테스트했습니다.

```bash
python -m unittest test_project test_notifications -v
```

총 **15개 테스트 통과**를 확인했습니다.

---

## Future Plan

**Multi-Platform Crawling**  
잡코리아, 원티드, 인크루트 등으로 수집 범위를 확대하고 여러 채용 사이트의 공고를 하나의 대시보드에서 통합 조회

**Server Deployment**  
localhost 환경을 서버 기반 서비스로 전환하여 PC 상태와 관계없이 정기적으로 공고 자동 수집

**Notification Expansion**  
Windows 로컬 알림을 Web Push 및 Chrome Extension으로 확장하여 외부에서도 신규 관심 공고 확인

---

## Project Goal

단순히 웹페이지의 데이터를 가져오는 것에 그치지 않고,

**채용공고 수집 → 데이터 저장 → 중복 관리 → 정기 실행 → 신규 공고 탐지 → 알림**

과정을 하나의 자동화 파이프라인으로 구현하는 것을 목표로 했습니다.
```
