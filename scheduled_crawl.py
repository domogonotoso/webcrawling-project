import argparse
from database import run_import

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='정기 전체/관심 태그 적재')
    parser.add_argument('--slot', choices=['auto', 'previous', 'today'], default='auto')
    parser.add_argument('--max-page', type=int, default=300)
    parser.add_argument('--delay', type=float, default=3)
    args = parser.parse_args()
    try:
        print(f'정기 적재 완료: 신규 {run_import(slot=args.slot, max_page=args.max_page, delay=args.delay)}개')
    except Exception as error:
        parser.exit(1, f'정기 적재 실패: {error}\n')
