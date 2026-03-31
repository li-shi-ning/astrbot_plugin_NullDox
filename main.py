import json
import random
from pathlib import Path

import astrbot.api.message_components as Comp
from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register
from astrbot.core.config import AstrBotConfig
from astrbot.core.star.filter import HandlerFilter
from astrbot.core.star.register.star_handler import get_handler_or_create
from astrbot.core.star.star_handler import EventType


class DecreaseTypeFilter(HandlerFilter):
    """Check active leave-group notice events."""

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
    """Register a custom filter for leave-group events."""

    def decorator(awaitable):
        handler_md = get_handler_or_create(awaitable, EventType.AdapterMessageEvent)
        handler_md.event_filters.append(DecreaseTypeFilter())
        return awaitable

    return decorator


@register(
    "NullDox",
    "lishining",
    "Generate fake user information for fun.",
    "1.0.0",
)
class NullDoxPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig | None = None):
        super().__init__(context)
        self.config = config or {}
        self.location_data: dict = {}
        self.location_pool: list[str] = []
        self._load_location_data()

    @filter.command("\u76d2")
    async def use_dox(self, event: AstrMessageEvent, qq: str):
        """Use /盒 [qq] to generate fake dox information."""
        group_id = event.get_group_id()
        if group_id and not self._is_group_allowed(
            group_id, getattr(event, "unified_msg_origin", None)
        ):
            yield event.plain_result(
                "\u5f53\u524d\u7fa4\u672a\u542f\u7528\u8be5\u529f\u80fd"
            )
            return

        target_id = None
        for component in event.message_obj.message:
            if isinstance(component, Comp.At):
                target_id = str(component.qq)
                break

        if target_id is None:
            qq = str(qq)
            if not self._validate_qq(qq):
                yield event.plain_result(
                    "QQ\u53f7\u683c\u5f0f\u9519\u8bef\uff0c\u8bf7\u4f7f\u7528\u7eaf\u6570\u5b57"
                )
                return
        else:
            qq = target_id

        yield event.plain_result(f"\u5f00\u59cb\u5bf9 {qq} \u8fdb\u884c\u5f00\u76d2")
        output_text = self.generate_fake_dox(qq)
        avatar = f"https://q4.qlogo.cn/headimg_dl?dst_uin={qq}&spec=640"
        chain = [
            Comp.Plain(output_text),
            Comp.Image.fromURL(avatar),
        ]
        yield event.chain_result(chain)

    @filter.platform_adapter_type(filter.PlatformAdapterType.AIOCQHTTP)
    @register_decrease_type()
    async def decrease_dox(self, event: AstrMessageEvent):
        """Listen for leave-group events and generate fake dox output."""
        group_id = event.get_group_id()
        sender_id = str(event.get_sender_id())
        if group_id is None:
            return
        if not self._is_group_allowed(
            group_id, getattr(event, "unified_msg_origin", None)
        ):
            return

        yield event.plain_result(
            f"\u68c0\u6d4b\u5230 {sender_id} \u9000\u51fa\u7fa4\u804a\uff0c\u6b63\u5728\u8fdb\u884c\u5f00\u76d2"
        )
        output_text = self.generate_fake_dox(sender_id, str(group_id))
        avatar = f"https://q4.qlogo.cn/headimg_dl?dst_uin={sender_id}&spec=640"
        chain = [
            Comp.Plain(output_text),
            Comp.Image.fromURL(avatar),
        ]
        yield event.chain_result(chain)

    def generate_fake_dox(self, sender_id: str, group_id: str | None = None) -> str:
        """Generate fake dox information."""
        output = "\u8eab\u4efd\u68c0\u7d22\u5b8c\u6bd5\n"
        output += f"\u8d26\u53f7\uff1a{sender_id}\n"

        if group_id:
            output += f"\u9000\u51fa\u7fa4\u804a\uff1a{group_id}\n"

        output += f"\u624b\u673a\uff1a{self._generate_phone()}\n"
        output += f"IP\u5730\u5740\uff1a{self._generate_ip()}\n"
        output += f"\u7269\u7406\u5730\u5740\uff1a{self._generate_location()}"
        return output.strip()

    def _load_location_data(self) -> None:
        """Load location JSON and flatten it for random selection."""
        data_path = Path(__file__).resolve().parent / "china_clean_v2.json"
        try:
            if not data_path.exists():
                logger.warning(f"[NullDox] Location file not found: {data_path}")
                return

            with data_path.open("r", encoding="utf-8") as file:
                self.location_data = json.load(file)

            if not isinstance(self.location_data, dict):
                logger.warning("[NullDox] Invalid location data format, expected dict")
                self.location_data = {}
                return

            self.location_pool = self._flatten_locations(self.location_data)
            logger.info(
                f"[NullDox] Loaded {len(self.location_pool)} locations into memory"
            )
        except json.JSONDecodeError as exc:
            logger.error(f"[NullDox] Failed to parse location JSON: {exc}")
            self.location_data = {}
            self.location_pool = []
        except Exception as exc:
            logger.error(f"[NullDox] Failed to load location data: {exc}")
            self.location_data = {}
            self.location_pool = []

    def _flatten_locations(self, data: dict) -> list[str]:
        """Flatten nested location JSON into readable addresses."""
        locations: list[str] = []
        for provinces in data.values():
            if not isinstance(provinces, dict):
                continue

            for province_name, cities in provinces.items():
                if not isinstance(cities, dict):
                    locations.append(str(province_name))
                    continue

                for city_name, districts in cities.items():
                    if not isinstance(districts, dict) or not districts:
                        locations.append(f"{province_name}{city_name}")
                        continue

                    for district_name, streets in districts.items():
                        if not isinstance(streets, dict) or not streets:
                            locations.append(
                                f"{province_name}{city_name}{district_name}"
                            )
                            continue

                        for street_name in streets.keys():
                            locations.append(
                                f"{province_name}{city_name}{district_name}{street_name}"
                            )

        return locations

    def _validate_qq(self, qq: str) -> bool:
        """Validate QQ number format."""
        if not qq or not isinstance(qq, str):
            return False
        if not qq.isdigit():
            logger.warning(f"Detected invalid QQ format: {qq}")
            return False
        return True

    def _is_group_allowed(
        self, group_id: int | str | None, unified_msg_origin: str | None = None
    ) -> bool:
        """Check whether the group is allowed by group filter settings."""
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

    def _generate_phone(self) -> str:
        """Generate a fake phone number."""
        prefixes = [
            "130",
            "131",
            "132",
            "133",
            "135",
            "136",
            "137",
            "138",
            "139",
            "150",
            "151",
            "152",
            "155",
            "156",
            "157",
            "158",
            "159",
            "166",
            "177",
            "180",
            "181",
            "182",
            "183",
            "184",
            "185",
            "186",
            "187",
            "188",
            "189",
            "198",
            "199",
        ]
        prefix = random.choice(prefixes)
        suffix = "".join(str(random.randint(0, 9)) for _ in range(8))
        return f"{prefix}{suffix}"

    def _generate_ip(self) -> str:
        """Generate a fake IP address."""
        first = random.choice(
            [
                58,
                61,
                110,
                112,
                113,
                114,
                115,
                116,
                117,
                118,
                119,
                120,
                121,
                122,
                123,
                124,
                125,
                126,
                127,
                172,
                192,
            ]
        )
        second = random.randint(1, 255)
        third = random.randint(0, 255)
        fourth = random.randint(1, 254)
        return f"{first}.{second}.{third}.{fourth}"

    def _generate_location(self) -> str:
        """Generate a random fake location."""
        if self.location_pool:
            return random.choice(self.location_pool)
        return "\u56db\u5ddd\u7701\u6210\u90fd\u5e02\u91d1\u725b\u533a"

    async def initialize(self):
        """Optional async plugin initialization hook."""
        pass

    async def terminate(self):
        """Optional async plugin cleanup hook."""
        pass
