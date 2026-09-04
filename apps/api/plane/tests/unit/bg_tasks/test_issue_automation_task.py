# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""
close_old_issues() is a system cron task with no request/actor, so it cannot
legally move an issue into a state that requires naming a registration
agent. It must skip such a project's close entirely rather than silently
violating the rule.
"""

from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

from plane.bgtasks.issue_automation_task import close_old_issues
from plane.db.models import Issue, RegistrationHandoffConfig, State
from plane.tests.factories import ProjectFactory


@pytest.mark.unit
class TestCloseOldIssuesRegistrationGuard:
    @pytest.mark.django_db
    def test_skips_project_whose_close_state_requires_a_registration_agent(self):
        project = ProjectFactory(close_in=1)
        registration_state = State.objects.create(
            name="Sent for Registration", workspace=project.workspace, project=project, group="started"
        )
        project.default_state = registration_state
        project.save(update_fields=["default_state"])
        RegistrationHandoffConfig.objects.create(
            project=project, workspace=project.workspace, trigger_state=registration_state
        )

        backlog_state = State.objects.create(
            name="Backlog", workspace=project.workspace, project=project, group="backlog"
        )
        stale_issue = Issue.objects.create(
            name="Stale issue",
            workspace=project.workspace,
            project=project,
            state=backlog_state,
            created_by=project.created_by,
        )
        stale_issue.updated_at = timezone.now() - timedelta(days=60)
        stale_issue.save(update_fields=["updated_at"])

        with patch("plane.bgtasks.issue_automation_task.issue_activity"):
            close_old_issues()

        stale_issue.refresh_from_db()
        assert stale_issue.state_id == backlog_state.id, "must not be moved into the gated state by a system task"

    @pytest.mark.django_db
    def test_still_closes_when_no_registration_config_exists(self):
        project = ProjectFactory(close_in=1)
        default_state = State.objects.create(
            name="Closed", workspace=project.workspace, project=project, group="completed", default=True
        )
        project.default_state = default_state
        project.save(update_fields=["default_state"])

        backlog_state = State.objects.create(
            name="Backlog", workspace=project.workspace, project=project, group="backlog"
        )
        stale_issue = Issue.objects.create(
            name="Stale issue",
            workspace=project.workspace,
            project=project,
            state=backlog_state,
            created_by=project.created_by,
        )
        stale_issue.updated_at = timezone.now() - timedelta(days=60)
        stale_issue.save(update_fields=["updated_at"])

        with patch("plane.bgtasks.issue_automation_task.issue_activity"):
            close_old_issues()

        stale_issue.refresh_from_db()
        assert stale_issue.state_id == default_state.id, "unaffected projects still close as before"
