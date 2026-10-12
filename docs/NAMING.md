# DDoSpector naming and compatibility

- Product: **DDoSpector**
- Subtitle: **AI-Powered DDoS Defense Validation Framework**
- Tagline: **Find the gaps before attackers do.**
- Description: AI-powered open-source framework for automated DDoS defense testing, mitigation gap discovery, and security validation.
- Python distribution: `ddospector`; Web package: `ddospector-ui`.

These identity strings follow the operator's `NAME.md`. They describe the project direction, not a claim that LIVE traffic, inference, device control or full S02 acceptance is implemented. Existing OFFLINE restrictions are unchanged.

## Public entry points

```sh
uv sync --frozen
.venv/bin/python -m uvicorn ddospector.api.app:app --host 127.0.0.1 --port 5180
.venv/bin/python -m ddospector.api.scenario_recovery --help
.venv/bin/python -m ddospector.runs.migrate
.venv/bin/python -m ddospector.runs.worker
```

The migration and worker require the existing separately provisioned private PostgreSQL endpoint. These examples are not automatic setup or authority to start a service. `make api` and `make runs-migrate` use the new public module names.

The internal `aiddos` implementation package remains installed. The new `ddospector` entry modules delegate to the existing functions and app object rather than loading a second implementation. This preserves shared class identities, locks, owner registries, legacy imports and existing producer-origin evidence. The new namespace exposes the documented entry points, not a second copy of every internal module. Existing `python -m aiddos...` commands still work.

## Startup-setting compatibility

| Preferred setting | Legacy fallback |
|---|---|
| `DDOSPECTOR_UI_STATE_PATH` | `AIDDOS_UI_STATE_PATH` |
| `DDOSPECTOR_SCENARIO_RECOVERY_TICKET` | `AIDDOS_SCENARIO_RECOVERY_TICKET` |
| `DDOSPECTOR_RUN_DB_SOCKET` | `AIDDOS_RUN_DB_SOCKET` |

A new setting takes precedence whenever present, including an empty value. Invalid or empty new configuration never silently adopts a legacy value. The existing caller validation still applies. Nonempty explicit `create_app(state_path=...)` arguments retain their precedence; an empty-string argument retains the existing environment fallback. This argument fallback does not make an empty preferred environment variable fall back to a legacy variable. A recovery ticket remains a one-use startup handoff, not a persistent setting; never save it in `.env`, logs or automatic restart configuration. Operator-supplied model credential-reference names are not renamed or resolved.

## Deliberately unchanged identifiers and data

- Draft and scenario paths, state formats, record identities, digests and recovery artifacts.
- PostgreSQL database/roles `aiddos_s02`, `aiddos_s02_owner`, schema `aiddos_runs_v1`, migration SQL and its checksum.
- Browser locale preference `aegis.locale` and pending receipt `aiddos.s02.pending.v1`.
- Existing frozen producer fixtures, raw response bytes and historical verification records/contracts.
- API routes, safety boundaries, loopback ports and OFFLINE behavior.

No data migration, database rename, service restart, directory move or Git history rewrite is part of this current-source rename. The checkout directory may therefore still be named `aiddostesting`. Earlier archived history-transition preparation is not proof of rewritten current history. The original `NAME.md` and `PLAN.md` remain operator-owned inputs.

## 한국어 요약

화면·브라우저 제목·배포 패키지와 공식 실행 명령을 DDoSpector로 변경합니다. 이전 실행 명령과 `AIDDOS_*` 설정은 호환 경로로 유지합니다. `DDOSPECTOR_*`가 존재하면 빈 값이어도 우선하며, 기존 값으로 자동 우회하지 않습니다. 언어 선택·대기 영수증·저장 데이터·DB 식별자와 과거 증거는 이름 변경 때문에 재작성하지 않습니다. 이번 작업은 전체 S02 완료나 서비스 재시작을 의미하지 않습니다.
