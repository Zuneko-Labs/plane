# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
"""
Seed dummy data to test: team calendar (+N more, month view), inbox hover,
mark-all-read (All + Mentions tabs), views search.

Run from apps/api (inside the api container or your venv):

    SEED_WORKSPACE=<workspace-slug> SEED_EMAIL=<your-email> \
        python manage.py shell -c "exec(open('seed_test_data.py').read())"

Remove everything it created:

    SEED_ACTION=clean SEED_WORKSPACE=<slug> SEED_EMAIL=<email> \
        python manage.py shell -c "exec(open('seed_test_data.py').read())"

All records are tagged with the "[SEED]" prefix so cleanup only touches them.
"""

import os
from datetime import timedelta

from django.utils import timezone

from plane.db.models import (
    Issue,
    IssueAssignee,
    IssueView,
    Notification,
    Project,
    ProjectMember,
    State,
    User,
    Workspace,
)

TAG = "[SEED]"
slug = os.environ.get("SEED_WORKSPACE")
email = os.environ.get("SEED_EMAIL")
action = os.environ.get("SEED_ACTION", "seed")

# Defaults: the only workspace, and its owner (override with SEED_WORKSPACE / SEED_EMAIL)
workspace = Workspace.objects.get(slug=slug) if slug else Workspace.objects.order_by("created_at").first()
assert workspace, "no workspace found"
user = User.objects.get(email=email) if email else workspace.owner
member_project_ids = ProjectMember.objects.filter(workspace=workspace, member=user, is_active=True).values_list(
    "project_id", flat=True
)
project = Project.objects.filter(pk__in=member_project_ids).order_by("created_at").first()
assert project, "user is not an active member of any project in this workspace"
print(f"using workspace '{workspace.slug}', user '{user.email}', project '{project.name}'")

if action == "clean":
    Notification.objects.filter(workspace=workspace, receiver=user, title__startswith=TAG).delete()
    seeded = Issue.objects.filter(project=project, name__startswith=TAG)
    IssueAssignee.objects.filter(issue__in=seeded).delete()
    seeded.delete()
    IssueView.objects.filter(project=project, name__startswith=TAG).delete()
    print("cleaned seed data")
else:

    def get_state(group):
        state = State.objects.filter(project=project, group=group).first()
        return state or State.objects.create(
            name=group.title(), color="#60646C", group=group, project=project, workspace=workspace, sequence=10000
        )

    today = timezone.localdate()
    states = [get_state("unstarted"), get_state("started")]

    # ---- work items (team calendar) ----------------------------------------
    # 6 items all covering 'today' -> month cell shows 3 chips + "+3 more"
    issues = []

    def make_issue(name, start_off, end_off, state):
        issue = Issue.objects.create(
            project=project,
            workspace=workspace,
            name=f"{TAG} {name}",
            start_date=today + timedelta(days=start_off),
            target_date=today + timedelta(days=end_off),
            state=state,
            created_by=user,
        )
        IssueAssignee.objects.create(issue=issue, assignee=user, project=project, workspace=workspace)
        issues.append(issue)
        return issue

    for i in range(6):
        make_issue(f"Busy day task {i + 1}", -1, i, states[i % 2])
    make_issue("Long running (spans month)", -12, 14, states[1])
    make_issue("Next week item A", 7, 9, states[0])
    make_issue("Next week item B", 8, 8, states[0])
    make_issue("Last month item", -35, -33, states[1])
    make_issue("Next month item", 35, 38, states[0])

    # ---- notifications (inbox hover + mark all read) -----------------------
    def make_notification(issue, sender, field="state", **extra):
        Notification.objects.create(
            workspace=workspace,
            project=project,
            receiver=user,
            triggered_by=user,
            entity_identifier=issue.id,
            entity_name="issue",
            sender=sender,
            title=f"{TAG} {field} changed on {issue.name}",
            data={
                "issue": {
                    "id": str(issue.id),
                    "name": issue.name,
                    "identifier": project.identifier,
                    "sequence_id": issue.sequence_id,
                    "state_name": issue.state.name,
                    "state_group": issue.state.group,
                },
                "issue_activity": {
                    "id": str(issue.id),
                    "verb": "updated",
                    "field": field,
                    "actor": str(user.id),
                    "new_value": "In Progress",
                    "old_value": "Todo",
                    "issue_comment": "",
                    "old_identifier": None,
                    "new_identifier": None,
                },
            },
            **extra,
        )

    for issue in issues[:8]:
        make_notification(issue, "in_app:issue_activities:subscribed")  # All tab
    for issue in issues[:4]:
        make_notification(issue, "in_app:issue_activities:mentioned", field="mention")  # Mentions tab
    make_notification(issues[8], "in_app:issue_activities:subscribed", archived_at=timezone.now())
    make_notification(
        issues[9], "in_app:issue_activities:subscribed", snoozed_till=timezone.now() + timedelta(days=1)
    )

    # ---- views (views search) ----------------------------------------------
    for name in ["gst returns", "GST filing", "gstin audit", "Sprint board", "Backlog grooming", "Customer bugs"]:
        IssueView.objects.create(
            project=project, workspace=workspace, name=f"{TAG} {name}", created_by=user, owned_by=user, query={}, filters={}
        )

    print(
        f"seeded in project '{project.name}': {len(issues)} work items, "
        "12 unread notifications (8 all + 4 mentions), 1 archived, 1 snoozed, 6 views"
    )
