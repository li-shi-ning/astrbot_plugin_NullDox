import random
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import astrbot.api.message_components as Comp
from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register
from astrbot.core.config import AstrBotConfig
from astrbot.core.star.filter import HandlerFilter
from astrbot.core.star.register.star_handler import get_handler_or_create
from astrbot.core.star.star_handler import EventType


DEFAULT_SENTENCES = [
    "你已被随机句子命中。",
    "资料检索失败，但头像看起来很有故事。",
    "今日鉴定结果：适合继续水群。",
    "系统提示：该用户暂未发现异常，建议多观察。",
]


@dataclass(slots=True)
class SentencePool:
    group_id: str
    sentences: list[str]


class DecreaseTypeFilter(HandlerFilter):
    """检查主动退群通知事件。"""

    def filter(self, event: AstrMessageEvent, cfg: AstrBotConfig) -> bool:
        raw_message = getattr(event.message_obj, "raw_message", None)
        if not isinstance(raw_message, dict):
            return False
        return (
            raw_message.get("post_type") == "notice"
            and raw_message.get("notice_type") == "group_decrease"
            and raw_message.get("sub_type") == "leave"
        )


def register_decrease_type(**kwargs):
    """注册一个用于群成员主动离开事件的自定义过滤器。"""

    def decorator(awaitable):
        handler_md = get_handler_or_create(awaitable, EventType.AdapterMessageEvent)
        handler_md.event_filters.append(DecreaseTypeFilter())
        return awaitable

    return decorator


@register(
    "NullDox",
    "lishining",
    "随机输出用户头像和句子的娱乐插件，不生成任何开盒信息。",
    "1.1.0",
)
class NullDoxPlugin(Star):
    """随机句子插件：按公共词库和群聊词库合并后抽取文案。"""

    def __init__(self, context: Context, config: Mapping[str, Any] | None = None):
        super().__init__(context)
        self.config = config if config is not None else self._load_config()
        self.global_sentences = self._load_global_sentences()
        self.group_sentence_pools = self._load_group_sentence_pools()

    def _load_config(self) -> Mapping[str, Any]:
        try:
            return self.context.get_config() or {}
        except Exception as exc:
            logger.error("[NullDox] 配置加载失败: %s", exc)
            return {}

    @filter.command("盒")
    async def use_dox(self, event: AstrMessageEvent, qq: str = ""):
        """使用 /盒 [QQ号|@用户] 输出随机句子和头像。"""

        sender_id = event.get_sender_id()
        if sender_id and not self._is_user_allowed(str(sender_id)):
            yield event.plain_result("当前账号未启用该功能")
            return

        target_id = self._resolve_target_qq(event, qq)
        if not target_id:
            yield event.plain_result("QQ号格式错误，请使用纯数字或@目标用户")
            return

        yield event.chain_result(self._build_random_sentence_chain(event, target_id))

    @filter.platform_adapter_type(filter.PlatformAdapterType.AIOCQHTTP)
    @register_decrease_type()
    async def decrease_dox(self, event: AstrMessageEvent):
        """监听群成员主动离开事件，输出随机句子和头像。"""

        group_id = event.get_group_id()
        target_id = str(event.get_sender_id())
        if group_id is None:
            return

        if not self._is_group_allowed(
            group_id, getattr(event, "unified_msg_origin", None)
        ):
            return

        yield event.chain_result(
            self._build_random_sentence_chain(event, target_id, str(group_id))
        )

    def _build_random_sentence_chain(
        self,
        event: AstrMessageEvent,
        user_id: str,
        group_id: str | None = None,
    ) -> list:
        sentence = self._pick_sentence(group_id or self._event_group_id(event))
        avatar = f"https://q4.qlogo.cn/headimg_dl?dst_uin={user_id}&spec=640"
        return [
            Comp.Plain(f"用户:{user_id}(ID:{user_id})[{sentence}]\n"),
            Comp.Image.fromURL(avatar),
        ]

    def _pick_sentence(self, group_id: str | None = None) -> str:
        sentences = self._sentences_for_group(group_id)
        if not sentences:
            sentences = DEFAULT_SENTENCES
        return random.choice(sentences)

    def _sentences_for_group(self, group_id: str | None = None) -> list[str]:
        merged = list(self.global_sentences)
        if group_id:
            pool = self.group_sentence_pools.get(str(group_id))
            if pool:
                merged.extend(pool.sentences)
        return merged

    def _load_global_sentences(self) -> list[str]:
        sentence_config = self._config_section(self.config, "sentence_library")
        return (
            self._config_list(sentence_config, "global_sentences")
            or self._config_list(self.config, "global_sentences")
            or list(DEFAULT_SENTENCES)
        )

    def _load_group_sentence_pools(self) -> dict[str, SentencePool]:
        raw_rules = self.config.get("group_sentence_rules", [])
        if not isinstance(raw_rules, list):
            return {}

        pools: dict[str, SentencePool] = {}
        for raw_rule in raw_rules:
            if not isinstance(raw_rule, Mapping):
                continue
            group_id = str(raw_rule.get("group_id", "")).strip()
            if not group_id:
                continue
            sentences = self._config_list(raw_rule, "sentences")
            if not sentences:
                continue
            pools[group_id] = SentencePool(group_id=group_id, sentences=sentences)
        return pools

    @staticmethod
    def _config_section(config: Mapping[str, Any], key: str) -> dict[str, Any]:
        value = config.get(key, {})
        return dict(value) if isinstance(value, Mapping) else {}

    @staticmethod
    def _config_list(config: Mapping[str, Any], key: str) -> list[str]:
        value = config.get(key, [])
        if not isinstance(value, list):
            return []
        return [item for raw in value if (item := str(raw).strip())]

    def _resolve_target_qq(self, event: AstrMessageEvent, qq: str = "") -> str | None:
        """解析目标：显式QQ优先，其次非bot @，再其次bot @，最后发送者。"""

        qq_candidate = str(qq or "").strip()
        if qq_candidate:
            if self._validate_qq(qq_candidate):
                logger.info("[NullDox] 目标解析：使用显式QQ参数 %s", qq_candidate)
                return qq_candidate
            logger.warning("[NullDox] 目标解析：显式QQ参数无效 %s", qq_candidate)

        mention_targets = self._extract_target_mentions(event)
        if mention_targets["non_bot"]:
            target_id = mention_targets["non_bot"][-1]
            logger.info("[NullDox] 目标解析：使用最后一个非bot @目标 %s", target_id)
            return target_id
        if mention_targets["bot"]:
            target_id = mention_targets["bot"][-1]
            logger.info("[NullDox] 目标解析：使用bot自身@目标 %s", target_id)
            return target_id

        sender_id = str(event.get_sender_id() or "").strip()
        if self._validate_qq(sender_id):
            logger.info("[NullDox] 目标解析：无显式目标，回退到发送者 %s", sender_id)
            return sender_id

        logger.warning("[NullDox] 目标解析失败：未找到有效目标")
        return None

    def _extract_target_mentions(self, event: AstrMessageEvent) -> dict[str, list[str]]:
        """提取消息中的@目标，分别记录bot自身和非bot目标。"""

        self_ids = self._get_bot_self_ids(event)
        targets: dict[str, list[str]] = {"non_bot": [], "bot": []}
        for component in event.message_obj.message:
            if not isinstance(component, Comp.At):
                continue
            mentioned_id = str(component.qq).strip()
            if not mentioned_id or mentioned_id.lower() == "all":
                logger.info("[NullDox] 目标解析：跳过@全体")
                continue
            if not self._validate_qq(mentioned_id):
                logger.warning("[NullDox] 目标解析：跳过无效@目标 %s", mentioned_id)
                continue
            if mentioned_id in self_ids:
                logger.info("[NullDox] 目标解析：记录bot自身@ %s", mentioned_id)
                targets["bot"].append(mentioned_id)
                continue
            targets["non_bot"].append(mentioned_id)
        return targets

    def _get_bot_self_ids(self, event: AstrMessageEvent) -> set[str]:
        """尽量从事件对象中取得机器人自身ID，用于识别bot @。"""

        self_ids: set[str] = set()
        raw_message = getattr(event.message_obj, "raw_message", None)
        if isinstance(raw_message, dict):
            self_id = raw_message.get("self_id")
            if self_id:
                self_ids.add(str(self_id))

        message_self_id = getattr(event.message_obj, "self_id", None)
        if message_self_id:
            self_ids.add(str(message_self_id))

        get_self_id = getattr(event, "get_self_id", None)
        if callable(get_self_id):
            try:
                self_id = get_self_id()
            except Exception as exc:
                logger.debug("[NullDox] 读取 event.get_self_id 失败: %s", exc)
            else:
                if self_id:
                    self_ids.add(str(self_id))
        return self_ids

    @staticmethod
    def _event_group_id(event: AstrMessageEvent) -> str:
        get_group_id = getattr(event, "get_group_id", None)
        if callable(get_group_id):
            group_id = get_group_id()
            return str(group_id) if group_id else ""

        raw_message = getattr(getattr(event, "message_obj", None), "raw_message", None)
        if isinstance(raw_message, dict):
            return str(raw_message.get("group_id") or "")
        return ""

    @staticmethod
    def _validate_qq(qq: str) -> bool:
        if not qq or not isinstance(qq, str):
            return False
        return qq.isdigit()

    def _is_user_allowed(self, user_id: str | None) -> bool:
        if not user_id:
            return True

        mode = str(self.config.get("user_list_mode", "none")).lower()
        if mode not in {"whitelist", "blacklist", "none"}:
            mode = "none"
        if mode == "none":
            return True

        user_list = {str(item) for item in self.config.get("user_list", [])}
        is_in_list = str(user_id) in user_list
        if mode == "whitelist":
            return is_in_list
        if mode == "blacklist":
            return not is_in_list
        return True

    def _is_group_allowed(
        self, group_id: int | str | None, unified_msg_origin: str | None = None
    ) -> bool:
        if not group_id:
            return True

        mode = str(self.config.get("group_list_mode", "none")).lower()
        if mode not in {"whitelist", "blacklist", "none"}:
            mode = "none"
        if mode == "none":
            return True

        group_list = [str(item) for item in self.config.get("group_list", [])]
        target = str(unified_msg_origin or group_id)
        target_simple_id = target.split(":")[-1] if ":" in target else target
        target_parent_id = (
            target_simple_id.split("#", 1)[0]
            if "#" in target_simple_id
            else target_simple_id
        )

        def _is_match(item: str) -> bool:
            if ":" in item:
                if item == target:
                    return True
                if ":" not in target or "#" not in target_simple_id:
                    return False

                item_prefix, item_tail = item.rsplit(":", 1)
                target_prefix, _ = target.rsplit(":", 1)
                return item_prefix == target_prefix and item_tail == target_parent_id

            if item == target_simple_id:
                return True
            return "#" in target_simple_id and item == target_parent_id

        is_in_list = any(_is_match(item) for item in group_list)
        if mode == "whitelist":
            return is_in_list
        if mode == "blacklist":
            return not is_in_list
        return True

    async def initialize(self):
        pass

    async def terminate(self):
        pass
