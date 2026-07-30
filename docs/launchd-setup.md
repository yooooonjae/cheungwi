# launchd 등록 — 매일 09:10 자동 갱신

`src/pipeline/refresh.py` 를 하루 한 번 발화시키는 절차다. plist 는 사용자 홈의
`~/Library/LaunchAgents/` 에 놓이므로 저장소에는 들어가지 않는다 — 대신 그 전문과 설치 명령을
여기에 둔다(다른 기계에 옮길 때 이 문서만 보면 된다).

시각을 09:10 으로 잡은 이유: 같은 계정에서 08:40 에 「시차」 수집(`com.sicha.collect`)이 돌기
때문에 그 뒤로 비켜 놓았다. 두 작업이 겹치면 공공 API 쿼터와 네트워크를 동시에 쓴다.

## 1. plist 전문

`~/Library/LaunchAgents/com.cheungwi.refresh.plist`

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>Label</key>
	<string>com.cheungwi.refresh</string>
	<key>ProgramArguments</key>
	<array>
		<string>/Users/iseul/층위/venv/bin/python</string>
		<string>/Users/iseul/층위/src/pipeline/refresh.py</string>
	</array>
	<key>WorkingDirectory</key>
	<string>/Users/iseul/층위</string>
	<key>EnvironmentVariables</key>
	<dict>
		<key>PATH</key>
		<string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
		<key>LANG</key>
		<string>ko_KR.UTF-8</string>
		<key>PYTHONUTF8</key>
		<string>1</string>
		<key>PYTHONIOENCODING</key>
		<string>utf-8</string>
	</dict>
	<key>StartCalendarInterval</key>
	<dict>
		<key>Hour</key>
		<integer>9</integer>
		<key>Minute</key>
		<integer>10</integer>
	</dict>
	<key>RunAtLoad</key>
	<false/>
	<key>StandardOutPath</key>
	<string>/Users/iseul/층위/logs/refresh-launchd.log</string>
	<key>StandardErrorPath</key>
	<string>/Users/iseul/층위/logs/refresh-launchd.log</string>
</dict>
</plist>
```

## 2. 설치·발화·해제

```sh
# 설치(부트스트랩). 이미 올라와 있으면 bootout 으로 내리고 다시 올린다.
launchctl bootout  gui/$(id -u)/com.cheungwi.refresh 2>/dev/null
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.cheungwi.refresh.plist

# 등록 확인 — 마지막 종료 코드(last exit code)와 다음 발화 시각이 보인다
launchctl print gui/$(id -u)/com.cheungwi.refresh | head -30

# 지금 한 번 돌려 보기(예약과 무관하게 즉시 발화. -k 는 돌고 있으면 죽이고 다시)
launchctl kickstart -k gui/$(id -u)/com.cheungwi.refresh

# 결과 확인 — started 를 함께 본다(오늘 날짜가 아니면 오늘은 아예 돌지 않은 것이다)
python3 -c "import json;d=json.load(open('logs/refresh-status.json'));\
print(d['started'], d['state'], d['ok'], d['failures'], d['resume_needed'])"
tail -40 logs/refresh-launchd.log

# 해제
launchctl bootout gui/$(id -u)/com.cheungwi.refresh
```

`launchctl load/unload` 는 낡은 인터페이스다. `bootstrap`/`bootout`/`kickstart` 를 쓴다.

## 3. launchd 는 로그인 셸의 환경을 물려주지 않는다

이 시리즈에서 실제로 겪은 사고들이라 세 가지를 못 박아 둔다.

**PATH.** launchd 가 주는 기본 PATH 는 `/usr/bin:/bin:/usr/sbin:/sbin` 뿐이다. Homebrew 로 깐
`node`·`npx`(`/opt/homebrew/bin`)가 거기 없으므로, PATH 를 명시하지 않으면 배포 단계가
"npx 를 PATH 에서 찾지 못했다"로 끝난다. refresh.py 는 `shutil.which("npx")` 로 찾는다 —
경로를 코드에 박지 않는 대신 **plist 의 `EnvironmentVariables/PATH` 가 그 근거**다.
(수지에서는 반대로 코드에 `/opt/homebrew/bin/npx` 를 박아 두었고, 그 탓에 Homebrew 경로가
다른 기계에서는 조용히 배포가 빠졌다.)

**LANG.** LANG 이 비면 파이썬 표준출력이 ASCII 로 잡혀 한글을 찍는 순간
`UnicodeEncodeError` 로 죽는다. plist 에 `LANG`·`PYTHONUTF8`·`PYTHONIOENCODING` 을 넣어 두고,
refresh.py 도 자식 프로세스에 `PYTHONIOENCODING=utf-8`·`PYTHONUTF8=1` 을 다시 붙여 부른다
(둘 다 있어야 한다 — plist 는 부모만, 코드는 자식만 지킨다).

**TCC(파일 접근 권한).** launchd 에서 발화된 프로세스는 Finder 에서 실행한 것과 권한 주체가
다르다. 저장소가 `~/Desktop`·`~/Documents`·외장 볼륨 아래 있으면 읽기·쓰기가 조용히 거부되고
그 실패가 로그에만 남는다(G2B 백업이 2주간 이 이유로 아무것도 남기지 못한 전력이 있다).
`~/층위` 는 보호 대상 폴더가 아니라 지금은 문제가 없지만, 저장소를 옮기면
`시스템 설정 → 개인정보 보호 및 보안 → 전체 디스크 접근 권한`에 실행 파이썬을 등록해야 한다.

## 4. Cloudflare 인증

배포는 `npx wrangler pages deploy web --project-name cheungwi` 다. wrangler 는 이 계정에 이미
로그인돼 있고(`~/Library/Preferences/.wrangler`), launchd 발화도 같은 사용자라 그 자격을
그대로 쓴다.

**프로젝트는 한 번 손으로 만들어야 한다.** 예전 wrangler 는 첫 배포 때 Pages 프로젝트를
자동 생성했지만 4.x 는 없는 프로젝트에 배포하면 `The Pages project "cheungwi" does not exist`
로 끝난다(2026-07-31 실측, wrangler 4.116). 새 계정·새 기계에서는 딱 한 번:

```sh
npx wrangler pages project create cheungwi --production-branch main
``` 토큰을 쓰는 기계로 옮긴다면 `CLOUDFLARE_API_TOKEN` 을 환경변수로 주되
**plist 에 토큰 값을 적지 말고** 별도 파일(`~/.config/cheungwi/env`)을 읽는 래퍼를 쓴다 —
plist 는 평문이고 Time Machine 에 그대로 실린다.

인증이 끊기면 배포 단계만 FAIL 로 남고 사이트는 직전 배포를 계속 서빙한다. 다시
`npx wrangler login` 한 뒤 `make refresh` 를 한 번 돌리면 된다.

## 5. 무엇이 남는가

| 자리 | 내용 |
|---|---|
| `logs/refresh-YYYYMMDD-HHMM.log` | 그 실행의 자식 출력 전량(수집기·엔진·빌더·wrangler) |
| `logs/refresh-status.json` | 마지막 실행의 기계 판독 요약 — `started`·`state`·`ok`, 단계별 ok·사유·초·마커, 실패 목록, 배포 여부 |
| `logs/refresh-launchd.log` | launchd 가 받은 stdout/stderr(파이프라인 요약 JSON 이 그대로 찍힌다) |

성공·실패 모두 macOS 알림이 한 번 뜬다(하루 한 번이라 소음이 아니다).
`resume_needed` 에 오른 수집기는 실패가 아니라 **다음 실행이 이어받을 것**이라는 뜻이다 —
건축물대장 활용신청이 승인되기 전까지 `buildings` 는 늘 여기에 오른다.

상태 파일은 **일하기 전에 한 번**(`state: running`·`ok: false`) 쓰고 끝에 다시 덮는다.
그래서 파이프라인이 트레이스백으로 즉사한 날에도 이 파일이 전날의 `ok: true` 로 남아 있지
않는다 — 예외는 `failures` 와 `traceback` 으로 환원되고 `state` 는 `crashed` 가 된다.
`state` 가 `running` 인 채 멈춰 있으면 지금 돌고 있거나, 도중에 기계가 꺼진 것이다.
