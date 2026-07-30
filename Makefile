# 「층위(層位)」 — 서울 오피스 언더라이팅 리서치
# 표준 워크플로: make setup → collect → manifest → analyze → build → test
# 매일 도는 것은 make refresh 하나다(수집부터 배포까지). launchd 는 docs/launchd-setup.md.
# venv 가 있으면 그 파이썬을, 없으면 시스템 python3 를 사용한다.

PY := $(shell if [ -x venv/bin/python ]; then echo venv/bin/python; else echo python3; fi)
# Chrome/Chromium 자동 탐색(이식성) — PATH 우선, 없으면 macOS 앱 경로 폴백.
CHROME ?= $(shell command -v google-chrome-stable || command -v google-chrome \
	 || command -v chromium || command -v chromium-browser || command -v chrome \
	 || echo "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
.DEFAULT_GOAL := help
.PHONY: help setup collect manifest analyze build serve test check responsive og refresh dryrun

help: ## 타깃 목록
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-12s %s\n", $$1, $$2}'
setup: ## venv 생성 + 의존성 설치
	python3 -m venv venv && venv/bin/pip install -U pip -q && venv/bin/pip install -r requirements.txt -q
collect: ## 수집기 전체 실행 (재개형 — 쿼터 소진 시 다음 실행이 이어받음)
	@for s in rone_office rates buildings trades reits; do echo "== $$s =="; $(PY) src/collect/$$s.py || exit 1; done
manifest: ## 데이터 원장 갱신
	$(PY) src/build/manifest.py
analyze: ## 엔진을 실데이터에 적용해 out/*.json 4종 생성 (멱등·원자적)
	$(PY) -m src.analysis.build_out
build: ## site/ 를 web/ 정적 산출로 굽는다 (원자적 — 실패하면 기존 web/ 그대로)
	$(PY) src/build/assemble.py
refresh: ## 수집→분석→원장→빌드→검증→배포 (ARGS 로 인자 전달: ARGS="--only trades")
	$(PY) src/pipeline/refresh.py $(ARGS)
dryrun: ## 수집·배포 없이 파이프라인 뒷단만 (분석→원장→빌드→검증)
	$(PY) src/pipeline/refresh.py --skip-collect --no-deploy
serve: ## web/ 을 로컬에서 서빙한다 (기본 8768, 봇 차단·noindex)
	$(PY) serve.py
test: ## pytest
	$(PY) -m pytest tests/ -q
check: ## 검사 묶음 — 바이트컴파일·스크립트 문법·전체 스위트·빌드 게이트 (CI 가 이것을 그대로 부른다)
	find src -name '*.py' -print0 | xargs -0 $(PY) -m py_compile
	@for f in site/js/*.js; do echo "node --check $$f"; node --check "$$f" || exit 1; done
	CHEUNGWI_REQUIRE_ARTIFACTS=1 $(PY) -m pytest tests/ -q
	$(PY) src/build/assemble.py
	@echo "검사 통과 (바이트컴파일·스크립트 문법·전체 스위트·빌드 게이트) — CI 와 같은 명령이다"
responsive: ## web/ 을 다섯 뷰포트에서 실제로 재고 다크 스크린샷을 남긴다 (make build 뒤)
	node tests/responsive_check.js
og: ## OG 카드 재생성 (src/build/og_card.html → site/static/og.png · 정확히 1200×630)
	@rm -f site/static/og.png
	"$(CHROME)" --headless=new --disable-gpu --hide-scrollbars --force-device-scale-factor=1 \
	  --window-size=1200,630 --screenshot=site/static/og.png "file://$(CURDIR)/src/build/og_card.html"
	@$(PY) -c "import sys,pathlib;p=pathlib.Path('site/static/og.png');\
	sys.exit('og.png 이 만들어지지 않았다 — 크롬을 찾았는지 보라(CHROME=... 로 지정 가능)') if not p.is_file() else None;\
	b=p.read_bytes();w=int.from_bytes(b[16:20],'big');h=int.from_bytes(b[20:24],'big');\
	sys.exit(None if b[:8]==b'\x89PNG\r\n\x1a\n' and (w,h)==(1200,630) else 'og.png 이 1200x630 PNG 가 아니다: %dx%d' % (w,h))"
	@echo "og.png 재생성 (1200×630) — 커밋 대상이다"
