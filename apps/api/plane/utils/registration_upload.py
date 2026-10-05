# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""
Once a work item sits in the registration state, its registrar's job is to
bring back the registered documents. When that registrar uploads a file to
the work item — an image or document in a comment, or a file in the
Attachments section — the work item moves on to the next stage on its own.

The move goes through plane.utils.state_transition like any other state
change, so the approval gate still applies. It never fails the upload: if the
move is refused or errors, the upload stands and the state stays put.
"""

import json
import logging
import re

from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.utils import timezone

from plane.app.serializers import IssueCreateSerializer
from plane.bgtasks.issue_activities_task import issue_activity
from plane.db.models import Issue, IssueAssignee, RegistrationHandoffRecord, State
from plane.utils.host import base_host
from plane.utils.registration_handoff import _NON_FORWARD_GROUPS, get_registration_handoff_config
from plane.utils.state_transition import commit_state_change, plan_state_change

logger = logging.getLogger("plane.api")

# images embedded by the editor, and documents attached from the comment toolbar
_IMAGE_SRC_RE = re.compile(r"<image-component\b[^>]*?\bsrc=[\"']([^\"']+)[\"']", re.IGNORECASE)
_DOCUMENT_RE = re.compile(r"/api/assets/v2/workspaces/[^\"'\s<>]+?/download/([0-9a-fA-F-]{32,36})/")


def html_file_refs(html):
    """Asset references (image srcs and document asset ids) found in editor HTML."""
    if not html:
        return set()
    return set(_IMAGE_SRC_RE.findall(html)) | {asset_id.lower() for asset_id in _DOCUMENT_RE.findall(html)}


def html_has_file(html):
    return bool(html_file_refs(html))


def get_registration_next_state(project_id, trigger_state):
    """The stage right after the registration state, by state order."""
    return (
        State.objects.filter(project_id=project_id, sequence__gt=trigger_state.sequence)
        .exclude(group__in=_NON_FORWARD_GROUPS)
        .order_by("sequence")
        .first()
    )


def advance_after_registrar_upload(issue_id, actor, request):
    """Move the work item past the registration state if `actor` is its
    registrar and it is still in that state. Returns True when it moved."""
    try:
        issue = Issue.issue_objects.filter(pk=issue_id).first()
        if issue is None or issue.state_id is None:
            return False
        config = get_registration_handoff_config(issue.project_id)
        if config is None or config.trigger_state is None or config.trigger_state_id != issue.state_id:
            return False
        if not RegistrationHandoffRecord.objects.filter(issue_id=issue.id, agent_id=actor.id).exists():
            return False
        next_state = get_registration_next_state(issue.project_id, config.trigger_state)
        if next_state is None:
            return False

        project_id = issue.project_id
        data = {"state_id": str(next_state.id)}
        state_change = plan_state_change(project_id, issue, data, actor)
        if state_change.error:
            logger.info(
                "Registrar upload did not advance work item %s: %s",
                issue.id,
                state_change.error,
            )
            return False

        current_instance = json.dumps(
            {
                "state_id": str(issue.state_id),
                "assignee_ids": [
                    str(uid)
                    for uid in IssueAssignee.objects.filter(issue_id=issue.id).values_list("assignee_id", flat=True)
                ],
            },
            cls=DjangoJSONEncoder,
        )
        requested_data = json.dumps(data, cls=DjangoJSONEncoder)
        serializer = IssueCreateSerializer(issue, data=data, partial=True, context={"project_id": project_id})
        if not serializer.is_valid():
            logger.warning("Registrar upload could not advance work item %s: %s", issue.id, serializer.errors)
            return False
        with transaction.atomic():
            serializer.save()
            commit_state_change(state_change, issue, actor)
        issue_activity.delay(
            type="issue.activity.updated",
            requested_data=requested_data,
            actor_id=str(actor.id),
            issue_id=str(issue.id),
            project_id=str(project_id),
            current_instance=current_instance,
            epoch=int(timezone.now().timestamp()),
            notification=True,
            origin=base_host(request=request, is_app=True),
        )
        return True
    except Exception:
        logger.exception("Registrar upload state advance failed for work item %s", issue_id)
        return False
