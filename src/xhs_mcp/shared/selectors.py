"""Shared CSS selectors and text constants for XHS operations.

Centralised so selector churn on XiaoHongShu's side is a one-file change.

A note on the ``:contains()`` entries below: that pseudo-class is jQuery syntax,
not CSS, so both ``querySelector`` and Playwright reject it. They never matched
anything in the TypeScript original either — they sit at the end of each list
and are only reached once every real selector has missed, where the resulting
error is caught by the calling code. They are kept verbatim so the control flow
in the miss case stays identical. Do **not** "fix" them to Playwright's
``:has-text()``: that would make them start matching elements they never
matched before, silently changing which buttons get clicked.
"""

from __future__ import annotations

COMMON_BUTTON_SELECTORS: dict[str, tuple[str, ...]] = {
    "CONFIRM": (
        ".confirm-btn",
        "button.confirm-btn",
        'button[class*="confirm"]',
        ".ok-btn",
        'button:contains("确认")',
        'button:contains("确定")',
        'button:contains("confirm")',
        'button:contains("ok")',
        '[aria-label*="确认"]',
        '[aria-label*="确定"]',
    ),
    "CANCEL": (
        'button[class*="cancel"]',
        ".cancel-btn",
        'button:contains("取消")',
        'button:contains("cancel")',
        '[aria-label*="取消"]',
    ),
    "DELETE": (
        'button[class*="delete"]',
        ".delete-btn",
        '[class*="remove"]',
        ".remove-btn",
        'button[title*="删除"]',
        'button[title*="delete"]',
        '[aria-label*="删除"]',
        '[aria-label*="delete"]',
        'button:contains("删除")',
        'button:contains("delete")',
    ),
    "MORE_OPTIONS": (
        'button[class*="more"]',
        ".more-btn",
        '[class*="menu"]',
        ".menu-btn",
        'button[class*="action"]',
        ".action-btn",
        'button[class*="option"]',
        ".option-btn",
        'button[title*="更多"]',
        'button[title*="more"]',
        '[aria-label*="更多"]',
        '[aria-label*="more"]',
        'button:contains("⋯")',
        'button:contains("...")',
        ".three-dots",
        ".ellipsis",
    ),
}

COMMON_MODAL_SELECTORS: dict[str, tuple[str, ...]] = {
    "CONFIRM": (
        '.modal button[class*="confirm"]',
        '.dialog button[class*="confirm"]',
        '[class*="modal"] button[class*="confirm"]',
        '.ant-modal button[class*="confirm"]',
        '.el-dialog button[class*="confirm"]',
    ),
    "CANCEL": (
        '.modal button[class*="cancel"]',
        '.dialog button[class*="cancel"]',
        '[class*="modal"] button[class*="cancel"]',
        '.ant-modal button[class*="cancel"]',
        '.el-dialog button[class*="cancel"]',
    ),
    "DROPDOWN_MENU": (
        ".dropdown-menu",
        ".menu-list",
        '[class*="dropdown"]',
        ".context-menu",
        ".action-menu",
        ".options-menu",
        '[role="menu"]',
        ".popover-menu",
    ),
}

COMMON_STATUS_SELECTORS: dict[str, tuple[str, ...]] = {
    "SUCCESS": (
        ".success-message",
        ".publish-success",
        '[data-testid="publish-success"]',
        ".toast-success",
        ".upload-success",
        ".video-upload-success",
        ".video-processing-complete",
        ".upload-complete",
    ),
    "ERROR": (
        ".error-message",
        ".publish-error",
        '[data-testid="publish-error"]',
        ".toast-error",
        ".error-toast",
        ".upload-error",
        ".video-upload-error",
    ),
    "PROCESSING": (
        ".video-processing",
        ".upload-progress",
        ".processing-indicator",
        '[class*="processing"]',
        '[class*="uploading"]',
        ".progress-bar",
        ".upload-status",
    ),
    "TOAST": (
        ".toast",
        ".message",
        ".notification",
        '[role="alert"]',
        ".ant-message",
        ".el-message",
    ),
}

COMMON_TEXT_PATTERNS: dict[str, tuple[str, ...]] = {
    "SUCCESS": ("成功", "success", "完成"),
    "ERROR": ("失败", "error", "错误"),
    "PROCESSING": ("处理中", "上传中", "processing", "uploading", "进度"),
}

COMMON_FILE_SELECTORS: dict[str, tuple[str, ...]] = {
    "FILE_INPUT": (
        "input[type=file]",
        ".upload-input",
        'input[accept*="video"]',
        'input[accept*="mp4"]',
        'input[class*="upload"]',
        'input[class*="file"]',
    ),
}
