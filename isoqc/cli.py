"""Command line / double-click entry point."""
from __future__ import annotations

import argparse
import multiprocessing as mp
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime

from . import __version__
from .config import Options
from .discover import find_dirs, pair_files
from .process import _safe, process_pair, verdict
from .report import write_excel, write_html


def _program_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.getcwd()


def parse_args(argv=None):
    ap = argparse.ArgumentParser(
        description="CIMS MARK-UP ISO 의 수정사항이 AS-BUILT ISO 에 반영되었는지 검사하고 보고서를 만듭니다.")
    ap.add_argument("--base", default=None, help="MARK-UP / AS-BUILT 폴더가 있는 폴더 (기본: 프로그램 위치)")
    ap.add_argument("--markup-dir", default=None, help="MARK-UP ISO 폴더 직접 지정")
    ap.add_argument("--asbuilt-dir", default=None, help="AS-BUILT ISO 폴더 직접 지정")
    ap.add_argument("--out", default=None, help="보고서 폴더 (기본: base\\QC_REPORT_날짜시각)")
    ap.add_argument("--workers", type=int, default=0, help="동시 처리 개수 (기본: CPU 수)")
    ap.add_argument("--only", default=None, help="이 문자열이 ISO No 에 포함된 것만 검사")
    ap.add_argument("--limit", type=int, default=0, help="앞에서부터 N 개만 검사 (시험용)")
    ap.add_argument("--no-images", action="store_true", help="비교 이미지 생략 (빠름)")
    ap.add_argument("--no-flattened", action="store_true", help="페이지에 합쳐진(flatten) 색상 mark-up 검출 끄기")
    ap.add_argument("--use-shx-text", action="store_true",
                    help="AS-BUILT 의 'AutoCAD SHX Text' 주석도 문자로 사용 (기본: 무시)")
    ap.add_argument("--near", type=float, default=0.06, help="검색 반경 (페이지 대각선 비율, 기본 0.06)")
    ap.add_argument("--ignore-text", action="append", default=[],
                    help="mark-up 으로 보지 않을 문구 (여러 번 지정 가능)")
    ap.add_argument("--no-pause", action="store_true", help="끝난 뒤 Enter 대기 안 함")
    return ap.parse_args(argv)


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:  # never crash on a console that cannot show Korean
            stream.reconfigure(errors="replace")
        except Exception:
            pass
    args = parse_args(argv)
    base = os.path.abspath(args.base or _program_dir())
    markup_dir, asbuilt_dir = find_dirs(base)
    if not args.base and not (markup_dir and asbuilt_dir):
        # "python C:\tools\iso_qc.py" run from elsewhere: also try the script's folder
        script_dir = os.path.dirname(os.path.abspath(sys.argv[0] or "."))
        if script_dir != base:
            found = find_dirs(script_dir)
            if found[0] and found[1]:
                base, (markup_dir, asbuilt_dir) = script_dir, found
    markup_dir = args.markup_dir or markup_dir
    asbuilt_dir = args.asbuilt_dir or asbuilt_dir
    pause = getattr(sys, "frozen", False) and not args.no_pause

    if not markup_dir or not asbuilt_dir:
        print(f"[오류] '{base}' 아래에서 MARK-UP / AS-BUILT 폴더를 찾지 못했습니다.")
        print(f"       MARK-UP : {markup_dir}\n       AS-BUILT: {asbuilt_dir}")
        print("       폴더 이름에 'MARK-UP' 과 'AS-BUILT' (또는 AS BUILT) 가 들어가야 합니다.")
        if pause:
            input("Enter 를 누르면 종료합니다...")
        return 2

    opts = Options(near_ratio=args.near, detect_flattened=not args.no_flattened,
                   use_shx_text=args.use_shx_text, images=not args.no_images,
                   extra_ignore_text=tuple(args.ignore_text))
    pairs, markup_only, asbuilt_only, dups = pair_files(markup_dir, asbuilt_dir)
    if args.only:
        pairs = [p for p in pairs if args.only.upper() in p[0]]
    if args.limit:
        pairs = pairs[:args.limit]

    out = args.out or os.path.join(base, "QC_REPORT_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
    os.makedirs(out, exist_ok=True)
    print(f"ISO Mark-up QC v{__version__}")
    print(f"MARK-UP  폴더: {markup_dir}")
    print(f"AS-BUILT 폴더: {asbuilt_dir}")
    print(f"매칭 {len(pairs)}건 · As-built 없음 {len(markup_only)}건 · Mark-up 없음 {len(asbuilt_only)}건")
    print(f"보고서 폴더  : {out}\n")

    t0 = time.time()
    results = []
    workers = args.workers or max(1, (os.cpu_count() or 2) - 1)
    if workers == 1 or len(pairs) <= 2:
        for n, (k, m, a) in enumerate(pairs, 1):
            r = process_pair(k, m, a, out, opts)
            results.append(r)
            print(f"[{n}/{len(pairs)}] {k}: {verdict(r)}")
    else:
        with ProcessPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(process_pair, k, m, a, out, opts): k for k, m, a in pairs}
            for n, f in enumerate(as_completed(futs), 1):
                r = f.result()
                results.append(r)
                print(f"[{n}/{len(pairs)}] {r['iso']}: {verdict(r)}")

    results.sort(key=lambda r: (r["iso"], r["markup"]))
    for r in results:
        r["html"] = _safe(os.path.splitext(os.path.basename(r["markup"]))[0]) + ".html"
    meta = {
        "실행 시각": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "기준 폴더": base,
        "MARK-UP 폴더": markup_dir,
        "AS-BUILT 폴더": asbuilt_dir,
        "매칭 건수": len(pairs),
        "소요 시간(초)": round(time.time() - t0, 1),
        "옵션": f"near={opts.near_ratio}, flattened={opts.detect_flattened}, shx_text={opts.use_shx_text}",
    }
    xlsx = write_excel(results, markup_only, asbuilt_only, dups, out, meta)
    page = write_html(results, out, meta)
    with open(os.path.join(out, "errors.log"), "w", encoding="utf-8") as f:
        for r in results:
            if r.get("error"):
                f.write(f"{r['markup']}\n{r.get('trace', r['error'])}\n\n")

    tally: dict = {}
    for r in results:
        tally[verdict(r)] = tally.get(verdict(r), 0) + 1
    print("\n결과: " + ", ".join(f"{k} {v}" for k, v in sorted(tally.items())))
    print(f"Excel : {xlsx}\nHTML  : {page}")
    if pause:
        input("\nEnter 를 누르면 종료합니다...")
    return 0


if __name__ == "__main__":
    mp.freeze_support()
    sys.exit(main())
