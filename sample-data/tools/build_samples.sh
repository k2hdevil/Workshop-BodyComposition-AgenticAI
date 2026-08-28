#!/usr/bin/env bash
#
# 샘플 결과지 PDF 빌드
#
#   ground-truth/*.json  (단일 원본)
#        -> html/*.html   (중간 산출물, git 미추적)
#        -> pdf/*.pdf     (참가자 배포용)
#        -> 스캔본 지정 문서는 이미지 전용 PDF로 재가공
#
# 사용법:  ./tools/build_samples.sh
#
# 참고: headless Chrome은 --print-to-pdf 작업을 마친 뒤에도 프로세스가 종료되지 않는
#       경우가 있습니다(Chrome 151 확인). 따라서 백그라운드로 띄우고 출력 파일 크기가
#       안정되는 시점을 성공으로 판정한 뒤 해당 인스턴스만 정리합니다.
#
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$(pwd)"

GT_DIR="$ROOT/ground-truth"
HTML_DIR="$ROOT/html"
PDF_DIR="$ROOT/pdf"
mkdir -p "$HTML_DIR" "$PDF_DIR"

CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
if [ ! -x "$CHROME" ]; then
  echo "오류: Chrome을 찾을 수 없습니다 — $CHROME" >&2
  exit 1
fi

# 사용자가 쓰는 Chrome 프로필과 충돌하지 않도록 전용 임시 프로필 사용.
# 이 경로를 커맨드라인에 가진 프로세스만 정리 대상이 되므로 사용자 브라우저는 안전합니다.
PROFILE="$(mktemp -d)"
cleanup() {
  pkill -9 -f "user-data-dir=$PROFILE" 2>/dev/null || true
  rm -rf "$PROFILE"
}
trap cleanup EXIT

WAIT_MAX=45  # PDF 1건당 최대 대기 초

render_pdf() {
  local html="$1" out="$2"
  rm -f "$out"

  "$CHROME" \
    --headless=new \
    --disable-gpu \
    --disable-extensions \
    --user-data-dir="$PROFILE" \
    --no-pdf-header-footer \
    --virtual-time-budget=5000 \
    --print-to-pdf="$out" \
    "file://$html" >/dev/null 2>&1 &
  local pid=$!

  # 파일이 생성되고 크기가 두 번 연속 동일해지면 쓰기 완료로 판정
  local waited=0 prev=-1 size=0
  while [ "$waited" -lt "$WAIT_MAX" ]; do
    sleep 1
    waited=$((waited + 1))
    if [ -f "$out" ]; then
      size=$(wc -c <"$out" | tr -d ' ')
      if [ "$size" -gt 2000 ] && [ "$size" -eq "$prev" ]; then
        break
      fi
      prev=$size
    fi
  done

  kill -9 "$pid" 2>/dev/null || true
  wait "$pid" 2>/dev/null || true
  pkill -9 -f "print-to-pdf=$out" 2>/dev/null || true

  if [ ! -f "$out" ] || [ "$(wc -c <"$out" | tr -d ' ')" -lt 2000 ]; then
    echo "  실패  $(basename "$out") — ${WAIT_MAX}초 내 생성되지 않았습니다" >&2
    return 1
  fi
  printf "  변환  %-24s %8s bytes\n" "$(basename "$out")" "$size"
}

echo "== 1/3  JSON -> HTML 렌더링 =="
for json in "$GT_DIR"/*.json; do
  base="$(basename "$json" .json)"
  python3 tools/render_sheet.py "$json" "$HTML_DIR/$base.html"
done

echo "== 2/3  HTML -> PDF 변환 (headless Chrome) =="
for html in "$HTML_DIR"/*.html; do
  base="$(basename "$html" .html)"
  render_pdf "$html" "$PDF_DIR/$base.pdf"
done

echo "== 3/3  스캔본 재가공 (텍스트 레이어 제거) =="
python3 tools/make_scan.py

echo
echo "빌드 완료. 검증:  python3 tools/verify_samples.py"
