# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""
Phase 3 regressions for the transactional outbox (bgtasks/event_outbox.py):

  * write_event persists a row with dispatch_seq NULL (outbox pending)
  * dispatch_event (fast path) and relay_events (backstop) both claim a row
    atomically — whichever gets there first wins, so an event dispatched by
    one is never re-dispatched by the other
  * relay_events is single-writer: a concurrent sweep is a no-op
  * dispatch_seq is assigned only to rows the caller believes are pending,
    is unique, and is assigned in `sequence` order within one relay sweep
"""

import json
from unittest.mock import patch
from uuid import uuid4

import pytest
from django.db import connection

from plane.bgtasks.event_outbox import (
    dispatch_event,
    relay_events,
    write_archive_event,
    write_delete_event,
    write_event,
    write_model_event,
)
from plane.db.models import EventLog, Webhook
from plane.tests.factories import ProjectFactory, WorkspaceFactory


@pytest.fixture(scope="session", autouse=True)
def _event_log_sequence_and_trigger(django_db_setup, django_db_blocker):
    # This test suite runs with pytest.ini's --nomigrations: the test DB is
    # built directly from model state, so migration 0126's RunSQL (the
    # sequence + trigger that make `sequence`/`dispatch_seq` work) never
    # runs. Recreate it here, idempotently, so these tests exercise the same
    # DB behavior real deployments get from the migration.
    with django_db_blocker.unblock():
        with connection.cursor() as cur:
            cur.execute("CREATE SEQUENCE IF NOT EXISTS event_log_sequence_seq")
            cur.execute("CREATE SEQUENCE IF NOT EXISTS event_log_dispatch_seq_seq")
            cur.execute(
                """
                CREATE OR REPLACE FUNCTION event_log_assign_sequence()
                RETURNS trigger AS $$
                BEGIN
                    IF NEW.sequence IS NULL THEN
                        NEW.sequence := nextval('event_log_sequence_seq');
                    END IF;
                    RETURN NEW;
                END;
                $$ LANGUAGE plpgsql;
                """
            )
            cur.execute("DROP TRIGGER IF EXISTS event_log_assign_sequence_trg ON event_log")
            cur.execute(
                """
                CREATE TRIGGER event_log_assign_sequence_trg
                BEFORE INSERT ON event_log
                FOR EACH ROW EXECUTE FUNCTION event_log_assign_sequence();
                """
            )


@pytest.mark.unit
@pytest.mark.django_db(transaction=True)
class TestWriteEvent:
    def test_creates_a_pending_row_with_sequence_assigned(self):
        workspace = WorkspaceFactory()

        event = write_event(
            workspace_id=workspace.id,
            entity_type="project",
            entity_id=workspace.id,
            event_type="project.created",
        )

        event.refresh_from_db()
        assert event.sequence is not None
        assert event.dispatch_seq is None
        assert event.dispatched_at is None


@pytest.mark.unit
@pytest.mark.django_db(transaction=True)
class TestWriteModelEvent:
    def test_current_instance_none_is_a_created_event(self):
        workspace = WorkspaceFactory()
        project = ProjectFactory(workspace=workspace)

        event = write_model_event(
            model_name="project",
            model_id=str(project.id),
            requested_data={"name": project.name},
            current_instance=None,
            actor_id=None,
            workspace_id=workspace.id,
        )

        assert event.event_type == "project.created"
        assert event.changes is None
        assert event.data is not None  # captured via get_model_data, not left null

    def test_diffs_current_instance_against_requested_data_into_one_row(self):
        # Mirrors model_activity's own diff, but as one row instead of one
        # webhook_activity.delay() per changed key.
        workspace = WorkspaceFactory()
        project = ProjectFactory(workspace=workspace, name="New Name")
        current_instance = json.dumps({"name": "Old Name", "identifier": "SAME"})

        event = write_model_event(
            model_name="project",
            model_id=str(project.id),
            requested_data={"name": "New Name", "identifier": "SAME"},
            current_instance=current_instance,
            actor_id=None,
            workspace_id=workspace.id,
        )

        assert event.event_type == "project.updated"
        assert event.changes == {"name": {"old": "Old Name", "new": "New Name"}}

    def test_no_changed_keys_stores_null_changes(self):
        workspace = WorkspaceFactory()
        project = ProjectFactory(workspace=workspace, name="Same Name")
        current_instance = json.dumps({"name": "Same Name"})

        event = write_model_event(
            model_name="project",
            model_id=str(project.id),
            requested_data={"name": "Same Name"},
            current_instance=current_instance,
            actor_id=None,
            workspace_id=workspace.id,
        )

        assert event.changes is None

    def test_deleted_entity_stores_null_data_instead_of_raising(self):
        workspace = WorkspaceFactory()

        event = write_model_event(
            model_name="project",
            model_id=str(uuid4()),  # no such project
            requested_data={"name": "x"},
            current_instance=None,
            actor_id=None,
            workspace_id=workspace.id,
        )

        assert event.data is None


@pytest.mark.unit
@pytest.mark.django_db(transaction=True)
class TestWriteDeleteEvent:
    def test_records_a_deleted_event_with_no_snapshot(self):
        workspace = WorkspaceFactory()
        entity_id = uuid4()

        event = write_delete_event(
            model_name="project",
            entity_id=entity_id,
            actor_id=None,
            workspace_id=workspace.id,
        )

        assert event.event_type == "project.deleted"
        assert event.data is None
        assert event.entity_id == entity_id


@pytest.mark.unit
@pytest.mark.django_db(transaction=True)
class TestWriteArchiveEvent:
    def test_archived_writes_a_snapshot(self):
        workspace = WorkspaceFactory()
        project = ProjectFactory(workspace=workspace)

        event = write_archive_event(
            model_name="project",
            model_id=str(project.id),
            archived=True,
            actor_id=None,
            workspace_id=workspace.id,
        )

        assert event.event_type == "project.archived"
        assert event.data is not None
        assert event.changes is None

    def test_unarchived_event_type(self):
        workspace = WorkspaceFactory()
        project = ProjectFactory(workspace=workspace)

        event = write_archive_event(
            model_name="project",
            model_id=str(project.id),
            archived=False,
            actor_id=None,
            workspace_id=workspace.id,
        )

        assert event.event_type == "project.unarchived"


@pytest.mark.unit
@pytest.mark.django_db(transaction=True)
class TestDispatchEventFastPath:
    @patch("plane.bgtasks.event_outbox.webhook_send_task")
    def test_claims_the_row_and_fans_out_to_matching_webhooks(self, mock_webhook_send):
        workspace = WorkspaceFactory()
        Webhook.objects.create(workspace=workspace, url="https://example.com/hook", project=True)
        # A webhook not subscribed to "project" events must not receive it.
        Webhook.objects.create(workspace=workspace, url="https://example.com/other", project=False, issue=True)

        event = write_event(
            workspace_id=workspace.id,
            entity_type="project",
            entity_id=workspace.id,
            event_type="project.updated",
            data={"id": str(workspace.id), "name": "Acme"},
            changes={"name": {"old": "Old", "new": "Acme"}},
        )

        dispatch_event.run(event_log_id=str(event.id))

        event.refresh_from_db()
        assert event.dispatch_seq is not None
        assert event.dispatched_at is not None
        assert mock_webhook_send.delay.call_count == 1
        kwargs = mock_webhook_send.delay.call_args.kwargs
        assert kwargs["action"] == "updated"
        assert kwargs["event_data"] == {"id": str(workspace.id), "name": "Acme"}
        # Phase 10: the outbox event's own id/cursor ride along on the
        # webhook payload so a receiver can dedupe deliveries by outbox event.
        assert kwargs["outbox_event_id"] == str(event.id)
        assert kwargs["dispatch_seq"] == event.dispatch_seq

    @patch("plane.bgtasks.event_outbox.webhook_send_task")
    def test_does_not_redispatch_a_row_already_claimed(self, mock_webhook_send):
        # Simulates the relay having already claimed this row first —
        # dispatch_event must be a no-op, not a second delivery.
        workspace = WorkspaceFactory()
        Webhook.objects.create(workspace=workspace, url="https://example.com/hook", project=True)

        event = write_event(
            workspace_id=workspace.id,
            entity_type="project",
            entity_id=workspace.id,
            event_type="project.created",
        )
        EventLog.objects.filter(id=event.id).update(dispatch_seq=1, dispatched_at=event.occurred_at)

        dispatch_event.run(event_log_id=str(event.id))

        mock_webhook_send.delay.assert_not_called()

    @patch("plane.bgtasks.event_outbox.webhook_send_task")
    def test_deleted_event_falls_back_to_id_only_payload(self, mock_webhook_send):
        workspace = WorkspaceFactory()
        Webhook.objects.create(workspace=workspace, url="https://example.com/hook", project=True)

        event = write_event(
            workspace_id=workspace.id,
            entity_type="project",
            entity_id=workspace.id,
            event_type="project.deleted",
            data=None,
        )

        dispatch_event.run(event_log_id=str(event.id))

        kwargs = mock_webhook_send.delay.call_args.kwargs
        assert kwargs["event_data"] == {"id": str(workspace.id)}

    @patch("plane.bgtasks.event_outbox.webhook_send_task")
    def test_entity_type_without_webhook_flag_is_skipped_without_error(self, mock_webhook_send):
        # Phase 9 reference entities (e.g. "state") have no webhook boolean
        # flag yet — fanout must no-op cleanly, not raise.
        workspace = WorkspaceFactory()
        Webhook.objects.create(workspace=workspace, url="https://example.com/hook", project=True)

        event = write_event(
            workspace_id=workspace.id,
            entity_type="state",
            entity_id=workspace.id,
            event_type="state.created",
        )

        dispatch_event.run(event_log_id=str(event.id))

        event.refresh_from_db()
        assert event.dispatch_seq is not None  # still claimed/dispatched...
        mock_webhook_send.delay.assert_not_called()  # ...just no webhook flag to match


@pytest.mark.unit
@pytest.mark.django_db(transaction=True)
class TestRelayEvents:
    @patch("plane.bgtasks.event_outbox.webhook_send_task")
    def test_claims_pending_rows_in_sequence_order_and_fans_out(self, mock_webhook_send):
        workspace = WorkspaceFactory()
        Webhook.objects.create(workspace=workspace, url="https://example.com/hook", project=True)

        e1 = write_event(
            workspace_id=workspace.id, entity_type="project", entity_id=workspace.id, event_type="project.created"
        )
        e2 = write_event(
            workspace_id=workspace.id, entity_type="project", entity_id=workspace.id, event_type="project.updated"
        )

        relay_events.run()

        e1.refresh_from_db()
        e2.refresh_from_db()
        assert e1.dispatch_seq is not None and e2.dispatch_seq is not None
        assert e1.dispatch_seq < e2.dispatch_seq  # matches insert (sequence) order
        assert mock_webhook_send.delay.call_count == 2

    @patch("plane.bgtasks.event_outbox.webhook_send_task")
    def test_skips_a_row_already_claimed_by_the_fast_path(self, mock_webhook_send):
        workspace = WorkspaceFactory()
        Webhook.objects.create(workspace=workspace, url="https://example.com/hook", project=True)

        event = write_event(
            workspace_id=workspace.id, entity_type="project", entity_id=workspace.id, event_type="project.created"
        )
        dispatch_event.run(event_log_id=str(event.id))
        mock_webhook_send.reset_mock()

        relay_events.run()

        mock_webhook_send.delay.assert_not_called()

    @patch("plane.bgtasks.event_outbox.connection")
    @patch("plane.bgtasks.event_outbox.webhook_send_task")
    def test_is_a_noop_when_the_advisory_lock_is_already_held(self, mock_webhook_send, mock_connection):
        # Simulates a concurrent sweep already holding the lock.
        cursor = mock_connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = (False,)

        workspace = WorkspaceFactory()
        write_event(
            workspace_id=workspace.id, entity_type="project", entity_id=workspace.id, event_type="project.created"
        )

        relay_events.run()

        mock_webhook_send.delay.assert_not_called()

    @patch("plane.bgtasks.event_outbox.webhook_send_task")
    def test_project_scoped_event_is_recorded_with_its_project(self, mock_webhook_send):
        workspace = WorkspaceFactory()
        project = ProjectFactory(workspace=workspace)

        event = write_event(
            workspace_id=workspace.id,
            project_id=project.id,
            entity_type="issue",
            entity_id=project.id,
            event_type="issue.created",
        )

        event.refresh_from_db()
        assert event.project_id == project.id
