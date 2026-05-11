const fs = require("fs");
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  Header, Footer, AlignmentType, LevelFormat, HeadingLevel,
  BorderStyle, WidthType, ShadingType, PageNumber, PageBreak,
  TableOfContents,
} = require("docx");

// Run `npm install` in this folder before generating the document.

// ── Helpers ──────────────────────────────────────────────────────────────────

const FONT = "Microsoft YaHei UI";
const FONT_MONO = "Consolas";
const PAGE_W = 11906; // A4
const PAGE_H = 16838;
const MARGIN = 1440; // 1 inch
const CONTENT_W = PAGE_W - 2 * MARGIN; // 9026

const thinBorder = { style: BorderStyle.SINGLE, size: 1, color: "CCCCCC" };
const borders = { top: thinBorder, bottom: thinBorder, left: thinBorder, right: thinBorder };
const cellMargins = { top: 60, bottom: 60, left: 100, right: 100 };

function p(text, opts = {}) {
  const runs = Array.isArray(text) ? text : [new TextRun({ text, font: FONT, size: 24, ...opts })];
  return new Paragraph({ spacing: { after: 120, line: 320 }, ...opts, children: runs });
}

function bold(text, size = 24) {
  return new TextRun({ text, font: FONT, size, bold: true });
}

function normal(text, size = 24) {
  return new TextRun({ text, font: FONT, size });
}

function mono(text, size = 22) {
  return new TextRun({ text, font: FONT_MONO, size });
}

function heading1(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_1,
    spacing: { before: 360, after: 200 },
    children: [new TextRun({ text, font: FONT, size: 36, bold: true })],
  });
}

function heading2(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_2,
    spacing: { before: 280, after: 160 },
    children: [new TextRun({ text, font: FONT, size: 30, bold: true })],
  });
}

function heading3(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_3,
    spacing: { before: 200, after: 120 },
    children: [new TextRun({ text, font: FONT, size: 26, bold: true })],
  });
}

function bullet(text) {
  const runs = Array.isArray(text) ? text : [normal(text)];
  return new Paragraph({
    numbering: { reference: "bullets", level: 0 },
    spacing: { after: 60, line: 300 },
    children: runs,
  });
}

function bulletBold(label, desc) {
  return bullet([bold(label), normal(desc)]);
}

function codeBlock(text) {
  return new Paragraph({
    spacing: { after: 80 },
    indent: { left: 360 },
    children: [mono(text, 20)],
  });
}

function codeLines(lines) {
  return lines.map((l) => codeBlock(l));
}

function emptyLine() {
  return new Paragraph({ spacing: { after: 60 }, children: [] });
}

// ── Table helper ─────────────────────────────────────────────────────────────

function makeTable(headers, rows, colWidths) {
  const totalW = colWidths.reduce((a, b) => a + b, 0);
  const headerCells = headers.map((h, i) =>
    new TableCell({
      borders,
      width: { size: colWidths[i], type: WidthType.DXA },
      shading: { fill: "D5E8F0", type: ShadingType.CLEAR },
      margins: cellMargins,
      children: [new Paragraph({ children: [new TextRun({ text: h, font: FONT, size: 22, bold: true })] })],
    })
  );
  const dataRows = rows.map((row) =>
    new TableRow({
      children: row.map((cell, i) =>
        new TableCell({
          borders,
          width: { size: colWidths[i], type: WidthType.DXA },
          margins: cellMargins,
          children: [new Paragraph({ children: [new TextRun({ text: String(cell), font: FONT, size: 20 })] })],
        })
      ),
    })
  );
  return new Table({
    width: { size: totalW, type: WidthType.DXA },
    columnWidths: colWidths,
    rows: [new TableRow({ children: headerCells }), ...dataRows],
  });
}

// 2-column param table (param | value)
function paramTable(rows) {
  return makeTable(["参数", "默认值 / 说明"], rows, [4500, CONTENT_W - 4500]);
}

// 3-col table
function table3(headers, rows, widths) {
  return makeTable(headers, rows, widths);
}

// ── Document Sections ────────────────────────────────────────────────────────

function coverPage() {
  return [
    emptyLine(), emptyLine(), emptyLine(), emptyLine(), emptyLine(),
    emptyLine(), emptyLine(), emptyLine(),
    new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { after: 200 },
      children: [new TextRun({ text: "云台数字孪生仿真系统", font: FONT, size: 56, bold: true })],
    }),
    new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { after: 100 },
      children: [new TextRun({ text: "技术文档 v1.0", font: FONT, size: 36 })],
    }),
    emptyLine(),
    new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { after: 80 },
      children: [new TextRun({ text: "Gimbal Digital Twin Simulation System", font: FONT, size: 28, italics: true, color: "666666" })],
    }),
    emptyLine(), emptyLine(), emptyLine(),
    new Paragraph({
      alignment: AlignmentType.CENTER,
      children: [normal("2026 年 4 月", 24)],
    }),
    new Paragraph({ children: [new PageBreak()] }),
  ];
}

function chapter1() {
  return [
    heading1("第 1 章 项目概述"),

    heading2("1.1 系统背景"),
    p("云台数字孪生仿真系统是一个面向视觉伺服跟踪场景的实时仿真平台，用于在纯软件环境中复现「云台-相机-目标」闭环跟踪链路。系统通过数字孪生技术模拟真实硬件的行为，使开发者能够在无需物理设备的情况下进行控制算法设计、参数调优和性能评估。"),

    heading2("1.2 四实体关系"),
    p("系统由四个核心实体构成，形成完整的跟踪闭环："),
    bulletBold("Target（目标运动体）：", "输出世界坐标 (x, y)，模拟被跟踪目标的运动"),
    bulletBold("Gimbal（两轴云台）：", "执行角速度/角度控制，输出姿态 yaw/pitch"),
    bulletBold("Camera（相机）：", "挂载在云台上，根据目标方位和云台姿态成像"),
    bulletBold("Raspi（树莓派控制器）：", "从帧中检测目标，输出控制命令，驱动云台转动"),
    emptyLine(),
    ...codeLines([
      "Target ── target_state (x, y) ──────┐",
      "                                     v",
      "Gimbal ── gimbal_state (yaw) ──> Camera ── frame + obs ──> Raspi",
      "   ^                                                              |",
      "   └────────── Command (set_rate_target) ─────────────────────────┘",
      "                         通过 Runtime 命令总线",
    ]),

    heading2("1.3 技术栈"),
    makeTable(
      ["组件", "用途"],
      [
        ["Python 3.10+", "核心开发语言，dataclass 类型系统"],
        ["NumPy", "矩阵运算、环形缓冲区"],
        ["PyQt5", "GUI 框架（仪表盘、配置编辑器、3D 可视化）"],
        ["pyqtgraph 0.14", "高性能实时绘图"],
        ["matplotlib", "2D/3D 科学可视化"],
        ["unittest", "单元测试与集成测试"],
      ],
      [3000, CONTENT_W - 3000]
    ),
    new Paragraph({ children: [new PageBreak()] }),
  ];
}

function chapter2() {
  return [
    heading1("第 2 章 系统架构设计"),

    heading2("2.1 三层架构"),
    p("系统采用三层架构，职责清晰分离："),
    bulletBold("实体层 (entities/)：", "四个独立实体，各自包含模型(model)、控制(control)、客户端(client)和测试(tests)"),
    bulletBold("运行时层 (runtime/)：", "DigitalTwinRuntime 统一调度，管理命令总线、tick 推进和快照发布"),
    bulletBold("应用层 (simulation/)：", "CLI 参数解析、无头运行、GUI 仪表盘、Bootstrap 编排"),

    heading2("2.2 统一调度机制"),
    p("所有实体由 DigitalTwinRuntime 统一调度，每个 tick 按固定顺序推进："),
    ...codeLines([
      "收命令 -> Target.update -> Gimbal.update -> Camera.update -> Raspi.update -> 发布快照",
    ]),
    p("命令仲裁采用 latest-wins 策略：同一 tick 内多条命令到同一实体时，最后一条生效。设备未 READY 时命令被拒绝，返回 CommandResult(accepted=False)。"),

    heading2("2.3 一个 Tick 的完整数据流"),
    bullet("1. _apply_due_commands()：分派到期命令到对应实体"),
    bullet("2. target.update(dt, t)：推进运动模型，输出 TargetState{x_m, y_m, bearing_deg, distance_m}"),
    bullet("3. gimbal.update(dt, t)：执行串级 PID，驱动被控对象，输出 GimbalState"),
    bullet("4. camera.update(dt, t, target, gimbal)：计算方位角，渲染帧，输出 CameraState + FramePacket"),
    bullet("5. raspi.update(t, world_obs, ...)：延时管线处理，调用控制程序，输出 Command"),
    bullet("6. 发布 WorldSnapshot：包含全部实体状态，供 UI 和工具读取"),

    heading2("2.4 命令总线"),
    p("命令通过三级路径完成闭环："),
    ...codeLines([
      "Raspi.on_tick(obs) → cmds → DelayPipeline → submit_cmd → Runtime._pending_commands",
      "下一 tick 的 _apply_due_commands() 将到期命令分派到对应实体。",
    ]),
    p("典型闭环路径（基线跟踪）：帧中检测目标质心 → 计算像素误差 (u - cx) → 比例映射 yaw_rate = Kp * pixel_error → Command(gimbal, set_rate_target) → Gimbal 转动 → Camera 帧变化 → 循环。"),
    new Paragraph({ children: [new PageBreak()] }),
  ];
}

function chapter3_target() {
  return [
    heading2("3.1 Target 目标运动体"),

    heading3("3.1.1 概述"),
    p("Target 是只读的被动实体——不接受任何命令，从创建起即活跃，无电源状态机。其他实体依赖 target_state 中的 x_m, y_m 计算方位角。"),

    heading3("3.1.2 五种运动模式"),
    p("核心方法 TargetKinematics2D.step(dt) -> (x, y)，根据 motion_type 分支："),
    emptyLine(),

    makeTable(
      ["模式", "公式", "使用参数"],
      [
        ["constant_velocity", "x += vx*dt, y += vy*dt", "velocity_x/y_mps"],
        ["constant_accel", "v += a*dt, x += v*dt", "velocity + accel_x/y_mps2"],
        ["sinusoidal", "x = x0, y = A*sin(2*pi*f*t)", "sin_amplitude/frequency"],
        ["random_walk", "v = v*damp + a*dt, x += v*dt", "random_max_accel/damping/seed"],
        ["waypoint", "朝航点飞行，到达后切换", "waypoints, arrival_radius"],
      ],
      [2200, 3800, CONTENT_W - 6000]
    ),

    heading3("3.1.3 派生属性"),
    ...codeLines([
      "bearing_deg = atan2(y, x) 转角度    // 目标方位角",
      "distance_m  = hypot(x, y)           // 目标距离",
    ]),

    heading3("3.1.4 配置参数"),
    makeTable(
      ["参数", "默认值", "含义"],
      [
        ["motion_type", '"sinusoidal"', "运动模式（Literal 类型，5 选 1）"],
        ["initial_x_m", "100.0", "初始 X 坐标（米）"],
        ["initial_y_m", "0.0", "初始 Y 坐标（米）"],
        ["velocity_x/y_mps", "0.0 / 1.5", "初速度（m/s）"],
        ["accel_x/y_mps2", "0.0 / 0.3", "加速度（m/s^2）"],
        ["sin_amplitude_m", "15.0", "正弦振幅（米）"],
        ["sin_frequency_hz", "0.2", "正弦频率（Hz）"],
        ["random_max_accel_mps2", "1.0", "随机最大加速度"],
        ["random_damping", "0.98", "速度阻尼系数"],
        ["random_seed", "42", "随机种子（可复现）"],
        ["waypoints", "None", "航点列表 [(x, y, speed), ...]"],
        ["waypoint_arrival_radius_m", "1.0", "到达判定半径（米）"],
      ],
      [3200, 1800, CONTENT_W - 5000]
    ),
  ];
}

function chapter3_gimbal() {
  return [
    heading2("3.2 Gimbal 两轴云台"),

    heading3("3.2.1 概述"),
    p("Gimbal 是系统的核心被控对象，接收角度/角速度指令，通过串级 PID 控制器驱动一阶惯性被控对象。"),

    heading3("3.2.2 电源状态机"),
    ...codeLines([
      "OFF ──(power_on)──> BOOTING (1.5s) ──> READY",
      "READY ──(power_off)──> OFF",
      "非 READY 状态拒绝所有控制命令",
    ]),

    heading3("3.2.3 串级 PID 控制器"),
    p("采用双环串级结构：外环角度环（P-only，50Hz）+ 内环角速度环（PI，200Hz）："),
    emptyLine(),

    makeTable(
      ["环节", "频率", "算法", "参数"],
      [
        ["角度外环", "50 Hz (dt=20ms)", "P-only", "angle_kp = 14.0"],
        ["角速度内环", "200 Hz (dt=5ms)", "PI", "rate_kp=1.6, rate_ki=5.0"],
        ["积分限幅", "-", "Anti-windup", "integral_limit = 30.0"],
        ["输出限幅", "-", "Clamp", "actuator_limit = 60.0 dps"],
      ],
      [2000, 2500, 1800, CONTENT_W - 6300]
    ),

    p("外环角度误差计算采用 wrap_pm180 归一化到 [-180, 180)，输出角速度参考值并限幅到 max_rate。内环对角速度误差做 PI 运算，积分项带 anti-windup 限幅。"),

    heading3("3.2.4 被控对象模型"),
    p("一阶惯性环节，模拟电机响应延迟："),
    ...codeLines([
      "alpha = dt / (tau + dt)         // tau = 0.03s",
      "rate = (1 - alpha) * current + alpha * cmd",
      "position += rate * dt            // 积分得到角度",
    ]),
    p("Yaw 轴无界（仅在显示时归一化），Pitch 轴硬限位 [-135, 90]，到达限位时对应方向速率归零。"),

    heading3("3.2.5 PID 参数总表"),
    makeTable(
      ["参数", "Yaw", "Pitch", "说明"],
      [
        ["angle_kp", "14.0", "14.0", "外环比例增益"],
        ["rate_kp", "1.6", "1.6", "内环比例增益"],
        ["rate_ki", "5.0", "5.0", "内环积分增益"],
        ["rate_integral_limit", "30.0", "30.0", "积分限幅"],
        ["actuator_cmd_limit", "60.0 dps", "60.0 dps", "输出限幅"],
        ["max_rate", "60.0 dps", "60.0 dps", "外环参考限幅"],
        ["response_tau", "0.03s", "0.03s", "被控对象时间常数"],
      ],
      [2800, 1600, 1600, CONTENT_W - 6000]
    ),

    heading3("3.2.6 GimbalState 字段"),
    makeTable(
      ["字段", "说明"],
      [
        ["yaw_deg_internal", "内部连续角度（无界）"],
        ["yaw_deg_display", "显示角度（0-360 或 -180~180，由 config 决定）"],
        ["pitch_deg", "俯仰角（硬限位 [-135, 90]）"],
        ["yaw_rate_dps / pitch_rate_dps", "实际角速度"],
        ["yaw_rate_ref_dps / pitch_rate_ref_dps", "角速度参考值（外环输出）"],
        ["mode", "ANGLE_MODE / RATE_MODE"],
        ["power_state", "OFF / BOOTING / READY"],
      ],
      [3500, CONTENT_W - 3500]
    ),
  ];
}

function chapter3_camera() {
  return [
    heading2("3.3 Camera 相机"),

    heading3("3.3.1 概述"),
    p("Camera 挂载在云台上，根据目标方位和云台姿态进行针孔成像。输出 CameraState 和 FramePacket（含灰度图像与内参）。"),

    heading3("3.3.2 针孔成像模型"),
    p("目标方位角 alpha 的计算："),
    ...codeLines([
      "bearing = atan2(target.y, target.x)           // 目标方位角",
      "yaw = radians(gimbal.yaw_deg_internal)        // 云台航向角",
      "alpha = (bearing - yaw + pi) % (2*pi) - pi    // 归一化到 [-pi, pi]",
    ]),
    p("像素坐标映射："),
    ...codeLines([
      "u = f_px * tan(alpha) + w/2     // 水平像素坐标",
      "v = h/2                          // 垂直居中（1D 简化）",
      "in_fov = |alpha| <= fov_half     // 是否在视野内",
    ]),
    p("信标渲染为 2D 高斯光斑（sigma = 3.2 px），叠加高斯噪声（std = 0.5）。"),

    heading3("3.3.3 变焦控制"),
    p("ZoomController 采用一阶惯性模型（tau = 0.2s），支持两种模式："),
    bullet("目标焦距模式：指数趋近 f_target"),
    bullet("恒速模式：f += clamp(rate, -120, +120) * dt"),
    p("焦距范围：[4.4mm, 200mm]。"),

    heading3("3.3.4 成像参数"),
    makeTable(
      ["参数", "值", "说明"],
      [
        ["分辨率", "640 x 480", "像素"],
        ["传感器尺寸", "4.8 x 3.6 mm", "物理尺寸"],
        ["默认焦距", "12.0 mm", "f_px = 1600"],
        ["FOV (12mm)", "22.6 deg", "水平全视角"],
        ["pixel_size", "7.5 um", "4.8/640"],
        ["px_per_deg (12mm)", "27.9 px/deg", "1600 * pi/180"],
        ["信标检测阈值", "180", "灰度值"],
      ],
      [2800, 2200, CONTENT_W - 5000]
    ),

    heading3("3.3.5 信标检测"),
    p("detect_beacon_centroid(image, threshold=180)：查找灰度 >= threshold 的像素，计算质心 (cx, cy) 和置信度。返回 Detection(found, cx, cy, confidence)。"),
  ];
}

function chapter3_raspi() {
  return [
    heading2("3.4 Raspi 树莓派控制器"),

    heading3("3.4.1 概述"),
    p("Raspi 是闭环控制的核心节点：接收观测，运行控制程序，输出命令。通过三级延时管线模拟真实硬件延迟。"),

    heading3("3.4.2 三级延时管线"),
    p("DelayPipeline 使用三个最小堆实现三级延迟："),
    emptyLine(),
    makeTable(
      ["阶段", "默认延迟", "说明"],
      [
        ["观测获取", "image_read + state_read delay", "从 Runtime 读取观测的延迟"],
        ["图像处理", "image_process_delay = 20ms", "控制程序处理观测的延迟"],
        ["命令发送", "command_tx_delay", "命令传送到 Runtime 的延迟"],
      ],
      [2000, 3500, CONTENT_W - 5500]
    ),
    p("每级可独立配置延迟和抖动（高斯噪声，单侧 max(0, gauss(0, std))）。每帧的观测经过管线后才会被控制程序处理。"),

    heading3("3.4.3 控制程序协议"),
    ...codeLines([
      "class ControlProgram(Protocol):",
      "    def on_tick(self, obs: dict) -> list[Command]: ...",
    ]),
    p("obs 包含 timestamp, target, gimbal, camera, frame。返回 list[Command] 控制设备。"),

    heading3("3.4.4 基线跟踪程序"),
    p("BaselineTrackerProgram 实现简单的比例控制："),
    ...codeLines([
      "pixel_error = det.cx - cx",
      "yaw_rate = clamp(kp * pixel_error, -max_rate, +max_rate)  // kp=0.08 dps/px",
      "若 |pixel_error| < deadband(2px), rate = 0",
      "若目标丢失, rate = lost_target_hold_rate(0)",
    ]),
    makeTable(
      ["参数", "默认值", "说明"],
      [
        ["yaw_rate_kp", "0.08 dps/px", "比例增益"],
        ["max_yaw_rate", "60.0 dps", "角速度限幅"],
        ["deadband", "2.0 px", "死区"],
        ["lost_target_hold", "0.0 dps", "丢失目标保持速率"],
      ],
      [2800, 2000, CONTENT_W - 4800]
    ),
    new Paragraph({ children: [new PageBreak()] }),
  ];
}

function chapter4() {
  return [
    heading1("第 4 章 配置系统设计"),

    heading2("4.1 配置结构"),
    p("config.py 包含 10 个 dataclass 配置类，均为模块级单例："),
    makeTable(
      ["配置类", "实例名", "覆盖范围"],
      [
        ["CameraConfig", "camera_cfg", "分辨率、传感器尺寸、焦距"],
        ["GimbalConfig", "gimbal_cfg", "角度范围、响应时间常数"],
        ["AxisLimitConfig", "axis_limit_cfg", "Pitch 限位、最大角速度"],
        ["LoopConfig", "loop_cfg", "内外环频率"],
        ["ControlPreset", "control_preset_cfg", "PID 参数"],
        ["YawDisplayConfig", "yaw_display_cfg", "航向角显示模式"],
        ["RaspiConfig", "raspi_cfg", "启动延时"],
        ["RaspiDelayConfig", "raspi_delay_cfg", "三级延时参数"],
        ["TargetConfig", "target_cfg", "运动模式与参数"],
        ["SceneConfig", "scene_cfg", "场景、动画、绘图参数"],
      ],
      [2800, 2600, CONTENT_W - 5400]
    ),

    heading2("4.2 MOTION_MODE_PARAMS 注册表"),
    p("为支持运动模式的可扩展性，config.py 定义了 MOTION_MODE_PARAMS 注册表："),
    ...codeLines([
      'MOTION_MODE_PARAMS = {',
      '    "sinusoidal":        ["sin_amplitude_m", "sin_frequency_hz"],',
      '    "constant_velocity": ["velocity_x_mps", "velocity_y_mps"],',
      '    "constant_accel":    [... , "accel_x_mps2", "accel_y_mps2"],',
      '    "random_walk":       ["random_max_accel_mps2", "random_damping", ...],',
      '    "waypoint":          ["waypoints", "waypoint_arrival_radius_m"],',
      '}',
    ]),
    p("Config Editor 自动读取此注册表，切换 motion_type 下拉框时隐藏不属于当前模式的参数。"),

    heading2("4.3 添加新运动模式（4 步）"),
    bullet("1. 在 TargetConfig.motion_type 的 Literal[...] 中加模式名"),
    bullet("2. 在 MOTION_MODE_PARAMS 中加模式 -> 字段映射"),
    bullet("3. 在 TargetConfig 中加新参数字段"),
    bullet("4. 在 TargetKinematics2D.step() 中加 elif 分支实现物理逻辑"),
    p("Config Editor 自动读取 Literal 类型生成下拉选项，并根据 MOTION_MODE_PARAMS 过滤显示对应参数。"),

    heading2("4.4 派生属性"),
    p("CameraConfig 定义了三个 @property 派生属性，在配置变更时自动重新计算："),
    bullet("pixel_size_mm = sensor_w_mm / resolution_w = 0.0075 mm"),
    bullet("focal_length_px = focal_length_mm / pixel_size_mm = 1600 px"),
    bullet("fov_h_deg = 2 * atan(sensor_w_mm / (2 * focal_length_mm)) = 22.6 deg"),
    new Paragraph({ children: [new PageBreak()] }),
  ];
}

function chapter5() {
  return [
    heading1("第 5 章 控制程序开发"),

    heading2("5.1 ControlProgram 协议"),
    ...codeLines([
      "from runtime.types import Command",
      "",
      "class ControlProgram(Protocol):",
      "    def on_tick(self, obs: dict) -> list[Command]: ...",
    ]),

    heading2("5.2 obs 观测字典结构"),
    makeTable(
      ["键", "内容", "类型"],
      [
        ["timestamp", "当前仿真时间", "float"],
        ["target", "{x_m, y_m, bearing_deg, distance_m}", "dict"],
        ["gimbal", "{power_state, mode, yaw_deg_internal, yaw_deg_display, pitch_deg, ...}", "dict"],
        ["camera", "{power_state, f_current_mm, frame_id, in_fov, u_px, v_px}", "dict"],
        ["frame", "FramePacket(image, intrinsics, optional_gt)", "FramePacket"],
      ],
      [1600, 5200, CONTENT_W - 6800]
    ),

    heading2("5.3 Command 命令类型"),
    makeTable(
      ["target", "合法 action"],
      [
        ["gimbal", "power_on, power_off, set_mode, set_angle_target, set_rate_target"],
        ["camera", "power_on, power_off, set_zoom_target_mm, zoom_by, set_zoom_rate_mmps"],
        ["raspi", "power_on, power_off"],
      ],
      [2000, CONTENT_W - 2000]
    ),

    heading2("5.4 自定义控制程序模板"),
    ...codeLines([
      "from runtime.types import Command",
      "from entities.camera.entity import detect_beacon_centroid",
      "",
      "class MyTracker:",
      "    def __init__(self, kp=0.1):",
      "        self.kp = kp",
      "",
      "    def on_tick(self, obs: dict) -> list[Command]:",
      "        ts = float(obs['timestamp'])",
      "        cmds = []",
      "        # 1. 确保 RATE_MODE",
      "        # 2. 从 frame 检测目标",
      "        # 3. 计算像素误差, 比例映射",
      "        # 4. 返回 Command 列表",
      "        return cmds",
    ]),

    heading2("5.5 CLI 注入"),
    ...codeLines([
      "# 命令行注入：格式 module:Class",
      "python app.py --control-program my_tracker:MyTracker --duration 10",
      "",
      "# 代码注入：",
      "from simulation.bootstrap import build_runtime",
      "runtime = build_runtime(control_program=MyTracker())",
    ]),
    new Paragraph({ children: [new PageBreak()] }),
  ];
}

function chapter6() {
  return [
    heading1("第 6 章 仿真运行与工具"),

    heading2("6.1 CLI 参数"),
    makeTable(
      ["参数", "类型", "默认值", "说明"],
      [
        ["--duration", "float", "60.0", "运行时长（秒）"],
        ["--mode", "realtime|offline", '"realtime"', "运行模式"],
        ["--delay-ms", "float", "0.0", "Raspi 链路延时（毫秒）"],
        ["--no-gui", "flag", "False", "不启用窗口，仅控制台输出"],
        ["--control-program", "str", '""', "控制程序 module:Class"],
        ["--target-type", "str", '""', "目标运动类型"],
        ["--waypoints", "str", '""', '航点 "(x,y,s),(x,y,s)"'],
      ],
      [2400, 2200, 1600, CONTENT_W - 6200]
    ),

    heading2("6.2 典型运行场景"),
    ...codeLines([
      "# 无 GUI 快速验证",
      'python app.py --no-gui --mode offline --duration 1.0',
      "",
      "# GUI 实时仿真",
      "python app.py --mode realtime --duration 60",
      "",
      "# 带延时链路",
      "python app.py --mode realtime --duration 30 --delay-ms 20",
      "",
      "# 自定义控制程序",
      "python app.py --no-gui --control-program my_tracker:MyTracker --duration 5",
      "",
      "# 航点轨迹",
      'python app.py --no-gui --waypoints "(100,0,2),(80,30,1.5)" --duration 20',
      "",
      "# 随机运动 + 延时",
      "python app.py --no-gui --target-type random_walk --delay-ms 15 --duration 20",
    ]),

    heading2("6.3 GUI 实时仪表盘"),
    p("仪表盘界面布局（1680x980）："),
    bullet("左侧上方：世界视图（轨迹、云台指向、FOV 扇形）"),
    bullet("左侧下方：时间轴曲线（像素误差、角速度参考、角度误差）"),
    bullet("右侧上方：双视角对比（相机原始帧 vs Raspi 延时观测帧）"),
    bullet("右侧下方：Tab 信息区（核心状态 / 诊断信息）"),
    bullet("控制栏：开始、暂停、重置、保存快照、链路延时设置"),

    heading2("6.4 可视化与调试工具"),
    makeTable(
      ["工具", "调用命令", "说明"],
      [
        ["目标轨迹预览", "python tools/target_preview.py", "2D 动画预览目标运动轨迹"],
        ["3D 相机投影", "python tools/camera_3d_viewer.py", "交互式 3D 针孔模型可视化"],
        ["阶跃响应分析", "python tools/step_response.py", "实时云台控制工作台，分析阶跃响应"],
        ["配置编辑器", "python tools/config_editor.py", "实体导航式 GUI 配置编辑"],
        ["数据录制", "python -m tools.record_session", "仿真运行导出 CSV"],
        ["离线回放", "python -m tools.replay_session", "CSV 回放驱动控制程序"],
      ],
      [2000, 4000, CONTENT_W - 6000]
    ),
    new Paragraph({ children: [new PageBreak()] }),
  ];
}

function chapter7() {
  return [
    heading1("第 7 章 测试与验证"),

    heading2("7.1 测试体系总览"),
    p("项目包含 228 个单元测试 + 4 个集成测试，总计 232 个测试方法："),
    makeTable(
      ["实体 / 层", "测试文件", "测试数"],
      [
        ["Target", "entities/target/tests/test_target_entity.py", "64"],
        ["Gimbal", "entities/gimbal/tests/test_gimbal_entity.py", "63"],
        ["Camera", "entities/camera/tests/test_camera_entity.py", "67"],
        ["Raspi", "entities/raspi/tests/test_raspi_entity.py", "26"],
        ["Tracker", "entities/raspi/tests/test_tracker_program.py", "2"],
        ["集成", "tests/test_gimbal_2axis_core.py", "2"],
        ["集成", "tests/test_digital_twin_runtime.py", "2"],
        ["集成", "tests/test_runtime_api.py", "1"],
        ["集成", "tests/test_pid_tuner_smoke.py", "1"],
        ["合计", "", "228"],
      ],
      [2800, 4800, CONTENT_W - 7600]
    ),

    heading2("7.2 测试覆盖范围"),
    bullet("Target：5 种运动模式 + bearing/distance + Entity 包装 + 边界条件"),
    bullet("Gimbal：电源状态机 + NOT_READY 拒绝 + ANGLE/RATE 模式 + pitch 限位 + yaw wrap + 一阶响应"),
    bullet("Camera：电源状态机 + zoom 控制 + FOV 检查 + 像素映射 + 质心检测 + 帧生成"),
    bullet("Raspi：电源状态机 + 控制程序加载 + 零延时/有延时管线 + backlog + delay profile"),

    heading2("7.3 运行命令"),
    ...codeLines([
      "# 全部实体测试",
      "python -m unittest entities.target.tests.test_target_entity \\",
      "    entities.gimbal.tests.test_gimbal_entity \\",
      "    entities.camera.tests.test_camera_entity \\",
      "    entities.raspi.tests.test_raspi_entity -v",
      "",
      "# 主线回归测试",
      "python -m unittest discover -s tests -v",
      "",
      "# 组装冒烟测试",
      "python app.py --no-gui --mode offline --duration 1.0",
    ]),

    heading2("7.4 通过标准"),
    bullet("所有测试通过（228 单元 + 4 集成 = 232 total）"),
    bullet("无 GUI 冒烟输出连续、无异常终止"),
    bullet("关键字段（yaw/pitch/u/v/in_fov/backlog）正常刷新"),
    new Paragraph({ children: [new PageBreak()] }),
  ];
}

function chapter8() {
  return [
    heading1("第 8 章 代码架构与规范"),

    heading2("8.1 目录结构"),
    ...codeLines([
      "systemSimulation/",
      "+-- app.py                          # 主入口（透传到 simulation.cli）",
      "+-- config.py                       # 统一配置（10 个 dataclass + MOTION_MODE_PARAMS）",
      "+-- simulation/                     # 应用编排层",
      "|   +-- bootstrap.py                # build_runtime / start_stack",
      "|   +-- cli.py                      # 参数解析 + 入口分发",
      "|   +-- headless.py                 # 无 GUI 运行入口",
      "|   +-- worker.py                   # 仿真推进 QThread",
      "|   +-- state_buffer.py             # UI 线程安全缓冲",
      "|   +-- gui/",
      "|       +-- window.py               # 仪表盘主窗口",
      "|       +-- runner.py               # create_dashboard / run_gui",
      "+-- runtime/",
      "|   +-- digital_twin_runtime.py     # 世界时钟 / 命令总线 / 调度器",
      "|   +-- types.py                    # Command / WorldSnapshot / POWER_*",
      "|   +-- clients.py                  # Client 导出",
      "+-- entities/",
      "|   +-- gimbal/                     # entity / model / control / client / tests",
      "|   +-- camera/                     # entity / model / control / client / tests",
      "|   +-- target/                     # entity / model / client / tests",
      "|   +-- raspi/                      # entity / model / pipeline / control_program",
      "+-- tests/                          # 主线回归测试",
      "+-- tools/                          # 可视化与调试工具",
      "+-- docs/                           # 文档",
      "+-- output/                         # 运行产物",
    ]),

    heading2("8.2 设计模式"),
    makeTable(
      ["模式", "应用场景"],
      [
        ["dataclass 配置", "config.py 中 10 个配置类，类型安全 + 自动补全"],
        ["Protocol 接口", "ControlProgram 协议，鸭子类型控制程序"],
        ["Client 代理", "GimbalClient / CameraClient / RaspiClient 封装命令提交"],
        ["观察者回调", "Raspi 通过 submit_cmd 回调注入命令到 Runtime"],
        ["工厂方法", "build_runtime() 一键创建并启动完整运行时"],
        ["注册表模式", "MOTION_MODE_PARAMS 映射运动模式到参数字段"],
      ],
      [2400, CONTENT_W - 2400]
    ),

    heading2("8.3 命名约定"),
    p("参数名使用物理量 + 单位后缀："),
    makeTable(
      ["后缀", "含义", "示例"],
      [
        ["_s", "秒 (seconds)", "boot_delay_s, response_tau_s"],
        ["_hz", "赫兹 (Hz)", "sin_frequency_hz, angle_loop_hz"],
        ["_deg", "度 (degrees)", "pitch_min_deg, angle_max_deg"],
        ["_dps", "度/秒 (deg/s)", "max_velocity_dps, yaw_rate_dps"],
        ["_mm", "毫米 (mm)", "focal_length_mm, sensor_w_mm"],
        ["_m", "米 (meters)", "initial_x_m, sin_amplitude_m"],
        ["_mps", "米/秒 (m/s)", "velocity_x_mps"],
        ["_mps2", "米/秒^2", "accel_x_mps2"],
        ["_px", "像素 (pixels)", "deadband_px"],
      ],
      [1200, 2400, CONTENT_W - 3600]
    ),

    heading2("8.4 维护约定"),
    bullet("新功能优先落在 entities/* 与 runtime/*"),
    bullet("config.py 仅保留主线配置"),
    bullet("修改实体代码时，同步更新对应实体的 README.md"),
    bullet("每次迭代更新 workspace_meta/agent_log.md"),
    emptyLine(),

    // ── 附录 ──
    new Paragraph({ children: [new PageBreak()] }),
    heading1("附录"),

    heading2("A. 核心数据类型"),
    makeTable(
      ["类型", "字段", "说明"],
      [
        ["Command", "target, action, payload, timestamp, source", "控制命令"],
        ["CommandResult", "accepted, code, message", "命令执行结果"],
        ["Detection", "found, cx, cy, confidence", "目标检测结果"],
        ["FramePacket", "timestamp, image, intrinsics, optional_gt", "相机帧数据"],
        ["WorldSnapshot", "timestamp, target, gimbal, camera, raspi", "世界快照"],
      ],
      [2000, 4000, CONTENT_W - 6000]
    ),

    heading2("B. 数值参数汇总"),
    makeTable(
      ["参数", "值", "来源"],
      [
        ["角度外环频率", "50 Hz (dt=20ms)", "LoopConfig"],
        ["角速度内环频率", "200 Hz (dt=5ms)", "LoopConfig"],
        ["被控对象时间常数", "0.03 s", "GimbalConfig"],
        ["Gimbal 启动延时", "1.5 s", "GimbalEntity"],
        ["Camera 启动延时", "0.5 s", "CameraEntity"],
        ["Raspi 启动延时", "1.0 s", "RaspiConfig"],
        ["默认图像处理延时", "0.02 s", "RaspiDelayConfig"],
        ["变焦时间常数", "0.2 s", "ZoomController"],
        ["变焦最大速率", "120 mm/s", "ZoomController"],
        ["场景时间步长", "0.005 s (200 Hz)", "SceneConfig"],
        ["跟踪 kp", "0.08 dps/px", "TrackerTuning"],
        ["跟踪死区", "2.0 px", "TrackerTuning"],
      ],
      [3000, 2200, CONTENT_W - 5200]
    ),
  ];
}

// ── Main ─────────────────────────────────────────────────────────────────────

async function main() {
  const doc = new Document({
    styles: {
      default: {
        document: { run: { font: FONT, size: 24 } },
      },
      paragraphStyles: [
        {
          id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
          run: { size: 36, bold: true, font: FONT },
          paragraph: { spacing: { before: 360, after: 200 }, outlineLevel: 0 },
        },
        {
          id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
          run: { size: 30, bold: true, font: FONT },
          paragraph: { spacing: { before: 280, after: 160 }, outlineLevel: 1 },
        },
        {
          id: "Heading3", name: "Heading 3", basedOn: "Normal", next: "Normal", quickFormat: true,
          run: { size: 26, bold: true, font: FONT },
          paragraph: { spacing: { before: 200, after: 120 }, outlineLevel: 2 },
        },
      ],
    },
    numbering: {
      config: [
        {
          reference: "bullets",
          levels: [{
            level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT,
            style: { paragraph: { indent: { left: 720, hanging: 360 } } },
          }],
        },
      ],
    },
    sections: [
      {
        properties: {
          page: {
            size: { width: PAGE_W, height: PAGE_H },
            margin: { top: MARGIN, right: MARGIN, bottom: MARGIN, left: MARGIN },
          },
        },
        headers: {
          default: new Header({
            children: [new Paragraph({
              alignment: AlignmentType.RIGHT,
              children: [new TextRun({ text: "云台数字孪生仿真系统 - 技术文档", font: FONT, size: 18, color: "999999" })],
            })],
          }),
        },
        footers: {
          default: new Footer({
            children: [new Paragraph({
              alignment: AlignmentType.CENTER,
              children: [
                new TextRun({ text: "- ", font: FONT, size: 18 }),
                new TextRun({ children: [PageNumber.CURRENT], font: FONT, size: 18 }),
                new TextRun({ text: " -", font: FONT, size: 18 }),
              ],
            })],
          }),
        },
        children: [
          // 目录
          new TableOfContents("目录", { hyperlink: true, headingStyleRange: "1-3" }),
          new Paragraph({ children: [new PageBreak()] }),

          // 封面
          ...coverPage(),

          // 第 1 章
          ...chapter1(),

          // 第 2 章
          ...chapter2(),

          // 第 3 章（实体模型）
          heading1("第 3 章 实体模型设计"),
          ...chapter3_target(),
          ...chapter3_gimbal(),
          ...chapter3_camera(),
          ...chapter3_raspi(),

          // 第 4 章
          ...chapter4(),

          // 第 5 章
          ...chapter5(),

          // 第 6 章
          ...chapter6(),

          // 第 7 章
          ...chapter7(),

          // 第 8 章 + 附录
          ...chapter8(),
        ],
      },
    ],
  });

  const buffer = await Packer.toBuffer(doc);
  const outPath = __dirname + "/云台数字孪生仿真系统-技术文档.docx";
  fs.writeFileSync(outPath, buffer);
  console.log("Document generated: " + outPath);
  console.log("Size: " + (buffer.length / 1024).toFixed(1) + " KB");
}

main().catch((err) => {
  console.error("Error:", err);
  process.exit(1);
});
