# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import pytest

from plane.app.views.asset.v2 import get_comment_attachment_type


@pytest.mark.unit
class TestGetCommentAttachmentType:
    @pytest.mark.parametrize(
        "name,detected_type,expected",
        [
            ("report.pdf", "application/pdf", "application/pdf"),
            (
                "spec.docx",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ),
            (
                "sheet.XLSX",
                "application/zip",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ),
            ("legacy.doc", "application/x-cfb", "application/msword"),
            ("notes.txt", "", "text/plain"),
            ("data.csv", "", "text/csv"),
        ],
    )
    def test_allowed_documents(self, name, detected_type, expected):
        assert get_comment_attachment_type(name, detected_type) == expected

    @pytest.mark.parametrize(
        "name,detected_type",
        [
            ("archive.zip", "application/zip"),
            ("script.html", "text/html"),
            ("noextension", ""),
            ("fake.pdf", "application/x-msdownload"),
            ("image.svg", "image/svg+xml"),
        ],
    )
    def test_rejected_files(self, name, detected_type):
        assert get_comment_attachment_type(name, detected_type) is None
