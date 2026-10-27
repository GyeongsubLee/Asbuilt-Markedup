# ISO Mark-up → As-built 반영 QC

CIMS MARK-UP ISO 의 수정사항이 AS-BUILT ISO 에 반영되었는지 자동으로 확인하고 보고서(Excel + HTML)를 만듭니다.

- **1. Routing 반영 여부** – 도면부의 삭선/덮어쓰기/추가 기입이 As-built 에 있는지
- **2. Line Condition 반영 여부** – Condition 표(OPER/DESIGN/TEST/INSULATION/NDE/PAINT/PWHT … , LOCAL REGULATION)의 값이 바뀌었는지

## 사용법

```
작업폴더\
 ├─ CIMS MARK-UP ISO\   ISO-1TC-PL-2302-30-024-01_3B.pdf ...
 ├─ AS BUILT ISO\       ISO-1TC-PL-2302-30-024-01_Sheet1-Model.pdf ...
 └─ ISO_QC.exe  (또는 iso_qc.py + run_qc.bat)
```

1. 작업폴더에 프로그램을 넣고 실행 (더블클릭). 폴더 이름에 `MARK-UP`, `AS BUILT`(또는 `AS-BUILT`)가 들어 있으면 자동으로 찾습니다. 하위 폴더까지 PDF 를 찾습니다.
2. 파일명의 첫 `_` 왼쪽(ISO No)으로 두 폴더의 파일을 매칭합니다.
3. `QC_REPORT_날짜_시각\` 폴더에 결과가 생깁니다.
   - `ISO_QC_Report.xlsx` – **요약**(ISO별 종합판정, Routing/Condition 판정), **상세**(Mark-up 항목별 기존값/변경값/As-built 값/판정/이미지 링크), **미매칭**, **정보**
   - `ISO_QC_Report.html` – 검색 가능한 목록 → ISO 별 페이지에서 MARK-UP / AS-BUILT 비교 이미지 확인 (초록=변경값 찾음, 빨강=기존값/불일치)
   - `errors.log` – 열리지 않은 PDF 등

### Python 으로 바로 실행 (권장)

```
pip install -r requirements.txt          (처음 한 번)
python iso_qc.py --base "C:\샤힌QC"      (작업폴더 지정)
python iso_qc.py                          (작업폴더에서 실행하면 --base 생략 가능)
```

`--base` 를 생략하면 현재 폴더 → `iso_qc.py` 가 있는 폴더 순서로 MARK-UP / AS-BUILT 폴더를 찾습니다.
`build_exe.bat` / `run_qc.bat` 는 Python 이 없는 PC 에 배포할 때만 필요합니다.

주요 옵션

| 옵션 | 설명 |
|---|---|
| `--base 폴더` | 작업폴더 (기본: 프로그램 위치) |
| `--markup-dir`, `--asbuilt-dir` | 폴더 직접 지정 |
| `--workers N` | 동시 처리 수 (기본 CPU-1) |
| `--only 024-01`, `--limit 20` | 일부만 시험 |
| `--no-images` | 비교 이미지 생략 (빠름) |
| `--near 0.06` | 검색 반경 (페이지 대각선 비율). 위치가 많이 바뀐 도면이 많으면 0.08~0.1 |
| `--ignore-text 문구` | Mark-up 으로 보지 않을 문구 (예: 검토자 이름 스탬프) |
| `--use-shx-text` | As-built 에 실제 문자가 없고 'AutoCAD SHX Text' 주석에만 문자가 있을 때 사용 (기본은 무시) |
| `--no-flattened` | 색상 문자/선 검출 끄기 (주석이 아닌, 페이지에 합쳐진 Mark-up 검출) |

## exe 배포

**방법 1 – GitHub 에서 자동 빌드 (PC 에 Python 불필요)**
1. GitHub 저장소 → **Actions** → **Build Windows exe** → **Run workflow** (브랜치 선택) 클릭
2. 5분쯤 뒤 완료된 실행을 열고 아래 **Artifacts → ISO_QC** 를 내려받아 압축 해제 → `ISO_QC.exe`
   (빌드 전에 샘플 시험 + exe 실행 시험까지 자동으로 합니다)
3. `v1.0.0` 같은 태그를 push 하면 Releases 페이지에 `ISO_QC.exe` 가 첨부됩니다.

**방법 2 – 내 PC 에서 빌드**: Python 3.10 이상 설치 후 `build_exe.bat` 더블클릭 → `dist\ISO_QC.exe`

**받는 사람 사용법**: `ISO_QC.exe` 를 `CIMS MARK-UP ISO` / `AS BUILT ISO` 폴더가 있는 폴더에 넣고 더블클릭.
처음 실행 시 압축을 푸느라 10초 정도 걸리고, 백신이 검사할 수 있습니다.

## 판정 방법

Mark-up 은 PDF 주석(FreeText, StrikeOut, Line, Ink, Polygon(구름), Square/Circle, Stamp …)과
페이지에 합쳐진 빨강/파랑 등 **색상 문자·선**에서 읽습니다. As-built 의 `AutoCAD SHX Text` 주석은 무시합니다.

| Mark-up 형태 | 해석 | As-built 확인 |
|---|---|---|
| 글자에 삭선 + 근처에 새 글자 (사진 1, 5) | 변경 | 같은 문맥 라인(예: `ORIENT HANDLE ___`)에서 새 값이면 반영, 기존값이면 미반영 |
| 숫자 위를 박스로 덮고 새 숫자 (사진 4) | 변경 | 해당 위치 근처에 새 숫자 → 반영, 기존 숫자만 → 미반영 |
| Condition 칸을 덮고 새 값 (사진 3) | Condition 변경 | As-built Condition 표의 **같은 칸** 값과 비교 |
| 삭선만 | 삭제 | 기존값이 남아 있으면 미반영 |
| 새 글자만 | 추가 | 근처에 있으면 반영 |
| 글자 없는 구름/원 | 형상 변경 | **육안확인** (이미지 제공) |
| 서명 박스 (Ink 서명 + 둘레 박스 + `PIPING FE …` 문구) | – | 보고서에서 **제외** |
| 우측 하단 Title/REV 영역 (REV NO 등) | – | **제외** (요약 비고에 제외 건수 표시) |
| 용접 번호 원 (`FW5`, `F12` … F 로 시작하는 번호) | – | **제외** |

제외 문구 규칙은 `isoqc/config.py` 의 `SIGN_TEXT_PATTERNS`, `WELD_TEXT_PATTERN` 에서 바꿀 수 있습니다.

비교 이미지는 가까운 Mark-up 끼리 한 장으로 묶고, Line Condition 항목은 표 한 장에 모두 표시합니다.

두 도면은 공통 문자(표제란, BOM, Note 등)로 좌표를 자동 정렬하므로 As-built 를 다시 출력해 크기/위치가 조금 달라도 됩니다.
숫자는 `65` = `65.0`, 대소문자 무시로 비교합니다.

**ISO 종합판정**: 미반영이 하나라도 있으면 `NG` → 확인필요 → 육안확인 → `OK` 순.
NG/확인필요/육안확인 ISO 만 이미지를 보고 확인하면 됩니다.

## 시험

```
python tests/make_samples.py sample_data   # 가상 Mark-up/As-built PDF 생성
python tests/test_samples.py               # 전체 동작 확인
```

## 한계 / 실제 도면으로 조정이 필요할 수 있는 부분

- 실제 CIMS Mark-up PDF 로는 아직 시험하지 않았습니다(가상 PDF 로 검증). 처음엔 `--limit 20` 으로 돌려 결과를 확인해 주세요.
- 손글씨(Ink)로 쓴 값은 문자를 읽을 수 없어 서명과 같이 `참고`로 분류됩니다.
- Mark-up 이 스캔 이미지(래스터)라면 문자를 읽을 수 없습니다 (OCR 미지원).
- Condition 표/BOM/Title 위치는 표 머리글 단어로 찾고, 못 찾으면 HDL/SHAHEEN 양식 비율(`isoqc/config.py`)을 씁니다.
