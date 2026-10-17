"""Reusable client for the verified MinerU online upload/poll/download contract.

This is production code built on the installed HTTP stack (``requests``). It
does not import the manual probe script and introduces no SDK.

Safety properties implemented here, not left to callers:

- HTTP success and provider *application* success are validated separately
  (``code == 0`` plus the documented response shapes).
- The account token is sent only to the provider API host. Storage upload and
  result download requests are issued separately and carry no credential.
- Only allowlisted HTTPS storage destinations are accepted, and redirects are
  never followed.
- Every wait is bounded by the caller's deadline (the five-minute local
  recognition budget); retries are finite and share that deadline.
- Result downloads are streamed under a byte ceiling and an interruption check.
- Error messages never contain the token or a signed storage URL.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Optional
from urllib.parse import quote, urlsplit

import requests

from .errors import (
    MineruInterrupted,
    MineruNetworkError,
    MineruRecognitionFailed,
    MineruRequestRejected,
    MineruResponseInvalid,
    MineruResultInvalid,
    MineruTimeout,
    MineruUploadFailed,
)

API_BASE = "https://mineru.net/api/v4"

# Verified standard-service contract (see the service-contract research notes).
MODEL_VERSION = "vlm"
OCR_LANGUAGE = "latin"
KNOWN_STATES = frozenset(
    {"pending", "running", "converting", "waiting-file", "done", "failed"}
)
_BATCH_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
_ERROR_DETAIL_LIMIT = 300

# Only the provider's documented storage hosts. A signed URL from anywhere else
# is treated as a malformed response, never followed.
ALLOWED_STORAGE_SUFFIXES = (".aliyuncs.com", ".openxlab.org.cn")

MAX_RESULT_BYTES = 256 * 1024 * 1024
DEFAULT_CONNECT_TIMEOUT = 10.0
DEFAULT_READ_TIMEOUT = 60.0
DEFAULT_RETRIES = 2
DEFAULT_RETRY_BACKOFF = 0.5


@dataclass(frozen=True)
class UploadTicket:
    """The provider's task identity plus the one-time upload destination."""

    batch_id: str
    upload_url: str


@dataclass(frozen=True)
class RemoteTaskState:
    """One validated snapshot of a remote recognition task."""

    state: str
    full_zip_url: Optional[str] = None
    err_msg: Optional[str] = None


def validate_storage_url(value: Any) -> str:
    """Return a verified HTTPS storage URL, or raise ``MineruResponseInvalid``.

    Rejects non-HTTPS schemes, embedded credentials, non-default ports and
    hosts outside the documented provider storage domains.
    """
    if not isinstance(value, str) or not value.strip():
        raise MineruResponseInvalid("MinerU returned no storage URL.")
    parsed = urlsplit(value)
    host = (parsed.hostname or "").lower()
    if (
        parsed.scheme != "https"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in (None, 443)
        or not host
        or not any(host == suffix.lstrip(".") or host.endswith(suffix)
                   for suffix in ALLOWED_STORAGE_SUFFIXES)
    ):
        raise MineruResponseInvalid(
            "MinerU returned a storage URL outside the verified HTTPS storage hosts.")
    return value


def _sanitize(text: Any) -> str:
    """Strip URLs and cap length so provider prose can never leak a signed URL."""
    if not isinstance(text, str):
        return ""
    cleaned = _URL_RE.sub("<URL>", text).strip()
    return cleaned[:_ERROR_DETAIL_LIMIT]


class MineruClient:
    """Client for one MinerU account, one operation at a time."""

    def __init__(
        self,
        token: str,
        *,
        session: Optional[requests.Session] = None,
        base_url: str = API_BASE,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        connect_timeout: float = DEFAULT_CONNECT_TIMEOUT,
        read_timeout: float = DEFAULT_READ_TIMEOUT,
        max_retries: int = DEFAULT_RETRIES,
        retry_backoff_seconds: float = DEFAULT_RETRY_BACKOFF,
        max_download_bytes: int = MAX_RESULT_BYTES,
    ) -> None:
        token = (token or "").strip()
        if token.lower().startswith("bearer "):
            token = token[7:].strip()
        self._token = token
        self._base_url = base_url.rstrip("/")
        self._session = session or requests.Session()
        # The environment's proxy settings must not receive the provider token.
        self._session.trust_env = False
        self._clock = clock
        self._sleep = sleep
        self._connect_timeout = connect_timeout
        self._read_timeout = read_timeout
        self._max_retries = max(0, int(max_retries))
        self._retry_backoff = max(0.0, float(retry_backoff_seconds))
        self._max_download_bytes = max(1, int(max_download_bytes))
        # Started retries of read-only provider operations (accounting only).
        self.retries = 0

    # -- public operations ---------------------------------------------

    def request_upload(self, file_name: str, data_id: str, *,
                       deadline: float) -> UploadTicket:
        """Submit one document for recognition and return its upload ticket."""
        data = self._api_call(
            "POST",
            "/file-urls/batch",
            deadline=deadline,
            retry_safe=False,
            json={
                "files": [{
                    "name": file_name,
                    "is_ocr": True,
                    "data_id": data_id,
                }],
                "model_version": MODEL_VERSION,
                "language": OCR_LANGUAGE,
                "enable_table": True,
                "enable_formula": True,
            },
        )
        batch_id = data.get("batch_id")
        if not isinstance(batch_id, str) or not _BATCH_ID_RE.fullmatch(batch_id):
            raise MineruResponseInvalid(
                "MinerU did not return a valid task identifier.")
        urls = data.get("file_urls")
        if not isinstance(urls, list) or len(urls) != 1:
            raise MineruResponseInvalid(
                "MinerU did not return exactly one upload destination.")
        return UploadTicket(batch_id=batch_id, upload_url=validate_storage_url(urls[0]))

    def upload(self, ticket: UploadTicket, source: Path, *, deadline: float) -> None:
        """Upload the source bytes to the verified storage destination.

        No provider authorization header is sent: the one-time destination is
        the only capability needed for this request.
        """
        self._remaining(deadline)
        try:
            with Path(source).open("rb") as stream:
                return self._storage_upload(ticket.upload_url, stream, deadline)
        except OSError as exc:
            raise MineruUploadFailed(
                f"The PDF could not be read for upload: {exc.strerror or exc}.") from exc

    def _storage_upload(self, url: str, stream: Any, deadline: float) -> None:
        timeout = self._timeout(deadline)
        try:
            response = self._session.request(
                "PUT", url, data=stream, headers={}, timeout=timeout,
                allow_redirects=False,
            )
        except requests.RequestException as exc:
            raise MineruNetworkError(
                "The upload to MinerU storage failed before it completed.") from exc
        if response.status_code not in (200, 201, 204):
            raise MineruUploadFailed(
                f"Uploading the PDF to MinerU storage failed "
                f"(HTTP {response.status_code}).")

    def poll(self, batch_id: str, *, expected_file_name: str,
             deadline: float) -> RemoteTaskState:
        """Return one validated remote task snapshot (read-only, retryable)."""
        if not _BATCH_ID_RE.fullmatch(batch_id or ""):
            raise MineruResponseInvalid("The stored task identifier is invalid.")
        data = self._api_call(
            "GET",
            f"/extract-results/batch/{quote(batch_id, safe='')}",
            deadline=deadline,
            retry_safe=True,
        )
        rows = data.get("extract_result")
        if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
            raise MineruResponseInvalid(
                "MinerU returned an unexpected recognition result list.")
        row = rows[0]
        if row.get("file_name") != expected_file_name:
            raise MineruResponseInvalid(
                "The recognition result does not match the uploaded document.")
        state = row.get("state")
        if state not in KNOWN_STATES:
            raise MineruResponseInvalid(
                f"MinerU reported an unknown task state {state!r}.")
        if state == "failed":
            reason = _sanitize(row.get("err_msg")) or "no reason reported"
            raise MineruRecognitionFailed(
                f"MinerU reported a recognition failure: {reason}.")
        if state == "done":
            return RemoteTaskState(
                state="done",
                full_zip_url=validate_storage_url(row.get("full_zip_url")),
            )
        return RemoteTaskState(state=state)

    def download(self, url: str, destination: Path, *, deadline: float,
                 check_interruption: Optional[Callable[[], bool]] = None) -> Path:
        """Stream the result archive to ``destination`` under all bounds."""
        url = validate_storage_url(url)
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + ".part")
        timeout = self._timeout(deadline)
        try:
            response = self._session.request(
                "GET", url, stream=True, timeout=timeout, allow_redirects=False,
            )
        except requests.RequestException as exc:
            raise MineruNetworkError(
                "The recognition result download failed.") from exc

        if response.status_code != 200:
            raise MineruResultInvalid(
                f"Downloading the recognition result failed "
                f"(HTTP {response.status_code}).")

        total = 0
        try:
            with temporary.open("wb") as output:
                for chunk in response.iter_content(1024 * 1024):
                    if check_interruption is not None and check_interruption():
                        raise MineruInterrupted(
                            "Local recognition was stopped while downloading the "
                            "result; the remote task may continue.")
                    total += len(chunk)
                    if total > self._max_download_bytes:
                        raise MineruResultInvalid(
                            "The recognition result archive exceeds the allowed size.")
                    if self._clock() >= deadline:
                        raise MineruTimeout(
                            "The local recognition budget elapsed during the "
                            "result download.")
                    output.write(chunk)
            temporary.replace(destination)
        except Exception:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:  # pragma: no cover - best-effort cleanup
                pass
            raise
        finally:
            close = getattr(response, "close", None)
            if close is not None:
                close()
        return destination

    def close(self) -> None:
        try:
            self._session.close()
        except Exception:  # pragma: no cover - closing never fails a job
            pass

    # -- internals ------------------------------------------------------

    def _api_call(self, method: str, path: str, *, deadline: float,
                  retry_safe: bool, json: Optional[Dict[str, Any]] = None
                  ) -> Dict[str, Any]:
        response = self._provider_request(
            method, path, deadline=deadline, retry_safe=retry_safe, json=json,
        )
        try:
            payload = response.json()
        except ValueError as exc:
            raise MineruResponseInvalid(
                "MinerU returned a response that is not JSON.") from exc
        if not isinstance(payload, dict):
            raise MineruResponseInvalid(
                "MinerU returned an unexpected response structure.")
        if payload.get("code") != 0:
            code = payload.get("code")
            raise MineruRequestRejected(
                f"MinerU rejected the request (application code {code}).",
                provider_code=str(code),
            )
        data = payload.get("data")
        if not isinstance(data, dict):
            raise MineruResponseInvalid(
                "MinerU returned an unexpected response structure.")
        return data

    def _provider_request(self, method: str, path: str, *, deadline: float,
                          retry_safe: bool, json: Optional[Dict[str, Any]] = None
                          ) -> requests.Response:
        url = f"{self._base_url}{path}"
        attempts = self._max_retries + 1 if retry_safe else 1
        last_error: Optional[Exception] = None
        for attempt in range(attempts):
            timeout = self._timeout(deadline)
            try:
                response = self._session.request(
                    method, url,
                    headers={"Authorization": f"Bearer {self._token}"},
                    json=json,
                    timeout=timeout,
                    allow_redirects=False,
                )
            except requests.RequestException as exc:
                last_error = exc
                if attempt + 1 < attempts and self._retry_later(deadline, attempt):
                    continue
                raise MineruNetworkError(
                    "A MinerU provider request failed after the allowed retries."
                ) from exc

            status = response.status_code
            if status in (401, 403):
                raise MineruRequestRejected(
                    f"MinerU rejected the configured credentials (HTTP {status}).")
            if status in (429,) or 500 <= status < 600:
                last_error = MineruNetworkError(
                    f"MinerU temporarily rejected the request (HTTP {status}).")
                if attempt + 1 < attempts and self._retry_later(deadline, attempt):
                    continue
                raise last_error
            if status >= 400:
                code = self._application_code(response)
                raise MineruRequestRejected(
                    f"MinerU rejected the request (HTTP {status}).",
                    provider_code=code,
                )
            return response
        raise MineruNetworkError(
            "A MinerU provider request failed after the allowed retries.") from last_error

    @staticmethod
    def _application_code(response: requests.Response) -> Optional[str]:
        try:
            payload = response.json()
        except ValueError:
            return None
        if isinstance(payload, dict) and payload.get("code") is not None:
            return str(payload.get("code"))
        return None

    def _retry_later(self, deadline: float, attempt: int) -> bool:
        remaining = deadline - self._clock()
        if remaining <= 0:
            raise MineruTimeout(
                "The local recognition budget elapsed while retrying a "
                "MinerU request.")
        self.retries += 1
        delay = min(self._retry_backoff * (2 ** attempt), remaining)
        self._sleep(delay)
        if self._clock() >= deadline:
            raise MineruTimeout(
                "The local recognition budget elapsed while retrying a "
                "MinerU request.")
        return True

    def _timeout(self, deadline: float) -> tuple:
        remaining = self._remaining(deadline)
        return (min(self._connect_timeout, remaining),
                min(self._read_timeout, remaining))

    def _remaining(self, deadline: float) -> float:
        remaining = deadline - self._clock()
        if remaining <= 0:
            raise MineruTimeout(
                "The local recognition budget elapsed before the request could "
                "start; this is not remote cancellation.")
        return remaining
