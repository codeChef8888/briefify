import importlib
import json
import os
import threading
from typing import Any, Dict

redis = None


class RedisError(Exception):
    pass


class WatchError(Exception):
    pass


try:  # pragma: no cover - keeps local dev functional without redis package
    redis = importlib.import_module("redis")
    redis_exceptions = importlib.import_module("redis.exceptions")
    RedisError = redis_exceptions.RedisError
    WatchError = redis_exceptions.WatchError
except Exception:
    redis = None


JOB_TTL_SECONDS = int(os.getenv("JOB_TTL_SECONDS", "86400"))
IDEMPOTENCY_TTL_SECONDS = int(os.getenv("IDEMPOTENCY_TTL_SECONDS", "86400"))
REDIS_URL = os.getenv("REDIS_URL", "").strip()

# Fallback stores for local single-process mode.
JOB_LEDGER: Dict[str, Dict[str, Any]] = {}
EVENT_LEDGER: Dict[str, str] = {}


class JobRepository:
    """Persist job status and idempotency keys in Redis with memory fallback."""

    def __init__(self, redis_url: str, job_ttl: int, idempotency_ttl: int):
        self.job_ttl = job_ttl
        self.idempotency_ttl = idempotency_ttl
        self._lock = threading.Lock()
        self.client = None

        if redis and redis_url:
            try:
                candidate = redis.Redis.from_url(redis_url, decode_responses=True)
                candidate.ping()
                self.client = candidate
            except RedisError:
                self.client = None

    @staticmethod
    def _job_key(job_id: str) -> str:
        return f"briefify:job:{job_id}"

    @staticmethod
    def _event_key(event_id: str) -> str:
        return f"briefify:event:{event_id}"

    def create_job(self, job_id: str, payload: Dict[str, Any]) -> None:
        if self.client:
            self.client.set(self._job_key(job_id), json.dumps(payload), ex=self.job_ttl)
            return
        with self._lock:
            JOB_LEDGER[job_id] = payload

    def get_job(self, job_id: str) -> Dict[str, Any] | None:
        if self.client:
            raw = self.client.get(self._job_key(job_id))
            if not raw:
                return None
            return json.loads(raw)
        return JOB_LEDGER.get(job_id)

    def update_job(self, job_id: str, updates: Dict[str, Any]) -> bool:
        if self.client:
            key = self._job_key(job_id)
            with self.client.pipeline() as pipe:
                for _ in range(3):
                    try:
                        pipe.watch(key)
                        raw = pipe.get(key)
                        if not raw:
                            pipe.unwatch()
                            return False
                        payload = json.loads(raw)
                        payload.update(updates)
                        pipe.multi()
                        pipe.set(key, json.dumps(payload), ex=self.job_ttl)
                        pipe.execute()
                        return True
                    except WatchError:
                        continue
            return False

        with self._lock:
            if job_id not in JOB_LEDGER:
                return False
            JOB_LEDGER[job_id].update(updates)
            return True

    def transition_status(
        self,
        job_id: str,
        from_statuses: set[str],
        to_status: str,
        updates: Dict[str, Any] | None = None,
    ) -> bool:
        if self.client:
            key = self._job_key(job_id)
            with self.client.pipeline() as pipe:
                for _ in range(3):
                    try:
                        pipe.watch(key)
                        raw = pipe.get(key)
                        if not raw:
                            pipe.unwatch()
                            return False
                        payload = json.loads(raw)
                        if payload.get("status") not in from_statuses:
                            pipe.unwatch()
                            return False
                        payload["status"] = to_status
                        if updates:
                            payload.update(updates)
                        pipe.multi()
                        pipe.set(key, json.dumps(payload), ex=self.job_ttl)
                        pipe.execute()
                        return True
                    except WatchError:
                        continue
            return False

        with self._lock:
            payload = JOB_LEDGER.get(job_id)
            if not payload or payload.get("status") not in from_statuses:
                return False
            payload["status"] = to_status
            if updates:
                payload.update(updates)
            return True

    def reserve_event(self, event_id: str, job_id: str) -> tuple[bool, str | None]:
        if self.client:
            event_key = self._event_key(event_id)
            accepted = self.client.set(event_key, job_id, nx=True, ex=self.idempotency_ttl)
            if accepted:
                return True, None
            return False, self.client.get(event_key)

        with self._lock:
            existing = EVENT_LEDGER.get(event_id)
            if existing:
                return False, existing
            EVENT_LEDGER[event_id] = job_id
            return True, None

    def get_job_id_for_event(self, event_id: str) -> str | None:
        if self.client:
            return self.client.get(self._event_key(event_id))
        return EVENT_LEDGER.get(event_id)


JOB_REPOSITORY = JobRepository(
    redis_url=REDIS_URL,
    job_ttl=JOB_TTL_SECONDS,
    idempotency_ttl=IDEMPOTENCY_TTL_SECONDS,
)
