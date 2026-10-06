"""
tests/test_ai_grounding.py

Modification():

- 提供 test ai grounding 的自動化回歸測試。
- 驗證修改後的行為與既有契約保持一致。
"""

from __future__ import annotations

from bot.mod.ai.provider.errors import ProviderUnavailableError
from bot.mod.ai.provider.gemini import GeminiTransport, inspect_response_observation


class Node:
    def __init__(self, **values) -> None:
        self.__dict__.update(values)


def test_grounded_response_requires_grounding_metadata() -> None:
    grounded = Node(
        candidates=[Node(grounding_metadata=Node(grounding_chunks=[Node(web=Node(uri="https://example.test"))]))]
    )
    ungrounded = Node(candidates=[Node(grounding_metadata=None)])

    assert inspect_response_observation(grounded, requested_web=True, requested_url_context=False).grounded
    assert not inspect_response_observation(ungrounded, requested_web=True, requested_url_context=False).grounded


def test_url_context_requires_an_explicit_success_status() -> None:
    successful = Node(
        url_context_metadata=Node(url_metadata=[Node(url_retrieval_status="URL_RETRIEVAL_STATUS_SUCCESS")])
    )
    failed = Node(
        url_context_metadata=Node(url_metadata=[Node(url_retrieval_status="URL_RETRIEVAL_STATUS_ERROR")])
    )

    assert inspect_response_observation(successful, requested_web=False, requested_url_context=True).url_context_succeeded
    assert not inspect_response_observation(failed, requested_web=False, requested_url_context=True).url_context_succeeded


def test_no_requested_grounding_is_considered_verified() -> None:
    observation = inspect_response_observation(Node(), requested_web=False, requested_url_context=False)

    assert observation.grounded
    assert observation.url_context_succeeded


def test_dns_connect_failure_is_retryable_provider_unavailable() -> None:
    error = OSError("Cannot connect to host generativelanguage.googleapis.com:443 [nodename nor servname provided]")

    assert isinstance(GeminiTransport._translate_error(error), ProviderUnavailableError)
