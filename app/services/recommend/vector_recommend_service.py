# app/services/recommend/vector_recommend_service.py
"""
Qdrant 벡터 검색 기반 추천 서비스

VectorRecommendService
  - recommend_routines(survey, user_id) → RoutineList
    - 설문 → 쿼리 텍스트 → 임베딩 → Qdrant 검색 → RoutineList 변환
    - repository 또는 embedding_model 이 None 이면 ConfigurationError raise
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from qdrant_client import models as qdrant_models

from app.core.config import RoutineTimePolicy
from app.core.exceptions import ConfigurationError
from app.domain.exercise import BodyPart, ExerciseType
from app.domain.routine import Routine, RoutineList
from app.domain.routinestep_factory import copy_routine_step, create_routinestep_from_exercise
from app.schemas.common import UserSurvey

if TYPE_CHECKING:
    from app.data.exercise_vector_repository import ExerciseVectorRepository
    from app.data.user_activity_repository import UserActivityVectorRepository
    from app.domain.exercise import BaseExercise
    from app.domain.routine import RoutineStep
    from app.services.llm_clients.base import LLMClient

logger = logging.getLogger(__name__)

# ── 상수 ──────────────────────────────────────────────────────────────────────

SEVERITY_THRESHOLD = (
    2  # 설문 응답 점수 하한 (range: 1~5 / UP:강한 증상만 반영, DOWN:경미한 증상도 포함)
)
DEFAULT_EXERCISES_PER_ROUTINE = 4  # 루틴당 최대 운동 수 (UP:루틴 길어짐, DOWN:짧아짐)
DEFAULT_SEARCH_LIMIT = (
    30  # Qdrant 검색 후보 수 (UP: 다양성 & 지연 증가, DOWN: 다양성 감소 · 속도 증가)
)
DEFAULT_SCORE_THRESHOLD = (
    0.85  # 벡터 유사도 하한 (UP: 정밀도 증가 · recall 감소, DOWN: recall 증가 · 노이즈 증가)
)

# Non-cold start 벡터 블렌딩 가중치 — 합이 반드시 1.0 (cosine 스케일 왜곡 방지)
SURVEY_VECTOR_WEIGHT = 0.4  # 설문조사 가중치
ACTIVITY_VECTOR_WEIGHT = 0.6  # 사용자 활동 가중치  (= 1 - SURVEY_VECTOR_WEIGHT)

# questionContent 키워드 → 쿼리용 건강 상태 문구 매핑
# questionContent에서 첫 매칭을 사용
_KEYWORD_TO_CONCERN: list[tuple[str, str]] = [
    ("목 부위", "목 부위의 불편함과 통증"),
    ("어깨", "어깨 부위의 뻐근함과 통증"),
    ("허리", "허리(요추) 부위의 불편함과 통증"),
    ("손목", "손목 불편함과 부담"),
    ("눈", "눈의 피로감과 시각적 불편함"),
    ("앉아서", "장시간 좌식 생활로 인한 피로"),
    ("피로", "전반적인 신체 피로"),
]

# questionContent 키워드 → BodyPart 매핑 (_KEYWORD_TO_CONCERN 동일 키 기준)
# "앉아서", "피로"는 특정 bodyPart 없음 — 포함하지 않음
_KEYWORD_TO_BODY_PART: dict[str, BodyPart] = {
    "목 부위": BodyPart.NECK,
    "어깨": BodyPart.SHOULDER,
    "허리": BodyPart.LOWER_BACK,
    "손목": BodyPart.WRIST,
    "눈": BodyPart.EYES,
}

_BODY_PART_TO_KOREAN: dict[BodyPart, str] = {
    BodyPart.NECK: "목",
    BodyPart.SHOULDER: "어깨",
    BodyPart.WRIST: "손목",
    BodyPart.LOWER_BACK: "허리",
}


def _build_fallback_reason(
    steps: list[RoutineStep],
    exercises_by_id: dict[int, BaseExercise],
) -> str:
    """steps의 운동 부위 기반으로 reason 생성 (룰베이스와 동일한 패턴)."""
    from collections import Counter

    exercises = [exercises_by_id[s.exerciseId] for s in steps if s.exerciseId in exercises_by_id]
    if not exercises:
        return "전신 스트레칭을 위한 루틴입니다."
    if all(ex.type == ExerciseType.EYES for ex in exercises):
        return "눈 피로 해소를 위한 눈 운동 루틴입니다."
    body_parts = [ex.bodyPart for ex in exercises if ex.type != ExerciseType.EYES]
    if not body_parts:
        return "전신 스트레칭을 위한 루틴입니다."
    top_part = Counter(body_parts).most_common(1)[0][0]
    part_name = _BODY_PART_TO_KOREAN.get(top_part, top_part.value)
    return f"{part_name} 부위 집중 케어를 위한 루틴입니다."


# ── VectorRecommendService ────────────────────────────────────────────────────


class VectorRecommendService:
    """
    Qdrant 벡터 검색 기반 추천 서비스.

    - 설문 → 임베딩 → 유사도 검색 → RoutineList 변환
    - repository / embedding_model 이 None 이면 ConfigurationError (비활성화 상태)
    - EYES 운동은 별도 루틴으로 분리 (룰베이스 방식과 동일)
    - routine.reason은 검증 & 보정 완료 후 generate_reasons()로 별도 생성
    """

    def __init__(
        self,
        exercise_repo: ExerciseVectorRepository | None,
        embedding_model: Any | None,  # SentenceTransformer 등 encode() 지원 모델
        llm_client: LLMClient | None = None,
        user_activity_repo: UserActivityVectorRepository | None = None,
    ) -> None:
        self._repo = exercise_repo
        self._model = embedding_model
        self._llm = llm_client
        self._user_activity_repo = user_activity_repo

    def is_available(self) -> bool:
        """벡터 검색 서비스 활성화 여부 (Qdrant + 임베딩 모델 준비 상태).

        O(1) 속성 확인 — 네트워크 호출 없음.
        API 레이어에서 요청 수락 전 조기 검사용.
        """
        return self._repo is not None and self._model is not None

    def recommend_routines(self, survey: UserSurvey, user_id: int) -> RoutineList:
        """
        설문 데이터를 기반으로 벡터 검색 추천을 수행합니다.

        Args:
        - survey: 사용자 설문 데이터 (routineCount, survey 문항 목록)
        - user_id: 사용자 식별자 (로그용)

        Returns:
        - RoutineList (V2ResponseBuilder.build()로 이후 검증됨)

        Raises:
        - ConfigurationError: Qdrant 미연결 또는 임베딩 모델 미설정 시
        """
        if self._repo is None or self._model is None:
            raise ConfigurationError(
                "VectorRecommendService 비활성화 상태입니다. "
                "Qdrant 연결 및 임베딩 모델 설정을 확인하세요."
            )

        query = self._build_query(survey)
        logger.debug("벡터 검색 쿼리 [user_id=%d]: %s", user_id, query)

        survey_vector: list[float] = self._model.encode(query).tolist()
        query_vector = self._get_query_vector(survey_vector, user_id)

        qdrant_filter = self._build_qdrant_filter(survey)
        hits = self._repo.search(
            query_vector=query_vector,
            limit=DEFAULT_SEARCH_LIMIT,
            score_threshold=DEFAULT_SCORE_THRESHOLD,
            query_filter=qdrant_filter,
        )
        logger.info(
            "벡터 검색 완료 [user_id=%d]: %d 개 운동 후보",
            user_id,
            len(hits),
        )

        return self._build_routine_list(hits, survey.routineCount, survey)

    # ── private ───────────────────────────────────────────────────────────────

    def _get_query_vector(self, survey_vector: list[float], user_id: int) -> list[float]:
        """
        설문 벡터와 사용자 활동 벡터를 결합하여 최종 검색 벡터를 반환.

        - user_activity_repo 미주입 → 설문 벡터만 사용 (cold start 경로)
        - Qdrant에 user_id 프로필 없음 → 설문 벡터만 사용 (cold start)
        - 프로필 존재 → 가중 합 블렌딩 (non-cold start)
        - 조회 중 예외 → 설문 벡터 fallback + WARNING 로그
        """
        if self._user_activity_repo is None:
            return survey_vector

        try:
            activity_vector = self._user_activity_repo.get_vector(user_id)
        except Exception as e:
            logger.warning(
                "사용자 활동 벡터 조회 실패 — 설문 벡터만 사용 [user_id=%d]: %s", user_id, e
            )
            return survey_vector

        if activity_vector is None:
            logger.debug("Cold start 사용자 — 설문 벡터만 사용 [user_id=%d]", user_id)
            return survey_vector

        logger.info(
            "Non-cold start — 사용자 활동 벡터 블렌딩 [user_id=%d, survey=%.1f, activity=%.1f]",
            user_id,
            SURVEY_VECTOR_WEIGHT,
            ACTIVITY_VECTOR_WEIGHT,
        )
        return self._blend_vectors(survey_vector, activity_vector)

    def _blend_vectors(
        self, survey_vector: list[float], activity_vector: list[float]
    ) -> list[float]:
        """
        설문 벡터와 사용자 활동 벡터를 가중 합으로 결합.

        두 벡터가 동일한 SentenceTransformer로 생성되었으므로 같은 의미 공간에 위치.
        Qdrant cosine 검색이 내부적으로 정규화하므로 블렌딩 후 별도 정규화 불필요.
        """
        if len(survey_vector) != len(activity_vector):
            logger.warning(
                "벡터 차원 불일치 (survey=%d, activity=%d) — 설문 벡터만 사용",
                len(survey_vector),
                len(activity_vector),
            )
            return survey_vector

        blended = [
            SURVEY_VECTOR_WEIGHT * s + ACTIVITY_VECTOR_WEIGHT * a
            for s, a in zip(survey_vector, activity_vector)
        ]
        logger.debug(
            "벡터 블렌딩 완료 [dim=%d, survey_norm=%.4f, activity_norm=%.4f, blended_norm=%.4f]",
            len(blended),
            sum(v * v for v in survey_vector) ** 0.5,
            sum(v * v for v in activity_vector) ** 0.5,
            sum(v * v for v in blended) ** 0.5,
        )
        return blended

    def _build_qdrant_filter(self, survey: UserSurvey) -> qdrant_models.Filter | None:
        """
        SEVERITY_THRESHOLD 미만 bodyPart를 Qdrant 검색에서 제외하는 must_not 필터.

        예) 허리(1점), 손목(1점) → lowerBack, wrist 운동 제외
        bodyPart와 무관한 문항("앉아서", "피로")은 필터에서 무시.
        """
        excluded: list[str] = []
        for answer in survey.survey:
            if answer.selectedOptionSortOrder >= SEVERITY_THRESHOLD:
                continue
            for keyword, body_part in _KEYWORD_TO_BODY_PART.items():
                if keyword in answer.questionContent:
                    excluded.append(body_part.value)

        if not excluded:
            return None

        logger.debug("Qdrant bodyPart 제외 필터: %s", excluded)
        return qdrant_models.Filter(
            must_not=[
                qdrant_models.FieldCondition(
                    key="bodyPart",
                    match=qdrant_models.MatchAny(any=excluded),
                )
            ]
        )

    def _build_query(self, survey: UserSurvey) -> str:
        """
        설문 응답 → 임베딩용 쿼리 문자열 변환.

        SEVERITY_THRESHOLD 이상인 문항만 건강 상태 문구로 변환합니다.
        매칭 키워드가 없는 문항은 questionContent를 그대로 사용합니다.
        """
        concerns: list[str] = []

        for answer in survey.survey:
            if answer.selectedOptionSortOrder < SEVERITY_THRESHOLD:
                continue

            content = answer.questionContent
            concern = self._extract_concern(content)
            concerns.append(concern)

        if not concerns:
            # 모든 문항이 낮은 점수인 경우 — 일반적인 스트레칭 추천
            concerns = ["업무로 인한 근골격계 피로"]

        return f"query: {', '.join(concerns)}"

    def _extract_concern(self, question_content: str) -> str:
        """questionContent에서 키워드 매칭으로 건강 상태 문구 추출."""

        for keyword, concern in _KEYWORD_TO_CONCERN:
            if keyword in question_content:
                return concern

        # 매칭 실패 시 questionContent 원문 사용
        return question_content

    def _has_eyes_concern(self, survey: UserSurvey, routine_count: int) -> bool:
        """
        EYES 루틴 추가 조건 (모두 충족 시 True):
        1. 눈 관련 문항 응답 >= SEVERITY_THRESHOLD (2)
        2. 설문 응답 우선순위 상위 routine_count 내에 눈 포함
        """
        eyes_score = max(
            (a.selectedOptionSortOrder for a in survey.survey if "눈" in a.questionContent),
            default=0,
        )
        if eyes_score < SEVERITY_THRESHOLD:
            return False

        top_n = sorted(survey.survey, key=lambda a: a.selectedOptionSortOrder, reverse=True)[
            :routine_count
        ]
        return any("눈" in a.questionContent for a in top_n)

    def _group_bilateral_pairs(
        self,
        hits: list[Any],
        exercises_by_id: dict[int, BaseExercise],
    ) -> list[list[Any]]:
        """
        bilateral pair 운동을 같은 그룹으로 묶어 반환.

        반환 형식: [[hit] 또는 [hit, paired_hit], ...]

        예) hits = [52(왼어깨), 60, 53(오른어깨), 61]
              → [[52, 53], [60], [61]]

        이후 그룹 단위로 루틴에 분배하면 pair가 항상 같은 루틴에 배정됨.
        pair 한쪽이 hits에 없으면 단독 그룹으로 처리하고,
        CoreResponseBuilder._validate_bilateral_exercise_rule이 사후 보완.
        """
        from app.domain.routinestep_factory import find_bilateral_pair

        hits_by_id = {int(h.id): h for h in hits}
        processed: set[int] = set()
        groups: list[list] = []

        for hit in hits:
            ex_id = int(hit.id)
            if ex_id in processed:
                continue

            ex = exercises_by_id[ex_id]
            pair = find_bilateral_pair(ex, exercises_by_id)

            if pair and pair.exerciseId in hits_by_id and pair.exerciseId not in processed:
                groups.append([hit, hits_by_id[pair.exerciseId]])
                processed.update({ex_id, pair.exerciseId})
            else:
                groups.append([hit])
                processed.add(ex_id)

        return groups

    def _build_routine_list(
        self,
        hits: list[Any],  # list[ScoredPoint]
        routine_count: int,
        survey: UserSurvey,
    ) -> RoutineList:
        """
        Qdrant 검색 결과 → RoutineList 변환.

        - exercise_repository에서 exerciseId로 BaseExercise 조회
        - create_routinestep_from_exercise()로 RoutineStep 생성
        - EYES 운동은 별도 루틴으로 분리 (룰베이스 방식과 동일)
        - body 운동은 routine_count 개의 Routine으로 균등 분배
        - routine.reason은 기본 문구로 설정 (LLM reason은 검증 & 보정 완료 후 generate_reasons()에서 생성)
        - 이후 V2ResponseBuilder(CoreResponseBuilder)가 유효성 검증 및 보완 수행
        """
        from app.data.loader import exercise_repository

        exercises_by_id = {ex.exerciseId: ex for ex in exercise_repository.get_all()}

        # 유효한 exerciseId를 가진 hit만 필터링 (중복 제거)
        seen: set[int] = set()
        valid_hits: list[Any] = []
        for hit in hits:
            ex_id = int(hit.id)
            if ex_id in exercises_by_id and ex_id not in seen:
                valid_hits.append(hit)
                seen.add(ex_id)

        if not valid_hits:
            logger.warning("벡터 검색 결과에 유효한 운동이 없습니다. 빈 RoutineList 반환")
            return RoutineList(routines=[])
        logger.debug(
            "유효한 벡터 검색 결과 - %d개:\n%s",
            len(valid_hits),
            [(h.id, h.score) for h in valid_hits],
        )

        # EYES / body 분리
        eyes_hits = [h for h in valid_hits if exercises_by_id[int(h.id)].type == ExerciseType.EYES]
        body_hits = [h for h in valid_hits if exercises_by_id[int(h.id)].type != ExerciseType.EYES]

        effective_count = max(routine_count, 1)

        # EYES 루틴 추가 여부:
        # 1. 눈 관련 문항에 대한 응답이 SEVERITY_THRESHOLD 이상
        # 2. 검색 결과에 EYES 운동이 포함
        # 3. 설문조사 결과 우선순위 나열 시, routineCount 내에 EYES 존재
        has_eyes_routine = self._has_eyes_concern(survey, effective_count) and bool(eyes_hits)

        body_count = effective_count - (1 if has_eyes_routine else 0)

        routines: list[Routine] = []

        # ── body 루틴 생성 ─────────────────────────────────────────────────────

        if body_count > 0:
            from app.services.recommend.rule_based_recommender import RuleBasedRecommender

            # bilateral pair 운동 같은 그룹으로 묶기 (non-bilateral exercise는 1 그룹당 1운동)
            body_hit_groups = self._group_bilateral_pairs(body_hits, exercises_by_id)

            # MIN_TIME 미달 시 rule-based filler (한 번만 생성)
            filler = RuleBasedRecommender(exercise_repository.raw_data)

            # 루틴 간 중복 감지를 위한 운동 ID 집합 누적
            seen_routine_id_sets: list[frozenset[int]] = []

            for i in range(body_count):
                steps: list[RoutineStep] = []
                used_ids: set[int] = set()
                total_time = 0
                step_order = 1

                # Phase 1: round-robin으로 hit groups 순회 (TARGET_TIME까지)
                # i번째 그룹부터 시작해 루틴마다 시작점을 달리함
                rotated_groups = body_hit_groups[i:] + body_hit_groups[:i]
                for group in rotated_groups:
                    if total_time >= RoutineTimePolicy.TARGET_TIME:
                        break
                    for hit in group:
                        ex_id = int(hit.id)
                        if ex_id in used_ids:
                            continue
                        ex = exercises_by_id[ex_id]
                        step = create_routinestep_from_exercise(ex, step_order)
                        steps.append(step)
                        used_ids.add(ex_id)
                        total_time += step.limitTime
                        step_order += 1

                # Phase 2: 동일 루틴 감지 — hit 교체로 차별화 시도, 불가 시 filler로 위임
                while frozenset(used_ids) in seen_routine_id_sets and steps:
                    # 마지막 운동 제거
                    removed = steps.pop()
                    used_ids.discard(removed.exerciseId)
                    total_time -= removed.limitTime
                    step_order -= 1
                    logger.debug(
                        "중복 루틴 감지 — 마지막 운동 제거 [routine_idx=%d, removed_id=%d]",
                        i,
                        removed.exerciseId,
                    )

                    # 미사용 hits에서 추가 시 중복이 해소되는 대체 운동 탐색
                    replacement_found = False
                    for group in body_hit_groups:
                        for hit in group:
                            ex_id = int(hit.id)
                            if ex_id in used_ids:
                                continue
                            # 이 운동 추가 시 중복 여부 사전 확인
                            if frozenset(used_ids | {ex_id}) not in seen_routine_id_sets:
                                ex = exercises_by_id[ex_id]
                                step = create_routinestep_from_exercise(ex, step_order)
                                steps.append(step)
                                used_ids.add(ex_id)
                                total_time += step.limitTime
                                replacement_found = True
                                break
                        if replacement_found:
                            break

                    if not replacement_found:
                        # 모든 hit 소진 — Phase 3 filler가 다른 운동으로 채워 루틴을 고유하게 만듦
                        logger.debug(
                            "hit 교체로 중복 해소 불가 — filler로 위임 [routine_idx=%d]", i
                        )
                        break

                # Phase 3: MIN_TIME 미달 시 rule-based filler로 보완
                if total_time < RoutineTimePolicy.MIN_TIME:
                    needed = RoutineTimePolicy.MIN_TIME - total_time
                    filler_steps = filler.get_filler_steps(
                        target_time=needed,
                        exclude_ids=used_ids,
                    )
                    for j, fs in enumerate(filler_steps, start=step_order):
                        steps.append(copy_routine_step(fs, step_order=j))

                seen_routine_id_sets.append(frozenset(s.exerciseId for s in steps))
                routines.append(
                    Routine(
                        routineOrder=len(routines) + 1,
                        reason=_build_fallback_reason(steps, exercises_by_id),
                        steps=steps,
                    )
                )

        # ── EYES 루틴 생성 ─────────────────────────────────────────────────────

        if has_eyes_routine:
            eyes_steps = [
                create_routinestep_from_exercise(exercises_by_id[int(h.id)], step_order=j + 1)
                for j, h in enumerate(eyes_hits)
            ]
            routines.append(
                Routine(
                    routineOrder=len(routines) + 1,
                    reason=_build_fallback_reason(eyes_steps, exercises_by_id),
                    steps=eyes_steps,
                )
            )

        logger.debug(
            "벡터 검색 추천 결과: %d개 루틴, 운동 분포=%s",
            len(routines),
            [[step.exerciseId for step in r.steps] for r in routines],
        )
        return RoutineList(routines=routines)

    def generate_reasons(self, routines: list[Routine], survey: UserSurvey) -> list[Routine]:
        """
        검증 & 보정 완료된 루틴에 LLM reason을 적용한다.

        - EYES 전용 루틴은 LLM 호출 없이 fallback reason을 사용
        - LLM 미설정 또는 호출 실패 시 기존 fallback reason을 유지
        """
        from app.data.loader import exercise_repository

        exercises_by_id = {ex.exerciseId: ex for ex in exercise_repository.get_all()}

        result: list[Routine] = []
        for routine in routines:
            # RoutineStep.type으로 직접 판별 — exercises_by_id 조회 실패 시 LLM 호출되는 버그 방지
            is_eyes = all(s.type == ExerciseType.EYES for s in routine.steps)
            if is_eyes:
                reason = "눈 피로 해소를 위한 눈 운동 루틴입니다."
            else:
                reason = self._generate_reason(routine.steps, survey, exercises_by_id)
            result.append(
                Routine(
                    routineOrder=routine.routineOrder,
                    reason=reason,
                    steps=routine.steps,
                )
            )
        return result

    def _generate_reason(
        self,
        steps: list[RoutineStep],
        survey: UserSurvey,
        exercises_by_id: dict[int, BaseExercise],
    ) -> str:
        """
        LLM을 사용하여 루틴 구성 운동과 설문 응답을 바탕으로 reason을 생성한다.
        - steps: 루틴을 구성하는 운동 단계 목록
        - survey: 사용자 설문 응답
        - exercises_by_id: exerciseId → BaseExercise 매핑 (LLM 호출 전 조회하여 전달)

        - LLM 미설정 또는 호출 실패 시 기본 문구를 반환
        - build_reason_prompt을 사용하여 사용자 프롬프트 생성
        - REASON_SYSTEM_PROMPT을 사용하여 시스템 프롬프트 생성
        """
        if self._llm is None:
            return _build_fallback_reason(steps, exercises_by_id)

        try:
            from app.prompts.v2.reason import REASON_SYSTEM_PROMPT, build_reason_prompt

            exercises = [
                exercises_by_id[step.exerciseId]
                for step in steps
                if step.exerciseId in exercises_by_id
            ]
            logger.debug("reason LLM 호출 [exercises=%s]", [ex.name for ex in exercises])
            prompt = build_reason_prompt(survey, exercises)
            reason = self._llm.generate(REASON_SYSTEM_PROMPT, prompt).strip()
            logger.debug("reason LLM 결과: %s", reason)
            return reason

        except Exception as e:
            logger.warning("루틴 reason LLM 생성 실패 — 기본값 사용: %s", e)
            return _build_fallback_reason(steps, exercises_by_id)
