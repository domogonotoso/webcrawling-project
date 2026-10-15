# 사람인 개발 채용 노트

사람인 IT·개발/데이터 목록을 requests + BeautifulSoup으로 수집하는 localhost Flask 프로젝트입니다. 수업 노트북 3개(`crawl/`)와 `레고이미지/`는 수정하지 않았습니다.

## 설치와 실행

일반 Python 3.12 이상이 설치되어 있다면 작업 폴더에서:

```powershell
python -m pip install -r requirements.txt
python initial_crawl.py
python scheduled_crawl.py --slot today
python app.py
```

이 환경에는 실행 가능한 Python이 없어 검증용 Python을 `.runtime/python/`에 설치했습니다. 현재 PC에서는 다음 명령을 바로 사용할 수 있습니다.

```powershell
.\.runtime\python\python.exe initial_crawl.py
.\.runtime\python\python.exe scheduled_crawl.py --slot today
.\.runtime\python\python.exe app.py
```

웹 화면: http://127.0.0.1:5000 . 서버 종료: Ctrl+C. 디버그 모드는 끈 상태이며 localhost에서만 실행합니다. 검증용 Python의 경로 설정은 현재 폴더를 가리키므로 폴더를 옮기는 경우 일반 Python/가상환경을 사용하세요.

초기 적재는 빈 페이지까지 완료한 경우에만 완료 표시됩니다. 완료 후 재실행은 차단합니다. 네트워크 오류나 MAX_PAGE 도달로 중단되었다면 같은 명령으로 재실행할 수 있습니다. 이미 저장된 공고는 중복 저장하지 않습니다. 한 페이지씩 DB에 저장하므로 중단 이전 데이터는 남습니다.

```powershell
# 00:05 실행: 전날 통계에 배정
python scheduled_crawl.py --slot previous
# 09:50 실행: 오늘 통계에 배정
python scheduled_crawl.py --slot today
# 기본 auto: 한국 시각 00시 실행은 전날, 그 외는 오늘
python scheduled_crawl.py
# 기본 300페이지, 요청 간 3초 (상한에 도달하면 실패 처리)
python initial_crawl.py --max-page 300 --delay 3
```

## 파일 역할

| 파일 | 역할 |
|---|---|
| `crawler.py` | URL 생성, Chrome User-Agent 요청, 목록 파싱, 신입/인턴 필터, 페이지 순회, 등록 시점 추정, UTF-8 BOM CSV 내보내기 |
| `database.py` | sqlite3 스키마, 중복 방지, 태그 연결, 초기/주기 실행과 통계 날짜 배정 |
| `initial_crawl.py` | 최초 전체 적재 CLI |
| `scheduled_crawl.py` | 정기 전체 + 등록 태그 검색 CLI |
| `app.py` | Flask 화면과 태그 추가/재수집/삭제/알림 설정 |
| `templates/index.html` | 통계 카드, 기간 조회, 전체 공고 수를 표시하는 관심 태그 칩과 태그 필터 |
| `static/style.css`, `static/script.js` | 반응형 화면, 삭제 확인과 중복 제출 방지 |
| `jobs.db` | 실제 수집 데이터 (실행 시 생성) |
| `requirements.txt` | 필요한 라이브러리 |
| `test_project.py` | 실제 HTML 파싱, 페이지 종료, 중복 방지, 날짜 배정, Flask 검증 |
| `tests/fixtures/list_page.html`, `tests/fixtures/empty_list.html` | 실제 응답에서 목록 영역만 추리고 불필요한 속성을 제거한 파싱 테스트 자료 |
| `.runtime/` | 이 PC의 테스트용 Python과 패키지 |

## DB 구조

`jobs`: `id`, `saramin_id UNIQUE`, `company`, `title`, `url`, `sectors` (JSON), `location`, `experience_employment`, `education`, `salary`, `deadline`, `posted_text`, `estimated_posted_at`, `first_seen_at`, `last_seen_at`, `stat_date`, `initial_import`.

`tags`: `id`, `keyword UNIQUE COLLATE NOCASE`, `alarm_enabled` (0/1), `created_at`. Python/python처럼 영문 대소문자만 다른 태그도 중복을 막습니다.

`job_tags`: `job_id`, `tag_id` 복합 기본키. 태그 삭제 시 연결만 함께 삭제되고 공고는 유지됩니다.

`crawl_runs`: 전체 수집의 시작/종료 시각, 초기/정기 구분, running/success/failed, 신규 수, 오류. `settings`: 초기 전체 적재 완료 표시. `stat_date`에는 조회용 인덱스가 있습니다.

시각은 UTC+09:00 한국 시각 ISO 문자열로 저장합니다. 초기 공고는 `posted_text`를 보존하고 추정 등록 날짜를 `stat_date`에 배정합니다. 월 단위는 30일로 근사합니다. `수정` 표시나 해석 불가능한 원문은 등록 날짜를 추정하지 않으며 `estimated_posted_at/stat_date`가 NULL이고 날짜별 통계에서 제외합니다. 화면에 제외 수를 표시합니다.

정기 신규 공고는 실제 발견 시각을 `first_seen_at`에 저장합니다. `stat_date`는 실행 시작의 slot으로 배정하므로 자정을 넘겨 수집해도 실행 기준 날짜가 유지됩니다. 기존 공고는 `last_seen_at`만 바뀌고 최초 원문·최초 발견 시각·초기 구분·통계 날짜는 유지합니다. 기존 공고가 새 태그 검색에도 등장하면 태그 연결을 추가합니다. 오늘/7일/30일은 오늘을 포함한 한국 달력 날짜 기준입니다.

## 실제 확인한 HTML과 범위

공고: `div.list_item`. 회사: `div.company_nm` 내부 `a.str_tit`. 제목: `div.job_tit` 내부 `a.str_tit`. ID: href의 `rec_idx`, 없으면 `rec_link_숫자`. 직무: `span.job_sector` 내부 `span` 목록.

실제 응답에서 `div.recruit_info` 내부 `p.work_place`, `p.career`, `p.education`, `p.salary`를 확인했습니다. `div.support_info` 내부에는 `span.date`(마감)와 `span.deadlines`(등록/수정 원문)가 있습니다.

`type=all` 실제 응답에 경력 전용 공고도 포함되어 있습니다. 전체 IT 수집에서는 목록의 경력·고용 조건에 `신입`, `인턴`, `경력무관`, `경력 무관`이 있는 공고를 저장합니다. 신입·경력 혼합 공고는 포함됩니다. 관심 태그 검색은 새 요구사항에 따라 신입 필터나 신규 여부로 수집을 제한하지 않고 모든 페이지의 모든 공고를 저장·연결합니다. IT 분류는 서버의 `cat_mcls=2` 결과를 따릅니다. 상세페이지에만 적힌 조건은 검사하지 않습니다.

페이지 종료는 필터 결과가 아니라 원래 `list_item` 개수가 0일 때입니다. 목록 영역 자체가 없거나 동일 ID 집합의 페이지가 반복되면 오류로 중단합니다. MAX_PAGE까지 빈 페이지가 없으면 미완료로 기록합니다.

태그 추가는 동기 수집이므로 HTTP 응답이 돌아올 때까지 기다려야 합니다. 수집 실패 시 태그와 이미 수집한 결과는 유지하고 재수집을 제공합니다. 알림 OFF라도 태그 검색/수집은 계속하며 Windows 알림 대상에서만 제외합니다. 웹 실행 전에 초기 전체 적재를 완료하는 것을 권장합니다. 초기 완료 전 태그 검색은 초기 데이터로 처리합니다.

## 테스트

```powershell
python test_project.py
# 이 PC
.\.runtime\python\python.exe test_project.py
```

실제 저장 HTML의 회사/제목/직무/채용/지원 필드를 검증합니다. 응답 대역으로 빈 페이지 종료, 반복 페이지 차단, 상한 실패를 검증하고 임시 SQLite로 최초/두 번째 실행, 다중 태그 연결, 태그 삭제, 실패 후 재시작, 00:05/09:50 날짜 배정과 Flask 화면/폼을 검증합니다. 테스트 데이터는 실제 jobs.db에 들어가지 않습니다.

## 관심 태그 화면

관심 태그는 `[Python 38 🔔 ×]` 형태의 칩이며 자동 줄바꿈됩니다. 숫자는 해당 태그에 연결된 전체 공고 수입니다. 알림 아이콘은 ON/OFF를 저장하고 ×는 태그 및 연결만 삭제합니다. `+ 태그 추가`를 누르면 입력창이 열립니다. 칩을 클릭하면 날짜와 관계없이 연결된 전체 공고를 표시하며, 선택된 태그의 재수집 버튼으로 검색 결과를 다시 적재할 수 있습니다. 통계 카드를 누르면 해당 기간의 전체 공고 조회로 돌아갑니다.

선택한 태그 칩을 다시 누르면 태그 필터를 해제하고 이전에 선택한 기간의 전체 목록으로 돌아갑니다.

공고 카드에는 날짜만 표시하며 상대시간 원문과 초기/정기 구분은 DB에 보존합니다. 설명 문구와 내부 수집 상태는 카드에 표시하지 않습니다.

태그 추가 시 인터넷 연결이 필요합니다. Codex의 네트워크 제한 환경에서 서버를 실행하면 사람인 요청이 WinError 10013으로 차단될 수 있습니다. 일반 PowerShell에서 위 Flask 실행 명령을 실행하면 해당 Codex 제한을 받지 않습니다.

## 실제 실행 검증 결과 (2026-10-07)

- 실제 Chrome User-Agent requests 응답과 FastAPI 검색 응답을 확인했습니다.
- 최초 전체 수집: 1~20페이지 수집, 21페이지 빈 목록에서 종료, 대상 276개 저장.
- 두 번째 전체 수집: 동일하게 21페이지에서 종료, 신규 0개, DB 276개 유지.
- 저장된 공고 수와 고유 saramin_id 수가 모두 276개입니다.
- 자동 테스트 8개 통과, Python 문법 검사 통과. 추가로 관심 검색의 여러 페이지/경력 공고 수집, 칩의 전체 연결 수, 과거 공고를 포함한 태그 필터를 검증했습니다.
- Flask 서버의 실제 localhost HTTP 응답 200과 화면 HTML을 확인했습니다. 브라우저 시각 검수는 수행하지 않았습니다.

## Windows 요약 알림

수정 파일: `database.py`, `app.py`, `requirements.txt`, `README.md`. 새 파일: `notify.py`, `test_notifications.py`, `run_scheduled_crawl.bat`, `run_notify.bat`. 크롤링 파서와 화면은 그대로 유지합니다.

```powershell
python -m pip install winotify==1.1.0
python notify.py --test  # DB를 읽거나 변경하지 않는 테스트 toast
python notify.py         # 실제 알림 대상 조회 및 발송
# 현재 PC의 테스트용 Python
.\.runtime\python\python.exe notify.py --test
.\.runtime\python\python.exe notify.py
# batch로도 실행 가능
.\run_notify.bat
```

winotify의 [공식 사용 예시](https://github.com/versa-syahptr/winotify#add-action-button)에 있는 `add_actions()`로 `공고 보기` 버튼을 추가했습니다. 버튼은 `http://127.0.0.1:5000`을 열므로 공고를 보려면 Flask 서버가 실행 중이어야 합니다.

### schema와 baseline

- `tags.baseline_ready`: 최초 전체 검색이 성공적으로 완료되었는지(0/1).
- `job_tags.matched_at`: 해당 공고와 태그가 처음 연결된 시각.
- `job_tags.is_baseline`: 최초 검색/웹 수집이면 1, 이후 정기 수집의 새 연결이면 0.
- `notifications`: `id`, `job_id`, `tag_id`, `notified_at`, `batch_id`. `(job_id,tag_id)` UNIQUE이며 태그 연결 삭제 시 알림 처리 기록도 삭제합니다.
- `notification_batches`: `id`, `notification_date UNIQUE`, `notified_at`, `unique_job_count`. 한국 날짜별 한 번의 요약 발송을 기록합니다.

기존 DB는 `init_db()`가 자동 이관합니다. 이미 존재하던 연결은 전부 baseline=1로 두어 처음 알림을 실행했을 때 과거 공고가 쏟아지지 않습니다. 이관을 다시 실행해도 새 연결의 baseline 상태를 덮어쓰지 않습니다. 이 작업 중 `jobs.before_notifications.*.db` 백업도 생성했습니다.

웹 태그 추가와 수동 재수집으로 만들어진 연결은 알림에서 제외합니다. 기존 baseline 연결은 이후 다시 검색되어도 baseline=1을 유지합니다. 정기 수집에서 처음 나타난 연결만 baseline=0이 됩니다. 공고 자체가 이미 jobs에 있어도 특정 태그에는 처음 연결되었다면 알림 대상이 될 수 있습니다. 태그 최초 수집이 중간에 실패하면 baseline_ready=0을 유지하고, 다음 성공한 전체 검색까지는 모두 baseline으로 처리합니다.

### 알림 대상과 중복 방지

알림 ON, 최초 검색 완료, baseline 아님, 아직 `(job_id,tag_id)` 알림 기록 없음 조건을 모두 만족하는 연결을 조회합니다. 태그별 숫자는 각각 집계하고 전체 공고 수는 job_id로 중복 제거합니다. 많으면 toast에는 첫 5개 태그와 나머지 태그 수를 표시하고 모든 대상의 처리 기록은 저장합니다. 날짜 제한 없이 미발송 대상을 처리하므로 놓친 날의 신규 연결도 다음 실행에서 포함합니다.

같은 날 두 번째 알림은 발송하지 않습니다. 발송 후 추가로 발견된 공고는 미발송 상태로 남겨 다음 날에 포함합니다. 대상이 없으면 `새로운 관심 공고가 없습니다.`만 출력합니다. 조회·발송·기록 구간에 SQLite 쓰기 잠금을 유지하여 동시 실행도 직렬 처리합니다.

winotify 기본 실행은 비동기로 오류를 숨기기 때문에, 버전 1.1.0의 알림 실행 부분을 동기 PowerShell 호출로 감싸 종료 코드와 예외를 확인합니다. PowerShell 실패/시간 초과 시 알림 기록과 하루 발송 기록을 남기지 않습니다. 정상 반환 후에만 기록합니다. API 정상 반환은 Windows가 알림 호출을 처리했다는 뜻이며 실제 화면 표시나 사용자의 읽음 확인을 뜻하지 않습니다. Windows 방해 금지/알림 설정에 따라 배너가 숨겨질 수 있습니다. 알림 전송 직후 프로세스가 강제 종료되거나 DB commit이 실패하는 극히 짧은 구간은 Windows와 SQLite를 하나의 트랜잭션으로 묶을 수 없어 재발송 가능성이 있습니다.

### 작업 스케줄러 명령

등록은 자동으로 하지 않았습니다. 사용자의 Python 경로를 확인하고 프로그램에 그 경로를 지정하세요.

```powershell
# 사용하는 conda 환경을 활성화한 터미널에서 실제 경로 확인
python -c "import sys; print(sys.executable)"
```

| 시각 | 프로그램 | 인수 | 시작 위치 |
|---|---|---|---|
| 00:05 | 위에서 확인한 python.exe | `scheduled_crawl.py --slot previous` | 프로젝트 폴더 |
| 09:50 | 동일 | `scheduled_crawl.py --slot today` | 프로젝트 폴더 |
| 10:00 | 동일 | `notify.py` | 프로젝트 폴더 |

toast는 사용자 데스크톱 세션이 필요하므로 알림 작업은 **사용자가 로그온할 때만 실행**을 선택하세요. 작업마다 이미 실행 중일 때 새 인스턴스를 시작하지 않도록 설정하고, 09:50 수집이 10:00 전에 완료되도록 실행 시간을 확인하세요. notify.py는 크롤링을 실행하거나 완료까지 대기하지 않습니다.

batch 파일은 `JOB_TRACKER_PYTHON` 환경변수가 있으면 그 경로, 없으면 현재 `CONDA_PREFIX`의 Python, 다음으로 프로젝트 `.runtime` Python, 마지막으로 PATH의 Python을 사용합니다. 스케줄러에서는 conda 활성화 상태가 상속되지 않을 수 있으므로 위 표처럼 Python 절대 경로를 지정하는 편이 명확합니다. 환경 이름/사용자 Python 경로는 하드코딩하지 않았습니다.

### 검증

```powershell
python -m unittest test_project test_notifications -v
python test_notifications.py --native  # 임시 DB에 테스트 공고 1건으로 실제 Windows 요약 호출
```

기존 테스트 포함 15개 통과. A 대상 없음, B 신규 요약, C 재실행 중복 방지, D OFF 제외, E 최초 태그 검색 제외, 다중 태그 고유 수, 발송 실패 rollback, 하루 제한, 첫 수집 실패 후 복구, 기존 DB 이관을 검증했습니다. 실제 DB의 기존 195개 연결도 모두 baseline으로 이관되어 `notify.py`는 대상 없음으로 종료했고 알림 기록은 0개입니다. Windows 테스트 호출과 임시 DB 실제 요약 호출이 성공했으며 배너의 시각 검수는 수행하지 않았습니다.

사람인 API·OCR·Selenium·ORM·비동기 수집·exe·확장 프로그램·작업 스케줄러 자동 등록·마감 공고 상태 추적은 현재 범위에 없습니다.
