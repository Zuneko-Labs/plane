/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

export const MAX_FILE_SIZE = 5 * 1024 * 1024; // 5MB

export const ACCEPTED_AVATAR_IMAGE_MIME_TYPES_FOR_REACT_DROPZONE = {
  "image/jpeg": [],
  "image/jpg": [],
  "image/png": [],
  "image/webp": [],
};
export const ACCEPTED_COVER_IMAGE_MIME_TYPES_FOR_REACT_DROPZONE = {
  "image/jpeg": [],
  "image/jpg": [],
  "image/png": [],
  "image/webp": [],
};

/**
 * Document extensions that can be attached inside comments (images are handled by the image extension).
 * Keep in sync with COMMENT_ATTACHMENT_EXTENSION_MIME_TYPES in the API settings.
 */
export const ACCEPTED_COMMENT_ATTACHMENT_EXTENSIONS = [
  "pdf",
  "doc",
  "docx",
  "xls",
  "xlsx",
  "ppt",
  "pptx",
  "odt",
  "ods",
  "odp",
  "rtf",
  "txt",
  "csv",
];

/**
 * Dangerous file extensions that should be blocked
 */
export const DANGEROUS_EXTENSIONS = [
  "exe",
  "bat",
  "cmd",
  "sh",
  "php",
  "asp",
  "aspx",
  "jsp",
  "cgi",
  "dll",
  "vbs",
  "jar",
  "ps1",
];
