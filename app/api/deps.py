# app/api/deps.py
"""
중앙 집중 DI 배선 모듈 (의존성 주입 전용)

이 파일은 "어떤 구현체를 어떤 인터페이스에 꽂을 것인가"만 결정한다.
비즈니스 로직은 없으며, 구현체 교체 시 이 파일만 수정하면 된다.

생명주기(lifecycle) 기준 두 그룹:

  [Group A] 싱글턴 — 모듈 로드 시 1회 초기화
    exercise data 의존 없음, 상태 없음, 프로세스 수명과 동일
    _llm_client, _task_store, _callback_client,
    _cold_start_checker, _exercise_vector_svc, _user_activity_vec_svc

  [Group B] per-request 팩토리 — 매 요청마다 새 인스턴스
    exercise_repository.raw_data를 항상 최신 상태로 반영해야 하는 객체
    get_recommend_service_v1/v2(), get_response_builder_v1/v2(),
    get_task_service(), get_task_executor()

도메인 섹션:
  [1] LLM / Recommend  — LLM 클라이언트, 추천 서비스, 응답 빌더
  [2] Task / Async     — TaskStore, CallbackClient, ColdStartChecker, TaskService, TaskExecutor
  [3] Vector / Embed   — ExerciseVectorService, UserActivityVectorService
"""

import logging

from fastapi import BackgroundTasks, Depends

from app.configs.llm_config import llm_config
from app.core.config import settings
from app.services.callback_client import CallbackClient
from app.services.exercise_vector_service import ExerciseVectorService
from app.services.llm_clients.base import LLMClient
from app.services.llm_clients.ollama_client import OllamaClient
from app.services.llm_clients.openai_client import OpenAIClient
from app.services.recommend.cold_start_checker import (
    ActivityBasedColdStartChecker,
    ColdStartChecker,
    DefaultColdStartChecker,
)
from app.services.recommend.recommend_service import RecommendService
from app.services.recommend.vector_recommend_service import VectorRecommendService
from app.services.response.v1 import V1ResponseBuilder
from app.services.response.v2 import V2ResponseBuilder
from app.services.task.executor import BackgroundTaskExecutor, TaskExecutor
from app.services.task.service import TaskService
from app.services.task.store import InMemoryTaskStore, TaskStore
from app.services.user_activity_vector_service import UserActivityVectorService

logger = logging.getLogger(__name__)


# ==============================================================================
# [1] LLM / Recommend
#   _llm_client    : OpenAIClient | OllamaClient  (설정 기반 자동 선택)
#   get_recommend_service_v1/v2() : per-request — llm_client 재사용, exercises 최신 반영
#   get_response_builder_v1/v2()  : per-request — exercise_repository 동적 조회
# ==============================================================================


def _create_llm_client() -> LLMClient:
    """설정(llm.yaml)에서 프로바이더를 읽어 LLM 클라이언트 싱글턴 생성.

    교체:
      configs/llm.yaml의 default_provider 변경 → 이 함수가 다른 구현체를 반환
    TODO: gemini 등 프로바이더 추가 시 elif 분기 추가
    """
    provider_name = llm_config.default_provider
    provider_config = llm_config.providers.get(provider_name)

    if provider_name == "openai":
        return OpenAIClient(
            api_key=settings.OPENAI_API_KEY,  # type: ignore
            model=provider_config.model,  # type: ignore
            default_timeout=provider_config.timeout_sec,  # type: ignore
        )
    elif provider_name == "ollama_cloud":
        return OllamaClient(
            api_key=settings.OLLAMA_API_KEY,  # type: ignore
            model=provider_config.model,  # type: ignore
            default_timeout=provider_config.timeout_sec,  # type: ignore
        )
    # elif provider_name == "gemini":
    #     return GeminiClient(api_key=settings.GEMINI_API_KEY, model=provider_config.model)
    raise ValueError(f"지원하지 않는 LLM 프로바이더: {provider_name}")


# [Group A] LLM 클라이언트 싱글턴 — 프로세스 수명과 동일
_llm_client: LLMClient = _create_llm_client()


def get_recommend_service_v1() -> RecommendService:
    """[Group B] V1 RecommendService 생성 — Depends(get_recommend_service_v1) 사용.

    per-request인 이유:
      exercise_repository.raw_data가 /update/exercises 이후 갱신되므로
      싱글턴으로 두면 프롬프트에 구버전 데이터가 들어갈 수 있음.
      실제 조회는 _build_prompt() 호출 시 동적으로 이루어짐.

    의존: _llm_client (싱글턴 참조)
    """
    return RecommendService(llm_client=_llm_client, api_version="v1")


def get_recommend_service_v2() -> RecommendService:
    """[Group B] V2 RecommendService 생성 — get_task_service() 내부에서 직접 호출.

    per-request인 이유: get_recommend_service_v1() 참조.

    의존: _llm_client (싱글턴 참조)
    """
    return RecommendService(llm_client=_llm_client, api_version="v2")


def get_response_builder_v1() -> V1ResponseBuilder:
    """[Group B] V1ResponseBuilder 생성 — Depends(get_response_builder_v1) 사용.

    per-request인 이유:
      build_core() 호출 시 exercise_repository.get_all()로 동적 갱신.
      싱글턴 유지하면서도 최신 데이터 반영이 가능하나,
      TODO #2 정책("싱글턴 → per-request 팩토리")에 따라 per-request로 변경.
    """
    return V1ResponseBuilder()


def get_response_builder_v2() -> V2ResponseBuilder:
    """[Group B] V2ResponseBuilder 생성 — get_task_service() 내부에서 직접 호출.

    per-request인 이유: get_response_builder_v1() 참조.
    """
    return V2ResponseBuilder()


# ==============================================================================
# [2] Task / Async
#   _task_store        : InMemoryTaskStore (TODO: RedisTaskStore)
#   _callback_client   : coreBE 콜백 전송 HTTP 클라이언트
#   _cold_start_checker: DefaultColdStartChecker (TODO: ActivityBasedColdStartChecker)
#   get_task_store()   : TaskStore DI — 교체 지점
#   get_cold_start_checker(): ColdStartChecker DI — 교체 지점
#   get_task_service() : per-request — store + checker + [1] 팩토리 조합
#   get_task_executor(): per-request — FastAPI BackgroundTasks 래핑 (TODO: Celery)
# ==============================================================================


def _create_cold_start_checker() -> ColdStartChecker:
    """Qdrant 연결 상태에 따라 ColdStartChecker 구현체 선택.

    성공: ActivityBasedColdStartChecker (Qdrant 사용자 프로필 기반 판단)
    실패: DefaultColdStartChecker (항상 cold start=True, 추천 흐름 정상 동작)

    Qdrant 미연결 상태에서도 추천 API는 정상 동작한다.
    TODO: Qdrant 연동 완료 시 이 함수가 자동으로 ActivityBased를 선택함 (변경 불필요)
    """
    try:
        from app.data.qdrant_client import get_qdrant_client
        from app.data.user_activity_repository import QdrantUserActivityVectorRepository

        client = get_qdrant_client()
        repo = QdrantUserActivityVectorRepository(client)
        logger.info("ActivityBasedColdStartChecker 초기화 완료 [url=%s]", settings.QDRANT_URL)
        return ActivityBasedColdStartChecker(repo)

    except Exception as e:
        logger.warning(
            "ActivityBasedColdStartChecker 초기화 실패 — DefaultColdStartChecker로 대체: %s",
            e,
        )
        return DefaultColdStartChecker()


# [Group A] Task 인프라 싱글턴
# TODO: _task_store 교체 → RedisTaskStore(redis_client)
# TODO: BackgroundTaskExecutor 교체 → CeleryTaskExecutor (get_task_executor 함께 수정)
_task_store: TaskStore = InMemoryTaskStore()
_callback_client: CallbackClient = CallbackClient()
_cold_start_checker: ColdStartChecker = _create_cold_start_checker()


def get_task_store() -> TaskStore:
    """[Group A] TaskStore 반환 — Depends(get_task_store) 사용.

    교체: _task_store 싱글턴을 RedisTaskStore로 변경하거나
          이 함수 본문을 수정하면 모든 엔드포인트에 자동 반영.
    의존: _task_store (싱글턴)
    """
    return _task_store


def get_cold_start_checker() -> ColdStartChecker:
    """[Group A] ColdStartChecker 반환 — Depends(get_cold_start_checker) 사용.

    교체: _create_cold_start_checker()가 Qdrant 연결 성공 시 자동으로
          ActivityBasedColdStartChecker 반환 (이 함수 변경 불필요).
    의존: _cold_start_checker (싱글턴)
    """
    return _cold_start_checker


def get_task_service(
    store: TaskStore = Depends(get_task_store),
    checker: ColdStartChecker = Depends(get_cold_start_checker),
) -> TaskService:
    """[Group B] TaskService 생성 — Depends(get_task_service) 사용.

    per-request인 이유:
      내부적으로 get_recommend_service_v2() / get_response_builder_v2()를 호출하여
      최신 exercise 데이터가 반영된 RecommendService, V2ResponseBuilder를 주입.

    의존:
      store   ← get_task_store()  (싱글턴 참조)
      checker ← get_cold_start_checker()  (싱글턴 참조)
      _callback_client  (싱글턴 참조)
      get_recommend_service_v2()  (per-request)
      get_response_builder_v2()   (per-request)
    """
    return TaskService(
        store=store,
        recommend_service=get_recommend_service_v2(),
        response_builder=get_response_builder_v2(),
        callback_client=_callback_client,
        cold_start_checker=checker,
    )


def get_task_executor(
    background_tasks: BackgroundTasks,
    task_service: TaskService = Depends(get_task_service),
) -> TaskExecutor:
    """[Group B] TaskExecutor 생성 — Depends(get_task_executor) 사용.

    BackgroundTasks는 FastAPI가 요청마다 생성하는 per-request 객체이므로
    이 함수도 반드시 per-request여야 한다.

    교체: BackgroundTaskExecutor → CeleryTaskExecutor로 변경 시
          이 함수의 본문과 background_tasks 파라미터 제거만으로 완료.
    의존:
      background_tasks ← FastAPI per-request 자동 주입
      task_service     ← get_task_service() (per-request)
    TODO: CeleryTaskExecutor 교체 시 background_tasks 파라미터 제거
    """
    return BackgroundTaskExecutor(background_tasks, task_service)


# ==============================================================================
# [3] Vector / Embed
#   _embedding_model         : SentenceTransformer 싱글턴 (모든 벡터 서비스 공유)
#   _exercise_vector_svc     : ExerciseVectorService (Qdrant 미연결 시 비활성화)
#   _user_activity_vec_svc   : UserActivityVectorService (Qdrant 미연결 시 비활성화)
#   _vector_recommend_svc    : VectorRecommendService (Qdrant 미연결 시 비활성화)
#   get_exercise_vector_service()      : ExerciseVectorService DI
#   get_user_activity_vector_service() : UserActivityVectorService DI
#
#   모든 서비스가 _embedding_model 싱글턴을 공유하므로 SentenceTransformer 1회 로드.
#   Qdrant/SentenceTransformer 없이도 비활성화 모드로 정상 기동.
#   try_upsert_*() 호출 시 조용히 건너뜀 — 추천 API 흐름에 영향 없음.
# ==============================================================================


def _create_embedding_model():
    """[Group A] SentenceTransformer 싱글턴 — 모든 벡터 서비스가 공유.

    100MB+ 대형 모델이므로 프로세스 내 1회만 로드합니다.
    실패 시 None 반환 → 각 서비스가 비활성화 모드로 동작.

    환경변수:
      QDRANT_EMBEDDING_MODEL : 임베딩 모델명 (기본 intfloat/multilingual-e5-small)
    TODO: 임베딩 모델 다양화 — SentenceTransformer 외 클라우드 API 지원
    """
    try:
        from sentence_transformers import SentenceTransformer

        model = SentenceTransformer(settings.QDRANT_EMBEDDING_MODEL)
        logger.info("SentenceTransformer 로드 완료 [model=%s]", settings.QDRANT_EMBEDDING_MODEL)
        return model
    except Exception as e:
        logger.warning("SentenceTransformer 로드 실패 — 벡터 기능 비활성화: %s", e)
        return None


def _create_exercise_vector_service() -> ExerciseVectorService:
    """ExerciseVectorService 싱글턴 생성.

    성공: QdrantExerciseVectorRepository + _embedding_model 공유
    실패: repository=None, embedding_model=None (비활성화 모드)

    환경변수:
      QDRANT_URL    : 연결 대상 (기본 http://localhost:6333)
      QDRANT_API_KEY: 클라우드 인스턴스용 (로컬 생략)
    """
    try:
        from app.data.exercise_vector_repository import QdrantExerciseVectorRepository
        from app.data.qdrant_client import get_qdrant_client

        client = get_qdrant_client()
        repo = QdrantExerciseVectorRepository(client)
        logger.info("ExerciseVectorService 초기화 완료 [url=%s]", settings.QDRANT_URL)
        return ExerciseVectorService(repository=repo, embedding_model=_embedding_model)

    except Exception as e:
        logger.warning("ExerciseVectorService 초기화 실패 — 벡터 upsert 비활성화: %s", e)
        return ExerciseVectorService(repository=None, embedding_model=None)


def _create_user_activity_vector_service() -> UserActivityVectorService:
    """UserActivityVectorService 싱글턴 생성.

    성공: QdrantUserActivityVectorRepository + _embedding_model 공유
    실패: repository=None, embedding_model=None (비활성화 모드)
    """
    try:
        from app.data.qdrant_client import get_qdrant_client
        from app.data.user_activity_repository import QdrantUserActivityVectorRepository

        client = get_qdrant_client()
        repo = QdrantUserActivityVectorRepository(client)
        logger.info("UserActivityVectorService 초기화 완료 [url=%s]", settings.QDRANT_URL)
        return UserActivityVectorService(repository=repo, embedding_model=_embedding_model)

    except Exception as e:
        logger.warning("UserActivityVectorService 초기화 실패 — 벡터 upsert 비활성화: %s", e)
        return UserActivityVectorService(repository=None, embedding_model=None)


def _create_vector_recommend_service() -> VectorRecommendService:
    """VectorRecommendService 싱글턴 생성.

    성공: QdrantExerciseVectorRepository + QdrantUserActivityVectorRepository
          + _embedding_model + _llm_client 공유
    실패: exercise_repo=None, embedding_model=None, user_activity_repo=None (비활성화 모드)
          → recommend_routines() 호출 시 ConfigurationError raise
    LLM: Qdrant 비활성화와 무관하게 _llm_client 항상 주입 (reason 생성용)
    user_activity_repo: non-cold start 사용자의 활동 벡터 조회용
                        Qdrant 미연결 시 None → 설문 벡터만으로 검색 (cold start 경로)
    """
    try:
        from app.data.exercise_vector_repository import QdrantExerciseVectorRepository
        from app.data.qdrant_client import get_qdrant_client
        from app.data.user_activity_repository import QdrantUserActivityVectorRepository

        client = get_qdrant_client()
        exercise_repo = QdrantExerciseVectorRepository(client)
        user_activity_repo = QdrantUserActivityVectorRepository(client)
        logger.info("VectorRecommendService 초기화 완료 [url=%s]", settings.QDRANT_URL)
        return VectorRecommendService(
            exercise_repo=exercise_repo,
            embedding_model=_embedding_model,
            llm_client=_llm_client,
            user_activity_repo=user_activity_repo,
        )

    except Exception as e:
        logger.warning("VectorRecommendService 초기화 실패 — 비활성화: %s", e)
        return VectorRecommendService(
            exercise_repo=None,
            embedding_model=None,
            llm_client=_llm_client,
            user_activity_repo=None,
        )


# [Group A] Vector 서비스 싱글턴
_embedding_model = _create_embedding_model()
_exercise_vector_svc: ExerciseVectorService = _create_exercise_vector_service()
_user_activity_vec_svc: UserActivityVectorService = _create_user_activity_vector_service()
_vector_recommend_svc: VectorRecommendService = _create_vector_recommend_service()


def get_exercise_vector_service() -> ExerciseVectorService:
    """[Group A] ExerciseVectorService 반환 — Depends(get_exercise_vector_service) 사용.

    Qdrant 미연결 시 비활성화 모드 인스턴스를 반환.
    try_upsert_all() 호출 시 조용히 건너뜀.
    의존: _exercise_vector_svc (싱글턴)
    """
    return _exercise_vector_svc


def get_user_activity_vector_service() -> UserActivityVectorService:
    """[Group A] UserActivityVectorService 반환 — Depends(get_user_activity_vector_service) 사용.

    Qdrant 미연결 시 비활성화 모드 인스턴스를 반환.
    try_upsert_batch() 호출 시 조용히 건너뜀.
    의존: _user_activity_vec_svc (싱글턴)
    """
    return _user_activity_vec_svc


def get_task_service_vectorsearch(
    store: TaskStore = Depends(get_task_store),
    checker: ColdStartChecker = Depends(get_cold_start_checker),
) -> TaskService:
    """[Group B] 벡터 검색용 TaskService 생성 — Depends(get_task_service_vectorsearch) 사용.

    _vector_recommend_svc 싱글턴을 TaskService에 주입합니다.
    Qdrant 미연결 시 비활성화 인스턴스가 주입되며,
    run_vectorbased_recommendation() 실행 시 ConfigurationError → FAILED 처리됩니다.

    의존:
      store                ← get_task_store()  (싱글턴)
      checker              ← get_cold_start_checker()  (싱글턴)
      _callback_client     (싱글턴)
      _vector_recommend_svc (싱글턴)
      get_recommend_service_v2()   (per-request, fallback용)
      get_response_builder_v2()    (per-request)
    """
    return TaskService(
        store=store,
        recommend_service=get_recommend_service_v2(),
        response_builder=get_response_builder_v2(),
        callback_client=_callback_client,
        cold_start_checker=checker,
        vector_recommend_service=_vector_recommend_svc,
    )


def get_task_executor_vectorsearch(
    background_tasks: BackgroundTasks,
    task_service: TaskService = Depends(get_task_service_vectorsearch),
) -> TaskExecutor:
    """[Group B] 벡터 검색용 TaskExecutor 생성 — Depends(get_task_executor_vectorsearch) 사용.

    submit_vectorsearch()를 호출하는 엔드포인트에서 사용합니다.

    의존:
      background_tasks ← FastAPI per-request 자동 주입
      task_service     ← get_task_service_vectorsearch() (per-request)
    """
    return BackgroundTaskExecutor(background_tasks, task_service)
