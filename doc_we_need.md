# v4 天文学后端：当前实现与待核查问题（初稿）

本文供参赛者和主办方同事共同审阅，描述 **2026-09-28 的 v4 原型**，不代表正式赛已冻结的规则。它只讨论实现机制和可复核的问题，不列未发布的评测实例、随机种子、天气真值、精确事件时刻或内部运行步骤。附录列出当前八份 v4 配置文件的**全部参数 key**；同类重复结构用 `<类别>` 表示。正式发布前，评分常数、输入输出字段和可见信息边界仍需形成单独的版本化参赛契约。

问题表使用 **已修复**、**已定规则**、**条件性**、**待决定** 和 **部署要求** 标记状态。前两者记录本轮修改；条件性问题在改动配置后才会触发，待决定项属于比赛模型选择。

## 1. 天区和 target

### 1.1 当前实现

- 天区由若干片互不连通的球面星形多边形组成。当前示例为 3 片、目标总面积 6000 平方度。每片以中心和一组周期谐波扰动生成顶点；边界按相邻顶点间的大圆弧解释，面积按球面三角形计算。生成器检查总面积误差、极区距离和片间距离。
- `footprint.csv` 保存每片的顶点；`targets.csv` 保存 `target_id, ra_deg, dec_deg, target_class, feature_flux, science_weight, required`。天区图为这些数据的可视化，不是额外的判定真值。
- 当前示例生成 30000 个 target，分为 ELG、BGS、LRG、QSO、Star 五类。类别占比按配置分配；位置由天区内的近似均匀抽样与高斯团簇抽样混合。每类 flux 采用对数正态分布，`science_weight` 由类别配置给定；本轮已删除无评分作用的 `redshift` 字段及生成参数。另有一定比例的 `required` 目标。
- 候选位置必须在赛季内至少有一夜满足：太阳高度低于配置门槛、目标高度不低于最低高度、连续窗口不少于配置秒数。当前太阳高度门槛为 −18°，最低目标高度 30°。晨昏使用与已发布 starter kit 相同的太阳位置近似和二分求交思路；目标窗口用恒星时与时角的解析交集判定。
- 这里的“至少一夜有窗口”是建表保证，**不保证**实际天气、月光、光纤分配或资源竞争后仍可完成观测。

### 1.2 核查与处理

| 状态      | 问题与影响                                                                                                                                                                     | 建议                                                                  |
| ------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------- |
| **已修复** | 建表窗口现在同时检查目标赤经相邻的 360° 展开区间，能计算日落前过中天但在前半夜仍可观测的 target。 | 赤经回绕及跨日落回归测试已加入；星表已重新生成。 |
| **条件性** | 片间间隔检查只比较顶点与顶点，不能严格证明两条大圆边之间保持设定间隔；换用更复杂轮廓时，可能出现边相交或边间距不足。                                                                                                                | 用球面弧段相交与弧段最短角距校验。                                                   |
| **待决定** | “均匀位置”由包围圆盘中的 `r∝√u` 抽样再拒绝，严格的球面面积均匀性未验证；高斯团簇也只是比赛用密度模型。                                                                                                                  | 若要求精确面密度，改为球面面积抽样并验证天区内的空间分布。                                       |
| **条件性** | 类别配额先逐类四舍五入，再按绝对舍入误差修正总数；在改动类别比例时，不一定等同标准最大余数法。当前示例比例可整除总数，未受影响。                                                                                                          | 改为先取下整，再按剩余小数分配名额。                                                  |

## 2. 天气和事件

### 2.1 当前实现

- 夜历按台址经纬度、地方日期和太阳高度门槛生成；示例 slot 为 900 秒，只保留完整落在暗夜区间内的 slot。天气真值按 slot 记录 `is_observable`、seeing、transparency、`sky_quality` 和 instrument efficiency。不可观测 slot 的数值字段留空；曝光落在 slot 以外的时间质量计零。
- seeing、transparency、`sky_quality` 有季节项、跨夜相关随机项和夜内相关随机项，并按各自上下限裁剪。`sky_quality` **越高越好**，评分时作分子；天气真值中没有全场月光项。instrument efficiency 以逐 slot 抖动为底，再叠加事件影响。
- 背景关闭是每夜重新开始的开/关随机过程。全场天气事件直接进入逐 slot 真值；方向性天气事件保留方向、时间和乘子，由 scorer 按目标位置施用。rainy 与 tornado 默认强制关闭；cloudy、smoggy、cold_wave 默认降低可用质量。
- 火箭发射是有时间和方位扇区的关闭事件；地形遮挡从开场持续到结束，命中扇区的观测计零。地震按震级映射为仪器损伤并逐夜指数恢复，当前配置**只降低仪器效率**，不修改 seeing、transparency、`sky_quality`。仪器故障是另一种效率损失，正确举报后从举报时刻起修复。
- 选手侧公告按 slot 发布粗粒度事件种类与八方位方向；预报按配置周期发布可预报事件的粗信息。地震只在发生后公告，不进入预报；仪器故障不公告、不预报。精确乘子、精确扇区和数值天气真值属于评分输入，不是公告字段。
- 压力场景另有数据丢失和指向偏差：前者在触发后的下一决策点用 `state_resync` 告知重算结果，后者是持续的 alt/az 指向偏差。两者均由压力开关控制。数据丢失按已执行 `observe` 动作的序号区间无效化，`wait` 不占序号，时间不退回。

| 类别          | 对观测的作用                | 选手能获知什么            |
| ----------- | --------------------- | ------------------ |
| 天气系统        | 全场或方位扇区的质量乘子；部分类型关闭观测 | 粗种类与方向的公告，部分有夜粒度预报 |
| 火箭发射        | 指定扇区在事件期计零            | 粗方向公告和夜粒度预报        |
| 地震          | 从发生时刻开始降低仪器效率，逐夜恢复    | 发生后有粗公告，无事前预报      |
| 地形遮挡        | 固定扇区内计零               | 开场的一次粗方向公告         |
| 仪器故障        | 降低效率直至正确举报            | 无公告、无预报；可从得分反馈推断   |
| 数据丢失 / 指向偏差 | 前者撤销部分既有观测，后者改变实际指向   | 前者触发时重同步，后者无公告     |

### 2.2 核查与处理

| 状态      | 问题与影响                                                                                                                | 建议                                                                |
| ------- | -------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------- |
| **已修复** | 天气和火箭事件的 `duration_slots` 现在按真正的可观测 slot 计数，跨越白天时延续到后续观测夜，且不超过赛季末尾。 | 已加入跨昼夜和生成事件覆盖 slot 数的测试。 |
| **条件性** | 预报先按覆盖区间选事件，但 `notices[].nights` 收集事件触及的**全部**夜晚，未再裁剪到该份预报的覆盖区间。较长事件会使一份预报列出期限外夜晚。                                   | 生成 `nights` 时与预报覆盖区间取交。                                           |
| **已修复** | 已删除未被生成器使用的 `quality.instrument_efficiency.nominal` key；效率基线由抖动区间定义。 | 默认与压力天气配置均已同步。 |
| **条件性** | 当前生成配置含固定 `seed`。若把生成配置连同可运行的真值生成器直接交给参赛者，未来天气与事件可被本地重建。                                                             | 正式赛将内部生成配置与选手包分离，并在官方轮次前轮换种子。                                     |
| **条件性** | 夜/slot 相关系数及部分概率、区间参数缺少完整范围校验；错误配置可能在生成期报数学异常或产生无意义真值。                                                               | 在加载配置时逐项校验概率、相关系数和区间端点。                                           |
| **待决定** | 地震损伤由震级直接映射，不含震源距、深度或台址响应；天气和地震效应分离已实现，但该损伤强度仍是比赛代理量。                                                                | 若要更接近台址物理，单独设计地震传播/响应模型，不把震级当作当地实测振动。                             |

## 3. fibermap

### 3.1 当前实现

- 当前示例是 4×4 的方形采集单元，共 16 个 fiber。单元玻璃面积、窗框间隙、fiber 数量决定玻璃边长、节距和总视场；fiber 按行优先编号。视场在曝光开始时使用以实际指向为中心的球面心射（gnomonic）切平面；局部纵轴指向高度角增大方向，横轴指向方位角增大方向，方位角 0° 为北、90° 为东。指向恰在天顶时，实际中心方位角（指令方位角加偏差）定义切平面的旋转方向。
- agent 的一次 `observe` 动作给出指令视场中心 `(alt_deg, az_deg)`、曝光秒数和 `fiber_id → target_id` 指派。压力场景的固定指向偏差先加到指令中心；若实际高度因此超出 `[0,90]`，该次曝光不命中，但时间照常消耗。只在曝光开始时判断 target 是否落在其**被指派 fiber 的玻璃**上；落在窗框、其他 fiber 或视场外都不命中。玻璃边界算命中。
- 命中之后假定恒星跟踪，target 相对 fiber 的位置在曝光中固定；不模拟视差角旋转、光纤入射耦合、PSF 或边缘吞吐损失。望远镜中心和 target 在全曝光期都须高于最低高度。结果反馈有目标命中与得分，不回传 fiber 编号。

### 3.2 核查与处理

| 状态      | 问题与影响                                                       | 建议                                    |
| ------- | ----------------------------------------------------------- | ------------------------------------- |
| **已修复** | 视场投影改为以实际指向为中心的球面心射切平面，在天顶和普通高度使用同一公式。天顶处以实际中心方位角约定平面方向。      | 已增加天顶、普通高度及玻璃边界回归测试。                  |
| **已修复** | 压力偏差若将实际中心推至 `[0,90]` 以外，该曝光判不命中、时间仍消耗。                     | 投影与 runner 对实际中心均检查范围。                |
| **已修复** | fiber 数量必须是**正的**完全平方数。                                     | 配置校验和零值回归测试已加入。                       |
| **待决定** | 方格玻璃是比赛抽象，不是实际光纤孔径。若未来加入边缘损失，不能直接把半度方格的中心距离套入角秒尺度 Gaussian。 | 先决定是否需要吞吐模型；如需要，再引入角秒级目标偏心、PSF 与孔径尺度。 |

## 4. scorer

### 4.1 当前实现

一次曝光对 target `i` 的未封顶质量使用下式；带星号的天气分量已包含适用的事件乘子：

```text
q_i = [eff* × transparency* × sky_quality* × lunar_i]
      / [q0 × seeing* × airmass_i^0.6]
lunar_i = 1 − p × illumination × sin(max(0, Moon altitude))^a
                 × exp(−Moon–target separation / theta)
factor_i = min(feature_flux_i × exposure_seconds × q_i / (f0 × t0), 1)
score_i,e = science_weight_i × factor_i,e × program_multiplier_e
best_i = max(有效曝光 e 的 score_i,e)
```

当前原型采用 `q0=0.68`、`f0=0.5`、`t0=900 s`、airmass 指数 `0.6`。月光沿用 starter kit 的经验式，`p=0.75`、`theta=35°`、`a=1`；式中的角度计算先由度转为弧度，月亮在地平线下时 `lunar_i=1`。太阳/月亮位置、恒星时和空气质量函数沿用与已发布 starter kit 对齐的近似算法。天气按曝光与 slot 的时间交集积分，方向性事件按真实起止时间切开，再以不超过 120 秒的片段按 target 当时方位判定。airmass 用曝光中点 target 高度。

agent 声明 `DARK`、`BRIGHT` 或 `BACKUP`；实际 band 由视场中心的天气、月光及空气质量判定，**不含**仪器效率或方向性事件。质量阈值为 `0.65/0.40`；声明吻合时倍率为 `1.20/1.12/1.06`，不吻合为 `1.00`。加成先进入该次 target 得分，再对多次曝光取单次最高分；本轮**不做多曝光累积**。

总分为所有 `best_i` 之和，减去 required 未达标罚分和 RA 条带均匀度罚分，再加举报结算。required 用所有**有效**曝光中的最大 `factor_i` 是否达到 `0.5` 判定，缺一个罚 `50`；均匀度按 10° RA 条带内 `factor_i≥0.5` 的 target 比例求 Jain 指数，权重 `200`。故障发生后首次正确举报 `+100` 并立即修复；错误或重复举报 `−150`。数据丢失后，账本从仍有效的曝光重算最高分和达标状态。

当前 runner 是本地 Python callable 原型。初始化上下文只含公开的台址、target、天区顶点、fiber 和评分规则等字段，不再传递内部真值文件路径；每次决策发送时间、最新公告/预报、新消息、上次动作结果和当前累计目标分。正式赛由主办方在 GitHub 服务器执行评测，并须以进程/文件权限隔离隐藏真值；本地 callable 原型本身不是隔离边界。

| 动作 | 当前输入与时间语义 |
| --- | --- |
| `observe` | 指令中心、`fiber_id → target_id` 指派、曝光秒数及 program；在曝光结束后给命中目标及该次得分。 |
| `wait` | 指定等待秒数，推进模拟时钟；不产生可被数据丢失无效化的观测序号。 |
| `report` | 举报当前仪器故障，立即结算且不推进模拟时钟；连续零时长举报超过 32 次时终止运行。 |

### 4.2 核查与处理

| 状态       | 问题与影响                                                                                                  | 建议                                                      |
| -------- | ------------------------------------------------------------------------------------------------------ | ------------------------------------------------------- |
| **部署要求** | 本地 runner 已从初始化上下文移除内部真值路径，只提供公开信息；同进程 callable 仍可访问本地文件系统，不能作为正式赛的安全边界。                               | 按主办方决定，正式赛在 GitHub 服务器运行，只挂载允许公开的数据，并验证 agent 无法读取隐藏真值。 |
| **已定规则** | 数据丢失在事件时刻之后的**下一决策点**触发；当前动作先完成，再按当时已执行的 observe 数量 `N` 无效化并发送重同步。                                     | 规则已写入 runner 注释和共享文档，相关测试保持此语义。                         |
| **已修复**  | `report` 仍不消耗模拟时间；连续超过 32 次零时长举报会终止运行，避免无限循环。                                                          | 已加入重复举报回归测试。                                            |
| **条件性**  | 天气生成器允许 `instrument_fault.count` 大于 1，但 runner 只取第一项作为可举报/修复的故障；多个故障时真值效率和修复语义会不一致。                    | 限定配置为 0 或 1，或把故障状态改成事件集合。（回复：故障改为事件集合，同一时刻只存在一个故障）      |
| **条件性**  | `rocket_launch.force_close` 可以配置为 false，但 scorer 仍按 `event_type=rocket_launch` 无条件把该扇区片段计零。            | 删除无效开关，或严格依照 `force_close` 判定。（回复：删除无效开关）               |
| **待决定**  | program band 使用**视场中心**月光和曝光开始时的中心空气质量，而 target 得分使用各自方向的月光与曝光中点空气质量；跨越阈值时，一个视场中不同 target 会共享同一个 band。 | 保留为清晰的“视场申报”规则，或改为逐目标/曝光中点判定，并在参赛契约中写明。（改为逐目标判定）        |
| **条件性**  | score、scenario、fiber 配置没有统一的交叉校验；例如现场参数和日期可彼此不一致，部分参数可设为零后在计算时才出错。                                     | 加载场景时联合校验配置版本、台址、时间范围、正值约束及输入产品一致性。                     |

## Appendix. 配置文件参数 key（当前原型）

以下列**全部现有 key**，不重复列出内部随机种子和产品路径的实际值。`site.*` 在 catalog、weather、fiber 和 scenario 中重复；weather 默认与 stress 文件的 key 结构相同，仅配置值不同。`<class>` 取 `ELG/BGS/LRG/QSO/Star`，`<condition>` 取 `rainy/cloudy/smoggy/cold_wave/tornado`。表中的 `{a,b}` 表示两个独立 key，不是 JSON 语法。

### A. `v4_catalog_config.json`

| 路径 / key                                                                                                                       | 含义                        |
| ------------------------------------------------------------------------------------------------------------------------------ | ------------------------- |
| `schema_version`, `seed`                                                                                                       | 配置版本；目录生成随机种子（内部）。        |
| `site.{name,latitude_deg,longitude_deg,utc_offset_hours}`                                                                      | 台址名称、经纬度、地方时间相对 UTC 的小时差。 |
| `footprint.{total_area_deg2,area_tolerance_fraction,n_components}`                                                             | 目标总面积、容差、分片数。             |
| `footprint.{component_area_weights,component_centers,component_gap_deg,pole_margin_deg}`                                       | 分片面积权重、候选中心、最小间隔、天极留白。    |
| `footprint.{vertices_per_component,harmonic_amplitude_ranges}`                                                                 | 每片顶点数、谐波振幅范围。             |
| `targets.{total_count,required_fraction,clustered_fraction,n_cluster_centers,cluster_sigma_deg}`                               | 总数、必做比例及成团位置模型。           |
| `targets.class_fractions.<class>`                                                                                              | 各类别比例。                    |
| `targets.models.<class>.{flux_median,flux_log_sigma,science_weight}`                              | 各类属性分布与科学权重。              |
| `observability.{start_date,end_date,sun_altitude_limit_deg,minimum_altitude_deg,minimum_window_seconds,max_position_attempts}` | 建表日期、高度门槛、最短连续窗口及重采样次数。   |
| `output.directory`                                                                                                             | 内部生成目录。                   |

### B. `v4_weather_config.json` 与 `v4_weather_stress_config.json`

| 路径 / key | 含义 |
| --- | --- |
| `schema_version`, `seed` | 配置版本；天气与事件随机种子（内部）。 |
| `site.{name,latitude_deg,longitude_deg,utc_offset_hours}` | 台址。 |
| `survey.{start_date,end_date,slot_seconds,sun_altitude_limit_deg}` | 夜历范围、slot 长度、太阳高度门槛。 |
| `quality.<field>.{nominal,seasonal_amplitude,night_sigma,slot_sigma,minimum,maximum}` | `<field>` 为 `seeing_arcsec/transparency/sky_quality`；季节、跨夜、slot 噪声及裁剪界。 |
| `quality.instrument_efficiency.{jitter_minimum,jitter_maximum,minimum,maximum}` | 仪器效率抖动区间与裁剪界。 |
| `quality.{night_correlation,slot_correlation,seasonal_phase_day}` | 两级相关系数与季节相位。 |
| `background_closure.{start_probability_per_open_slot,reopen_probability_per_closed_slot,seasonal_probability_amplitude}` | 背景开闭马尔可夫过程。 |
| `weather_events.{sector_width_deg_range,sector_altitude_limit_deg_range}` | 方向性天气的扇区参数。 |
| `weather_events.conditions.<condition>.{count,duration_slots,force_close,seeing_multiplier,transparency_multiplier,sky_quality_multiplier}` | 五类天气事件各自的次数、持续时间、关闭标记和质量乘子。 |
| `weather_events.conditions.<condition>.scope_weights.ALL`、`weather_events.conditions.<condition>.scope_weights.HORIZON_SECTOR` | 全场/扇区抽样权重；`HORIZON_SECTOR` 只存在于允许方向事件的类别。 |
| `rocket_launch.{count,duration_slots,azimuth_sector_width_deg,max_altitude_deg,force_close}` | 火箭发射次数、时长、扇区和关闭标记。 |
| `earthquake.{count,magnitude_range,impact_coefficient,reference_magnitude,max_degradation,decay_nights,negligible_degradation}` | 地震抽样和指数损伤/恢复参数。 |
| `earthquake.{seeing_impact_coefficient,transparency_impact_coefficient,sky_quality_impact_coefficient}` | 对大气质量的附加影响；当前配置均为零。 |
| `terrain_obstruction.{sector_count,width_deg_range,max_altitude_deg_range}` | 地形遮挡扇区数与范围。 |
| `instrument_fault.{count,instrument_efficiency_multiplier_range}` | 仪器故障次数与效率损失区间。 |
| `publication.{forecast_interval_days,forecast_horizon_days}` | 预报发布周期与覆盖天数。 |
| `stress_tests.enabled` | 压力事件总开关。 |
| `stress_tests.data_loss.{trigger,window_max_fraction}` | 数据丢失触发方式及最大窗口比例；当 `trigger=fixed_slot` 时另需 `slot_id`，当 `trigger=fixed_date` 时另需 `date`（这两个可选 key 不在当前两份 JSON 中）。 |
| `stress_tests.pointing_offset.{max_abs_alt_rad,max_abs_az_rad}` | 高度角、方位角固定偏差的抽样绝对上限。 |
| `output.directory` | 内部生成目录。 |

### C. `v4_fiber_config.json` 与 `v4_sky_map_config.json`

| 文件 | 路径 / key | 含义 |
| --- | --- | --- |
| fiber | `schema_version` | fiber 几何配置版本。 |
| fiber | `site.{name,latitude_deg,longitude_deg,utc_offset_hours}` | 台址。 |
| fiber | `field.{fiber_area_deg2,gap_deg,n_fibers}` | 单元玻璃面积、窗框间隔、单元数量。 |
| fiber | `exposure.{min_duration_seconds,max_duration_seconds}` | 动作时长下上界。 |
| fiber | `demo.{targets_csv,moment_utc,png_output}` | 演示数据和绘图设置，不参与正式评分。 |
| sky map | `targets_csv`, `footprint_csv`, `summary_json` | 天区图读取的三个产物。 |
| sky map | `pdf_output`, `png_output`, `png_dpi` | 图件输出位置与 PNG 分辨率。 |

### D. `v4_score_config.json`

| 路径 / key | 当前含义 |
| --- | --- |
| `schema_version` | 评分配置版本。 |
| `q0`, `flux_zero_point`, `exposure_zero_point_seconds`, `airmass_exponent` | 观测质量、flux、曝光时间和空气质量归一化。 |
| `lunar_model.{angular_decay_scale_deg,altitude_exponent,maximum_penalty}` | 月亮角距衰减尺度、高度指数、最大损失。 |
| `program.bands.{DARK,BRIGHT}` | 视场质量的两道 program 阈值。 |
| `program.multipliers.{DARK,BRIGHT,BACKUP}`, `program.mismatch_multiplier` | 三种匹配加成和不匹配倍率。 |
| `required.{penalty_per_missing,observed_factor_threshold}` | required 未达标罚分与完成因子门槛。 |
| `uniformity.{weight,ra_band_width_deg,observed_factor_threshold}` | RA 均匀度权重、分带宽度及已观测门槛。 |
| `reporting.{correct_reward,false_penalty}` | 正确与错误故障举报结算。 |

### E. `v4_scenario_default.json` 与 `v4_scenario_stress.json`

| 路径 / key | 含义 |
| --- | --- |
| `schema_version`, `name` | 场景配置版本、场景名。 |
| `site.{name,latitude_deg,longitude_deg,utc_offset_hours}` | 当前场景台址。 |
| `minimum_altitude_deg`, `fiber_config`, `score_config` | 最低观测高度、fiber 配置和评分配置引用。 |
| `products.{targets_csv,footprint_csv,night_calendar_csv,slots_csv,weather_truth_csv,events_csv,earthquake_effects_csv,bulletins_jsonl,forecasts_jsonl}` | 场景输入产物引用；其中真值文件只应由隔离的评分端读取。 |
| `stress.enabled` | 是否启用压力事件。 |
| `stress.stress_events_csv` | 压力事件真值引用，仅 stress 场景存在。 |
| `agent_params.max_observes` | 当前探针 agent 的最大 observe 次数；不是 runner 通用硬上限。 |

配置键盘点：`catalog.observability`、`weather.survey` 和 `scenario.minimum_altitude_deg` 分别独立配置；台址也重复出现。当前样例手工对齐，代码尚未统一校验，因此改一处时必须同步检查其他配置及派生产物。
