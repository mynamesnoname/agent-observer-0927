# v4 重新设计实现文档（组织方内部）

> **组织方内部文档。** 本文档包含隐藏真值语义与极限工况机制的完整细节
> （地震参数、仪器故障、数据丢失窗口、方位角偏置数值等），**不属于选手可见
> 材料**。选手可见的产物仅包括：targets.csv、天区图 PDF、公告/预报 JSONL 与
> 未来协议文档中明确列出的字段。

**2026-09-28 天文学模型评审增补：**开放观测门槛为太阳高度 −18°，地震
持续影响限定为仪器效率。逐目标月光已按旧 starter kit 的方向模型加入评分，
`sky_quality` 恢复为越高越好；当前天气与运行生成物在
`_0927output/astronomy_review/review_fixes/`。多次曝光仍只取单次最高分，
本轮不增加累积计分；光纤边缘损失另议。下文旧分数仅作历史对照。

原始概念：`idea-0927.md`。计划节点：`_plan/plan/MP-053` ~ `MP-057`（原型已完成），
天文学模型修订见 `MP-058`。
仓库：`agent-observer-0927/`（v4 全部为新文件，冻结的 v3 未被触碰）。

## 目录

1. [总览](#1-总览)
2. [天区与 target 生成器（MP-053）](#2-天区与-target-生成器mp-053)
3. [天气与事件（MP-054）](#3-天气与事件mp-054)
4. [极限工况事件（MP-055）](#4-极限工况事件mp-055)
5. [fiber map（MP-056）](#5-fiber-mapmp-056)
6. [scorer 与 run 循环（MP-057）](#6-scorer-与-run-循环mp-057)
7. [调参指南](#7-调参指南)
8. [再生成与验证](#8-再生成与验证)

## 1. 总览

**v4 概念**：比赛不再给选手预制 tile，只公布天区轮廓、target 列表、观测起止
时间和望远镜参数；选手自己解算 target 起降、自行规划每次指向（tile）。天气对
选手不透明——agent 只能从粗粒度公告/预报和每次观测的分数反推天气。

### 1.1 五个板块与计划节点

| 板块 | 节点 | 交付 |
| --- | --- | --- |
| 天区与 target 生成器 | MP-053 | `challenge/v4_catalog_generator.py`、`challenge/v4_sky_map.py` |
| 天气与事件 | MP-054 | `challenge/v4_weather_simulator.py`、`challenge/v4_output_digest.py` |
| 极限工况事件 | MP-055 | （并入 MP-054 模块，全局开关 `stress_tests.enabled`） |
| fiber map | MP-056 | `challenge/v4_fiber_map.py` |
| scorer 与 run 循环 | MP-057 | `challenge/v4_scorer.py`、`challenge/v4_runner.py`、`challenge/v4_probe_agent.py` |

### 1.2 文件总表

| 类别 | 文件 |
| --- | --- |
| 配置 | `config/v4_catalog_config.json`、`config/v4_sky_map_config.json`、`config/v4_weather_config.json`、`config/v4_weather_stress_config.json`、`config/v4_fiber_config.json`、`config/v4_score_config.json`、`config/v4_scenario_default.json`、`config/v4_scenario_stress.json` |
| 模块（纯标准库运行时） | `challenge/v4_catalog_generator.py`、`challenge/v4_weather_simulator.py`、`challenge/v4_fiber_map.py`、`challenge/v4_scorer.py`、`challenge/v4_runner.py`、`challenge/v4_probe_agent.py`、`challenge/v4_output_digest.py` |
| 开发期工具（matplotlib/numpy 仅构建期） | `challenge/v4_sky_map.py`、`challenge/v4_fiber_map.py`（演示图部分） |
| 测试 | `tests/test_v4_catalog.py`、`tests/test_v4_weather.py`、`tests/test_v4_stress_events.py`、`tests/test_v4_fiber_map.py`、`tests/test_v4_scorer.py` |
| 产物 | `_0927output/astronomy_review/review_fixes/` 保存当前星表、天区图、天气真值、公告和 default/stress 运行结果；其余目录为旧样例。 |

**未实现（后续工作）**：选手协议（stdin/stdout JSONL 进程）、worker/平台接线、
有竞争力的 baseline agent。本设计只交付到"Python callable 驱动的可计分 run
循环"为止。

## 2. 天区与 target 生成器（MP-053）

### 2.1 天区模型

- **多片不连通星形球面多边形**：默认 3 片（`n_components` 可配，权重
  [0.40, 0.32, 0.28]），中心 (335°, −22°) / (65°, −54°) / (145°, −22°)；
  片间最小间隙实测 14.88°（生成器强制校验 `component_gap_deg`，默认 2°）。
- 顶点半径用 3 阶随机谐波剖面（`harmonic_amplitude_ranges`），边界语义为
  **相邻顶点间的大圆弧**——面积（从片中心扇形三角化的球面角盈）与点包含判定
  （切平面方位角缠绕 + 角距预筛）均精确。
- 总面积配置 6000 deg²，实测 **6000.532 deg²**（误差 0.009%，容差 ±2%）；
  `pole_margin_deg`（默认 5°）禁止包围天极的多边形。
- 点包含判定的教训（记录于节点决策）：扇形立体角与平面 shoelace 同理，其值
  恒为多边形面积、不能判内外；方位角缠绕必须先按角距预筛，否则对跖点附近的
  远片产生假阳性。

### 2.2 target 采样

- 总数 30000（可配）；五类配额逐类四舍五入后校正总数：ELG 10200 / BGS 7200 /
  LRG 6000 / QSO 4200 / Star 2400。ELG/BGS/LRG/QSO 属性模型复用 v3
  `tile_config.json` 的对数正态 flux 与 per-class science_weight；
  **Star 为新增类**（flux_median 4.0、weight 0.3、占比 8%，均可调）。
  无评分作用的 redshift 列及生成参数已按审阅意见移除。
- **覆盖 + 疏密变化**：75% 均匀 + 25% 围绕 150 个成团中心的高斯采样
  （σ=0.5°）。成团份额是提案密度参数——均匀采样在外接圆盘内拒绝率约 1/3，
  实际成团占比约 31%（实测 9165 个）。
- **required**：5%（1500 个）随机抽取，比例可配。
- **可观测窗口保证**：每个 target 在 2026-10-01 ~ 2027-02-01（123 夜）内至少
  一夜存在"太阳高度 < −18° 且高度角 ≥ 30° 且连续 ≥ 900 s"的窗口，否则重采样
  （上限 64 次）。判定是解析的（夜 LST 区间 ∩ target 时角区间 [ra−H0, ra+H0]，
  按恒星时速率换算），不是逐步扫描；当前产物中每个 target 至少 58 夜有窗口，
  最短最长窗口 16999.6 s。赤经按相邻 360° 展开检查，涵盖日落前过中天的目标。

### 2.3 产物与确定性

- `targets.csv`：列契约 `target_id, ra_deg, dec_deg, target_class, feature_flux,
  science_weight, required`（固定精度格式化）。
- `footprint.csv`：`component_id, vertex_index, ra_deg, dec_deg`（组织方侧，
  随产物输出）。
- `summary.json`：参数与统计 + 全部 sha256（不含墙钟时间，保证字节确定）。
- 天区图：`sky_map.pdf` + `sky_map.png`，**Mollweide 全天投影**（RA 向左递增，
  网格标签带白色光晕），深蓝天区轮廓、实色蓝填充（#2e5aac）、白色普通点、
  红色 ⊙ required。
- 同种子两次运行，targets/footprint/summary 逐一 `cmp` 字节一致；3 万 target
  全程约 7 s。

再生成：

```bash
conda run -n survey-agent python -m challenge.v4_catalog_generator \
    --config config/v4_catalog_config.json
conda run -n survey-agent python -m challenge.v4_sky_map \
    --config config/v4_sky_map_config.json
```

## 3. 天气与事件（MP-054）

### 3.1 真值侧

- **夜历**：v4 站点（Paranal：lat −24.6157、lon −70.3976、UTC−4）上按
  "太阳高度 ≤ −18°"逐日求晨昏（复用 v3 的二分穿越思路），slot 900 s。
  当前季节 123 夜 / 3777 slot（其中背景关闭 244 slot）。晨昏以 300 s
  粗采样与 1 s 二分精度求解，与已发布 starter kit 的方法一致；在相同地点、
  日期和 −18° 阈值下，123 夜全部晨昏时刻及 3777 个 slot 起点逐一相同。
- **逐 slot 天气真值**（`v4_weather_truth.csv`，列契约复用 v3
  WEATHER_COLUMNS）：seeing/transparency/sky_quality 为季节 + AR(1) 夜/slot
  相关模型（参数继承 v3 `weather_config.json`），efficiency 为抖动基线
  [0.90, 1.00] 加事件乘子；背景开闭为马尔可夫开/关模型。旧配置中未使用的
  `instrument_efficiency.nominal` 已删除。
- **月球分量**：不进入逐 slot 的全场 `sky_quality` 真值；scorer 用公开天文
  历表按目标方向计算（第 6 节），避免同一次月光影响重复计入。月光因子不写入
  公告、预报或天气真值。
- **字段语义**：沿用已发布 starter kit，`sky_quality` 越高表示条件越好，在
  评分公式中作分子。阴云等不利事件的乘子小于 1 时会降低该量。

### 3.2 事件层语义

| 事件 | 空间 | 时间演化 | 真值作用 | 可预报性 |
| --- | --- | --- | --- | --- |
| 天气系统（rainy/cloudy/smoggy/cold_wave/tornado） | ALL 或方位扇区 | 持续若干可观测 slot，跨昼夜续算 | 乘子作用于质量分量；rainy/tornado 强制关闭 | 可预报（粗措辞 rain/overcast/haze/cold_snap/storm） |
| 火箭发射 | 方位扇区 | 排程驱动，2–5 个可观测 slot | 扇区内 force_close | 可预报 |
| 地震 | 全局 | 瞬时 shock + 按夜指数衰减 | d₀ = min(0.95, exp(0.75·(M−6.8))) 随震级指数上升；dₙ = d₀·exp(−n/4)；仅仪器效率 eff ×(1−d)，seeing/transparency/sky 保持独立的天气真值；逐夜明细单列 CSV | **不可预报**（公告可见） |
| 地形遮挡 | 方位扇区（1–3 个） | 开场即有、永久 | 扇区内观测判零分（`zero_score=true`） | 仅开场公告一次粗方向 |
| 仪器故障 | 全局 | 持续至被举报修复 | 隐藏效率乘数 [0.4, 0.7]，叠加在抖动基线上 | **不可预报、不公告**（只能从分数抖动反推） |

默认配置实例：地震 M5.94（d₀=0.523，衰减 16 夜）与 M5.48（d₀=0.372，15 夜）；
遮挡扇区方位 45.3°→103.4°、高度 ≤43.7°（方向 E，超过 30° 计分下限）；仪器故障使真值效率从
~0.914 降至 ~0.620。nova/reddening 两类 v3 异常已移除。

### 3.3 agent 侧发布契约

- **`v4_bulletins.jsonl`**（每 slot 一条，3777 条）：`{record_type: "bulletin",
  slot_id, night_id, issued_at_utc, initial, notices: [{event_kind, direction}]}`。
  方向为 8 方位码（N/NE/E/SE/S/SW/W/NW，22.5° 分界）或 ALL（全场）；
  `initial=true` 的首条携带地形遮挡方向；地震从实际发生的 slot 起至衰减期结束
  （d ≥ 0.01）出现在公告，事发前的同夜 slot 不提前播报；仪器故障绝不出现。
- **`v4_forecasts.jsonl`**（每 7 天一条，18 条）：`{record_type: "forecast",
  issued_at_utc, coverage_*, notices: [{event_kind, direction, nights}]}`——只含
  事件种类 + 粗方向 + 夜粒度日期，**无任何数值天气量**；地震/仪器故障绝不
  出现（测试与 grep 双重实证）。
- 信息隐藏清单（永不下发）：逐 slot 数值天气量、精确时刻/扇区/乘子、震级与
  衰减表、故障存在性、关闭原因细分、种子与 sha256 等（完整清单见对照文档第
  5 章）。

### 3.4 产物清单（`_0927output/astronomy_review/review_fixes/`）

`v4_night_calendar.csv`、`v4_slots.csv`、`v4_weather_truth.csv`、
`v4_events.csv`、`v4_earthquake_effects.csv`（真值）；`v4_bulletins.jsonl`、
`v4_forecasts.jsonl`（agent 侧）；`v4_weather_summary.json`（统计 + sha256）。
同种子两次运行 8 件全部字节一致，生成约 2 s。

## 4. 极限工况事件（MP-055）

### 4.1 全局开关

`stress_tests.enabled`（默认 false）。关闭时 `generate_stress_events` 整体
短路、不消耗任何随机抽取，**产物与无开关基线字节级一致**（终端实证：MP-054
原配置原文复现 8 产物 cmp 全同）。开启时另产出 `v4_stress_events.csv` 与
`v4_state_resync_schema.json`（示例配置 `config/v4_weather_stress_config.json`
输出到 `stress/` 子目录，与基线同种子、天气完全一致）。

### 4.2 数据丢失（data_loss）

- **触发规则**：`after_earthquake`（默认，trigger_ref = 首次地震 event_id，
  无地震时告警跳过）、`fixed_slot`、`fixed_date`。
- **窗口参数**：i、j 在 [0, 1] 均匀抽取排序，j−i 超 `window_max_fraction`
  （默认 0.05）重抽。实例：i=0.828565、j=0.877466。
- **窗口约定（2026-09-27 用户确认）**：序号空间**仅含 observe 动作**（wait 不
  产生可丢失数据）；0 起计；无效化窗口为左闭右开区间
  `[floor(i·N), floor(j·N))`（N = 触发时已执行 observe 数）；floor 宽度上界
  ceil(x·N)；被无效动作花掉的时间**不退还**；原始 action 数据后台保留。
- **state_resync 契约**（`v4_state_resync_schema.json`，生成期只有 schema）：
  record_type=state_resync，含触发事件 id、无效化窗口（N/i/j/x 原值 + floor 后
  序号）、observed_target_ids、best_scores。触发时**不另发公告**，消息本身即
  通知；实际填数由 runner 完成（见第 6 章）。

### 4.3 仪器方位角偏置（pointing_offset）

- 建造期定标误差：δalt/δaz 在配置的 ±max_abs（默认 0.002 rad）内种子化抽取
  （实例 −0.00055322 rad = −1.902′、+0.00010694 rad = +0.368′），**开局即有、
  永久不修复**。
- **全程无任何公告/预报**（2026-09-27 修订：存在性公告无信息量，纯隐藏系统
  误差与仪器故障同构）。agent 只能从"指派 target 系统性未命中且呈方向性
  分布"自行推断偏置存在与大小，自主决定修正指令或承受偏差。
- 施用点：实际视场中心 = 指令 + (δalt, δaz)，在 alt/az 端（fiber map 几何库
  接受偏置参数）；视场包含判定与最低高度角判定一律用含偏置的实际指向。

### 4.4 对照文档

`challenge/v4_output_digest.py` 生成 `_0927output/astronomy_review/review_fixes/
v4_agent_output_digest_zh.md`：平时三份样例 + 九类事件 + 极限工况两类，每份
"agent 实际收到的 JSONL 原文 × 背后真值表格"并列，末尾为信息隐藏清单。供
组织方核对受众分离是否落实。

## 5. fiber map（MP-056）

### 5.1 方形视场参数化

配置 `fiber_area_deg2` + `gap_deg` + `n_fibers`（完全平方数校验）。默认
0.4 deg² × 16（4×4）、gap 0.05°：

| 派生量 | 值 |
| --- | --- |
| 玻璃边长 | 0.632456° |
| 节距 pitch | 0.682456° |
| 视场边长 | 2.729822°（= 4×pitch，面积 7.452 deg²） |
| 玻璃占空比 | 0.858838 |

网格与曝光开始时刻的局部高度/方位方向对齐（行沿高度增加方向、列沿方位增加
方向，不随视差角旋转）；fiber 编号 row-major、0 号在左下。目标与实际指向
的相对位置通过以实际指向为中心的球面心射切平面求得，普通高度和天顶共用同一
公式；恰在天顶时，实际中心方位角规定平面方向。

### 5.2 命中语义（玻璃窗三态）

只认"**被指派且实际落在其 fiber 玻璃上（含边界，歧义归玻璃）**"的 target：
落在窗框（不记录）、其他 fiber、视场外均不算命中——不计分也不罚分，几何层
只报告布尔结果。邻 fiber 不串扰有测试锁定。

### 5.3 action 链（alt/az 指令 + 赤道跟踪）

1. agent 指令视场中心 (alt, az) + 每条 fiber 的 target 指派 + 曝光时长；
2. 实际中心 = 指令 + (δalt, δaz)（stress 真值，缺省 0）；
   若偏差使实际高度越出 [0,90]，本次曝光计零且仍消耗时间；
3. 曝光开始时刻把实际中心换算为 RA/Dec，此后恒星跟踪——target 相对 fiber 在
   曝光内固定，**命中判定在曝光开始时刻做一次**；
4. `ACTION_SCHEMA` + `validate_action()`：fiber id 合法（0..n−1）、target 不
   重复、duration ∈ [60, 3600]、alt ∈ [0, 90]、az ∈ [0, 360)；返回给 agent 的
   命中结果**不带 fiber id**（裁定）。

scorer 查询接口：`target_altaz`、`min_altitude_during`（采样）、`altitude_ok`
（全曝光区间 ≥ 最低高度角判定）。

### 5.4 演示

`python -m challenge.v4_fiber_map --config config/v4_fiber_config.json` 打印
派生量并对默认 targets.csv 给命中示例（on_glass 33 / on_frame 4 / outside
29963 / assigned_hits 12/12）；演示图
`_0927output/astronomy_review/review_fixes/v4_fiber_demo.png`。

## 6. scorer 与 run 循环（MP-057）

### 6.1 评分公式（2026-09-28 用户确认）

```text
q_exp(i) = q0⁻¹ · eff* · transp* · sky_quality* · lunar(i)
           / (seeing* · airmass(i)^0.6)
lunar(i) = 1 − p · illum · sin(max(0, moon_alt))^a · exp(−rho(i)/theta)
g(i,e)   = min( f(i)·t·q_exp(i) / (f0·t0), 1 )        # 遮挡/未命中/高度无效 → 0
s(i,e)   = weight(i) · g(i,e) · prog_mult(e)           # 加成折入贡献再取 max
best(i)  = max over valid exposures e of s(i,e)

total = Σ_i best(i)
      − P_req · #(required 中有效曝光的最大 factor < 0.5)
      − U · (1 − Jain(r_1..r_K))
      ± 举报结算
```

| 常数 | 值 | 常数 | 值 |
| --- | --- | --- | --- |
| q0（晴夜归一化） | 0.68 | prog_mult DARK/BRIGHT/BACKUP | 1.20 / 1.12 / 1.06 |
| f0（flux 零点） | 0.5 | 不匹配 multiplier | 1.00（不罚） |
| t0（曝光零点） | 900 s | required 罚 P_req | 50 / 个 |
| airmass 指数 | 0.6 | 均匀度权重 U | 200 |
| band 阈值 | 0.65 / 0.40 | RA 条带宽 / 已观测门槛 | 10° / 0.5 |
| 举报结算 | +100 / −150 | 最低高度角 | 30° |
| 月光 p / theta / a | 0.75 / 35° / 1 | sky_quality 语义 | 越高越好 |

实施细节：site 级分量按曝光区间与 slot 真值求交加权（关闭 slot 和夜间 slot 之外
的时间计零）；airmass 用曝光中点 target 高度角；方向性事件按实际起止时刻切分
曝光、逐 target 在不超过 120 s 的片段中判定方位；星号分量含适用事件乘子；地形遮挡与火箭 force_close
只将命中扇区的片段计零；最低高度角同时检查含偏置的实际视场中心与目标自身的
整个曝光区间；仪器故障含在真值效率中，事发后首次正确举报在该决策
时刻结算并修复，后续曝光按乘数反除；地震从发生的 slot 起进入真值，同夜此前
的 slot 不受影响。`illum` 由太阳—月亮角距求月相照亮度；`rho(i)` 为月亮—目标
角距，`moon_alt` 为月亮高度角。月光因子在每个不超过 120 s 的评分片段中按
片段中点计算；月亮在地平线下时为 1。参数在 `score_config.lunar_model`，
`maximum_penalty=0` 可关闭该项。

### 6.2 程序分段机制（防刷分设计）

每次曝光申报 P ∈ {DARK, BRIGHT, BACKUP}；由视场中心的天气、空气质量与月光
因子（不含效率与方向性事件）定 band：q ≥ 0.65 → DARK、≥ 0.40 → BRIGHT、
否则 BACKUP。月光在每段天气真值的中点计算。匹配时加成
1.20/1.12/1.06（难者重赏；BACKUP 最低是刻意的），不匹配 1.00 不罚。加成**折入
该次曝光的逐 target 贡献后再取 max**——空转刷分无收益。

### 6.3 罚分体系

- required：所有有效曝光的最大 factor < 0.5 的每个 required target 罚 50；
- RA 条带均匀度：footprint 内按 10° 分带，r = 带内 factor ≥ 0.5 的占比，
  罚 U·(1 − Jain(r))（全空带定义 Jain=0）；
- 举报：故障实际发生后首次正确举报 +100（立即修复）；提前举报、重复举报或空报 −150；连续超过 32 次零时长举报会终止运行；
- 不设 wait 罚分（连续时间下时间本身就是预算）、不设换向成本。

### 6.4 连续时间模型与数据丢失施用

- action 自带时长（[60, 3600] s），决策时刻 = 上次曝光结束时刻；天气按曝光
  区间与 slot 真值求交施用；公告按 slot 网格发布，决策时刻获得已发布的最新
  bulletin/forecast。
- **数据丢失**：事件时刻（默认 = 首次地震结束）之后的**下一决策点**触发；
  进行中的动作先完成。无效化 `[floor(i·N), floor(j·N))` 窗口内的 observe 动作
  （N = 该决策点已执行的 observe 数），best 账本
  用保留的原始记录重算（架构不变量），按 schema 发 state_resync；时间不退。
- 本地 callable agent 的初始化上下文只含公开的台址、target、天区、fiber 和
  评分规则，不再传入内部真值路径。它仍与 runner 同进程，正式赛须在评测服务端
  隔离隐藏文件，不把本地原型当成安全边界。
- runner 落盘：`decisions.csv`、`observations.csv`、`messages.jsonl`、
  `score_report.json`。

### 6.5 两场景端到端实测（历史 `causality_fixed/`，验证 agent：探针 + 贪心，非契约）

| 分项 | default（700 曝光） | stress（4500 曝光） |
| --- | --- | --- |
| Σ best | 3083.757 | 8894.140 |
| required 罚 | −59750（缺 1195/1500） | −47200（缺 944/1500） |
| 均匀度罚 | −100.475 | −98.417 |
| 举报结算 | 0 | 0 |
| **total** | **−56766.717** | **−38404.277** |
| 观测 target 数 | 7766 | 27302 |
| by_class（最大→最小） | ELG > LRG > QSO > BGS > Star | ELG > LRG > BGS > QSO > Star |

解读：default 探针 agent 的许多曝光落在夜间 slot 之外；修正昼夜积分后这些曝光
不再借用下一夜天气，因此分数大幅低于旧样例。required 罚仍主导总分；by_class
排序以 ELG、LRG 为主。stress 场景实证：**数据丢失在 2026-11-08T02:32Z
（首次地震结束后 2 分钟）触发**——触发时 N=3416，窗口 [2830, 2997)
（167 个 observe、854 条观测失效），resync 恰一条、含 24613 个 target 的重算
best；偏置 δalt=−1.902′、δaz=+0.368′ 全程施用
（单测实证玻璃边缘 target 默认命中、stress 脱框）。

**上一版 `astronomy_review/` 样例**（单次最高分 scorer，仍有全场月光项且
`sky_quality` 作分母）：default 700 次曝光，Σbest 2597.484、
required 缺 1246、总分 −59809.531738；stress 4500 次曝光，Σbest 8533.617、
required 缺 983、总分 −40719.282362。stress 数据丢失于 2026-11-07T03:47Z
触发，窗口 [2764,2928)，983 条观测失效。旧表仅供前后比较。

**上一版 `astronomy_review/lunar_target/` 样例**（逐目标月光、`sky_quality`
作分子）：default 700 次曝光，Σbest 2614.957046、required 缺 1235、总分
−59242.277436；stress 4500 次曝光，Σbest 7416.363909、required 缺 992、
总分 −42286.192196。stress 无效化窗口仍为 [2764,2928)，983 条观测失效。
这些是探针 agent 的回归产物，不是参赛成绩锚点。

**当前 `astronomy_review/review_fixes/` 样例**（修正赤经窗口、事件可观测
slot 计时与心射投影）：default 700 次曝光，Σbest 2712.633403、required 缺
1225、总分 −58630.654700；stress 4500 次曝光，Σbest 7531.873850、
required 缺 981、总分 −41621.099434，数据丢失窗口 [2772,2936)，
974 条观测失效。两组数字只用于核对生成器、几何和计分流水线。

### 6.6 确定性与性能

- 旧样例的字节确定性与性能数据属于早期实现；当前回归以新目录
  `_0927output/astronomy_review/review_fixes/` 为准，不能沿用旧分数锚点。score_report 内含
  scenario 与三份落盘产物的 sha256。

## 7. 调参指南

| 旋钮 | 位置 | 作用方向 |
| --- | --- | --- |
| `required_fraction` ↔ `P_req` | catalog / score | required 占比决定风险暴露面（5% → 1500 个、罚满 75000）；P_req 决定单个未完成 required 的代价。调 required 占比时同步评估罚分总量与 Σbest 的量级平衡 |
| 成团三参数（`clustered_fraction`、`n_cluster_centers`、`cluster_sigma_deg`） | catalog | 控制疏密起伏：团块多而密 → 局部 tile 规划深度高；为 0 则全均匀（失去 fiber 指派博弈） |
| fiber 参数（`fiber_area_deg2`、`gap_deg`、`n_fibers`） | fiber | 面积小/窗框宽 → 命中精度要求高、偏置博弈强；n_fibers 决定单次曝光容量上限 |
| band 阈值与 prog_mult | score | 阈值决定 DARK 稀缺性；加成梯度决定"为好天气留白"的收益 |
| `required.penalty_per_missing`、`uniformity.weight` | score | 罚分权重 vs Σbest 的量级比决定策略取向（冲 required 还是铺覆盖） |
| `lunar_model.maximum_penalty`、`angular_decay_scale_deg`、`altitude_exponent` | score | 逐目标月光的最大损失、角距衰减和高度依赖；最大损失为 0 时关闭 |
| 地震/火箭/遮挡参数 | weather | 极限工况发生率与冲击深度 |

**容量估算**（默认参数）：普通天区一场约 5/deg²×7.45 deg² ≈ 37 个 target，
**3~6 次曝光**可覆盖；成团核心密度高一个量级，需 **15~30 次**；全局可用曝光
槽位（3777 slot）对理论最小曝光数（30000/16 = 1875）的**冗余约 2.0×**——
天气损失与重复观测都要从冗余里出，这是排程压力的来源。

## 8. 再生成与验证

### 8.1 完整命令序列（`agent-observer-0927/` 下，conda env survey-agent）

```bash
# 1. 天区与 target（MP-053）
conda run -n survey-agent python -m challenge.v4_catalog_generator \
    --config config/v4_catalog_config.json
conda run -n survey-agent python -m challenge.v4_sky_map \
    --config config/v4_sky_map_config.json

# 2. 天气与事件（MP-054/055：默认开关关 / stress 开关开）
conda run -n survey-agent python -m challenge.v4_weather_simulator \
    --config config/v4_weather_config.json
conda run -n survey-agent python -m challenge.v4_weather_simulator \
    --config config/v4_weather_stress_config.json

# 3. 对照文档（组织方内部）
conda run -n survey-agent python -m challenge.v4_output_digest \
    --config config/v4_weather_config.json \
    --stress-dir ../_0927output/astronomy_review/review_fixes/stress \
    --output ../_0927output/astronomy_review/review_fixes/v4_agent_output_digest_zh.md

# 4. fiber 演示（MP-056）
conda run -n survey-agent python -m challenge.v4_fiber_map \
    --config config/v4_fiber_config.json

# 5. 端到端 run（MP-057）
conda run -n survey-agent python -m challenge.v4_runner \
    --scenario config/v4_scenario_default.json \
    --agent challenge.v4_probe_agent:make_agent \
    --output-dir ../_0927output/astronomy_review/review_fixes/runs/default
conda run -n survey-agent python -m challenge.v4_runner \
    --scenario config/v4_scenario_stress.json \
    --agent challenge.v4_probe_agent:make_agent \
    --output-dir ../_0927output/astronomy_review/review_fixes/runs/stress
```

### 8.2 测试套件与回归要求

| 套件 | 项数 | 覆盖 |
| --- | --- | --- |
| `tests/test_v4_catalog.py` | 8 | 字节确定性、面积容差、赤经跨日落窗口保证、CSV 契约、成团覆盖、点包含交叉验证 |
| `tests/test_v4_weather.py` | 14 | 确定性、事件按可观测 slot 跨昼夜计时、地震曲线及发生前无效、遮挡语义、预报过滤、无全场月光项、夜历与 starter kit 对齐 |
| `tests/test_v4_stress_events.py` | 11 | 开关双向、窗口约束、偏置界、反向公告断言、触发规则 |
| `tests/test_v4_fiber_map.py` | 27 | 派生量、命中三态、球面心射投影与天顶、回绕、偏置、坐标往返、曝光终点高度、action 校验、CLI 冒烟 |
| `tests/test_v4_scorer.py` | 28 | 昼夜空档、方向事件时间与空间施用、实时举报、逐目标月光与旧版公式一致、sky_quality 方向、完成门槛、无效化重算、resync、上下文隔离、重复举报终止、确定性 |

任何改动后必须通过：上述 88 项 v4 测试 + v3 冻结回归
（`pytest challenge/tests tests/test_challenge_runner.py
tests/test_starter_kit.py`）。

### 8.3 v3 冻结注意事项

- v4 全部产物为**新增文件**；`challenge/` 的字节锁测试
  （`tests/test_starter_kit.py`）只从 starter kit 侧枚举文件，新增文件不影响；
  v3 回归锚点（`BASELINE_TOTAL = 12287.478365`）不得触碰。
- `_0927output/` 在仓库 git 之外。当前天文配置的星表、天气、stress 与运行结果放在
  `_0927output/astronomy_review/review_fixes/`；旧产物保留。极限工况开关回归用当前代码和当前
  配置在测试临时目录中生成两组产物比较，不再依赖旧 `/tmp/v4_baseline/`。
- 运行时核心保持纯 Python 标准库（worker 契约）；matplotlib/numpy 只允许出现
  在 `v4_sky_map.py` 与 `v4_fiber_map.py` 的演示图部分（构建期依赖，惰性导入）。
