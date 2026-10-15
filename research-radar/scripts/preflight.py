"""Local readiness checks before discovery; never authenticate or expose secrets."""
from __future__ import annotations

import copy
from datetime import datetime, timezone

import fulltext_access as access
import institution_credentials as institution
import venue_table
from credentials import CredentialError, resolve_key


def check(profile, max_pages=None):
    checks, fallbacks = [], {}

    def add(name, state, message, action="", decision=False):
        checks.append({"id": name, "state": state, "message": message,
                       "action": action, "requires_user_choice": decision})

    add("research_request", "ok", "研究问题、检索式、日期与筛选条件已通过配置校验。")
    for service, needed in (("easyscholar", profile["easyscholar"]["enabled"]),
                            ("openalex", "openalex" in profile["sources"])):
        if not needed:
            add(service, "disabled", "该服务未在本次任务中启用。")
            continue
        try:
            value = resolve_key(profile[service], service)
            placeholder = bool(value and value.casefold() in {"[redacted]", "your_own_key", "your_own_optional_key", "your_api_key"})
            present = bool(value) and not placeholder
            state = "configured_not_verified" if present else "placeholder" if placeholder else "missing"
            value = None
        except (CredentialError, OSError):
            present, state = False, "invalid_local_source"
        if present:
            add(service, state, "已找到凭据；本地检查不验证远端有效性、额度或数据集权限。")
        else:
            effect = "期刊评级将保持待核验" if service == "easyscholar" else "OpenAlex 多页检索受限，可能遗漏论文"
            add(service, state, effect + "。", "在配置文档引用自己的 key，或明确接受此缺口继续。", True)
            fallbacks[service] = "disable_enrichment" if service == "easyscholar" else "keyless_first_page_only"

    invalid_tables = []
    for number, path in enumerate(profile.get("venue_metrics_files") or [], 1):
        try:
            venue_table.load_venue_tables([path])
            add("venue_table_" + str(number), "ok", "本地期刊表可读取；具体指标身份、年份和版次在匹配时核验。")
        except (OSError, ValueError, KeyError, TypeError):
            invalid_tables.append(path)
            add("venue_table_" + str(number), "invalid_local_source", "本地期刊表不可读取或格式无效。",
                "修正文件，或明确接受本次跳过该表；保留原评级筛选要求。", True)
    if invalid_tables:
        fallbacks["venue_metrics_files"] = invalid_tables
    gates = profile["filters"]["include_only"]
    venue_requested = any(gates.get(k) is not None for k in ("min_jif", "jcr_quartiles", "wos_indexes", "cas_partitions", "ccf_ranks"))
    if venue_requested and not profile["easyscholar"]["enabled"] and not profile.get("venue_metrics_files"):
        add("venue_gate_provider", "missing", "已要求期刊评级筛选，但未配置评级来源。",
            "配置 EasyScholar 或期刊表，或接受相关门槛继续保持待核验。", True)

    cfg = profile["fulltext_access"]
    if cfg["unpaywall"]["enabled"]:
        if access.contact(cfg):
            add("unpaywall_contact", "configured_not_verified", "已配置有效格式的 OA 联系邮箱；不会显示其值。")
        else:
            add("unpaywall_contact", "missing", "Unpaywall 已启用但缺少有效联系邮箱。",
                "配置自己的联系邮箱，或接受本次跳过此 OA 补查。", True)
            fallbacks["unpaywall"] = "disabled_for_this_run"
    if not cfg["institution"]["enabled"]:
        add("institution", "disabled", "机构访问未启用；使用公开全文线索或用户文件。")
    else:
        try:
            route = access.institution_route(cfg)
            add("institution_routing", "ok", "学校入口、SSO 来源和凭据引用已通过本地检查；未登录。")
            pair = None
            if route.get("credential_login_mode") == "user_authorized_ephemeral":
                try:
                    pair = institution.resolve(route.get("credential_source"), route["profile"])
                    state = "configured_not_verified" if pair else "missing"
                except institution.CredentialError:
                    state = "invalid_local_source"
                finally:
                    if pair:
                        pair.clear()
                if state == "configured_not_verified":
                    add("institution_account", state, "学校邮箱/账号与密码已成对配置；会话和逐篇订阅权限未验证。")
                else:
                    add("institution_account", state, "机构凭据缺失或本地来源无效。",
                        "用隐藏输入补全邮箱/账号和密码，或接受交互登录及 OA 路线。", True)
                    fallbacks["institution"] = "interactive_login_or_oa"
            else:
                add("institution_account", "browser_session_required", "使用现有浏览器会话或交互登录；本地文件不证明订阅权限。")
        except (access.AccessError, OSError, ValueError):
            add("institution_routing", "invalid_local_source", "机构入口配置不可用。",
                "修正学校入口，或明确接受本次仅使用其他合法全文路线。", True)
            fallbacks["institution"] = "disabled_for_this_run"
    add("host_tools", "host_check_required", "宿主需确认 HTTPS 检索、全文阅读、图片查看及文件保存能力；Python 无法替宿主验证。")
    if max_pages is not None:
        add("page_budget", "limited", "设置了每查询页数上限，结果可能截断，不能报告为全面检索。")
    gaps = [item["id"] for item in checks if item["requires_user_choice"]]
    return {"schema_version": 1, "checked_at": datetime.now(timezone.utc).isoformat(),
            "status": "needs_user_choice" if gaps else "ready_for_discovery",
            "network_used": False, "credential_values_returned": False,
            "gaps": gaps, "checks": checks, "fallbacks": fallbacks,
            "decision": "pending" if gaps else "not_needed",
            "requested": {"easyscholar_enabled": profile["easyscholar"]["enabled"],
                          "institution_enabled": cfg["institution"]["enabled"]},
            "next_action": "offer_complete_configuration_or_continue_with_disclosed_gaps" if gaps else "start_search"}


def effective_profile(profile, report):
    """Apply only the disclosed temporary fallbacks; never change user's file/gates."""
    result = copy.deepcopy(profile)
    fallbacks = report["fallbacks"]
    if "easyscholar" in fallbacks:
        result["easyscholar"].update(enabled=False, credentials_file=None, secret_key=None)
    if "openalex" in fallbacks:
        result["openalex"].update(credentials_file=None, api_key=None)
    bad_tables = fallbacks.get("venue_metrics_files", [])
    result["venue_metrics_files"] = [p for p in result["venue_metrics_files"] if p not in bad_tables]
    if "unpaywall" in fallbacks:
        result["fulltext_access"]["unpaywall"]["enabled"] = False
    if fallbacks.get("institution") == "disabled_for_this_run":
        result["fulltext_access"]["institution"]["enabled"] = False
    return result
