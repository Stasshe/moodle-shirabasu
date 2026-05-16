"""軽量 CLI: Aura 呼び出しとページ抽出をモジュール化して利用する。"""

import sys
import webbrowser
import json
from pathlib import Path
import argparse
from typing import Optional

from syllabus.aura import academic_year, load_ctx, save_ctx, call_api, fetch_fresh_ctx
from syllabus.parser import fetch_page, parse_syllabus, page_looks_rendered


PROJECT_ROOT = Path(__file__).resolve().parent
INPUT_FILE = PROJECT_ROOT / "in" / "codes.txt"
OUTPUT_DIR = PROJECT_ROOT / "out"


def process_code(raw: str, default_year: str, ctx: dict, open_browser: bool) -> None:
    raw = raw.strip()
    if not raw or not raw.isdigit():
        print(f"無効なコードをスキップ: {raw}")
        return

    if len(raw) == 5:
        course_code = default_year + raw
        year = default_year
    elif len(raw) == 9:
        course_code = raw
        year = raw[:4]
    else:
        print(f"桁数が合いません ({len(raw)}桁)。スキップ: {raw}")
        return

    print(f"\n処理: {course_code}")

    print("  検索中...", end=" ", flush=True)
    url, ctx_err = call_api(course_code, year, ctx)

    if ctx_err:
        print("fwuid が古い模様。自動更新を試みます...")
        fresh = fetch_fresh_ctx()
        if fresh:
            save_ctx(fresh)
            ctx.update(fresh)
            print("  リトライ中...", end=" ", flush=True)
            url, _ = call_api(course_code, year, ctx)
        else:
            print("  自動更新に失敗しました。")

    if not url:
        print("シラバスが見つかりませんでした。")
        return

    print("見つかりました。")
    print(f"  {url}")

    html = fetch_page(url, render_with_selenium=False)
    if not html or not page_looks_rendered(html):
        html = fetch_page(url, render_with_selenium=True)

    if not html:
        print("ページの取得に失敗しました (urllib/selenium)。")
        if open_browser:
            webbrowser.open(url)
        return

    parsed = parse_syllabus(html)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_file = OUTPUT_DIR / f"syllabus_{course_code}.json"
    with open(out_file, "w") as f:
        json.dump(parsed, f, ensure_ascii=False, indent=2)

    teachers = parsed.get('teachers') or []
    fields = parsed.get('fields') or []
    tables = parsed.get('tables') or []
    lists = parsed.get('lists') or []
    print(f"  担当教員: {', '.join(teachers) if teachers else '未検出'}")
    print(f"  項目数: {len(fields)}, テーブル数: {len(tables)}, リスト数: {len(lists)}")

    if fields:
        print("  抽出項目の例:")
        for field in fields[:5]:
            label = field.get('label', '')
            value = field.get('value', '')
            preview = value.replace('\n', ' / ')
            if len(preview) > 80:
                preview = preview[:80] + '...'
            print(f"    - {label}: {preview}")

    if open_browser:
        webbrowser.open(url)


def main(argv: Optional[list[str]] = None):
    p = argparse.ArgumentParser(description='Ritsumei syllabus fetcher')
    p.add_argument('code', nargs='?', help='授業コード (5桁 or 9桁)')
    p.add_argument('--open', action='store_true', help='処理後にブラウザで開く')
    args = p.parse_args(argv)

    year = academic_year()

    ctx = load_ctx()
    if ctx is None:
        print("キャッシュがないので Aura コンテキストを取得中...")
        ctx = fetch_fresh_ctx()
        if not ctx:
            print("Aura コンテキストの取得に失敗しました。")
            return
        save_ctx(ctx)

    # 単発コードがあればそれを処理、なければ固定入力ファイルを読む
    if args.code:
        process_code(args.code, year, ctx, open_browser=args.open)
        return

    if not INPUT_FILE.exists():
        print(f"入力ファイルが見つかりません: {INPUT_FILE}")
        return

    with open(INPUT_FILE, 'r') as fh:
        lines = [line.strip() for line in fh if line.strip()]
    for line in lines:
        process_code(line, year, ctx, open_browser=args.open)
    print('\nバッチ処理完了')


if __name__ == '__main__':
    main()