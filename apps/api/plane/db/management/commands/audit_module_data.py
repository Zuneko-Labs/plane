# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""
B4 — read-only audit of existing project data before B2 (module required)
and B3 (name format) are enforced. The client fixes the data; this command
only reports it.

Usage:
    python manage.py audit_module_data --workspace-slug <slug> --output-dir ./b4-report

Reports four things, one CSV per check when --output-dir is given:
  1. work_items_no_module          -- would 400 the instant B2 ships
  2. work_items_multi_module       -- would 400 the instant B2 ships
  3. near_duplicate_module_names   -- same builder split across two module
                                       spellings, silently fragmenting their
                                       Hourbeat hours (typo/case/whitespace)
  4. naming_rule_violations        -- names that won't pass B3's pattern,
                                       once a WorkItemNamingRule exists for
                                       the project/module (empty otherwise —
                                       this check is a no-op until B3's
                                       pattern is confirmed and rules exist)
"""

import csv
import difflib
import os
from collections import defaultdict

from django.core.management.base import BaseCommand
from django.db.models import Count, Q

from plane.db.models import Issue, Module, Project, WorkItemNamingRule
from plane.utils.naming_rules import validate_work_item_name


class Command(BaseCommand):
    help = "B4: read-only audit of module/naming data quality across projects, before B2/B3 are enforced."

    def add_arguments(self, parser):
        parser.add_argument(
            "--workspace-slug",
            type=str,
            default=None,
            help="Limit the audit to one workspace. Omit to audit every workspace in the database.",
        )
        parser.add_argument(
            "--output-dir",
            type=str,
            default=None,
            help="Write one CSV per check into this directory (created if missing). Always prints a summary to stdout regardless.",
        )
        parser.add_argument(
            "--similarity-threshold",
            type=float,
            default=0.82,
            help="0-1 similarity score (difflib ratio) above which two module names in the SAME project are "
            "flagged as a likely typo. Exact matches after trimming whitespace and casefolding are always "
            "flagged regardless of this threshold. Default 0.82 -- lower it to catch more, at the cost of "
            "more false positives between genuinely different short names.",
        )

    def handle(self, *args, **options):
        slug = options["workspace_slug"]
        output_dir = options["output_dir"]
        threshold = options["similarity_threshold"]

        projects = Project.objects.all()
        if slug:
            projects = projects.filter(workspace__slug=slug)
        project_count = projects.count()
        if project_count == 0:
            self.stdout.write(self.style.WARNING("No projects matched -- check --workspace-slug."))
            return

        moduleless = self._find_moduleless(projects)
        multi_module = self._find_multi_module(projects)
        near_dupes = self._find_near_duplicate_modules(projects, threshold)
        naming_violations = self._find_naming_violations(projects)

        self._report(
            "work_items_no_module", moduleless, ["project", "identifier", "work_item", "sequence_id"], output_dir
        )
        self._report(
            "work_items_multi_module",
            multi_module,
            ["project", "identifier", "work_item", "sequence_id", "module_count", "modules"],
            output_dir,
        )
        self._report(
            "near_duplicate_module_names",
            near_dupes,
            ["project", "module_a", "module_b", "similarity"],
            output_dir,
        )
        self._report(
            "naming_rule_violations",
            naming_violations,
            ["project", "identifier", "work_item", "sequence_id", "module", "rule_pattern", "rule_example"],
            output_dir,
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"\n{project_count} project(s) audited. "
                f"{len(moduleless)} moduleless, {len(multi_module)} multi-module, "
                f"{len(near_dupes)} near-duplicate module name pair(s), "
                f"{len(naming_violations)} naming-rule violation(s)."
            )
        )
        if not WorkItemNamingRule.objects.filter(project__in=projects).exists():
            self.stdout.write(
                self.style.WARNING(
                    "No WorkItemNamingRule rows exist for any audited project -- the naming_rule_violations "
                    "check above ran against zero configured rules and will always be empty until B3's "
                    "pattern is confirmed and rules are created via the naming-rules endpoint."
                )
            )

    def _find_moduleless(self, projects):
        rows = []
        issues = (
            Issue.issue_objects.filter(project__in=projects)
            .annotate(
                module_count=Count(
                    "issue_module", filter=Q(issue_module__deleted_at__isnull=True), distinct=True
                )
            )
            .filter(module_count=0)
            .select_related("project")
            .order_by("project__name", "sequence_id")
        )
        for issue in issues:
            rows.append(
                {
                    "project": issue.project.name,
                    "identifier": f"{issue.project.identifier}-{issue.sequence_id}",
                    "work_item": issue.name,
                    "sequence_id": issue.sequence_id,
                }
            )
        return rows

    def _find_multi_module(self, projects):
        rows = []
        issues = (
            Issue.issue_objects.filter(project__in=projects)
            .annotate(
                module_count=Count(
                    "issue_module", filter=Q(issue_module__deleted_at__isnull=True), distinct=True
                )
            )
            .filter(module_count__gt=1)
            .select_related("project")
            .prefetch_related("issue_module__module")
            .order_by("project__name", "sequence_id")
        )
        for issue in issues:
            modules = [im.module.name for im in issue.issue_module.all() if im.deleted_at is None and im.module_id]
            rows.append(
                {
                    "project": issue.project.name,
                    "identifier": f"{issue.project.identifier}-{issue.sequence_id}",
                    "work_item": issue.name,
                    "sequence_id": issue.sequence_id,
                    "module_count": len(modules),
                    "modules": "; ".join(modules),
                }
            )
        return rows

    def _find_near_duplicate_modules(self, projects, threshold):
        """Two spellings of the same builder's module silently split their
        Hourbeat hours in two -- flag exact case/whitespace-only duplicates
        always, and fuzzy near-matches above `threshold`."""
        rows = []
        by_project = defaultdict(list)
        for module in Module.objects.filter(project__in=projects, deleted_at__isnull=True).select_related("project"):
            by_project[module.project].append(module)

        for project, modules in by_project.items():
            for i, a in enumerate(modules):
                for b in modules[i + 1 :]:
                    norm_a, norm_b = a.name.strip().casefold(), b.name.strip().casefold()
                    if norm_a == norm_b:
                        similarity_label = "exact (case/whitespace only)"
                    else:
                        ratio = difflib.SequenceMatcher(None, norm_a, norm_b).ratio()
                        if ratio < threshold:
                            continue
                        similarity_label = f"{ratio:.2f}"
                    rows.append(
                        {
                            "project": project.name,
                            "module_a": a.name,
                            "module_b": b.name,
                            "similarity": similarity_label,
                        }
                    )
        return rows

    def _find_naming_violations(self, projects):
        """Empty until B3's pattern is confirmed and WorkItemNamingRule rows
        exist -- validate_work_item_name returns None with no rule configured,
        which is correct (nothing to violate yet), not a false negative."""
        rows = []
        issues = (
            Issue.issue_objects.filter(project__in=projects)
            .select_related("project")
            .prefetch_related("issue_module__module")
            .order_by("project__name", "sequence_id")
        )
        for issue in issues:
            module_links = [im for im in issue.issue_module.all() if im.deleted_at is None and im.module_id]
            if not module_links:
                continue  # already reported by work_items_no_module

            # A multi-module item has no single module to resolve a rule
            # against -- check it against the project's default rule only.
            module_id = module_links[0].module_id if len(module_links) == 1 else None

            error = validate_work_item_name(issue.project_id, module_id, issue.name)
            if not error:
                continue

            rule = None
            if module_id:
                rule = WorkItemNamingRule.objects.filter(
                    project_id=issue.project_id, module_id=module_id, is_active=True
                ).first()
            if rule is None:
                rule = WorkItemNamingRule.objects.filter(
                    project_id=issue.project_id, module_id__isnull=True, is_active=True
                ).first()

            rows.append(
                {
                    "project": issue.project.name,
                    "identifier": f"{issue.project.identifier}-{issue.sequence_id}",
                    "work_item": issue.name,
                    "sequence_id": issue.sequence_id,
                    "module": module_links[0].module.name if len(module_links) == 1 else "(multiple)",
                    "rule_pattern": rule.regex_pattern if rule else "",
                    "rule_example": rule.example if rule else "",
                }
            )
        return rows

    def _report(self, name, rows, fieldnames, output_dir):
        self.stdout.write(self.style.MIGRATE_HEADING(f"\n=== {name} ({len(rows)}) ==="))
        for row in rows[:20]:
            self.stdout.write(str(row))
        if len(rows) > 20:
            self.stdout.write(f"... and {len(rows) - 20} more (see CSV)" if output_dir else f"... and {len(rows) - 20} more")

        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
            path = os.path.join(output_dir, f"{name}.csv")
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)
            self.stdout.write(self.style.SUCCESS(f"Wrote {path} ({len(rows)} rows)"))
