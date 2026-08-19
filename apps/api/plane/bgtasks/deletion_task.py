# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Django imports
from django.utils import timezone
from django.apps import apps
from django.conf import settings
from django.db import models, transaction
from django.db.models.fields.related import OneToOneRel


# Third party imports
from celery import shared_task


@shared_task
def soft_delete_related_objects(app_label, model_name, instance_pk, using=None):
    """
    Soft delete related objects for a given model instance
    """
    # Get the model class using app registry
    model_class = apps.get_model(app_label, model_name)

    # Get the instance using all_objects to ensure we can get even if it's already soft deleted
    try:
        instance = model_class.all_objects.get(pk=instance_pk)
    except model_class.DoesNotExist:
        return

    # Get all related fields that are reverse relationships
    all_related = [
        f for f in instance._meta.get_fields() if (f.one_to_many or f.one_to_one) and f.auto_created and not f.concrete
    ]

    # Handle each related field
    for relation in all_related:
        related_name = relation.get_accessor_name()

        # Skip if the relation doesn't exist
        if not hasattr(instance, related_name):
            continue

        # Get the on_delete behavior name
        on_delete_name = relation.on_delete.__name__ if hasattr(relation.on_delete, "__name__") else ""

        if on_delete_name == "DO_NOTHING":
            continue

        elif on_delete_name == "SET_NULL":
            # Handle SET_NULL relationships
            if isinstance(relation, OneToOneRel):
                # For OneToOne relationships
                related_obj = getattr(instance, related_name, None)
                if related_obj and isinstance(related_obj, models.Model):
                    setattr(related_obj, relation.remote_field.name, None)
                    related_obj.save(update_fields=[relation.remote_field.name])
            else:
                # For other relationships
                related_queryset = getattr(instance, related_name).all()
                related_queryset.update(**{relation.remote_field.name: None})

        else:
            # Handle CASCADE and other delete behaviors
            try:
                if relation.one_to_one:
                    # Handle OneToOne relationships
                    related_obj = getattr(instance, related_name, None)
                    if related_obj:
                        if hasattr(related_obj, "deleted_at"):
                            if not related_obj.deleted_at:
                                related_obj.deleted_at = timezone.now()
                                related_obj.save()
                                # Recursively handle related objects
                                soft_delete_related_objects(
                                    related_obj._meta.app_label,
                                    related_obj._meta.model_name,
                                    related_obj.pk,
                                    using,
                                )
                else:
                    # Handle other relationships
                    related_queryset = getattr(instance, related_name)(manager="objects").all()

                    for related_obj in related_queryset:
                        if hasattr(related_obj, "deleted_at"):
                            if not related_obj.deleted_at:
                                related_obj.deleted_at = timezone.now()
                                related_obj.save()
                                # Recursively handle related objects
                                soft_delete_related_objects(
                                    related_obj._meta.app_label,
                                    related_obj._meta.model_name,
                                    related_obj.pk,
                                    using,
                                )
            except Exception as e:
                # Log the error or handle as needed
                print(f"Error handling relation {related_name}: {str(e)}")
                continue

    # Finally, soft delete the instance itself if it hasn't been deleted yet
    if hasattr(instance, "deleted_at") and not instance.deleted_at:
        instance.deleted_at = timezone.now()
        instance.save()


# @shared_task
def restore_related_objects(app_label, model_name, instance_pk, using=None):
    pass


@shared_task
def hard_delete():
    from plane.db.models import (
        Workspace,
        Project,
        Cycle,
        Module,
        Issue,
        Page,
        IssueView,
        Label,
        State,
        IssueActivity,
        IssueComment,
        IssueLink,
        IssueReaction,
        UserFavorite,
        ModuleIssue,
        CycleIssue,
        Estimate,
        EstimatePoint,
    )
    from plane.bgtasks.event_outbox import emit_delete_event

    days = settings.HARD_DELETE_AFTER_DAYS
    cutoff = timezone.now() - timezone.timedelta(days=days)

    # Helper: emit delete events for hard-deleted rows.
    # emit_delete_event writes outbox rows and schedules dispatch atomically.
    def _hard_delete_with_events(model, workspace_fk="workspace_id", project_fk="project_id"):
        """
        Hard-delete all rows past the retention window and emit one
        ``<entity>.deleted`` outbox event per row so consumers don't diverge.

        ``workspace_fk`` / ``project_fk`` are the field names on the model
        that hold workspace/project context; pass ``None`` for models that
        have no such field.
        """
        qs = model.all_objects.filter(deleted_at__lt=cutoff)
        # Collect the fields we need before the rows disappear.
        extra = {}
        if workspace_fk:
            extra["workspace_id"] = workspace_fk
        if project_fk:
            extra["project_id"] = project_fk

        rows = list(qs.values("id", *[v for v in extra.values()]))

        with transaction.atomic():
            qs.delete()
            entity_type = model._meta.model_name
            for row in rows:
                emit_delete_event(
                    model_name=entity_type,
                    entity_id=row["id"],
                    actor_id=None,  # system-initiated
                    workspace_id=row.get(workspace_fk) if workspace_fk else None,
                    project_id=row.get(project_fk) if project_fk else None,
                )

    # Entity types that have meaningful consumers in the events API.
    # Order mirrors the original cascade order (parents before children where
    # Django would cascade, but hard_delete already handles each table
    # independently so order mainly matters for FK constraint safety).
    _hard_delete_with_events(Workspace, workspace_fk="id", project_fk=None)
    _hard_delete_with_events(Project, workspace_fk="workspace_id", project_fk="id")
    _hard_delete_with_events(Cycle)
    _hard_delete_with_events(Module)
    _hard_delete_with_events(Issue)
    _hard_delete_with_events(Page)
    _hard_delete_with_events(IssueView)
    _hard_delete_with_events(Label)
    _hard_delete_with_events(State)

    # Activity / join tables — emit events but they typically have no
    # direct webhook subscribers; still important for pull-API consumers.
    _hard_delete_with_events(IssueActivity)
    _hard_delete_with_events(IssueComment)
    _hard_delete_with_events(IssueLink)
    _hard_delete_with_events(IssueReaction)
    _hard_delete_with_events(UserFavorite, project_fk=None)
    _hard_delete_with_events(ModuleIssue)
    _hard_delete_with_events(CycleIssue)
    _hard_delete_with_events(Estimate)
    _hard_delete_with_events(EstimatePoint)

    # Catch-all for any remaining models with deleted_at that weren't
    # covered explicitly above.  These get a plain hard-delete without
    # outbox emission (no webhook subscribers; unknown workspace context).
    all_models = apps.get_models()
    handled = {
        Workspace, Project, Cycle, Module, Issue, Page, IssueView, Label,
        State, IssueActivity, IssueComment, IssueLink, IssueReaction,
        UserFavorite, ModuleIssue, CycleIssue, Estimate, EstimatePoint,
    }
    for model in all_models:
        if model in handled:
            continue
        if hasattr(model, "deleted_at"):
            model.all_objects.filter(deleted_at__lt=cutoff).delete()

    return
