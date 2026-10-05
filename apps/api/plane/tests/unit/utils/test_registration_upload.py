# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import pytest

from plane.utils.registration_upload import html_file_refs, html_has_file

DOC_ID = "3f2a1b0c-1d2e-4f50-8a6b-7c8d9e0f1a2b"
DOC = f'<a href="http://localhost:8000/api/assets/v2/workspaces/ws/projects/p/download/{DOC_ID}/?ext=pdf">a.pdf</a>'
IMAGE = '<image-component src="img-asset-1" width="100"></image-component>'


@pytest.mark.unit
class TestHtmlFileRefs:
    def test_finds_documents_and_images(self):
        assert html_file_refs(f"<p>{DOC}</p>{IMAGE}") == {DOC_ID, "img-asset-1"}

    @pytest.mark.parametrize("html", [None, "", "<p>plain text</p>", '<a href="https://example.com/download/x/">x</a>'])
    def test_no_files(self, html):
        assert html_has_file(html) is False

    def test_has_file(self):
        assert html_has_file(DOC) is True
        assert html_has_file(IMAGE) is True
