# 「층위(層位)」 — 서울 오피스 언더라이팅 리서치
# 표준 워크플로: make setup → collect → manifest → analyze → build → test
# 매일 도는 것은 make refresh 하나다(수집부터 배포까지). launchd 는 docs/launchd-setup.md.
# venv 가 있으면 그 파이썬을, 없으면 시스템 python3 를 사용한다.

PY := $(shell if [ -x venv/bin/python ]; then echo venv/bin/python; else echo python3; fi)
.DEFAULT_GOAL := help
.PHONY: help setup collect manifest analyze build serve test responsive refresh dryrun

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
responsive: ## web/ 을 다섯 뷰포트에서 실제로 재고 다크 스크린샷을 남긴다 (make build 뒤)
	node tests/responsive_check.js
