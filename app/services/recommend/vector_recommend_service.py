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

from app.core.exceptions import ConfigurationError
from app.domain.exercise import ExerciseType
from app.domain.routine import Routine, RoutineList
from app.domain.routinestep_factory import create_routinestep_from_exercise
from app.schemas.common import UserSurvey

if TYPE_CHECKING:
    from app.data.exercise_vector_repository import ExerciseVectorRepository
    from app.data.user_activity_repository import UserActivityVectorRepository
    from app.domain.exercise import BaseExercise
    from app.domain.routine import RoutineStep
    from app.services.llm_clients.base import LLMClient

logger = logging.getLogger(__name__)

# ── 상수 ──────────────────────────────────────────────────────────────────────
# TODO: Constants 한곳에서 중앙 집중 관리

SEVERITY_THRESHOLD = 2  # 이 값 이상인 문항만 쿼리에 포함
DEFAULT_EXERCISES_PER_ROUTINE = 4
DEFAULT_SEARCH_LIMIT = 30
DEFAULT_SCORE_THRESHOLD = 0.4  # multilingual-e5 기준 충분한 하한값

# Non-cold start 벡터 블렌딩 가중치
# 사용자 활동 이력을 설문보다 높게 반영 (행동 기반 프로필 우선)
SURVEY_VECTOR_WEIGHT = 0.4
ACTIVITY_VECTOR_WEIGHT = 0.6

# questionContent 키워드 → 쿼리용 건강 상태 문구 매핑
# 순서대로 questionContent에서 첫 매칭을 사용
_KEYWORD_TO_CONCERN: list[tuple[str, str]] = [
    ("목 부위", "목 부위의 불편함과 통증"),
    ("어깨", "어깨 부위의 뻐근함과 통증"),
    ("허리", "허리(요추) 부위의 불편함과 통증"),
    ("손목", "손목 불편함과 부담"),
    ("눈", "눈의 피로감과 시각적 불편함"),
    ("앉아서", "장시간 좌식 생활로 인한 피로"),
    ("피로", "전반적인 신체 피로"),
]

_REASON_FALLBACK = "설문 기반 벡터 검색 맞춤 추천"


# ── VectorRecommendService ────────────────────────────────────────────────────


class VectorRecommendService:
    """
    Qdrant 벡터 검색 기반 추천 서비스.

    - LLM 없이 설문 → 임베딩 → 유사도 검색 → RoutineList 변환
    - repository / embedding_model 이 None 이면 ConfigurationError (비활성화 상태)
    - EYES 운동은 별도 루틴으로 분리 (룰베이스 방식과 동일)
    - routine.reason은 LLM으로 생성 (llm_client 없으면 기본 문구 사용)
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

        hits = self._repo.search(
            query_vector=query_vector,
            limit=DEFAULT_SEARCH_LIMIT,
            score_threshold=DEFAULT_SCORE_THRESHOLD,
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

        return (
            f"query: 건강 상태: {', '.join(concerns)} | 목표: 장시간 업무로 인한 근골격계 피로 회복"
        )

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

        top_n = sorted(
            survey.survey, key=lambda a: a.selectedOptionSortOrder, reverse=True
        )[:routine_count]
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
        - routine.reason은 LLM으로 생성 (실패 시 기본 문구)
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
        if body_hits and body_count > 0:
            # bilateral pair를 같은 루틴에 배정하기 위해 그룹 단위로 분배
            body_hit_groups = self._group_bilateral_pairs(body_hits, exercises_by_id)
            groups_per_routine = max(1, len(body_hit_groups) // body_count)

            for i in range(body_count):
                chunk_groups = body_hit_groups[i * groups_per_routine : (i + 1) * groups_per_routine]
                chunk = [h for group in chunk_groups for h in group]
                if not chunk:
                    break

                steps = [
                    create_routinestep_from_exercise(exercises_by_id[int(h.id)], step_order=j + 1)
                    for j, h in enumerate(chunk)
                ]
                reason = self._generate_reason(steps, survey, exercises_by_id)
                routines.append(
                    Routine(
                        routineOrder=len(routines) + 1,
                        reason=reason,
                        steps=steps,
                    )
                )

        # ── EYES 루틴 생성 ─────────────────────────────────────────────────────
        if has_eyes_routine:
            eyes_steps = [
                create_routinestep_from_exercise(exercises_by_id[int(h.id)], step_order=j + 1)
                for j, h in enumerate(eyes_hits)
            ]
            reason = self._generate_reason(eyes_steps, survey, exercises_by_id)
            routines.append(
                Routine(
                    routineOrder=len(routines) + 1,
                    reason=reason,
                    steps=eyes_steps,
                )
            )

        logger.debug(
            "벡터 검색 추천 결과: %d개 루틴, 운동 분포=%s",
            len(routines),
            [
                [step.exerciseId for step in r.steps]
                for r in routines
            ],
        )
        return RoutineList(routines=routines)

    def _generate_reason(
        self,
        steps: list[RoutineStep],
        survey: UserSurvey,
        exercises_by_id: dict[int, BaseExercise],
    ) -> str:
        """
        루틴 구성 운동과 설문 응답을 바탕으로 LLM이 reason을 생성합니다.

        LLM 미설정 또는 호출 실패 시 기본 문구를 반환합니다.
        """
        if self._llm is None:
            return _REASON_FALLBACK

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
            return _REASON_FALLBACK
