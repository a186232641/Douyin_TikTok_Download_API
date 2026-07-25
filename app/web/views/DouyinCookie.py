from pywebio.output import (
    close_popup,
    popup,
    put_buttons,
    put_error,
    put_markdown,
    put_scope,
    put_success,
    put_table,
    use_scope,
)
from pywebio.pin import pin, pin_update, put_textarea

from app.runtime_config import (
    clear_douyin_cookie,
    get_douyin_cookie_status,
    set_douyin_cookie,
)
from app.web.views.ViewsUtils import ViewsUtils


t = ViewsUtils().t
STATUS_SCOPE = "douyin_cookie_status"
COOKIE_PIN = "douyin_cookie_value"


def _put_cookie_status(status):
    source_labels = {
        "runtime": t("网页配置", "Web configuration"),
        "yaml": t("config.yaml 兜底", "config.yaml fallback"),
        "none": t("未配置", "Not configured"),
    }
    put_table(
        [
            [t("状态", "Status"), t("已配置", "Configured") if status["configured"] else t("未配置", "Not configured")],
            [t("当前来源", "Current source"), source_labels[status["source"]]],
            [t("字符数", "Length"), status["length"]],
            [t("脱敏预览", "Masked preview"), status["masked_preview"] or "-"],
        ]
    )


def _refresh_cookie_status(status):
    with use_scope(STATUS_SCOPE, clear=True):
        put_markdown(t("### 当前配置", "### Current configuration"))
        _put_cookie_status(status)


def _handle_cookie_action(action):
    if action == "cancel":
        close_popup()
        return

    try:
        if action == "save":
            status = set_douyin_cookie(pin[COOKIE_PIN])
            pin_update(COOKIE_PIN, value="")
            put_success(t("Cookie 已更新并立即生效。", "Cookie updated and applied immediately."))
        else:
            status = clear_douyin_cookie()
            put_success(t(
                "网页配置已清除，当前使用 config.yaml 兜底值。",
                "Web configuration cleared; config.yaml fallback is active.",
            ))
    except ValueError as exc:
        with use_scope(STATUS_SCOPE):
            put_error(str(exc))
        return

    _refresh_cookie_status(status)


def douyin_cookie_pop_window():
    with popup(t("抖音 Cookie 配置", "Douyin Cookie Configuration"), size="large"):
        put_scope(STATUS_SCOPE)
        _refresh_cookie_status(get_douyin_cookie_status())
        put_markdown(t("### 更新配置", "### Update configuration"))
        put_textarea(
            COOKIE_PIN,
            label=t("新的 Cookie", "New Cookie"),
            rows=8,
            placeholder=t("粘贴完整的抖音 Cookie", "Paste the complete Douyin Cookie"),
        )
        put_buttons(
            [
                {"label": t("保存", "Save"), "value": "save"},
                {"label": t("清除网页配置", "Clear web configuration"), "value": "clear"},
                {"label": t("取消", "Cancel"), "value": "cancel"},
            ],
            onclick=_handle_cookie_action,
        )
