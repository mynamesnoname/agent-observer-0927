#!/usr/bin/env python3
"""Build the organizer-internal Chinese digest comparing v4 agent output with truth.

Reads the v4 weather artifacts (bulletins/forecasts JSONL plus the truth CSVs) and emits
a Markdown document that places, side by side, what the agent actually receives and the
underlying truth behind it. Organizer-internal: the document quotes truth values that
must never reach participants. Pure standard library; deterministic given the inputs.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
from datetime import datetime
from pathlib import Path

from .v4_weather_simulator import (
    COARSE_KIND,
    FORECASTABLE_TYPES,
    azimuth_to_direction,
    _sector_center_azimuth,
)


WEATHER_TRUTH_FIELDS = ("is_observable", "seeing_arcsec", "transparency", "sky_quality", "instrument_efficiency")

EVENT_TYPE_ORDER = (
    "cloudy", "rainy", "smoggy", "cold_wave", "tornado",
    "rocket_launch", "earthquake", "terrain_obstruction", "instrument_fault",
)

EVENT_TYPE_ZH = {
    "cloudy": "多云（阴天）",
    "rainy": "下雨",
    "smoggy": "霾",
    "cold_wave": "降温（寒潮）",
    "tornado": "强风暴",
    "rocket_launch": "火箭发射",
    "earthquake": "地震",
    "terrain_obstruction": "地形遮挡",
    "instrument_fault": "仪器故障",
}

STRESS_FIELD_ZH = {
    "event_id": "事件 ID",
    "event_type": "类型",
    "trigger_mode": "触发模式",
    "trigger_ref": "触发参照",
    "window_start_fraction": "窗口下比例 i",
    "window_end_fraction": "窗口上比例 j",
    "window_max_fraction": "窗口上限 x",
    "alt_offset_rad": "高度角偏置 δalt (rad)",
    "az_offset_rad": "方位角偏置 δaz (rad)",
}

ARCMIN_PER_RAD = 206265.0 / 60.0

EVENT_FIELD_ZH = {
    "event_id": "事件 ID",
    "event_type": "类型",
    "actual_start_utc": "开始 (UTC)",
    "actual_end_utc": "结束 (UTC)",
    "scope_type": "空间范围",
    "azimuth_start_deg": "方位角起 (°)",
    "azimuth_end_deg": "方位角止 (°)",
    "min_altitude_deg": "高度角下限 (°)",
    "max_altitude_deg": "高度角上限 (°)",
    "magnitude": "震级",
    "severity": "严重度",
    "force_close": "强制关闭",
    "zero_score": "零分标记",
    "seeing_multiplier": "seeing 乘子",
    "transparency_multiplier": "transparency 乘子",
    "sky_quality_multiplier": "sky_quality 乘子",
    "instrument_efficiency_multiplier": "instrument_efficiency 乘子",
}


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _read_jsonl(path: Path) -> list[tuple[str, dict]]:
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            records.append((line, json.loads(line)))
    return records


def _parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _kv_table(pairs: list[tuple[str, str]]) -> str:
    lines = ["| 字段 | 值 |", "| --- | --- |"]
    lines += [f"| {key} | {value} |" for key, value in pairs]
    return "\n".join(lines)


def _table(headers: list[str], rows: list[list[str]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    lines += ["| " + " | ".join(row) + " |" for row in rows]
    return "\n".join(lines)


def _json_block(raw: str) -> str:
    parsed = json.loads(raw)
    pretty = json.dumps(parsed, ensure_ascii=False, sort_keys=True)
    return f"```json\n{pretty}\n```"


def _slot_truth_table(row: dict[str, str]) -> str:
    return _table(
        ["slot_id", "timestamp_utc", *WEATHER_TRUTH_FIELDS],
        [[row["slot_id"], row["timestamp_utc"], *(row[field] or "—" for field in WEATHER_TRUTH_FIELDS)]],
    )


def _event_kv(event: dict[str, str]) -> str:
    pairs = [
        (EVENT_FIELD_ZH.get(key, key), value if value != "" else "—")
        for key, value in event.items()
    ]
    return _kv_table(pairs)


def _bulletin_during(bulletins, kind: str, start: datetime, end: datetime):
    for raw, record in bulletins:
        issued = _parse_utc(record["issued_at_utc"])
        if start <= issued < end and any(n["event_kind"] == kind for n in record["notices"]):
            return raw, record
    return None


def _forecast_with(forecasts, kind: str):
    for raw, record in forecasts:
        if any(n["event_kind"] == kind for n in record["notices"]):
            return raw, record
    return None


def build_digest(input_dir: Path, sample_seed: int = 0, stress_dir: Path | None = None) -> str:
    events = _read_csv(input_dir / "v4_events.csv")
    truth = {row["slot_id"]: row for row in _read_csv(input_dir / "v4_weather_truth.csv")}
    effects = _read_csv(input_dir / "v4_earthquake_effects.csv")
    bulletins = _read_jsonl(input_dir / "v4_bulletins.jsonl")
    forecasts = _read_jsonl(input_dir / "v4_forecasts.jsonl")
    summary = json.loads((input_dir / "v4_weather_summary.json").read_text(encoding="utf-8"))
    bulletin_by_slot = {record["slot_id"]: (raw, record) for raw, record in bulletins}

    stress_events: list[dict[str, str]] = []
    resync_schema: dict | None = None
    if stress_dir is not None and (stress_dir / "v4_stress_events.csv").is_file():
        stress_events = _read_csv(stress_dir / "v4_stress_events.csv")
        resync_schema = json.loads(
            (stress_dir / "v4_state_resync_schema.json").read_text(encoding="utf-8")
        )
    has_stress = bool(stress_events)

    out: list[str] = []
    add = out.append

    add("# v4 天气与事件：agent 可见输出 × 背后真值 对照文档（组织方内部）")
    add("")
    add("## 1. 说明")
    add("")
    add(
        "本文档对照展示 v4 天气与事件子系统的两条产出线：**agent 实际收到的公告/预报**"
        "（粗粒度，仅事件种类 + 8 方位/全场）与 **scorer/主办方侧的全量真值**。"
        "受众分离规则：真值 CSV 中的数值（seeing/transparency/sky_quality/instrument_efficiency、"
        "精确扇区、震级等）仅供组织方与 scorer 使用，绝不下发给选手；本文档因此属组织方内部材料。"
    )
    add("")
    add("产物文件清单：")
    add("")
    artifact_rows = [
        ["`v4_night_calendar.csv` / `v4_slots.csv`", "组织方", "v4 站点夜历与 900 s slot 划分"],
        ["`v4_weather_truth.csv`", "组织方/scorer", "逐 slot 天气真值（背景模型 + 全局事件已并入）"],
        ["`v4_events.csv`", "组织方/scorer", "全部事件真值（含数值乘子、精确扇区、震级）"],
        ["`v4_earthquake_effects.csv`", "组织方/scorer", "地震逐夜衰减真值明细"],
        ["`v4_bulletins.jsonl`", "agent", "逐 slot 公告（当前事件种类 + 粗方向）"],
        ["`v4_forecasts.jsonl`", "agent", "每 7 天粗预报（可预报事件的种类 + 粗方向 + 夜粒度日期）"],
        ["`v4_weather_summary.json`", "组织方", "生成参数、统计与全部产物 sha256"],
    ]
    if has_stress:
        artifact_rows.append(
            ["`stress/` 子目录", "组织方/scorer + agent", "开关开启的全套产物，另含 `v4_stress_events.csv`（极限工况真值）与 `v4_state_resync_schema.json`（重同步契约）"]
        )
    add(_table(["文件", "受众", "内容"], artifact_rows))
    add("")
    add(
        f"本次产物：{summary['survey']['night_count']} 夜 / {summary['survey']['slot_count']} slot；"
        f"事件 {summary['events']['total']} 个；公告 {summary['publications']['bulletin_count']} 条、"
        f"预报 {summary['publications']['forecast_count']} 条。"
    )
    if has_stress:
        add("")
        add(
            "极限工况事件（数据丢失、仪器方位角偏置）由 `stress_tests.enabled` 全局开关控制："
            "开关关闭时产物无任何痕迹；本文档第 4 章样例取自**开启开关**的产物（`stress/` 子目录）。"
        )
    add("")

    # --- 2. quiet-period samples ---------------------------------------------------
    add("## 2. 平时（无事件活动）")
    add("")

    add("### 2.1 每周开始时的输出（第一周粗预报）")
    add("")
    raw_fc, fc = forecasts[0]
    add("**agent 实际收到（forecast 记录）：**")
    add("")
    add(_json_block(raw_fc))
    add("")
    cover_start, cover_end = _parse_utc(fc["coverage_start_utc"]), _parse_utc(fc["coverage_end_utc"])
    week_events = [
        event for event in events
        if _parse_utc(event["actual_start_utc"]) < cover_end and _parse_utc(event["actual_end_utc"]) > cover_start
    ]
    week_truth = [
        row for row in truth.values()
        if cover_start <= _parse_utc(row["timestamp_utc"]) < cover_end
    ]
    closed = sum(1 for row in week_truth if row["is_observable"] == "false")
    observable_seeing = [float(row["seeing_arcsec"]) for row in week_truth if row["is_observable"] == "true"]
    add("**背后真值（该覆盖期概要，agent 不可见）：**")
    add("")
    add(_table(
        ["指标", "值"],
        [
            ["覆盖期内事件数", str(len(week_events))],
            ["其中可预报事件", str(sum(1 for e in week_events if e["event_type"] in FORECASTABLE_TYPES))],
            ["其中不可预报事件", str(sum(1 for e in week_events if e["event_type"] not in FORECASTABLE_TYPES))],
            ["覆盖期 slot 数 / 关闭 slot 数", f"{len(week_truth)} / {closed}"],
            ["可观测 slot 的 seeing 范围", f"{min(observable_seeing):.3f} – {max(observable_seeing):.3f} 角秒"],
        ],
    ))
    add("")
    add("> 注意：覆盖期内的不可预报事件（如地形遮挡恒定存在）不会出现在预报记录中。")
    add("")

    add("### 2.2 某无事件夜的第一条公告")
    add("")
    quiet_night_first = None
    by_night: dict[str, list[tuple[str, dict]]] = {}
    for raw, record in bulletins:
        by_night.setdefault(record["night_id"], []).append((raw, record))
    for night_id, night_bulletins in by_night.items():
        if all(not record["notices"] for _, record in night_bulletins):
            quiet_night_first = night_bulletins[0]
            break
    raw_q, quiet = quiet_night_first
    add(f"选取夜晚：`{quiet['night_id']}`（全夜无任何事件公告）。")
    add("")
    add("**agent 实际收到（bulletin 记录）：**")
    add("")
    add(_json_block(raw_q))
    add("")
    add("**背后真值（该 slot 的天气真值行，agent 不可见）：**")
    add("")
    add(_slot_truth_table(truth[quiet["slot_id"]]))
    add("")

    add("### 2.3 随机一个平静 slot 的公告")
    add("")
    empty_bulletins = [(raw, record) for raw, record in bulletins if not record["notices"]]
    raw_r, rnd = random.Random(sample_seed).choice(empty_bulletins)
    add(f"种子化选取（seed={sample_seed}）：slot `{rnd['slot_id']}`。")
    add("")
    add("**agent 实际收到（bulletin 记录）：**")
    add("")
    add(_json_block(raw_r))
    add("")
    add("**背后真值（该 slot 的天气真值行，agent 不可见）：**")
    add("")
    add(_slot_truth_table(truth[rnd["slot_id"]]))
    add("")

    # --- 3. per event type ---------------------------------------------------------
    add("## 3. 各事件类型样例")
    add("")

    for event_type in EVENT_TYPE_ORDER:
        type_events = [event for event in events if event["event_type"] == event_type]
        add(f"### 3.{EVENT_TYPE_ORDER.index(event_type) + 1} {EVENT_TYPE_ZH[event_type]}（`{event_type}`）")
        add("")
        if not type_events:
            add("本次默认配置未生成该类型事件。")
            add("")
            continue
        event = type_events[0]
        kind = COARSE_KIND[event_type]
        if len(type_events) > 1:
            add(f"本次共 {len(type_events)} 个该类型事件，取 `{event['event_id']}` 为样例。")
            add("")

        start, end = _parse_utc(event["actual_start_utc"]), _parse_utc(event["actual_end_utc"])

        add("**agent 实际收到：**")
        add("")
        if event_type == "instrument_fault":
            add(
                "**无任何公告或预报。** 仪器故障是隐藏事件：agent 只能从每次观测分数中的"
                "效率抖动自行察觉并举报。"
            )
            add("")
        elif event_type == "terrain_obstruction":
            initial_raw = bulletins[0][0]
            add("仅在开场公告中告知一次粗略方向（此后不再重复；遮挡恒定存在）：")
            add("")
            add(_json_block(initial_raw))
            add("")
        else:
            found = _bulletin_during(bulletins, kind, start, end)
            if event_type == "earthquake" and found is None:
                # The shock slot itself is brief; bulletins list the decaying effect nightly.
                found = next(
                    ((raw, record) for raw, record in bulletins
                     if any(n["event_kind"] == kind for n in record["notices"])),
                    None,
                )
            if found is not None:
                add("事件影响期间的公告样例（bulletin 记录）：")
                add("")
                add(_json_block(found[0]))
                add("")
            if event_type in FORECASTABLE_TYPES:
                forecast = _forecast_with(forecasts, kind)
                if forecast is not None:
                    add("同一事件出现在粗预报中（forecast 记录）：")
                    add("")
                    add(_json_block(forecast[0]))
                    add("")
            else:
                add("该类型**不可预报**：不出现在任何 forecast 记录中。")
                add("")

        add("**背后真值（agent 不可见）：**")
        add("")
        add(_event_kv(event))
        add("")
        if event_type == "earthquake":
            event_effects = [row for row in effects if row["event_id"] == event["event_id"]]
            excerpt = event_effects[:3] + event_effects[-1:]
            add(f"逐夜衰减真值摘录（前 3 夜 + 末夜，共 {len(event_effects)} 夜）：")
            add("")
            add(_table(
                ["night_id", "震级", "降级量", "seeing ×", "transparency ×", "sky_quality ×", "efficiency ×"],
                [
                    [
                        row["night_id"], row["magnitude"], row["degradation"],
                        row["seeing_multiplier"], row["transparency_multiplier"],
                        row["sky_quality_multiplier"], row["instrument_efficiency_multiplier"],
                    ]
                    for row in excerpt
                ],
            ))
            add("")
        if event_type == "instrument_fault":
            before, after = [], []
            for row in truth.values():
                if row["is_observable"] != "true":
                    continue
                moment = _parse_utc(row["timestamp_utc"])
                if moment < start:
                    before.append(float(row["instrument_efficiency"]))
                else:
                    after.append(float(row["instrument_efficiency"]))
            add("故障前后的效率真值对比（agent 只能凭分数抖动反推）：")
            add("")
            add(_table(
                ["区间", "可观测 slot 数", "平均 instrument_efficiency", "最小", "最大"],
                [
                    ["故障前", str(len(before)), f"{sum(before)/len(before):.4f}", f"{min(before):.4f}", f"{max(before):.4f}"],
                    ["故障后", str(len(after)), f"{sum(after)/len(after):.4f}", f"{min(after):.4f}", f"{max(after):.4f}"],
                ],
            ))
            add("")
        if event["scope_type"] == "ALL" and event_type not in ("earthquake", "instrument_fault", "terrain_obstruction"):
            affected = [
                row for row in truth.values()
                if start <= _parse_utc(row["timestamp_utc"]) < end
            ]
            if affected:
                samples = list(
                    {
                        row["slot_id"]: row
                        for row in (affected[0], affected[len(affected) // 2], affected[-1])
                    }.values()
                )
                add(f"受影响 slot 真值示例（共 {len(affected)} 个 slot，取首/中/末去重后）：")
                add("")
                add(_table(
                    ["slot_id", "is_observable", "seeing", "transparency", "sky_quality", "efficiency"],
                    [
                        [
                            row["slot_id"], row["is_observable"],
                            row["seeing_arcsec"] or "—", row["transparency"] or "—",
                            row["sky_quality"] or "—", row["instrument_efficiency"] or "—",
                        ]
                        for row in samples
                    ],
                ))
                add("")
        if event["scope_type"] == "HORIZON_SECTOR":
            add(
                "> 方向性事件不并入逐 slot 全局真值；scorer 按观测指向的方位角/高度角"
                "与扇区求交后施用乘子（地形遮挡则判零分）。"
            )
            add("")

    # --- stress-test events (gated) -------------------------------------------------
    hidden_section_no = 4
    if has_stress:
        hidden_section_no = 5
        add("## 4. 极限工况事件（stress_tests 开关开启产物）")
        add("")
        offset_rows = [row for row in stress_events if row["event_type"] == "pointing_offset"]
        loss_rows = [row for row in stress_events if row["event_type"] == "data_loss"]

        add("### 4.1 仪器方位角偏置（`pointing_offset`）")
        add("")
        if offset_rows:
            offset = offset_rows[0]
            add("**agent 实际收到：**")
            add("")
            add(
                "**无任何公告或预报**（2026-09-27 裁定取消存在性公告：只公告存在性没有信息量，"
                "纯隐藏系统误差与仪器故障同构）。agent 唯一的探测通道是**观测结果本身**："
                "被指派的 target 系统性未命中，且脱靶方向呈一致的方向性分布——据此可自行"
                "推断偏置的存在与大小，并自主决定修正指令或承受偏差（博弈点）。"
            )
            add("")
            add("**背后真值（agent 不可见）：**")
            add("")
            alt_arcmin = float(offset["alt_offset_rad"]) * ARCMIN_PER_RAD
            az_arcmin = float(offset["az_offset_rad"]) * ARCMIN_PER_RAD
            pairs = [
                (STRESS_FIELD_ZH.get(key, key), value if value != "" else "—")
                for key, value in offset.items()
            ]
            pairs.append(("δalt 换算", f"{alt_arcmin:+.3f} 角分"))
            pairs.append(("δaz 换算", f"{az_arcmin:+.3f} 角分"))
            add(_kv_table(pairs))
            add("")
            add(
                "> scorer 语义：视场包含判定与最低高度角判定一律使用**含偏置的实际指向**"
                "（真指向 = 指令指向 + 偏置）；偏置建造期即有、永久不修复。该施用随 "
                "fiber map（第 4 项）落地。"
            )
            add("")

        add("### 4.2 数据丢失（`data_loss`）")
        add("")
        if loss_rows:
            loss = loss_rows[0]
            add("**agent 实际收到：**")
            add("")
            add(
                "触发时**无独立公告**——agent 收到的是 `state_resync` 状态重同步消息"
                "（消息本身即通知）。生成期只定义契约，实际填数由第 3 项 runner 完成。"
                "契约字段（`v4_state_resync_schema.json`）："
            )
            add("")
            if resync_schema is not None:
                field_rows = []
                window = resync_schema["fields"]["invalidated_window"]
                for name, desc in resync_schema["fields"].items():
                    if name == "invalidated_window":
                        for sub_name, sub_desc in window.items():
                            field_rows.append([f"invalidated_window.{sub_name}", str(sub_desc)])
                    elif isinstance(desc, str):
                        field_rows.append([name, desc])
                    else:
                        field_rows.append([name, f"`{json.dumps(desc, ensure_ascii=False)}`"])
                add(_table(["字段", "含义"], field_rows))
                add("")
            add("**背后真值（agent 不可见）：**")
            add("")
            pairs = [
                (STRESS_FIELD_ZH.get(key, key), value if value != "" else "—")
                for key, value in loss.items()
            ]
            quake = next(
                (event for event in events if event["event_id"] == loss["trigger_ref"]),
                None,
            )
            if loss["trigger_mode"] == "after_earthquake" and quake is not None:
                pairs.append(("跟随的地震", f"{quake['event_id']}（震级 {quake['magnitude']}）"))
            add(_kv_table(pairs))
            add("")
            add(
                "> 窗口约定：序号空间**仅含 observe 动作**（wait 不产生可丢失数据），0 起计；"
                "无效化窗口为左闭右开区间 `[floor(i·N), floor(j·N))`（N = 触发时已执行的 "
                "observe 动作数）；被无效动作花掉的时间不退还，原始 action 数据后台保留。"
            )
            add("")

    # --- hidden fields --------------------------------------------------------------
    add(f"## {hidden_section_no}. 信息隐藏清单（永不下发给 agent）")
    add("")
    add("- 逐 slot 数值天气量：`seeing_arcsec`、`transparency`、`sky_quality`、`instrument_efficiency`（含效率抖动基线）。")
    add("- 事件的精确时刻（秒级起止）、严重度、全部数值乘子。")
    add("- 方向性事件的精确扇区参数（方位角起止、高度角上限）；agent 只知 8 方位粗方向。")
    add("- 地形遮挡的精确遮罩范围与零分判定的输入参数；agent 仅在开场公告中听到一次粗方向。")
    add("- 地震的震级、初始降级量、衰减常数与逐夜衰减表；地震绝不出现在预报中。")
    add("- 仪器故障的存在性本身（公告与预报均不出现）、其效率乘数与起止时间；agent 只能凭分数反推。")
    add("- 不可观测 slot 的关闭原因细分（背景关闭 vs 强制关闭事件）。")
    add("- 全部产物的种子与 sha256（`v4_weather_summary.json` 属组织方侧）。")
    if has_stress:
        add("- 仪器方位角偏置的**存在性与数值**（δalt/δaz）均不下发：无公告、无预报，agent 只能从系统性脱靶图案自行推断。")
        add("- 数据丢失的窗口参数（i/j/x）与触发规则真值：具体窗口由触发时的重同步消息披露，真值参数不下发。")
    add("")

    return "\n".join(out) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=None, help="v4 weather config JSON (locates default input dir)")
    parser.add_argument("--input-dir", type=Path, default=None, help="directory holding the v4 weather artifacts")
    parser.add_argument("--stress-dir", type=Path, default=None,
                        help="directory holding the stress-test artifacts (default: <input-dir>/stress; skipped when absent)")
    parser.add_argument("--output", type=Path, default=None, help="digest output path")
    parser.add_argument("--sample-seed", type=int, default=0, help="seed for the random quiet-slot sample")
    args = parser.parse_args()
    input_dir = args.input_dir
    if input_dir is None:
        if args.config is None:
            parser.error("either --input-dir or --config is required")
        config = json.loads(args.config.read_text(encoding="utf-8"))
        input_dir = (args.config.parent / str(config["output"]["directory"])).resolve()
    stress_dir = args.stress_dir if args.stress_dir is not None else input_dir / "stress"
    if not stress_dir.is_dir():
        stress_dir = None
    output = args.output or (input_dir / "v4_agent_output_digest_zh.md")
    text = build_digest(input_dir, args.sample_seed, stress_dir)
    output.write_text(text, encoding="utf-8", newline="\n")
    print(json.dumps({"digest": str(output), "bytes": len(text.encode("utf-8"))}))


if __name__ == "__main__":
    main()
