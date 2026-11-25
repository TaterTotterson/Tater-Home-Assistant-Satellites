"""Dashboard composition examples, installed components, and bounded edit scopes."""

from copy import deepcopy
import json
import re
from urllib.parse import urlsplit

LAYOUTS = {
    "auto": {
        "label": "Let the designer choose",
        "brief": "Choose or combine compositions to suit this home.",
    },
    "original": {
        "label": "Invent an original design",
        "brief": "Invent your own composition. Examples are structural references, not templates to copy. Pick a focal point, a clear hierarchy, varied card sizes, useful navigation and a distinctive rhythm. Explain the actual design choices. Do not default to rows of identical tiles.",
    },
    "bento": {
        "label": "Bento overview",
        "brief": "Asymmetric groups: a wide focal section, smaller supporting controls, and compact status. Vary section and card spans; preserve breathing room.",
    },
    "editorial": {
        "label": "Editorial home",
        "brief": "A magazine-like opening with an expressive header, a large feature card and a quieter supporting column. Use a deliberate reading order and concise labels.",
    },
    "rooms": {
        "label": "Room navigator",
        "brief": "A compact overview with navigation into room subviews. Put each room's useful controls together, with clear routes back. Use actual rooms only.",
    },
    "control": {
        "label": "Control center",
        "brief": "A strong status band followed by compact task groups, trends and detailed controls. Use nested grids and different card types; make priority information obvious.",
    },
    "media": {
        "label": "Media wall",
        "brief": "Lead with an actual camera or media player, give it space, and group supporting controls beside or below it. Fall back to another useful focal point when media is absent.",
    },
}

# Only these known module filenames enable new custom types. An arbitrary
# registered script is not evidence that a particular custom card is installed.
COMPONENTS = {
    "mushroom.js": {
        "id": "mushroom",
        "label": "Mushroom",
        "types": [
            "custom:mushroom-entity-card",
            "custom:mushroom-light-card",
            "custom:mushroom-climate-card",
        ],
        "guidance": 'Each needs entity. Entity card: {"type":"custom:mushroom-entity-card","entity":"<actual ID>","layout":"horizontal","icon_color":"amber"}. Light/climate cards require the corresponding domain. Use fill_container for grids.',
    },
    "bubble-card.js": {
        "id": "bubble",
        "label": "Bubble Card",
        "types": ["custom:bubble-card"],
        "guidance": "Use card_type button with entity and button_type switch, slider, state or name; card_type separator needs name; card_type media-player needs a media_player entity. Prefer documented simple configurations. Static CSS styles are allowed; no JavaScript templates or invented modules/pop-up dependencies.",
    },
    "button-card.js": {
        "id": "button",
        "label": "Button Card",
        "types": ["custom:button-card"],
        "guidance": 'Use entity, name, icon, show_state and static styles such as {"styles":{"card":[{"border-radius":"24px"}]}}. Do not invent named button_card_templates or write JavaScript templates.',
    },
    "mini-graph-card-bundle.js": {
        "id": "mini_graph",
        "label": "Mini Graph Card",
        "types": ["custom:mini-graph-card"],
        "guidance": "Needs a nonempty entities array containing actual sensor/binary_sensor IDs. Optional name, hours_to_show, line_color and show options. Use for genuine history, not invented values.",
    },
    "card-mod.js": {
        "id": "card_mod",
        "label": "card-mod",
        "types": [],
        "guidance": 'Static scoped CSS can use {"card_mod":{"style":"ha-card { border-radius: 24px; box-shadow: none; }"}}. Keep styling on the intended card; do not change global HA styles, fetch assets, or use executable templates.',
    },
}


def installed_components(resources):
    result, seen = [], set()
    for resource in resources if isinstance(resources, list) else []:
        if not isinstance(resource, dict) or resource.get("type") not in {"module", "js"}:
            continue
        url = resource.get("url")
        if not isinstance(url, str) or len(url) > 2048:
            continue
        try:
            parsed = urlsplit(url)
        except ValueError:
            continue
        if parsed.scheme not in {"", "http", "https"} or (
            not parsed.scheme and not url.startswith("/")
        ):
            continue
        spec = COMPONENTS.get(parsed.path.rsplit("/", 1)[-1])
        if not spec or spec["id"] in seen:
            continue
        seen.add(spec["id"])
        result.append({**deepcopy(spec), "resource_url": url})
    return result


def prompt_inventory(ordered, required_ids=(), limit=96, text=""):
    """Balance a compact prompt across rooms/domains without truncating drafts."""
    if len(ordered) <= limit:
        return list(ordered)
    selected, seen = [], set()

    def add(entity):
        if entity["entity_id"] not in seen and len(selected) < limit:
            seen.add(entity["entity_id"])
            selected.append(entity)

    generic = {
        "design",
        "dashboard",
        "home",
        "actual",
        "controls",
        "create",
        "creative",
        "the",
        "for",
        "and",
        "using",
        "with",
        "make",
        "please",
        "use",
        "useful",
        "different",
        "rooms",
        "devices",
        "entities",
    }
    terms = set(re.findall(r"\w{3,}", text.lower())) - generic
    for entity in ordered:
        if len(selected) >= limit // 3:
            break
        words = set(
            re.findall(r"\w{3,}", (entity.get("name", "") + " " + entity.get("area", "")).lower())
        )
        if terms & words:
            add(entity)
    for entity in ordered:
        if len(selected) >= 2 * limit // 3:
            break
        if entity["entity_id"] in required_ids:
            add(entity)
    groups = {}
    for entity in ordered:
        groups.setdefault((entity.get("area", ""), entity.get("domain", "")), []).append(entity)
    for offset in range(max(map(len, groups.values()), default=0)):
        for group in groups.values():
            if offset < len(group):
                add(group[offset])
            if len(selected) >= limit:
                return selected
    return selected


def layout_examples(inventory, layout):
    """Small working examples use real entity IDs, and may be freely adapted."""
    if layout == "original" or not inventory:
        return []
    entities = {item["domain"]: item["entity_id"] for item in reversed(inventory)}
    primary = entities.get("light", inventory[0]["entity_id"])
    supporting = entities.get("sensor", primary)
    media = entities.get("camera") or entities.get("media_player")
    tile = lambda entity: {"type": "tile", "entity": entity}
    heading = lambda title: {"type": "heading", "heading": title}
    section = lambda cards, **options: {"type": "grid", "cards": cards, **options}
    examples = {
        "bento": {
            "views": [
                {
                    "title": "Home",
                    "path": "home",
                    "type": "sections",
                    "max_columns": 3,
                    "sections": [
                        section(
                            [
                                heading("At a glance"),
                                {**tile(primary), "grid_options": {"columns": 12, "rows": 2}},
                            ],
                            column_span=2,
                        ),
                        section([heading("Useful now"), tile(supporting)]),
                    ],
                }
            ]
        },
        "editorial": {
            "views": [
                {
                    "title": "Home",
                    "path": "home",
                    "type": "sections",
                    "max_columns": 2,
                    "header": {
                        "layout": "start",
                        "card": {
                            "type": "markdown",
                            "content": "# Your home\nA few things worth seeing.",
                        },
                    },
                    "sections": [
                        section(
                            [
                                {
                                    **tile(primary),
                                    "vertical": True,
                                    "grid_options": {"columns": 12, "rows": 3},
                                }
                            ]
                        ),
                        section([heading("The essentials"), tile(supporting)]),
                    ],
                }
            ]
        },
        "rooms": {
            "views": [
                {
                    "title": "Home",
                    "path": "home",
                    "type": "sections",
                    "sections": [
                        section(
                            [
                                {
                                    "type": "button",
                                    "name": "Room controls",
                                    "icon": "mdi:home-outline",
                                    "tap_action": {"action": "navigate", "navigation_path": "room"},
                                }
                            ]
                        )
                    ],
                },
                {
                    "title": "Room",
                    "path": "room",
                    "type": "sections",
                    "subview": True,
                    "sections": [
                        section([heading("Room controls"), tile(primary), tile(supporting)])
                    ],
                },
            ]
        },
        "control": {
            "views": [
                {
                    "title": "Controls",
                    "path": "controls",
                    "type": "sections",
                    "max_columns": 2,
                    "badges": [{"type": "entity", "entity": supporting}],
                    "sections": [
                        section(
                            [
                                heading("Quick control"),
                                {
                                    "type": "grid",
                                    "columns": 2,
                                    "square": False,
                                    "cards": [tile(primary), tile(supporting)],
                                },
                            ]
                        ),
                        section(
                            [
                                {
                                    "type": "entities",
                                    "title": "Home details",
                                    "entities": [primary, supporting],
                                }
                            ]
                        ),
                    ],
                }
            ]
        },
        "media": {
            "views": [
                {
                    "title": "Media",
                    "path": "media",
                    "type": "sections",
                    "max_columns": 3,
                    "sections": [
                        section(
                            (
                                [
                                    {
                                        "type": (
                                            "picture-entity"
                                            if media and media.startswith("camera.")
                                            else "media-control"
                                        ),
                                        "entity": media,
                                    }
                                ]
                                if media
                                else [tile(primary)]
                            ),
                            column_span=2,
                        ),
                        section([heading("Around the room"), tile(primary), tile(supporting)]),
                    ],
                }
            ]
        },
    }
    keys = [layout] if layout in examples else ["bento", "editorial", "control"]
    return [{"layout": key, "example": examples[key]} for key in keys]


def scoped_config(config, focus):
    if focus is None:
        return deepcopy(config)
    if not isinstance(focus, dict) or set(focus) - {"view_index", "section_index"}:
        raise ValueError("Choose a view or section from the current draft.")
    index = focus.get("view_index")
    views = config.get("views", [])
    if (
        not isinstance(views, list)
        or type(index) is not int
        or index < 0
        or index >= len(views)
        or not isinstance(views[index], dict)
    ):
        raise ValueError("Choose a view from the current draft.")
    view = deepcopy(views[index])
    section_index = focus.get("section_index")
    if section_index is not None:
        sections = view.get("sections", [])
        if (
            not isinstance(sections, list)
            or type(section_index) is not int
            or section_index < 0
            or section_index >= len(sections)
            or view.get("type") != "sections"
        ):
            raise ValueError("Choose a section from the current draft.")
        view["sections"] = [sections[section_index]]
        for key in ("header", "footer", "badges", "sidebar"):
            view.pop(key, None)
    return {"views": [view]}


def scope_errors(config, focus):
    if focus is None or config is None:
        return []
    views = config.get("views", []) if isinstance(config, dict) else []
    if not isinstance(views, list) or len(views) != 1:
        return [
            "For this focused edit return exactly one view; the rest of the dashboard is preserved automatically."
        ]
    if focus.get("section_index") is not None and (
        not isinstance(views[0], dict)
        or not isinstance(views[0].get("sections"), list)
        or len(views[0]["sections"]) != 1
    ):
        return ["For this focused edit return exactly one section in one Sections view."]
    return []


def merge_scope(original, proposal, focus):
    if focus is None or proposal is None:
        return proposal
    scoped_config(original, focus)  # Validate before indexing.
    errors = scope_errors(proposal, focus)
    if errors:
        raise ValueError(errors[0])
    result = deepcopy(original)
    index = focus["view_index"]
    if focus.get("section_index") is None:
        result["views"][index] = deepcopy(proposal["views"][0])
    else:
        result["views"][index]["sections"][focus["section_index"]] = deepcopy(
            proposal["views"][0]["sections"][0]
        )
    return result


def composition_signature(config):
    """Ignore palette/entity changes when comparing the shape of concepts."""

    def shape(node):
        if not isinstance(node, dict):
            return None
        return (
            {
                key: deepcopy(node[key])
                for key in (
                    "type",
                    "max_columns",
                    "column_span",
                    "grid_options",
                    "vertical",
                    "subview",
                    "columns",
                )
                if key in node
            }
            | {
                key: [shape(child) for child in node[key]]
                for key in ("views", "sections", "cards")
                if isinstance(node.get(key), list)
            }
            | {key: bool(node[key]) for key in ("header", "footer", "badges") if key in node}
        )

    return json.dumps(shape(config), sort_keys=True)
