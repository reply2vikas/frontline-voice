#!/bin/bash
pass(){ printf "  PASS  %s\n" "$1"; }
fail(){ printf "  FAIL  %s\n" "$1"; F=1; }
F=0
echo "=== FILE LAYOUT ==="
for f in backend/app/simulator.py backend/app/engine.py backend/app/safety.py \
         backend/static/index.html backend/static/app.css backend/static/app.js \
         backend/static/favicon.svg backend/data/precedent_corpus.json \
         backend/data/sop_corpus.json backend/tests/test_a11y.py \
         backend/tests/test_simulator.py backend/Dockerfile README.md; do
  [ -f "$f" ] && pass "$f" || fail "$f MISSING"
done

echo; echo "=== V2 MARKERS ==="
grep -q 'role="tablist"' backend/static/index.html && pass "3 tabs present" || fail "tabs missing"
grep -q 'favicon.svg' backend/static/index.html && pass "favicon linked" || fail "favicon not linked"
grep -q 'venue-state' backend/app/main.py && pass "map endpoint present" || fail "map endpoint missing"

echo; echo "=== RENAME ==="
if grep -rqi "micro-megaphone" --exclude-dir=.venv --exclude-dir=.git . 2>/dev/null; then
  fail "old name still present:"; grep -ril "micro-megaphone" --exclude-dir=.venv --exclude-dir=.git . 2>/dev/null | sed 's/^/        /'
else pass "no old name anywhere"; fi
grep -q "Frontline Voice" backend/static/index.html && pass "new name in UI" || fail "new name missing in UI"

echo; echo "=== REPO HYGIENE ==="
[ -z "$(find . -name '*.tar.gz' -not -path './.venv/*' 2>/dev/null)" ] && pass "no archives in repo" || fail "archives present - move them out"
[ -z "$(find . -name '*.db' -not -path './.venv/*' 2>/dev/null)" ] && pass "no db committed" || fail "*.db present"
echo "  size: $(du -sh --exclude=.venv --exclude=.git . 2>/dev/null | cut -f1)"

echo; [ "$F" = 1 ] && echo ">>> ISSUES FOUND ABOVE" || echo ">>> ALL CHECKS PASSED"
