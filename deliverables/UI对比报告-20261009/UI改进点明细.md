# AgentGate UI 对比：51 项改进明细

比较日期：2026-10-09

基线：`/Users/baibo/915-NH-WEB/frontend`
当前：`/Users/baibo/915-HN-AgentGate/frontend`

本地工作区冻结快照（含快照时已存在修改）；不等同于两个纯提交间的差异。

## 汇总

| 功能模块 | 合计 | 新增 | 增强 | 体验调整 |
|---|---:|---:|---:|---:|
| 全局入口与公共体验 | 6 | 2 | 0 | 4 |
| 测评总览 | 3 | 0 | 0 | 3 |
| 测评任务与A/B | 10 | 4 | 4 | 2 |
| 测评集与样本 | 10 | 1 | 4 | 5 |
| 人工标注 | 12 | 7 | 4 | 1 |
| 评估器 | 3 | 1 | 2 | 0 |
| 结果、Trace与分析 | 7 | 2 | 4 | 1 |
| **合计** | **51** | **17** | **18** | **16** |

## 统计口径

以独立用户目的计功能或交互点；同一公共样式/术语全局只计一次；不计纯重构、原有能力、待设计占位。各业务页接入目录按其不同业务用途独立计数。

A/B、稳定性、静态分析、调优、测评集命名/版本/导入导出、多轮与工具/Skill 检查在基线已有，不作为从零新增。图中目录、模版、版本、LLM 证据的演示响应均在对应页脚标注。截图展示交互，持久化与运行语义另结合源码核验，不代表本轮完成所有流程的真实后端验收。

## 逐项明细

### 全局入口与公共体验

#### SH01 行内/行外双模式及空间选择

类型：新增；页面：欢迎登录；PPT：第 4 页。

- 基线：无欢迎页或路由登录守卫，直接进入工作台。
- 当前：新增 token 校验、行内团队/个人空间选择和行外本地登录。
- 基线源码：`/Users/baibo/915-NH-WEB/frontend/src/router/index.ts:1`
- 当前源码：`/Users/baibo/915-HN-AgentGate/frontend/src/views/evaluation/Welcome.vue:27`

#### SH02 登录状态和主动退出

类型：新增；页面：顶部/会话；PPT：第 4 页。

- 基线：顶部显示后端连接状态，无会话退出入口。
- 当前：顶部显示行内空间或行外环境并可登出；token仅驻内存，刷新需重新登录。
- 边界说明：登录功能相关的可见生命周期，独立于录入/目录模式选择。
- 基线源码：`/Users/baibo/915-NH-WEB/frontend/src/layout/EvaluationLayout.vue:17`
- 当前源码：`/Users/baibo/915-HN-AgentGate/frontend/src/layout/EvaluationLayout.vue:19`

#### SH03 统一测评与资产术语

类型：体验调整；页面：全站术语；PPT：第 5 页。

- 基线：评测/测评、数据集/评测集、A/B实验/Test 等混用。
- 当前：统一为测评、测评集、A/B试验，任务中的应用改称被测Agent。
- 边界说明：全局一次计数；各页面改名不再计独立点。
- 基线源码：`/Users/baibo/915-NH-WEB/frontend/src/layout/EvaluationLayout.vue:4`
- 当前源码：`/Users/baibo/915-HN-AgentGate/frontend/src/layout/EvaluationLayout.vue:5`

#### SH04 统一主要操作按钮

类型：体验调整；页面：创建类按钮；PPT：第 21 页。

- 基线：标注/评估器 asset-primary 深绿色覆盖样式，和创建数据集不同。
- 当前：asset-primary 与 primary 共用绿色、字重、内边距和交互态。
- 边界说明：颜色/圆角/字重归为同一统一样式功能点。
- 基线源码：`/Users/baibo/915-NH-WEB/frontend/src/styles/review-assets.scss:128`
- 当前源码：`/Users/baibo/915-HN-AgentGate/frontend/src/styles/main.scss:110`

#### SH05 收紧导航并让状态就近展示

类型：体验调整；页面：工作台框架；PPT：第 5 页。

- 基线：侧栏220px，顶部独立连接徽标，导航组说明占位。
- 当前：侧栏160px；移除导航组说明，连接状态放侧栏底部，正文增加60px横向空间。
- 边界说明：属于版面效率；不能直接声称业务效率提升百分比。
- 基线源码：`/Users/baibo/915-NH-WEB/frontend/src/styles/main.scss:58`
- 当前源码：`/Users/baibo/915-HN-AgentGate/frontend/src/styles/main.scss:58`

#### SH06 收敛弹窗尺寸与滚动

类型：体验调整；页面：弹窗；PPT：第 15 页。

- 基线：通用弹窗最大88vh，创建测评集/新增样本分别1060/1050px。
- 当前：通用最大80vh并约束内部滚动；创建测评集/新增样本均800px，确认框标题/按钮更紧凑。
- 边界说明：需截图核实，较短body可能增加滚动，不将所有尺寸变化自动宣称效率提升。
- 基线源码：`/Users/baibo/915-NH-WEB/frontend/src/styles/revision.scss:202`
- 当前源码：`/Users/baibo/915-HN-AgentGate/frontend/src/styles/revision.scss:239`

### 测评总览

#### T01 时间快捷项与标题一体化

类型：体验调整；页面：总览；PPT：第 5 页。

- 基线：今日/近7天/近30天位于独立工具栏，标题区显示刷新说明
- 当前：时间快捷项移至标题右侧，底部对齐，统一绿色选中态
- 基线源码：`/Users/baibo/915-NH-WEB/frontend/src/views/evaluation/components/OverviewMetrics.vue:64`
- 当前源码：`/Users/baibo/915-HN-AgentGate/frontend/src/views/evaluation/index.vue:330`

#### T02 移除无数据指标占位

类型：体验调整；页面：总览；PPT：第 5 页。

- 基线：五张指标卡包含仅显示—的Token消耗
- 当前：保留四张有数据依据的指标卡，减少无效信息
- 边界说明：删除占位不表示已完成Token用量统计。
- 基线源码：`/Users/baibo/915-NH-WEB/frontend/src/views/evaluation/components/OverviewMetrics.vue:104`
- 当前源码：`/Users/baibo/915-HN-AgentGate/frontend/src/views/evaluation/components/OverviewMetrics.vue:94`

#### T03 最近任务信息紧凑呈现

类型：体验调整；页面：总览；PPT：第 5 页。

- 基线：智能体名称和版本分两行
- 当前：名称与版本同行，主要列不换行
- 基线源码：`/Users/baibo/915-NH-WEB/frontend/src/views/evaluation/index.vue:335`
- 当前源码：`/Users/baibo/915-HN-AgentGate/frontend/src/views/evaluation/index.vue:365`

### 测评任务与A/B

#### T04 任务名称由用户配置

类型：新增；页面：新建与列表；PPT：第 7 页。

- 基线：任务名由Agent/评估模式/短ID拼接，创建时不可填
- 当前：新建增加01任务名称；列表与详情使用配置名；旧记录回退Agent名称+月日
- 边界说明：旧记录日期是月+两位日，10月以后自然为四位数字，并非始终三位。
- 基线源码：`/Users/baibo/915-NH-WEB/frontend/src/views/evaluation/utils/dashboard-data.ts:12`
- 当前源码：`/Users/baibo/915-HN-AgentGate/frontend/src/views/evaluation/components/EvaluationTaskForm.vue:902`

#### T05 接入平台智能体目录级联选择

类型：新增；页面：新建测评任务；PPT：第 7 页。

- 基线：只选登记的本地智能体和内置Demo，云虾填写Git分支地址
- 当前：统一目录查询智能体/分支/版本，abcclaw按分支取版本；无效、空、错误有提示与重试
- 边界说明：当前UI不再单独手选类型；类型来自目录；Token/团队在欢迎登录页统一配置。行内真实网关本次不接触。
- 基线源码：`/Users/baibo/915-NH-WEB/frontend/src/views/evaluation/components/EvaluationTaskForm.vue:566`
- 当前源码：`/Users/baibo/915-HN-AgentGate/frontend/src/views/evaluation/components/AgentTargetPicker.vue:215`

#### T06 平台目标与测评集适配校验

类型：增强；页面：新建测评任务；PPT：第 9 页。

- 基线：未针对平台目标限制业务初始状态和文本输入格式
- 当前：提交前检查平台用例为纯txt且无业务初始状态，指出不兼容数量
- 边界说明：错误分支从源码核验，截图为入口，未发起任务。
- 基线源码：`/Users/baibo/915-NH-WEB/frontend/src/views/evaluation/components/EvaluationTaskForm.vue:389`
- 当前源码：`/Users/baibo/915-HN-AgentGate/frontend/src/views/evaluation/components/EvaluationTaskForm.vue:609`

#### T07 提交异常区分处理

类型：增强；页面：新建测评任务；PPT：第 9 页。

- 基线：提交异常直接String(error)
- 当前：区分读取失败、权限拒绝、创建结果不明；提示先查任务列表避免重复提交
- 边界说明：代码证据；未人为触发业务提交故障。
- 基线源码：`/Users/baibo/915-NH-WEB/frontend/src/views/evaluation/components/EvaluationTaskForm.vue:505`
- 当前源码：`/Users/baibo/915-HN-AgentGate/frontend/src/views/evaluation/components/EvaluationTaskForm.vue:823`

#### T08 任务类型直接切换

类型：体验调整；页面：任务列表；PPT：第 6 页。

- 基线：以状态页签为主，类型藏在下拉框
- 当前：全部/单任务/A/B试验页签直接切换，列表新增独立任务类型列
- 边界说明：旧状态筛选及稳定性类型筛选入口被移除，见观察项。
- 基线源码：`/Users/baibo/915-NH-WEB/frontend/src/views/evaluation/components/TaskList.vue:160`
- 当前源码：`/Users/baibo/915-HN-AgentGate/frontend/src/views/evaluation/components/TaskList.vue:205`

#### T09 时间快捷筛选

类型：新增；页面：任务列表；PPT：第 6 页。

- 基线：只有起止日期范围输入
- 当前：新增今日/近7天/近30天，默认近7天
- 边界说明：当前没有超过30天/全部历史的可见选项，见观察项。
- 基线源码：`/Users/baibo/915-NH-WEB/frontend/src/views/evaluation/components/TaskList.vue:186`
- 当前源码：`/Users/baibo/915-HN-AgentGate/frontend/src/views/evaluation/components/TaskList.vue:190`

#### T10 列表在一屏内紧凑对齐

类型：体验调整；页面：任务列表；PPT：第 6 页。

- 基线：表格最小宽1250，长信息易换行，单任务/A-B得分字号不同
- 当前：固定比例列宽、超长省略+title，行顶端对齐，评估方式纯文本，得分字号一致
- 边界说明：按一组表格可读性优化计1项，不将字号/间距/列宽逐项膨胀。
- 基线源码：`/Users/baibo/915-NH-WEB/frontend/src/views/evaluation/components/TaskList.vue:344`
- 当前源码：`/Users/baibo/915-HN-AgentGate/frontend/src/views/evaluation/components/TaskList.vue:432`

#### T11 删除任务操作

类型：新增；页面：任务列表；PPT：第 6 页。

- 基线：操作列只有导出/取消
- 当前：新增删除，确认不可恢复后调用任务删除接口，并刷新列表
- 边界说明：只审核入口和实现，不执行删除业务数据。
- 基线源码：`/Users/baibo/915-NH-WEB/frontend/src/views/evaluation/components/TaskList.vue:280`
- 当前源码：`/Users/baibo/915-HN-AgentGate/frontend/src/views/evaluation/components/TaskList.vue:99`

#### T12 执行参数按目标适配

类型：增强；页面：新建测评任务；PPT：第 9 页。

- 基线：所有登记bank目标均固定串行/不重试，默认并发2
- 当前：默认并发1；平台目标按能力填写并发和重试，本地贷款/A-B保持限制
- 边界说明：预约、稳定性重复执行原本已有，不计新增。
- 基线源码：`/Users/baibo/915-NH-WEB/frontend/src/views/evaluation/components/EvaluationTaskForm.vue:776`
- 当前源码：`/Users/baibo/915-HN-AgentGate/frontend/src/views/evaluation/components/EvaluationTaskForm.vue:1195`

#### T13 平台同智能体双版本比较

类型：增强；页面：新建测评任务-A/B；PPT：第 8 页。

- 基线：本地登记智能体不支持A/B，主要用内置Demo双版本
- 当前：平台目录共用基线选取，候选同源加载，禁止相同版本；不把并行开发中的本地贷款双版本后台接入计入本次完成项。
- 边界说明：独立A/B结果对比页主要仅术语变化，不另计新增。
- 基线源码：`/Users/baibo/915-NH-WEB/frontend/src/views/evaluation/components/EvaluationTaskForm.vue:622`
- 当前源码：`/Users/baibo/915-HN-AgentGate/frontend/src/views/evaluation/components/EvaluationTaskForm.vue:958`

### 测评集与样本

#### DS01 先命名，再关联智能体

类型：体验调整；页面：创建测评集；PPT：第 15 页。

- 基线：第一步为关联智能体；名称在第二步且位于定义会话区域后。
- 当前：第一步为测评集名称，描述紧随；第二步才关联智能体。
- 边界说明：名称及卡片名称旧版已有，不算新增命名能力。
- 基线源码：`/Users/baibo/915-NH-WEB/frontend/src/views/datasets/components/DatasetCreateForm.vue:277`
- 当前源码：`/Users/baibo/915-HN-AgentGate/frontend/src/views/datasets/components/DatasetCreateForm.vue:274`

#### DS02 降低创建前置条件

类型：增强；页面：创建测评集；PPT：第 15 页。

- 基线：创建必须确认智能体、填写名称描述并至少一个场景标签。
- 当前：只必填名称；描述改为单行选填，场景标签选填，可先建立空测评集。
- 基线源码：`/Users/baibo/915-NH-WEB/frontend/src/views/datasets/components/DatasetCreateForm.vue:233`
- 当前源码：`/Users/baibo/915-HN-AgentGate/frontend/src/views/datasets/components/DatasetCreateForm.vue:233`

#### DS03 关联智能体接入统一目录选择

类型：增强；页面：创建测评集；PPT：第 15 页。

- 基线：以 /bank-targets 为目录，基础编排/工作流/云虾及登记版本选择。
- 当前：接入统一 AgentTargetPicker，沿用登录时的行内/行外模式与个人/团队空间；智能体→分支地址→版本级联，类型由目录识别，按来源匹配历史会话。
- 边界说明：共享目录能力如任务模块已计数，本条仅计测评集页面接入。当前不另选类型/团队：团队在登录时选，类型由目录自动识别。关联控件可操作。
- 基线源码：`/Users/baibo/915-NH-WEB/frontend/src/views/datasets/components/DatasetCreateForm.vue:156`
- 当前源码：`/Users/baibo/915-HN-AgentGate/frontend/src/views/datasets/components/DatasetCreateForm.vue:14`

#### DS04 图谱化查看关联定义

类型：体验调整；页面：创建测评集；PPT：第 13 页。

- 基线：以提示词、Skill/Tool、节点结构三个文本页签显示定义。
- 当前：统一智能体图谱页签，显示 TargetStructure；保留已有会话页签。
- 边界说明：共享图谱组件本体可归到目标分析，不与其他模块重复计组件新增。
- 基线源码：`/Users/baibo/915-NH-WEB/frontend/src/views/datasets/components/DatasetCreateForm.vue:349`
- 当前源码：`/Users/baibo/915-HN-AgentGate/frontend/src/views/datasets/components/DatasetCreateForm.vue:351`

#### DS05 精简基础录入字段

类型：体验调整；页面：新增样本；PPT：第 16 页。

- 基线：顶部含输入字段、样本名称、分类、场景标签四组字段。
- 当前：仅留样本名称；新样本默认 txt 输入和正例，已有数据仍保留原值。
- 基线源码：`/Users/baibo/915-NH-WEB/frontend/src/views/datasets/components/SampleEditor.vue:153`
- 当前源码：`/Users/baibo/915-HN-AgentGate/frontend/src/views/datasets/components/SampleEditor.vue:183`

#### DS06 基本与高级测评项分区

类型：体验调整；页面：新增样本；PPT：第 16、18 页。

- 基线：输入、输出、工具纵向堆叠，Skill 在折叠高级检查里。
- 当前：基本测评项集中输入/期望/规则；高级测评项展示工具和 Skill，其他条件及备注折叠。
- 基线源码：`/Users/baibo/915-NH-WEB/frontend/src/views/datasets/components/SampleEditor.vue:197`
- 当前源码：`/Users/baibo/915-HN-AgentGate/frontend/src/views/datasets/components/SampleEditor.vue:206`

#### DS07 输入与期望并排对照

类型：体验调整；页面：新增样本；PPT：第 16 页。

- 基线：用户输入与 AI·期望输出上下排列。
- 当前：用户输入与 System·期望输出左右并排，仍可切换 JSON。
- 基线源码：`/Users/baibo/915-NH-WEB/frontend/src/views/datasets/components/SampleEditor.vue:197`
- 当前源码：`/Users/baibo/915-HN-AgentGate/frontend/src/views/datasets/components/SampleEditor.vue:208`

#### DS08 将输出路径及评估方式直接暴露

类型：增强；页面：新增样本；PPT：第 17 页。

- 基线：完整输出等于规则隐藏在主期望区，其他规则经高级检查→添加期望配置。
- 当前：基本区直接显示输出路径/评估方式，支持增加多行和删除且至少留一行；去掉检查名称等冗余。
- 边界说明：多条期望旧版已有，本次计简化配置及约束，不计规则枚举新增。新建多行共享顶部期望输出，不能写成每行独立期望值。
- 基线源码：`/Users/baibo/915-NH-WEB/frontend/src/views/datasets/components/ExpectationEditor.vue:102`
- 当前源码：`/Users/baibo/915-HN-AgentGate/frontend/src/views/datasets/components/ExpectationEditor.vue:122`

#### DS09 支持导入并保留执行路径检查

类型：增强；页面：导入/编辑样本；PPT：第 19 页。

- 基线：导入类型白名单不含 execution_path，相关样本报未知期望类型。
- 当前：支持 workflow/tool/skill 执行路径校验；编辑器可展开查看原始检查，保存保留。
- 边界说明：UI 支持接入新契约；不计后台算法。
- 基线源码：`/Users/baibo/915-NH-WEB/frontend/src/views/datasets/utils/sample-import.ts:205`
- 当前源码：`/Users/baibo/915-HN-AgentGate/frontend/src/views/datasets/utils/sample-import.ts:39`

#### DS10 可清理仅草稿的整个测评集

类型：新增；页面：测评集列表→删除；PPT：第 20 页。

- 基线：仅删除草稿；整个记录删除显示接口不支持。
- 当前：无已发布版本时可删除整个记录，二次确认；含发布版本仍只允许删草稿。
- 边界说明：不执行删除，仅打开对话框。
- 基线源码：`/Users/baibo/915-NH-WEB/frontend/src/views/datasets/index.vue:964`
- 当前源码：`/Users/baibo/915-HN-AgentGate/frontend/src/views/datasets/index.vue:100`

### 人工标注

#### AN01 V1、V2 模版独立入口与详情/标注分流

类型：新增；页面：模板列表 / 创建模板；PPT：第 21 页。

- 基线：单一创建标注模板入口，卡片点击进入标注。
- 当前：保留 V1 并新增 V2 创建入口；V2 卡片展示版本标识、模版详情和开始标注两个明确动作。
- 基线源码：`/Users/baibo/915-NH-WEB/frontend/src/views/evaluation/components/AnnotationAssets.vue:505`
- 当前源码：`/Users/baibo/915-HN-AgentGate/frontend/src/views/evaluation/components/AnnotationAssets.vue:861`

#### AN02 关联精确 Agent、分支、版本并按登录模式读取目录

类型：增强；页面：创建模板；PPT：第 22 页。

- 基线：/bank-targets 的单一关联智能体下拉；模板只保存 agent 引用，未让用户选分支版本。
- 当前：通过统一目录选择智能体、分支和版本；团队/个人空间在登录时确定，类型由目录识别。行内/行外数据源分流，按精确版本筛选待标注会话。
- 基线源码：`/Users/baibo/915-NH-WEB/frontend/src/views/evaluation/components/AnnotationAssets.vue:658`
- 当前源码：`/Users/baibo/915-HN-AgentGate/frontend/src/views/evaluation/components/AnnotationAssets.vue:1048`

#### AN03 按标注对象开关配置维度与标签

类型：新增；页面：创建 V2 模版；PPT：第 22 页。

- 基线：消息评分与工具评分两块固定展示，默认评分范围 0—5。
- 当前：测评集、评估器、智能体三类对象可勾选展开各自维度/标签；V2 默认 0—100。智能体执行页仍待设计，不计为已完成的智能体标注。
- 基线源码：`/Users/baibo/915-NH-WEB/frontend/src/views/evaluation/components/AnnotationAssets.vue:680`
- 当前源码：`/Users/baibo/915-HN-AgentGate/frontend/src/views/evaluation/components/AnnotationAssets.vue:1077`

#### AN04 以任务、综合分、测评时间建立会话上下文

类型：增强；页面：V2 会话列表；PPT：第 23 页。

- 基线：会话名称、标注状态、消息数、进度、创建时间。
- 当前：显示测评任务、会话名称、综合分、标注状态、测评时间；去除消息数和进度冗余，操作列位于末尾。
- 基线源码：`/Users/baibo/915-NH-WEB/frontend/src/views/evaluation/components/AnnotationAssets.vue:777`
- 当前源码：`/Users/baibo/915-HN-AgentGate/frontend/src/views/evaluation/components/AnnotationV2Workspace.vue:82`

#### AN05 列头按需筛选、分数区间与 Bad Case 直达

类型：增强；页面：V2 会话列表；PPT：第 23、24 页。

- 基线：页面常驻会话名称搜索框和标注状态下拉。
- 当前：各列通过过滤图标弹出控件；支持任务、名称、综合分区间/Bad Case、状态、时间，并有单列小叉清空及全局清空。
- 基线源码：`/Users/baibo/915-NH-WEB/frontend/src/views/evaluation/components/AnnotationAssets.vue:761`
- 当前源码：`/Users/baibo/915-HN-AgentGate/frontend/src/views/evaluation/components/AnnotationV2Workspace.vue:266`

#### AN06 明确免标注与恢复标注动作

类型：体验调整；页面：V2 会话列表；PPT：第 23 页。

- 基线：行内跳过会话 / 恢复会话，状态为已跳过。
- 当前：操作统一为开始标注、免标注；支持恢复标注，列表及概览直接显示免标注状态。
- 基线源码：`/Users/baibo/915-NH-WEB/frontend/src/views/evaluation/components/AnnotationAssets.vue:820`
- 当前源码：`/Users/baibo/915-HN-AgentGate/frontend/src/views/evaluation/components/AnnotationV2Workspace.vue:380`

#### AN07 按轮次/对象组织左右对照标注

类型：增强；页面：V2 会话标注详情；PPT：第 25 页。

- 基线：每轮用户输入、实际回答与消息评分并排；评语为多行，原始期望未展示。
- 当前：按勾选对象在每轮组织标注区；测评集区左侧同时呈现输入、实际、期望，右侧评分/标签/单行评语/修订期望，评分框收窄。
- 基线源码：`/Users/baibo/915-NH-WEB/frontend/src/views/evaluation/components/AnnotationAssets.vue:866`
- 当前源码：`/Users/baibo/915-HN-AgentGate/frontend/src/views/evaluation/components/AnnotationV2Editor.vue:139`

#### AN08 工具评分落到真实调用证据与规则期望

类型：新增；页面：V1 会话标注详情；PPT：第 26 页。

- 基线：模板可配置工具评分维度，但会话页只渲染消息评分；没有逐调用工具标注区。
- 当前：展示真实 Trace 的工具参数/返回值/所属轮次，逐调用评分/标签/评语；可配置必须或禁止调用及参数匹配规则。
- 基线源码：`/Users/baibo/915-NH-WEB/frontend/src/views/evaluation/components/AnnotationAssets.vue:866`
- 当前源码：`/Users/baibo/915-HN-AgentGate/frontend/src/views/evaluation/components/AnnotationAssets.vue:1461`

#### AN09 规则评估器证据、结果、关键代码联动折叠

类型：新增；页面：V2 评估器人工标注；PPT：第 27 页。

- 基线：没有对本次实际评估器的人工审阅表单。
- 当前：列出运行配置的每个评估器；规则默认折叠，展开后左右同时展示期望/实际证据、结果、当前实现关键代码与人工评分。
- 基线源码：`/Users/baibo/915-NH-WEB/frontend/src/views/evaluation/components/AnnotationAssets.vue:866`
- 当前源码：`/Users/baibo/915-HN-AgentGate/frontend/src/views/evaluation/components/EvaluatorAnnotation.vue:33`

#### AN10 LLM 实际提示词/证据/响应与优化提示词录入

类型：新增；页面：V2 评估器人工标注；PPT：第 28 页。

- 基线：没有本次 LLM 评估请求和完整响应的人工审阅入口。
- 当前：显示系统提示词、请求证据、评估结果、完整响应，并区分实际留存与重建来源；右侧录入优化提示词随标注保存。
- 基线源码：`/Users/baibo/915-NH-WEB/frontend/src/views/evaluation/components/AnnotationAssets.vue:866`
- 当前源码：`/Users/baibo/915-HN-AgentGate/frontend/src/views/evaluation/components/EvaluatorAnnotation.vue:56`

#### AN11 人工标注导出新测评集草稿

类型：新增；页面：标注详情 / 测评集反馈；PPT：第 29 页。

- 基线：标注仅在浏览器保存，未提供测评集出口。
- 当前：V1、V2 均可将已保存标注转换为新测评集草稿；V2 操作位于测评集标注区底部，含预览及目标跳转。
- 基线源码：`/Users/baibo/915-NH-WEB/frontend/src/views/evaluation/components/AnnotationAssets.vue:903`
- 当前源码：`/Users/baibo/915-HN-AgentGate/frontend/src/views/evaluation/components/AnnotationV2Feedback.vue:126`

#### AN12 修订期望回写原测评集草稿

类型：新增；页面：标注详情 / 测评集反馈；PPT：第 29 页。

- 基线：人工期望只是本地标注字段，未影响后端样本期望。
- 当前：已保存人工期望可预览并回写原测评集草稿；校验输入/轮次/样本存在性及草稿变化，发布版本保持不变。
- 基线源码：`/Users/baibo/915-NH-WEB/frontend/src/views/evaluation/components/AnnotationAssets.vue:891`
- 当前源码：`/Users/baibo/915-HN-AgentGate/frontend/src/views/evaluation/components/AnnotationV2Feedback.vue:77`

### 评估器

#### EV01 LLM 设计保存为后端可恢复草稿

类型：增强；页面：LLM 评估器设计；PPT：第 30 页。

- 基线：保存 UX 设计只更新页内数组；页面明确提示刷新后清除。
- 当前：保存完整名称、描述、模型、范围、阈值、维度提示词及权重到后端；重新进入可继续编辑草稿，列表显示草稿状态。
- 基线源码：`/Users/baibo/915-NH-WEB/frontend/src/views/evaluation/components/JudgeSystem.vue:161`
- 当前源码：`/Users/baibo/915-HN-AgentGate/frontend/src/views/evaluation/components/JudgeSystem.vue:226`

#### EV02 发布启用后可参与真实评估

类型：新增；页面：LLM 评估器设计 / 测评配置；PPT：第 31 页。

- 基线：自建设计仅 UI 草稿，不能从设计直接成为可选择的已发布评估器。
- 当前：发布并启用生成真实定义版本，维度提示词与权重写入 answer_quality@2，已发布启用版本可打开测评配置。
- 基线源码：`/Users/baibo/915-NH-WEB/frontend/src/views/evaluation/components/JudgeSystem.vue:397`
- 当前源码：`/Users/baibo/915-HN-AgentGate/frontend/src/views/evaluation/components/JudgeSystem.vue:259`

#### EV03 发布版本与运行配置可追溯

类型：增强；页面：LLM 版本历史；PPT：第 31 页。

- 基线：UX 版本历史是本页数组中的临时设计历史，刷新清除。
- 当前：从后端查询发布版本，查看只读配置和内容指纹；编辑已发布版本先建立新版本草稿，保留历史。 任务配置页还展示运行时固定的维度、权重与提示词。
- 基线源码：`/Users/baibo/915-NH-WEB/frontend/src/views/evaluation/components/JudgeSystem.vue:436`
- 当前源码：`/Users/baibo/915-HN-AgentGate/frontend/src/views/evaluation/components/JudgeSystem.vue:317`

### 结果、Trace与分析

#### T14 展示实际评估器得分

类型：增强；页面：任务结果；PPT：第 10 页。

- 基线：LLM按rubric拆列但独立维度分数均显示—
- 当前：按评估器列展示实际score，详情明确“评估器得分”
- 基线源码：`/Users/baibo/915-NH-WEB/frontend/src/views/evaluation/utils/task-report.ts:3`
- 当前源码：`/Users/baibo/915-HN-AgentGate/frontend/src/views/evaluation/utils/task-report.ts:3`

#### T15 任务详情直达Skill静态分析

类型：新增；页面：任务结果；PPT：第 10 页。

- 基线：任务结果仅样本结果/任务配置两页签
- 当前：增加Skill静态分析页签，锁定本任务对象
- 基线源码：`/Users/baibo/915-NH-WEB/frontend/src/views/evaluation/components/TaskResults.vue:269`
- 当前源码：`/Users/baibo/915-HN-AgentGate/frontend/src/views/evaluation/components/TaskResults.vue:280`

#### T17 单轮多轮统一导航

类型：体验调整；页面：样本详情；PPT：第 11 页。

- 基线：仅多轮展示轮次目录/轮次标题
- 当前：单轮也显示目录与第1轮，布局统一
- 基线源码：`/Users/baibo/915-NH-WEB/frontend/src/views/evaluation/components/TaskResults.vue:476`
- 当前源码：`/Users/baibo/915-HN-AgentGate/frontend/src/views/evaluation/components/TaskResults.vue:500`

#### T18 执行图与完整Trace JSON联动

类型：新增；页面：样本详情；PPT：第 12 页。

- 基线：展示会话与评分，缺少专门执行图及完整JSON查看器
- 当前：新增环节层级、类型、状态、耗时图；点击定位只读JSON，支持搜索/折叠
- 边界说明：按完整Trace排障能力计1项；模拟轨迹有明确标识，不代表真实线上全链路数据。
- 基线源码：`/Users/baibo/915-NH-WEB/frontend/src/views/evaluation/components/TaskResults.vue:591`
- 当前源码：`/Users/baibo/915-HN-AgentGate/frontend/src/views/evaluation/components/TraceExplorer.vue:132`

#### T19 工作流按执行关系分层展示

类型：增强；页面：智能体图谱；PPT：第 13 页。

- 基线：按节点kind排成列，不区分工作流执行类型/条件
- 当前：DAG分层、箭头方向、分支条件，节点区分LLM/规则/工具/起止；循环图回退关系展示
- 边界说明：本项只评价可视化表达，拓扑完整性依赖接口描述符。
- 基线源码：`/Users/baibo/915-NH-WEB/frontend/src/views/evaluation/components/TargetStructure.vue:62`
- 当前源码：`/Users/baibo/915-HN-AgentGate/frontend/src/views/evaluation/components/TargetStructure.vue:73`

#### T20 约束有效分析对象

类型：增强；页面：Skill静态分析；PPT：第 14 页。

- 基线：有1个Skill也可运行职责比较
- 当前：至少2个Skill才允许分析，明确不适用提示
- 边界说明：原有分析能力不计新增，仅计适用性校验增强。
- 基线源码：`/Users/baibo/915-NH-WEB/frontend/src/views/evaluation/components/UpstreamAnalysis.vue:195`
- 当前源码：`/Users/baibo/915-HN-AgentGate/frontend/src/views/evaluation/components/UpstreamAnalysis.vue:195`

#### T21 分析依据和覆盖范围透明

类型：增强；页面：Skill静态分析；PPT：第 14 页。

- 基线：只有发现项列表和复核输入
- 当前：增加模型名、完成比较组数、两两Skill关系与置信度，声明职责分析边界
- 边界说明：本次不启动付费模型分析；需已有报告或明确样例响应才能截图表格。
- 基线源码：`/Users/baibo/915-NH-WEB/frontend/src/views/evaluation/components/UpstreamAnalysis.vue:412`
- 当前源码：`/Users/baibo/915-HN-AgentGate/frontend/src/views/evaluation/components/UpstreamAnalysis.vue:415`

## 未计入改进的待补齐项

- 任务列表缺少全部历史、任意日期和状态筛选，选择框缺少配套批量导出入口。
- 人工标注模版与记录仍保存在 localStorage；智能体标注的执行区域仍为待设计。
- 测评集关联信息、图标与场景标签不随创建请求持久化。
- execution_path 导入预览的期望检查计数遗漏；多条输出检查共享顶部期望输出文本。
- 部分历史 Trace 缺少规范化参数和返回值；规则关键代码来自当前实现，非历史运行源码快照。
- 行内网关及真实 LLM 连通与运行应在具备权限的环境中单独验收。

## 证据包内容

同目录的“UI对比_证据包.zip”包含本报告用到的原始截图、逐页截图映射、功能点清单、源文件哈希与截图场景说明。截图完整原件用于复核，PPT只截取与说明相关的区域。原件可能保留无关的演示环境提示，不将其算作产品差异。源码位置对应冻结时刻，后续工程修改可能导致原路径行号变化。
