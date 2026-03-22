#!/usr/bin/env python3
"""
버전별 추천 응답 시간 통합 보고서

측정 항목:
  e2e_sec    = POST 전송 ~ COMPLETED 수신까지 (perf_counter 기준, 클라이언트 측정)
  server_sec = completedAt(UTC) − POST 전송 시각(UTC)  ← API 무변경, localhost 기준 정확
  overhead   = e2e_sec − server_sec  (폴링 대기 + 네트워크 왕복)

  V1은 동기 응답이라 e2e ≈ server이므로 overhead 항목은 생략합니다.

전제 조건:
  uvicorn app.main:app --port 8000

사용법:
  python latency.py
  python latency.py --url http://host:8000 --repeat 5
  python latency.py --skip-v1
  python latency.py --skip-v2
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpx

# ── 설정 ─────────────────────────────────────────────────────────────────────
DEFAULT_URL = "http://localhost:8000"
DEFAULT_REPEAT = 3
POLL_INTERVAL_SEC = 0.5
POLL_TIMEOUT_SEC = 120.0

SURVEY_PAYLOAD: dict = {
    "surveyData": {
        "routineCount": 2,
        "survey": [
            {
                "questionContent": "최근 1주일 동안, 목 부위의 불편함이나 통증은 어느 정도였나요?",
                "selectedOptionSortOrder": 3,
            },
            {
                "questionContent": "최근 1주일 동안, 어깨 부위에 뻐근함이나 통증을 느낀 정도는 어느 정도였나요?",
                "selectedOptionSortOrder": 2,
            },
            {
                "questionContent": "최근 1주일 동안, 허리(요추) 부위의 불편함이나 통증은 어느 정도였나요?",
                "selectedOptionSortOrder": 1,
            },
            {
                "questionContent": "최근 1주일 동안, 손목 사용 시 불편함이나 부담을 느낀 정도는 어느 정도였나요?",
                "selectedOptionSortOrder": 1,
            },
            {
                "questionContent": "최근 1주일 동안, 하루 평균 장시간 앉아서 보내는 시간은 어느 정도였나요?",
                "selectedOptionSortOrder": 3,
            },
            {
                "questionContent": "최근 1주일 동안, 전반적인 신체 피로감은 어느 정도였나요?",
                "selectedOptionSortOrder": 2,
            },
            {
                "questionContent": "최근 1주일 동안, 화면을 오래 본 후 눈의 피로감이나 시각적 불편함을 느낀 정도는 어느 정도였나요?",
                "selectedOptionSortOrder": 4,
            },
        ],
    }
}


# ── 데이터 클래스 ─────────────────────────────────────────────────────────────
@dataclass
class Sample:
    """측정 1회 결과"""

    e2e_sec: float
    server_sec: float | None  # completedAt 기반 추정 (V2만 해당)

    @property
    def overhead_sec(self) -> float | None:
        if self.server_sec is None:
            return None
        return max(self.e2e_sec - self.server_sec, 0.0)


@dataclass
class VersionResult:
    label: str
    path: str  # llm | vector | cf
    samples: list[Sample] = field(default_factory=list)

    def _col(self, attr: str) -> list[float]:
        vals = [getattr(s, attr) for s in self.samples]
        return [v for v in vals if v is not None]

    def stats(self, attr: str) -> dict[str, float] | None:
        vals = self._col(attr)
        if not vals:
            return None
        result = {"mean": statistics.mean(vals), "min": min(vals), "max": max(vals)}
        if len(vals) > 1:
            result["stdev"] = statistics.stdev(vals)
        return result


# ── HTTP 헬퍼 ─────────────────────────────────────────────────────────────────
def _parse_completed_at(data: dict) -> datetime | None:
    raw = data.get("completedAt")
    if not raw:
        return None
    return datetime.fromisoformat(raw.replace("Z", "+00:00"))


async def _poll_until_done(
    client: httpx.AsyncClient, base_url: str, task_id: str
) -> dict:
    deadline = time.perf_counter() + POLL_TIMEOUT_SEC
    while time.perf_counter() < deadline:
        resp = await client.get(f"{base_url}/api/v2/routines/{task_id}")
        resp.raise_for_status()
        data = resp.json()
        if data["status"] in ("COMPLETED", "FAILED"):
            return data
        await asyncio.sleep(POLL_INTERVAL_SEC)
    raise TimeoutError(f"Task {task_id} did not complete in {POLL_TIMEOUT_SEC}s")


# ── 측정 ─────────────────────────────────────────────────────────────────────
async def measure_v1(
    client: httpx.AsyncClient, base_url: str, repeat: int
) -> VersionResult:
    result = VersionResult(label="V1  LLM (동기)", path="llm")
    for i in range(repeat):
        sent_at = datetime.now(timezone.utc)
        t0 = time.perf_counter()

        resp = await client.post(f"{base_url}/api/v1/routines", json=SURVEY_PAYLOAD)
        e2e = time.perf_counter() - t0
        resp.raise_for_status()

        # V1 응답에 completedAt이 있으면 server_sec 계산, 없으면 e2e로 대체
        data = resp.json()
        completed_at = _parse_completed_at(data)
        server_sec = (completed_at - sent_at).total_seconds() if completed_at else None

        result.samples.append(Sample(e2e_sec=e2e, server_sec=server_sec))
        print(f"  V1 [{i + 1}/{repeat}]  e2e={e2e:.3f}s  status={data.get('status', '?')}")
    return result


async def measure_v2(
    client: httpx.AsyncClient, base_url: str, repeat: int
) -> VersionResult:
    result = VersionResult(label="V2  비동기 (vector | llm)", path="vector|llm")
    for i in range(repeat):
        task_id = uuid.uuid4().hex
        payload = {"taskId": task_id, "userId": 1, **SURVEY_PAYLOAD}

        sent_at = datetime.now(timezone.utc)
        t0 = time.perf_counter()

        resp = await client.post(f"{base_url}/api/v2/routines", json=payload)
        resp.raise_for_status()
        data = await _poll_until_done(client, base_url, task_id)
        e2e = time.perf_counter() - t0

        completed_at = _parse_completed_at(data)
        server_sec = (completed_at - sent_at).total_seconds() if completed_at else None
        overhead = max(e2e - server_sec, 0.0) if server_sec else None

        result.samples.append(Sample(e2e_sec=e2e, server_sec=server_sec))
        print(
            f"  V2 [{i + 1}/{repeat}]  "
            f"e2e={e2e:.3f}s  "
            f"server≈{server_sec:.3f}s  "
            f"overhead≈{overhead:.3f}s  "
            f"status={data['status']}"
        )
    return result


# ── 보고서 출력 ───────────────────────────────────────────────────────────────
W = 62  # 표 너비
COL = 16  # 값 열 너비


def _fmt(val: float | None) -> str:
    return f"{val:.3f}s" if val is not None else "—"


def _row(label: str, *values: float | None) -> str:
    cells = "".join(f"{_fmt(v):>{COL}}" for v in values)
    return f"  {label:<14}{cells}"


def _stats_row(label: str, attr: str, results: list[VersionResult]) -> str:
    values: list[float | None] = []
    for r in results:
        s = r.stats(attr)
        values.append(s[label] if s and label in s else None)
    return _row(label, *values)


def print_report(results: list[VersionResult]) -> None:
    headers = "".join(f"{r.label:>{COL}}" for r in results)
    sep = "─" * W

    print(f"\n{'═' * W}")
    print("  버전별 추천 응답 시간 통합 보고서")
    print(f"{'═' * W}")
    print(f"  {'':14}{headers}")
    print(sep)

    # E2E
    print("  [E2E 시간]    (POST 전송 ~ COMPLETED 수신, 클라이언트 측정)")
    for stat in ("mean", "min", "max", "stdev"):
        print(_stats_row(stat, "e2e_sec", results))
    print(sep)

    # 서버 처리 (server_sec)
    has_server = any(r.stats("server_sec") for r in results)
    if has_server:
        print("  [서버 처리]   (completedAt − POST 전송 시각, localhost 기준)")
        for stat in ("mean", "min", "max"):
            print(_stats_row(stat, "server_sec", results))
        print(sep)

    # 폴링 오버헤드 (overhead_sec) — V2만 의미 있음
    has_overhead = any(r.stats("overhead_sec") for r in results)
    if has_overhead:
        print("  [폴링 오버헤드]  (e2e − server, V1은 동기라 해당 없음)")
        for stat in ("mean", "min", "max"):
            print(_stats_row(stat, "overhead_sec", results))
        print(sep)

    # 버전 간 E2E 비교
    if len(results) >= 2:
        means = [r.stats("e2e_sec") for r in results]
        if all(m for m in means):
            diff = means[1]["mean"] - means[0]["mean"]  # type: ignore[index]
            direction = "느림" if diff > 0 else "빠름"
            print(
                f"  {results[1].label.strip()} E2E mean이 "
                f"{results[0].label.strip()} 보다  {abs(diff):.3f}s  {direction}"
            )
    print(f"{'═' * W}\n")


# ── 메인 ─────────────────────────────────────────────────────────────────────
async def run(base_url: str, repeat: int, skip_v1: bool, skip_v2: bool) -> None:
    async with httpx.AsyncClient(timeout=httpx.Timeout(POLL_TIMEOUT_SEC)) as client:
        try:
            resp = await client.get(f"{base_url}/api/v2/health")
            h = resp.json()
            print(f"서버 연결 OK  status={h.get('status')}  version={h.get('version')}\n")
        except httpx.ConnectError:
            print(f"[ERROR] 서버에 연결할 수 없습니다: {base_url}")
            print("  uvicorn app.main:app --port 8000 으로 서버를 먼저 기동하세요.")
            return

        results: list[VersionResult] = []

        if not skip_v1:
            print(f"── V1 측정 중 (×{repeat}) ──")
            results.append(await measure_v1(client, base_url, repeat))

        if not skip_v2:
            print(f"\n── V2 측정 중 (×{repeat}) ──")
            results.append(await measure_v2(client, base_url, repeat))

    if results:
        print_report(results)


def main() -> None:
    parser = argparse.ArgumentParser(description="추천 API 버전별 응답 시간 통합 보고서")
    parser.add_argument("--url", default=DEFAULT_URL, help=f"서버 URL (기본: {DEFAULT_URL})")
    parser.add_argument("--repeat", type=int, default=DEFAULT_REPEAT, help="반복 횟수")
    parser.add_argument("--skip-v1", action="store_true", help="V1 측정 건너뜀")
    parser.add_argument("--skip-v2", action="store_true", help="V2 측정 건너뜀")
    args = parser.parse_args()
    asyncio.run(run(args.url, args.repeat, args.skip_v1, args.skip_v2))


if __name__ == "__main__":
    main()
