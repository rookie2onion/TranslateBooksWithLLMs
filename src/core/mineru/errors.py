"""Typed failures of the online recognition path.

Every error carries a stable ``code`` so the Web layer can resolve an actionable,
localized message without parsing English prose. Messages themselves are
actionable English for the operator/developer; they never include credentials,
signed URLs or server filesystem paths.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional


class MineruError(Exception):
    """Base class for every failure of the online recognition path."""

    code = "mineru_error"

    def __init__(self, message: str, *, limits: Optional[Mapping[str, Any]] = None,
                 detail: Optional[str] = None) -> None:
        super().__init__(message)
        self.message = message
        self.limits: Optional[Dict[str, Any]] = dict(limits) if limits else None
        self.detail = detail

    def to_payload(self) -> Dict[str, Any]:
        """HTTP-safe description of this failure (no credentials, no URLs)."""
        payload: Dict[str, Any] = {"code": self.code, "message": self.message}
        if self.limits:
            payload["limits"] = dict(self.limits)
        return payload


class MineruAuthorizationRequired(MineruError):
    """The task never received explicit upload authorization."""

    code = "mineru_authorization_required"


class MineruTokenMissing(MineruError):
    """No MinerU account token is configured in the environment."""

    code = "mineru_token_missing"


class MineruPdfUnreadable(MineruError):
    """The source cannot be read as a PDF."""

    code = "mineru_pdf_unreadable"


class MineruPdfEncrypted(MineruError):
    """The source PDF is password-protected."""

    code = "mineru_pdf_encrypted"


class MineruPageLimit(MineruError):
    """The source exceeds the recognition page ceiling."""

    code = "mineru_page_limit"


class MineruByteLimit(MineruError):
    """The source exceeds the recognition byte ceiling."""

    code = "mineru_byte_limit"


class MineruStateUnavailable(MineruError):
    """The task-owned recognition state could not be read or written."""

    code = "mineru_state_unavailable"


class MineruContinuationUnavailable(MineruError):
    """Safe continuation is not implemented yet, so the attempt fails closed."""

    code = "mineru_continuation_unavailable"


class MineruSubmissionUncertain(MineruError):
    """A submission may have succeeded; it must never be replaced automatically."""

    code = "mineru_submission_unknown"


class MineruUploadFailed(MineruError):
    """The source upload to the provider storage did not complete."""

    code = "mineru_upload_failed"


class MineruRecognitionFailed(MineruError):
    """The provider reported a recognition failure."""

    code = "mineru_recognition_failed"


class MineruTimeout(MineruError):
    """The local recognition budget elapsed; this is not remote cancellation."""

    code = "mineru_recognition_timeout"


class MineruInterrupted(MineruError):
    """Local processing stopped cooperatively; the remote task may continue."""

    code = "mineru_recognition_interrupted"


class MineruNetworkError(MineruError):
    """A provider request failed after bounded retries."""

    code = "mineru_network_error"


class MineruResponseInvalid(MineruError):
    """The provider response did not match the verified contract."""

    code = "mineru_response_invalid"


class MineruRequestRejected(MineruError):
    """The provider explicitly rejected the request (a definite outcome)."""

    code = "mineru_provider_rejected"

    def __init__(self, message: str, *, provider_code: Optional[str] = None,
                 limits: Optional[Mapping[str, Any]] = None) -> None:
        super().__init__(message, limits=limits)
        self.provider_code = provider_code


class MineruResultInvalid(MineruError):
    """The returned recognition result is unusable or does not match the source."""

    code = "mineru_result_invalid"


class MineruOutputInvalid(MineruError):
    """The generated translated PDF failed its validation."""

    code = "mineru_output_invalid"
