# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import logging

# Django imports
from django.conf import settings
from django.core.mail import EmailMultiAlternatives, get_connection

# Third party imports
from celery import shared_task

# Module imports
from plane.db.models import Issue, User
from plane.license.utils.instance_value import get_email_configuration
from plane.utils.exception_logger import log_exception


@shared_task
def send_registration_agent_email(issue_id, agent_id):
    """Notify a user by email the moment they're named registration agent on
    a work item (see plane.utils.registration_handoff) — they need to know
    which ticket to act on and what it's about, since they may not have been
    an assignee on it before."""
    try:
        issue = Issue.objects.select_related("project", "project__workspace").get(pk=issue_id)
        agent = User.objects.get(pk=agent_id)
    except (Issue.DoesNotExist, User.DoesNotExist):
        return

    if not agent.email:
        return

    (
        EMAIL_HOST,
        EMAIL_HOST_USER,
        EMAIL_HOST_PASSWORD,
        EMAIL_PORT,
        EMAIL_USE_TLS,
        EMAIL_USE_SSL,
        EMAIL_FROM,
    ) = get_email_configuration()

    base_url = settings.WEB_URL or settings.APP_BASE_URL
    issue_identifier = f"{issue.project.identifier}-{issue.sequence_id}"
    issue_url = f"{base_url}/{issue.project.workspace.slug}/projects/{issue.project.id}/issues/{issue.id}"
    description = issue.description_stripped or ""

    subject = f"You've been named registration agent on {issue_identifier}"
    text_content = (
        f"Hi {agent.first_name},\n\n"
        f"You've been named the registration agent on {issue_identifier} - {issue.name}.\n\n"
        f"Description:\n{description}\n\n"
        f"View the work item: {issue_url}\n"
    )
    html_content = (
        f"<p>Hi {agent.first_name},</p>"
        f"<p>You've been named the registration agent on "
        f"<a href='{issue_url}'>{issue_identifier} - {issue.name}</a>.</p>"
        f"<p><strong>Description:</strong><br/>{description}</p>"
        f"<p><a href='{issue_url}'>View the work item</a></p>"
    )

    try:
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
        logging.getLogger("plane.worker").info("Registration agent email sent successfully")
    except Exception as e:
        log_exception(e)
