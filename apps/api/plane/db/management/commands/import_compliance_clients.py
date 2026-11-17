# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Import a client/compliance matrix (e.g. "Client List- KKA") into the
Compliance engine.

Sheet layout (header row is auto-detected by the "Client Name" cell; title
rows above it and empty leading columns are ignored)::

    Client Name | VCFO | Accounts | GST | GST Annual Return | TDS | ... | MCA
    Acme Pvt Ltd|      | YES      | YES | NO                | NO  | ... | YES

* Each row's client name is matched to a project in the workspace
  (case/punctuation-insensitive). Unmatched clients are reported, or created
  as projects with ``--create-projects``.
* Each service column becomes one ComplianceTemplate (category = column
  name). Templates that already exist (same key) are reused untouched, so
  cadence/due dates edited in the UI are never overwritten.
* A "YES" cell ticks the Applicability checkbox for (project, template).
  "NO"/blank cells are left alone unless ``--sync`` is passed.

Runs as a dry run (everything executed, then rolled back) unless
``--commit`` is given.

Usage::

    python manage.py import_compliance_clients <file.xlsx|file.csv> \\
        --workspace <slug> [--sheet NAME] [--create-projects --actor EMAIL] \\
        [--sync] [--commit]
"""

import csv
import difflib
import re
from collections import OrderedDict

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.text import slugify

from plane.app.serializers import ProjectSerializer
from plane.db.models import (
    DEFAULT_STATES,
    ComplianceApplicability,
    ComplianceCategory,
    ComplianceTemplate,
    Project,
    ProjectIdentifier,
    ProjectMember,
    State,
    User,
    Workspace,
    WorkspaceMember,
)

CLIENT_HEADER = "client name"

# Defaults used only when a template for a column does not exist yet.
# key -> (cadence, due_day, due_month). Adjust before running if needed;
# everything is also editable afterwards in the Compliance UI.
TEMPLATE_DEFAULTS = {
    "vcfo": ("monthly", 10, None),
    "accounts": ("monthly", 10, None),
    "gst": ("monthly", 20, None),  # GSTR-3B
    "gst-annual-return": ("annual", 31, 12),  # GSTR-9, 31 Dec
    "tds": ("monthly", 7, None),
    "ptrc": ("monthly", 31, None),  # clamped to the last day of the month
    "pf": ("monthly", 15, None),
    "income-tax": ("annual", 31, 7),  # ITR, 31 Jul
    "statutory-audit": ("annual", 30, 9),
    "tax-audit": ("annual", 30, 9),
    "trust-audit": ("annual", 30, 9),
    "internal-audit": ("quarterly", 15, None),
    "mca": ("annual", 30, 10),  # AOC-4, 30 Oct
}

YES_VALUES = {"yes", "y", "true", "1", "✓", "✔"}
NO_VALUES = {"", "no", "n", "false", "0", "-", "na", "n/a"}

# Characters Project.FORBIDDEN_IDENTIFIER_CHARS_PATTERN rejects in names.
FORBIDDEN_NAME_CHARS = re.compile(r"[&+,:;$^}{*=?@#|'<>.()%!\-]")


def normalize(name):
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def clean(value):
    return re.sub(r"\s+", " ", str(value if value is not None else "")).strip()


def sanitize_project_name(name):
    name = name.replace("&", " and ").replace("'", "").replace("’", "")
    name = FORBIDDEN_NAME_CHARS.sub(" ", name)
    return re.sub(r"\s+", " ", name).strip()


class Command(BaseCommand):
    help = "Import a client x compliance-service matrix (xlsx/csv) into Compliance templates & applicability."

    def add_arguments(self, parser):
        parser.add_argument("file", help="Path to the .xlsx or .csv file")
        parser.add_argument("--workspace", required=True, help="Workspace slug")
        parser.add_argument("--sheet", help="Sheet name (xlsx only). Defaults to every sheet in the workbook.")
        parser.add_argument(
            "--create-projects",
            action="store_true",
            help="Create a project for every client with no matching project",
        )
        parser.add_argument("--actor", help="Email of the workspace member who will own created projects/rows")
        parser.add_argument(
            "--sync",
            action="store_true",
            help="Also untick applicability for NO/blank cells (default only adds)",
        )
        parser.add_argument("--commit", action="store_true", help="Write changes (default is a dry run)")

    # ------------------------------------------------------------------ #
    # Reading
    # ------------------------------------------------------------------ #
    def read_rows(self, path, sheet_name):
        lower = path.lower()
        if lower.endswith(".csv"):
            with open(path, newline="", encoding="utf-8-sig") as fh:
                return [("csv", list(csv.reader(fh)))]
        if lower.endswith((".xlsx", ".xlsm")):
            from openpyxl import load_workbook

            wb = load_workbook(path, read_only=True, data_only=True)
            if sheet_name:
                if sheet_name not in wb.sheetnames:
                    raise CommandError(f"Sheet '{sheet_name}' not found. Available: {wb.sheetnames}")
                sheets = [wb[sheet_name]]
            else:
                sheets = wb.worksheets
            return [(ws.title, [list(r) for r in ws.iter_rows(values_only=True)]) for ws in sheets]
        raise CommandError("Unsupported file type; use .xlsx or .csv")

    def parse_matrix(self, sheets):
        """Return (service_columns, clients) where clients is an ordered
        mapping client_name -> {column_name: bool|None}."""
        columns = OrderedDict()  # column name -> True
        clients = OrderedDict()

        for sheet_title, rows in sheets:
            header_idx = name_col = None
            for i, row in enumerate(rows):
                for j, cell in enumerate(row):
                    if clean(cell).lower() == CLIENT_HEADER:
                        header_idx, name_col = i, j
                        break
                if header_idx is not None:
                    break
            if header_idx is None:
                self.stdout.write(self.style.WARNING(f"[{sheet_title}] no 'Client Name' header found, skipped"))
                continue

            header = rows[header_idx]
            service_cols = [(j, clean(h)) for j, h in enumerate(header) if j > name_col and clean(h)]
            for _, col in service_cols:
                columns[col] = True

            for row_no, row in enumerate(rows[header_idx + 1 :], start=header_idx + 2):
                name = clean(row[name_col] if name_col < len(row) else "")
                if not name:
                    continue
                values = clients.setdefault(name, {})
                if values:
                    self.stdout.write(
                        self.style.WARNING(
                            f"[{sheet_title}] row {row_no}: duplicate client '{name}', merging (YES wins)"
                        )
                    )
                for j, col in service_cols:
                    raw = clean(row[j] if j < len(row) else "").lower()
                    if raw in YES_VALUES:
                        values[col] = True
                    elif raw in NO_VALUES:
                        values.setdefault(col, False)
                    else:
                        self.stdout.write(
                            self.style.WARNING(
                                f"[{sheet_title}] row {row_no} '{name}' / {col}: "
                                f"unrecognised value '{raw}', treated as NO"
                            )
                        )
                        values.setdefault(col, False)

        return list(columns), clients

    # ------------------------------------------------------------------ #
    # Writing
    # ------------------------------------------------------------------ #
    def get_or_create_template(self, workspace, column, actor, stats):
        key = slugify(column)
        template = ComplianceTemplate.objects.filter(workspace=workspace, key__iexact=key).first()
        if template:
            return template

        if key not in TEMPLATE_DEFAULTS:
            self.stdout.write(
                self.style.WARNING(f"Column '{column}' has no template and no defaults in TEMPLATE_DEFAULTS, skipped")
            )
            return None

        cadence, due_day, due_month = TEMPLATE_DEFAULTS[key]
        category = ComplianceCategory.objects.filter(workspace=workspace, name__iexact=column).first()
        if not category:
            category = ComplianceCategory.objects.create(workspace=workspace, name=column, created_by=actor)
        template = ComplianceTemplate.objects.create(
            workspace=workspace,
            key=key,
            title=column,
            category=category,
            cadence=cadence,
            due_day=due_day,
            due_month=due_month,
            created_by=actor,
        )
        stats["templates_created"].append(
            f"{column} ({cadence}, day {due_day}{f', month {due_month}' if due_month else ''})"
        )
        return template

    def unique_identifier(self, workspace, name, used):
        words = re.findall(r"[A-Za-z0-9]+", name)
        base = "".join(w[0] for w in words[:5]) if len(words) > 1 else (words[0][:5] if words else "PRJ")
        base = base.upper()[:10] or "PRJ"
        candidate, n = base, 1
        while (
            candidate in used
            or Project.objects.filter(workspace=workspace, identifier=candidate).exists()
            or ProjectIdentifier.objects.filter(workspace=workspace, name=candidate).exists()
        ):
            n += 1
            candidate = f"{base}{n}"[:12]
        used.add(candidate)
        return candidate

    def create_project(self, workspace, client_name, actor, used_identifiers):
        name = sanitize_project_name(client_name)
        identifier = self.unique_identifier(workspace, name, used_identifiers)
        serializer = ProjectSerializer(
            data={"name": name, "identifier": identifier}, context={"workspace_id": workspace.id}
        )
        if not serializer.is_valid():
            raise CommandError(f"Cannot create project for '{client_name}' ({name}/{identifier}): {serializer.errors}")
        project = serializer.save(created_by=actor)
        ProjectMember.objects.create(project=project, member=actor, role=20, created_by=actor)
        State.objects.bulk_create(
            [
                State(
                    name=state["name"],
                    color=state["color"],
                    project=project,
                    sequence=state["sequence"],
                    workspace=workspace,
                    group=state["group"],
                    default=state.get("default", False),
                    created_by=actor,
                )
                for state in DEFAULT_STATES
            ]
        )
        return project

    def handle(self, *args, **opts):
        workspace = Workspace.objects.filter(slug=opts["workspace"]).first()
        if not workspace:
            raise CommandError(f"Workspace '{opts['workspace']}' not found")

        actor = None
        if opts["actor"]:
            actor = User.objects.filter(email__iexact=opts["actor"]).first()
            if (
                not actor
                or not WorkspaceMember.objects.filter(workspace=workspace, member=actor, is_active=True).exists()
            ):
                raise CommandError(f"'{opts['actor']}' is not an active member of workspace '{workspace.slug}'")
        if opts["create_projects"] and not actor:
            raise CommandError("--create-projects requires --actor <email> (the project admin)")

        columns, clients = self.parse_matrix(self.read_rows(opts["file"], opts["sheet"]))
        if not clients:
            raise CommandError("No client rows found")
        self.stdout.write(f"Parsed {len(clients)} clients x {len(columns)} services: {', '.join(columns)}")

        projects = list(Project.objects.filter(workspace=workspace, archived_at__isnull=True))
        by_norm = {}
        for p in projects:
            by_norm.setdefault(normalize(p.name), p)
        norm_names = list(by_norm)

        stats = {
            "templates_created": [],
            "projects_created": [],
            "unmatched": [],
            "ticked": 0,
            "already": 0,
            "unticked": 0,
        }

        with transaction.atomic():
            templates = {}
            for col in columns:
                template = self.get_or_create_template(workspace, col, actor, stats)
                if template:
                    templates[col] = template

            used_identifiers = set()
            for client, values in clients.items():
                project = by_norm.get(normalize(client)) or by_norm.get(normalize(sanitize_project_name(client)))
                if not project and opts["create_projects"]:
                    project = self.create_project(workspace, client, actor, used_identifiers)
                    by_norm[normalize(project.name)] = project
                    stats["projects_created"].append(f"{client} -> {project.name} [{project.identifier}]")
                if not project:
                    hint = difflib.get_close_matches(normalize(client), norm_names, n=1, cutoff=0.75)
                    suggestion = f" (closest project: '{by_norm[hint[0]].name}')" if hint else ""
                    stats["unmatched"].append(f"{client}{suggestion}")
                    continue

                for col, template in templates.items():
                    wanted = values.get(col, False)
                    existing = ComplianceApplicability.objects.filter(project=project, template=template)
                    if wanted:
                        if existing.exists():
                            stats["already"] += 1
                        else:
                            ComplianceApplicability.objects.create(
                                project=project,
                                template=template,
                                workspace=workspace,
                                created_by=actor,
                            )
                            stats["ticked"] += 1
                    elif opts["sync"] and existing.exists():
                        existing.delete()
                        stats["unticked"] += 1

            if not opts["commit"]:
                transaction.set_rollback(True)

        self.report(stats, opts)

    def report(self, stats, opts):
        out = self.stdout
        out.write("")
        for line in stats["templates_created"]:
            out.write(self.style.SUCCESS(f"  + template  {line}"))
        for line in stats["projects_created"]:
            out.write(self.style.SUCCESS(f"  + project   {line}"))
        for line in stats["unmatched"]:
            out.write(self.style.WARNING(f"  ? no project for client: {line}"))
        out.write("")
        out.write(
            f"Templates created: {len(stats['templates_created'])} | "
            f"Projects created: {len(stats['projects_created'])} | "
            f"Unmatched clients: {len(stats['unmatched'])}"
        )
        out.write(
            f"Checkboxes ticked: {stats['ticked']} | already ticked: {stats['already']}"
            + (f" | unticked: {stats['unticked']}" if opts["sync"] else "")
        )
        if opts["commit"]:
            out.write(self.style.SUCCESS("Committed."))
        else:
            out.write(self.style.NOTICE("DRY RUN - nothing was saved. Re-run with --commit to apply."))
