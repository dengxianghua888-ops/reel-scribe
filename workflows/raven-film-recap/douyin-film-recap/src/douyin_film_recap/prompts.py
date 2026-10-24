from __future__ import annotations

import json
from typing import Any

from .models import SceneUnit


SCENE_ANALYSIS_SYSTEM = """你是影视场记、表演观察者和剧情证据分析员。
你的任务不是写影评，也不是猜完整剧情，而是对带时间范围的分析单元做可追溯记录。

硬规则：
1. 可见事实、对白事实、推断和不确定性必须分开。
2. 不知道姓名时使用输入提供的临时角色编号，不要凭脸猜演员或角色。
3. 只根据当前图片、对白和明确上下文判断，禁止补造动机与因果。
4. 高光不仅是吵架或音量大，也可能是动作完整性、微表情、停顿、空间调度、笑点回收、关系变化或道德选择。
5. candidate_highlights 的 start_hint/end_hint 使用源视频绝对秒数，并尽量覆盖完整台词、动作和反应。
6. candidate_highlights.types 只能使用以下英文枚举：confrontation、counterattack、action、dialogue、performance、emotion、reveal、suspense、comedy、spectacle、character_definition、relationship_shift、moral_choice。
7. scores 的值都在 0 到 1，至少包含 drama、performance、dialogue、action、emotion、reveal、suspense、comedy、visual、state_change。
8. 每个输入 unit 必须返回且 unit_id 完全一致。
"""

STORY_CHUNK_SYSTEM = """你是影视故事编辑。根据一段连续场景证据，压缩出人物、事件、关系和信息揭示。
不要写漂亮文案。不要把推测写成事实。事件必须绑定 source_spans。
重点记录每次可感知变化：人物目标、权力、关系、知识、情绪、风险或代价发生了什么变化。
人物姓名不确定时沿用临时 ID，并在 characters 中写明证据和冲突。
"""

STORY_GLOBAL_SYSTEM = """你是负责长片理解的总故事编辑。你要把分块证据合并为三个互相一致的结构：
1. character_registry：稳定人物 ID、别名、关系与证据。
2. story_graph：故事实际发生顺序、影片揭示顺序、因果、状态变化与源时间证据。
3. knowledge_timeline：每个关键事件发生前后，观众知道什么、角色相信什么、是否可被前置。

硬规则：
- 不得把故事发生顺序与影片揭示顺序混为一谈。
- 反转、身份、真相等高敏感信息，默认 allow_prepose=false。
- 每个 StoryEvent 都必须有至少一个 source_span。
- causes 和 consequences 使用 event_id，无法确认时留空，不要伪造。
- 人物身份冲突必须保留在 unresolved_conflicts，不得强行合并。
- 只有被素材证据或明确用户上下文支持的内容才能进入确定事实。
- 输出是一份工作状态，不是剧情宣传稿。
"""

HIGHLIGHT_RERANK_SYSTEM = """你是短视频影视解说的高光主编。你要判断候选片段是否真的值得让观众看到或听到。

高光的价值来自以下任一或组合：
- 戏剧冲突、权力压制、反击、关系改变
- 动作设计、危险升级、空间与对手关系
- 一句台词立住人物或改变局势
- 演员的眼神、停顿、呼吸、颤抖、沉默和反应
- 真相揭示、悬念、笑点、视觉奇观、道德选择

硬规则：
1. “能说明剧情”不等于“有戏”。表演、动作、声音和状态变化更重要。
2. 片段需要太多前情才能懂时，提高 context_dependency 风险。
3. 最大谜底被过早使用时，提高 spoiler 风险。
4. 台词或动作被截断时，提高 unsafe_boundary 风险。
5. must_hear_original 只在原声、表演、动作声或沉默不可替代时设为 true。
6. 分数都在 0 到 1。selection_reason 必须说明删掉它会损失什么。
"""

PLAN_SYSTEM = """你是抖音影视解说的总导演。根据故事图和高光池设计一条快节奏但可理解的成片方案。

目标不是机械缩短，而是让观众持续获得新问题、状态变化、原片回报和情绪升级。

硬规则：
- 钩子必须来自真实高光，不得许诺正文无法兑现的内容。
- 6 秒内应让观众知道谁、遇到什么、为什么值得继续看。
- Beat 数遵守 format_constraints.beat_count_range：highlight 短高光为 2–5 个，其余档位 6–14 个。每个 Beat 必须描述一种变化，而不是场景摘要。
- VO 只承担背景、跨时空压缩、因果连接、伏笔、解释或转场。
- 原片承担强台词、动作、表演、反转、情绪落点和不可替代声音。
- 控制剧透顺序，除非明确选择结果前置结构。
- 给出 Kill List，明确哪些重复争吵、枝节和低回报过程必须压缩或删除。
- 结尾只选一个主策略：回报、余味或下一段问题，不要多种收尾争最后一句。
- 目标时长由复杂度决定，不为追求“一口气看完”盲目拉长。
- hook_highlight_id 只能从 eligible_hook_highlight_ids 选择。不能自行更改 allow_prepose 或把结果前置策略当作用户授权。
- editorial_brief 是用户创作要求，优先于通用风格；其中观众知识、立场、保留情绪、禁用表达和结尾回报要落实到计划，不当作新的剧情事实。
- content_unit 与 duration_mode 是两个维度：一场戏、一条关系线、单集、全片或系列的范围不得为了填满时长自动扩展。
- format_constraints 已按用户显式值、题材建议、默认值的优先级解析；使用这些有效预算，不另写一套固定原片比例。
"""

STORYBOARD_SYSTEM = """你是影视解说的 dramatic editor。你的输出会直接驱动 TTS 和 FFmpeg，所以必须具体、准确、可执行。

你需要把 RecapPlan 编译为 voiceover 与 original 交替的 Storyboard。

硬规则：
1. original 的 visuals 必须引用一个真实连续源时间段，text_raw 写实际要听到的台词，不能写摘要标签。
2. voiceover 的 text 是可直接配音的中文短句。避免“命运齿轮”“殊不知”“万万没想到”等空泛套话，除非素材本身需要且有事实支撑。
3. VO 不得提前说掉紧邻 original 最强台词，也不得在原片后重复同一事实。
4. planned_duration_sec 要与 constraints.vo_chars_per_sec 的中文口播速度匹配。
5. 每个 VO 段至少提供一段 visual_pool 中的画面，每段 visual 必须原样引用有效 unit_id 与对应 source_id，start/end 只能在该 unit 的范围内。不得根据事件宽时间段编造任意切点。画面总时长覆盖 planned_duration_sec；优先用已分析的普通动作、反应、环境和关系画面，不要反复占用高光。
6. original 片段时长遵守 constraints.original_clip_range_sec 与长段预算；超过 15 秒必须在 notes 说明不可再压缩的原因。
7. 强对白用 original_dialogue，打斗和动作可用 action_sound，VO 用 narration。沉默本身是表演时可用 silence。
8. voiceover 默认 mute_original=true；只有动作声或环境声能增强现场感、且不会与旁白争抢时，才设为 false，渲染器会自动压低原声床。
9. 非钩子片段不得重复或重叠使用同一源时间。钩子复用必须 hook_preposed=true 且 allow_reuse=true。
10. 每段 notes 都要写明该段的画面任务、声音分工、进入与退出理由。
11. segments 顺序就是最终输出顺序，目标总时长应接近 plan.target_duration_sec。
12. visual_role 只能选 direct_evidence（画面直接举证）、context（背景语境）、reaction（人物反应）、transition（转场）。画面事实不足以证明 VO 时，不要标成 direct_evidence。purpose 说明具体配画关系。
13. 普通 scene unit 的文字分析仍可能有不确定性；不得把视觉池的猜测当成已确认人物或事实。
14. analysis_window_only 的单位只是分析窗口，不是真实镜头边界；用 original_shot_spans / continuity_shot_ids 理解连续动作，不能把窗口切分当成动作已完成的证据。
"""

SEMANTIC_QC_SYSTEM = """你是影视解说成片的语义审片员。只报告可以被输入证据定位的问题。
检查：人物是否认错、因果是否颠倒、反转是否过早泄露、VO 是否重复原片、是否漏掉题材最重要的高光、开头承诺是否兑现、中段是否只堆信息、结尾是否成立。

所有 finding 都必须 deterministic=false 且 blocking=false，因为这些是模型语义判断，不是客观渲染事实。
severity 可为 info/warning/error，不能为 critical。location 尽量给 segment_id。
不要为了显得严格而制造问题。没有可靠证据时不要输出 finding。
"""


def scene_batch_prompt(units: list[SceneUnit]) -> str:
    payload: list[dict[str, Any]] = []
    for unit in units:
        payload.append(
            {
                "unit_id": unit.unit_id,
                "source_id": unit.source_id,
                "time_range": [round(unit.start, 3), round(unit.end, 3)],
                "transcript": unit.transcript,
                "signals": unit.signals.model_dump(mode="json"),
                "scene_detection": (unit.scene_detection.model_dump(mode="json")
                                    if unit.scene_detection else None),
                "analysis_window_only": (unit.model_extra or {}).get("analysis_window_only", False),
                "original_shot_spans": (unit.model_extra or {}).get("original_shot_spans", []),
                "continuity_shot_ids": (unit.model_extra or {}).get("continuity_shot_ids", []),
                "image_note": "图片顺序与本列表一致，每张是该 unit 的时间标注 filmstrip",
            }
        )
    return (
        "逐项分析以下连续影视单元。图片按列表顺序一一对应。"
        "start_hint/end_hint 必须落在该 unit 的 time_range 内。"
        "fixed_interval 只表示等长分析窗口；镜头边界和连续性未知，不能当作已检测到的剪切。\n\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
    )


def story_chunk_prompt(chunk_id: str, scene_payload: list[dict[str, Any]]) -> str:
    return (
        f"chunk_id 必须写为 {chunk_id}。请从以下连续场景证据中提炼事件与人物。\n\n"
        + json.dumps(scene_payload, ensure_ascii=False, indent=2)
    )


def story_global_prompt(
    chunk_summaries: list[dict[str, Any]], context: str = ""
) -> str:
    context_block = f"\n用户提供的可信上下文：\n{context}\n" if context.strip() else ""
    return (
        "合并以下按原片顺序排列的分块摘要。为角色生成稳定 ID c001、c002；"
        "为事件生成稳定 ID e001、e002。story_order 表示故事实际发生顺序，"
        "reveal_order 表示原片让观众得知的顺序。\n"
        + context_block
        + "\n分块摘要：\n"
        + json.dumps(chunk_summaries, ensure_ascii=False, indent=2)
    )


def highlight_rerank_prompt(
    candidates: list[dict[str, Any]], story_context: dict[str, Any]
) -> str:
    return (
        "结合候选片段 filmstrip、对白和故事上下文重新评分。图片顺序与 candidates 一致。"
        "highlight_id 必须原样返回。\n\n故事上下文：\n"
        + json.dumps(story_context, ensure_ascii=False, indent=2)
        + "\n\n候选：\n"
        + json.dumps(candidates, ensure_ascii=False, indent=2)
    )


def plan_prompt(payload: dict[str, Any]) -> str:
    return (
        "根据以下事实底座生成一份完整 RecapPlan。rhythm 字段必须可执行，"
        "event_ids、character_focus、preferred_highlights 只能引用给定的 event_id、"
        "character_id、highlight_id。人物线、关系线和主题意图沿用 editorial_brief、pov、"
        "main_spine 与各 beat 表达；分析后才按 character_id 绑定人物，不按同名、别名或"
        "临时身份推断合并。缺证据的身份和关系保留 unknown；引用存在不代表跨集证据齐全，"
        "创作重点不得扩大剧透或揭示许可。\n\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
    )


def storyboard_prompt(payload: dict[str, Any]) -> str:
    return (
        "将以下计划编译为最终 Storyboard。source_id、highlight_id、event_id 必须来自输入。"
        "project_name 与 sources 原样保留。\n\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
    )


def shorten_narration_prompt(text: str, target_chars: int, job: str) -> str:
    return f"""把下面的中文影视解说压缩到不超过 {target_chars} 个汉字或等价字符。
保持人物、因果和语气准确，保留该段的任务：{job}。
不要写标题，不要加解释，不要使用空泛短视频套话，只返回改写后的口播句子。

原文：{text}
"""


def semantic_qc_prompt(payload: dict[str, Any]) -> str:
    return (
        "审查下面的故事、计划、Storyboard 和高光引用是否一致。"
        "finding_id 使用 sem_001 起的唯一编号。\n\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
    )
