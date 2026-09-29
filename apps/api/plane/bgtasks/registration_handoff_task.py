# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import logging

# Django imports
from django.conf import settings
from django.core.mail import EmailMultiAlternatives, get_connection
from django.template.loader import render_to_string

# Third party imports
from celery import shared_task

# Module imports
from plane.db.models import Issue, ProjectMember, User
from plane.license.utils.instance_value import get_email_configuration
from plane.utils.email import generate_plain_text_from_html
from plane.utils.exception_logger import log_exception

logger = logging.getLogger("plane.worker")


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_registration_agent_email(self, issue_id, agent_id, actor_id=None):
    """Email a user that they've been assigned as registrar on a work item
    (see plane.utils.registration_handoff). Queued on transaction commit, so
    it is only sent once the move into the registration state is saved, and
    sent on every entry into that state — each entry is a fresh call to act.
    """
    issue = (
        Issue.objects.select_related("project", "project__workspace", "state").filter(pk=issue_id).first()
    )
    agent = User.objects.filter(pk=agent_id, is_active=True).first()
    if issue is None or agent is None or not agent.email:
        return

    # the registrar may have left the project between the request and now
    if not ProjectMember.objects.filter(project_id=issue.project_id, member_id=agent_id, is_active=True).exists():
        return

    actor = User.objects.filter(pk=actor_id).first() if actor_id else None
    assigned_by_name = None
    if actor and str(actor.id) != str(agent.id):
        assigned_by_name = actor.display_name or actor.first_name or actor.email

    base_url = (settings.WEB_URL or settings.APP_BASE_URL or "").rstrip("/")
    project = issue.project
    issue_identifier = f"{project.identifier}-{issue.sequence_id}"
    issue_url = f"{base_url}/{project.workspace.slug}/projects/{project.id}/issues/{issue.id}"

    context = {
        "agent_first_name": agent.first_name or agent.display_name or agent.email,
        "assigned_by_name": assigned_by_name,
        "issue_identifier": issue_identifier,
        "issue_name": issue.name,
        "issue_url": issue_url,
        "state_name": issue.state.name if issue.state_id else "Registration",
        "project_name": project.name,
        "workspace_name": project.workspace.name,
        "description": (issue.description_stripped or "")[:1000],
        "email": agent.email,
    }

    subject = f"You've been assigned as registrar for {issue_identifier} in {project.name}"
    html_content = render_to_string("emails/notifications/registrar_assignment.html", context)
    text_content = generate_plain_text_from_html(html_content)

    try:
        (
            EMAIL_HOST,
            EMAIL_HOST_USER,
            EMAIL_HOST_PASSWORD,
            EMAIL_PORT,
            EMAIL_USE_TLS,
            EMAIL_USE_SSL,
            EMAIL_FROM,
        ) = get_email_configuration()

        connection = get_connection(
            host=EMAIL_HOST,
            port=int(EMAIL_PORT),
            username=EMAIL_HOST_USER,
            password=EMAIL_HOST_PASSWORD,
            use_tls=EMAIL_USE_TLS == "1",
            use_ssl=EMAIL_USE_SSL == "1",
        )
        msg = EmailMultiAlternatives(
            subject=subject,
            body=text_content,
            from_email=EMAIL_FROM,
            to=[agent.email],
            connection=connection,
        )
        msg.attach_alternative(html_content, "text/html")
        msg.send()
        logger.info("Registrar assignment email sent for %s", issue_identifier)
    except Exception as e:
        # transient SMTP failures shouldn't lose the registrar's notice
        if self.request.retries < self.max_retries:
            raise self.retry(exc=e)
        log_exception(e)
