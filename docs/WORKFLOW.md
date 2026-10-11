# 轻量工作流 v2

本版减少模型读取的重复内容，学校检查频率保持每条学习消息一次。context 无网络；turn 才是学习消息入口。项目开发、Token 咨询不读取学习档案或触发学校检查。各同学从空白档案开始。

## 一条学习消息

1. 运行 .venv/Scripts/python.exe tools/study/light.py turn --course 课程号；不明确课程时省略课程参数。
2. notifications 是全课程范围。失败、errors、scope_limits 必须保留为未检查/待确认。通知队列包含所有已获取的新来源、修改版本、不可见变化与采集限制，不根据关键词自动丢弃“看起来不重要”的内容。
3. 按 pending 队列读取 source 原文，识别教师确认、同学推测、未答复和助手核算。教师说“不考”、时间变更、提交限制以及图片条件必须保留。作业 intro/activity 的图文、附件及 resource/page/book 等链接资料都须实际核读，目录元数据不等于正文。不同版本分别审阅；旧版本不能覆盖新结论，消失不推定删除。
4. 先合并实际结论到最新 state，再 accept 对应 event_id/hash。含图片/附件必须提供实际 media-evidence；媒体无法查看、账号无权限或采集不完整时保持待审。
5. 合并状态使 revision 改变后重取 context，再使用 course_details/teaching_cursor 与所需课件、错题、讨论证据教学。根据当前待做作业要求映射 assignment_focus，不用最高发布章节或平台完成勾选推断掌握。
6. 检查 inbox 的未索引文件，按本人目录规则核读后归档。记录本人的新问题/真实作答，合并去重。学习状态改变或要呈现计划时运行 plan；仅读取通知回执不必在概念追问中重复呈现计划。

每轮没有变化且没有积压时，通知只返回小份回执。首次使用、长时间离线后或重要内容大量改变时，需要完整核读，不能为了目标缩减率跳过。

## 分页与批量读取

命令前缀为 .venv/Scripts/python.exe tools/study/light.py。

- turn/refresh 的 pending 字段已含首批原文，后续用 review 读取；每页最多12条、12000字符，大项标 requires_source_paging，必须用 source 补齐。pending 命令保留轻量目录查询。读完并确认这一批后重新取 review --offset 0，直到 pending_review_count 为0或明确存在待确认阻碍。若暂不确认而连续分页，携带返回的 --queue-version；队列变化会拒绝旧分页，避免跳项。
- source --id post:30 --event 实际版本号 --offset 0 --limit 6000 返回原文。has_more:true 必须继续；事件原文不会因新快照覆盖。
- accept --id 来源 --event 版本 --hash 实际哈希 --evidence 实际核读说明 [--media-evidence 图片附件核读依据]。这不是自动确认老师身份或掌握；不能批量编造核读说明。
- context 的 more 按集合给出 offset 和 total；list --collection materials --course 课程 --offset N --revision 当前版本 可发现所有省略编号。list 支持 --query 搜索、--limit 分页；状态变化须重新开始，不能继续旧页。
- item --collection courses --id 课程 --field orientation 提供未内联字段原文；settings 可按 --id 键名读取。truncated_fields 明示长字段的预览截断，需 item 补全。
- bundle 从标准输入接收1–50项 JSON 请求，避免逐条包装与重复调用。状态请求为 {"collection":"mistakes","id":"实际编号"}；来源请求为 {"source_id":"post:实际编号","event_id":"实际版本"}。可带 offset/limit。完整结果直接返回结构化 data；分页结果继续提供原文和 has_more。
- 已逐项实际核读的一页可用 accept-batch 从标准输入一次提交：[{"id":"来源","event":"版本","hash":"哈希","evidence":"该条核读依据","media_evidence":"如需媒体核读的依据"}]。任一条校验失败整批不写入，不能用批量接口虚构核读。
- inbox 支持 offset/limit，只在本项目计算内容哈希，列出新文件、与 materials.sha256 不同的文件或尚无比对依据的文件；不把已索引路径当成内容不变，不自动移动或修改原件。核读归档时保存 sha256。

每个入口有小输出，不代表整个任务有固定 Token 上限。按题目所需补读，不能把省略当不存在。

## 持久性与失败

学校采集先写 Study/_System/collections/，再更新 latest/last-complete。Python 将每个版本事务性写入 notification-journal.sqlite3 后才清除对应待导入副本。正文、作者、附件元数据、数组顺序、讨论元数据及可见性变化都保留；重复不变采集不产生重复事件。

较早时间戳的未见版本仍入库，标 observed_late，不覆盖较新的当前版本，也不凭迟到快照推断消失。实时采集时间落后于存档时拒绝宣称完整，须校准系统时间后重新检查；核读迟到版本时不可直接覆盖当前要求。快照指纹持久去重，旧数据库自动增表并保留历史事件编号。

合法 JSON 也须通过容器与时间校验；异常队列保留原件，修复后才能继续导入，不把异常响应当成空的成功结果。

SQLite 保存观察到的来源原文与版本，是不可丢弃的本地档案。学习判断和核读回执仍在唯一 state.json。备份整个 Study/，同时保留 JSON 与数据库，不单独复制状态后删除数据库。没有收到的学校内容无法凭空恢复。

日历范围为当前时间起31天：行动事件按 aftereventid 完整分页，同时采集普通课程、本人小组、站点和用户事件。普通日历接口返回完整时间窗，不作50条截断；同ID合并，接口之间原文冲突保留两个版本且标待确认，旧版本媒体同样须核读。未覆盖31天外日历；接口或组权限不足明确标采集不完整。后页失败、论坛数量不符或接口警告时保留已返回的原文。

采集部分失败、超时、损坏快照/数据库或运行失败会记录失败并将考试要求标 needs_review，保留原证据。所有考试入口共用最近刷新结果：刷新失败或输入不是最近成功核验的快照时，exam-profile/同步不能用旧快照恢复为已核读；exam-intake 也不把旧候选标为本轮完整。成功恢复不会自动清除过去的考试待核读标记。考试来源核验同时比较原始图文及附件元数据；旧版仅文本哈希在首次升级后可能要求重新核读一次。scope_limits 即使不使采集失败，也成为持续待审事件并出现在刷新回执。

v1 首次使用会尽可能导入现有 latest/last-complete，匹配原有已核读哈希；导入后按版本回执维护。v1 过去已经覆盖且没有存档的正文无法恢复；新版本不会静默清除这些已观察事件。

turn 始终强制实时刷新。refresh 默认也实时，--cached 仅供使用者明确接受缓存时调用，返回 live_checked:false；不把30分钟有效期当定时任务。没有后台监控。

## 保留功能与依据

daily.py、FSRS、SymPy、考试覆盖和模拟卷引擎继续提供。学校活动状态 progress 仅作辅助；图片有 MCP 内存核读和独立预览入口，见 TOOLS.md。资料原件、同名冲突、题目与答案分离、70%–85%容量和同日15–30分钟复习预算继续沿用。

设计借鉴以下公开项目的思路，未复制其实现或引入在线压缩服务：
- [RTK 输出精简与计量边界](https://github.com/rtk-ai/rtk/blob/develop/docs/guide/resources/savings-explained.md)：压缩返回文本，分开报告输出量与整轮成本。
- [Microsoft Graph delta](https://github.com/microsoftgraph/microsoft-graph-docs-contrib/blob/main/concepts/delta-query-overview.md)：变化游标、删除/不可见记录与完整分页。本项目 Moodle 无同等服务器 delta，仍完整读取后在本地比较。
- [Context7](https://github.com/upstash/context7/blob/master/packages/sdk/README.md)：先定位对象，再按问题读取相关内容。本项目检索完全在本地。

接口范围依据：[Moodle 官方日历实现](https://github.com/moodle/moodle/blob/MOODLE_405_STABLE/calendar/externallib.php)、[本人课程小组接口](https://github.com/moodle/moodle/blob/MOODLE_405_STABLE/group/externallib.php)。新增接口均为只读；学校是否允许调用须由各同学实际登录验证。
