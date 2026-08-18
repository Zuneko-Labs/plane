# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""
Phase 1 delivery-reliability regressions for ``webhook_send_task``:

  * a worker killed mid-task must redeliver, not silently drop the task
    (``task_acks_late`` / ``task_reject_on_worker_lost``)
  * a non-2xx response must retry and must not be recorded as delivered
    (``raise_for_status``), and must not be logged twice
  * the HMAC signature must sign the exact bytes sent on the wire, not a
    second independent serialization of the same payload
"""

import hashlib
import hmac
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest
import requests

from plane.bgtasks.webhook_task import webhook_send_task


def _webhook(**overrides):
    webhook = MagicMock()
    webhook.id = "wh-1"
    webhook.workspace_id = "ws-1"
    webhook.secret_key = ""
    webhook.url = "https://example.com/hook"
    webhook.created_by_id = "user-1"
    for key, value in overrides.items():
        setattr(webhook, key, value)
    return webhook


def _response(status_code, raise_error=False):
    resp = MagicMock(spec=requests.Response)
    resp.status_code = status_code
    resp.headers = {}
    resp.text = "body"
    if raise_error:
        resp.raise_for_status.side_effect = requests.HTTPError(response=resp)
    else:
        resp.raise_for_status.return_value = None
    return resp


@contextmanager
def _bound_task(retries=0):
    # `webhook_send_task.run` is already a bound method (celery's autoretry
    # wrapper rebinds `self` to the real Task instance) — a fake `self` passed
    # positionally collides with it. Simulate a worker-assigned request
    # context on the real task instead, via celery's own push/pop_request.
    webhook_send_task.push_request(retries=retries)
    try:
        yield webhook_send_task
    finally:
        webhook_send_task.pop_request()


_CALL_KWARGS = dict(
    slug="acme",
    event="project",
    event_data={"id": "p-1"},
    action="PATCH",
    current_site="https://app.plane.so",
    activity=None,
)


@pytest.mark.unit
def test_worker_ack_late_and_reject_on_lost_are_configured():
    # Without these, Celery acks a task before it runs — a worker killed
    # mid-task (OOM, deploy, crash) silently loses it, no retry, no error.
    from plane.celery import app

    assert app.conf.task_acks_late is True
    assert app.conf.task_reject_on_worker_lost is True


@pytest.mark.unit
class TestNon2xxIsNotDelivered:
    @patch("plane.bgtasks.webhook_task.Webhook")
    @patch("plane.bgtasks.webhook_task.save_webhook_log")
    @patch("plane.bgtasks.webhook_task.pinned_fetch")
    def test_500_response_retries_and_logs_the_real_status_once(self, mock_fetch, mock_save_log, mock_webhook_cls):
        mock_webhook_cls.objects.get.return_value = _webhook()
        mock_fetch.return_value = _response(500, raise_error=True)

        with _bound_task(retries=0), pytest.raises(requests.RequestException):
            webhook_send_task.run(webhook_id="wh-1", **_CALL_KWARGS)

        # Previously a 500 fell through to "sent successfully" and was never
        # retried — raise_for_status() must turn it into a retryable failure.
        assert mock_save_log.call_count == 1
        assert mock_save_log.call_args.kwargs["response_status"] == 500
        mock_webhook_cls.objects.filter.assert_not_called()

    @patch("plane.bgtasks.webhook_task.send_webhook_deactivation_email")
    @patch("plane.bgtasks.webhook_task.Webhook")
    @patch("plane.bgtasks.webhook_task.save_webhook_log")
    @patch("plane.bgtasks.webhook_task.pinned_fetch")
    def test_exhausted_retries_deactivates_without_raising(
        self, mock_fetch, mock_save_log, mock_webhook_cls, mock_deactivation_email
    ):
        mock_webhook_cls.objects.get.return_value = _webhook()
        mock_fetch.return_value = _response(500, raise_error=True)

        with _bound_task(retries=5):
            webhook_send_task.run(webhook_id="wh-1", **_CALL_KWARGS)

        mock_webhook_cls.objects.filter.return_value.update.assert_called_once_with(is_active=False)
        mock_deactivation_email.delay.assert_called_once()
        assert mock_save_log.call_count == 1

    @patch("plane.bgtasks.webhook_task.Webhook")
    @patch("plane.bgtasks.webhook_task.save_webhook_log")
    @patch("plane.bgtasks.webhook_task.pinned_fetch")
    def test_200_response_is_logged_once_and_not_retried(self, mock_fetch, mock_save_log, mock_webhook_cls):
        mock_webhook_cls.objects.get.return_value = _webhook()
        mock_fetch.return_value = _response(200)

        with _bound_task(retries=0):
            webhook_send_task.run(webhook_id="wh-1", **_CALL_KWARGS)

        assert mock_save_log.call_count == 1
        assert mock_save_log.call_args.kwargs["response_status"] == 200

    @patch("plane.bgtasks.webhook_task.Webhook")
    @patch("plane.bgtasks.webhook_task.save_webhook_log")
    @patch("plane.bgtasks.webhook_task.pinned_fetch")
    def test_transport_failure_with_no_response_logs_fallback_status(self, mock_fetch, mock_save_log, mock_webhook_cls):
        # A connection error / timeout never produces a response at all —
        # this is the "already_logged is still False" path.
        mock_webhook_cls.objects.get.return_value = _webhook()
        mock_fetch.side_effect = requests.ConnectionError("refused")

        with _bound_task(retries=0), pytest.raises(requests.RequestException):
            webhook_send_task.run(webhook_id="wh-1", **_CALL_KWARGS)

        assert mock_save_log.call_count == 1
        assert mock_save_log.call_args.kwargs["response_status"] == 500


@pytest.mark.unit
class TestHmacSignsExactBytesSent:
    @patch("plane.bgtasks.webhook_task.Webhook")
    @patch("plane.bgtasks.webhook_task.save_webhook_log")
    @patch("plane.bgtasks.webhook_task.pinned_fetch")
    def test_signature_matches_the_body_actually_sent(self, mock_fetch, mock_save_log, mock_webhook_cls):
        mock_webhook_cls.objects.get.return_value = _webhook(secret_key="s3cr3t")
        mock_fetch.return_value = _response(200)

        with _bound_task(retries=0):
            webhook_send_task.run(webhook_id="wh-1", **_CALL_KWARGS)

        kwargs = mock_fetch.call_args.kwargs
        # Sent as `data=<bytes>`, not `json=`, so nothing re-serializes it
        # between signing and sending.
        assert "json" not in kwargs
        sent_bytes = kwargs["data"]
        assert isinstance(sent_bytes, bytes)

        expected_signature = hmac.new(b"s3cr3t", sent_bytes, hashlib.sha256).hexdigest()
        assert kwargs["headers"]["X-Plane-Signature"] == expected_signature


@pytest.mark.unit
class TestOutboxEventIdOnPayloadAndLog:
    """
    Phase 10: a webhook fired from the outbox carries the event_log row's id
    and dispatch_seq, both on the wire (so a receiver can dedupe across
    retries) and on the WebhookLog row (so the delivery can be traced back
    to the outbox event that triggered it).
    """

    @patch("plane.bgtasks.webhook_task.Webhook")
    @patch("plane.bgtasks.webhook_task.save_webhook_log")
    @patch("plane.bgtasks.webhook_task.pinned_fetch")
    def test_outbox_event_id_reaches_the_payload_and_the_log(self, mock_fetch, mock_save_log, mock_webhook_cls):
        import json

        mock_webhook_cls.objects.get.return_value = _webhook()
        mock_fetch.return_value = _response(200)

        with _bound_task(retries=0):
            webhook_send_task.run(
                webhook_id="wh-1",
                outbox_event_id="evt-123",
                dispatch_seq=42,
                **_CALL_KWARGS,
            )

        sent_payload = json.loads(mock_fetch.call_args.kwargs["data"])
        assert sent_payload["outbox_event_id"] == "evt-123"
        assert sent_payload["dispatch_seq"] == 42

        assert mock_save_log.call_args.kwargs["outbox_event_id"] == "evt-123"

    @patch("plane.bgtasks.webhook_task.Webhook")
    @patch("plane.bgtasks.webhook_task.save_webhook_log")
    @patch("plane.bgtasks.webhook_task.pinned_fetch")
    def test_absent_outbox_event_id_defaults_to_none(self, mock_fetch, mock_save_log, mock_webhook_cls):
        import json

        mock_webhook_cls.objects.get.return_value = _webhook()
        mock_fetch.return_value = _response(200)

        with _bound_task(retries=0):
            webhook_send_task.run(webhook_id="wh-1", **_CALL_KWARGS)

        sent_payload = json.loads(mock_fetch.call_args.kwargs["data"])
        assert sent_payload["outbox_event_id"] is None
        assert sent_payload["dispatch_seq"] is None
        assert mock_save_log.call_args.kwargs["outbox_event_id"] is None
