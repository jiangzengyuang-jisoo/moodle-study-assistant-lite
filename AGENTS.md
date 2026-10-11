# HKU 学习轻量模式

每位同学独立初始化，只读写本项目本人资料。Study/_System/state.json 是学习状态；setup.cmd 后由本人登录选课。不读取作者或其他工作区的数据。

- 默认中文，先回答当前问题。项目开发/设置咨询不触发学校读取。
- **每条学习消息（含追问）先运行** .venv/Scripts/python.exe tools/study/light.py turn --course 课程号；课程不明则不传 --course。它强制实时采集、持久记录变化、返回全课程待审入口与本科上下文；不设后台任务。context 仅供本轮补读，缓存仅在用户明确接受时使用。
- 先处理 notifications：失败或权限限制明确标待确认；全课程 pending 必须逐页核读，不能只看本科、第一页或 changed_count。turn 首批已含原文，后续用 review；requires_source_paging 时 source --event 版本 --id 来源 分页。可用 bundle 批量补读。未读版本一直保留。
- 核对教师角色、正文限定、嵌图和附件。图片用 study_forum_image（discussionid、postid、index、expected_src）或本校浏览器实际查看；无法查看保持待审。核读并合并状态后 accept --event 版本 --id 来源 --hash 哈希 --evidence 核读说明；含媒体还须 --media-evidence。确认一页后重新取 review --offset 0；保留分页时传 --queue-version 防止跳项。不可见不等于删除。observed_late 须核对时间，不能覆盖较新的要求；目录链接资料也须实际核读正文。
- 教学使用 course_details、teaching_cursor、相关 discussion_notes/本人卡点及课件原页。detail_fields 中 inline:false 用 item 补读；more 给出 list 的 offset，带当前 --revision 继续分页。truncated_fields/has_more 不代表已读完。不整份载入状态或采集快照。
- 推进章节依当前待做作业范围，保留实际教学位置。提交、小组代交、纸面完成与掌握分开；讲过/看答案不等于独立掌握。学科问题与真实错误去重记入本科错题本。
- turn 的 inbox 提示新资料；按 settings.course_folder_policy 核对内容与同名冲突后归档，保留原件。学校活动状态仅辅助定位，用 tools/moodle/run.mjs progress 按需查询，不推断掌握。
- 状态修改用安全保存接口，写前重读、保留上一版，串行写入。合并学习变化后运行 light.py plan；呈现计划前也运行 plan 校验日期版本。复习保持同日总预算，按真实容量安排。
- 实际作答/曝光/反馈读 docs/TOOLS.md；考试任务读 docs/EXAM_PREP.md；持久队列、分页和迁移细节读 docs/WORKFLOW.md。无关说明不预加载。
- 不读取凭据或浏览器 Cookie；不提交、不发帖、不发邮件、不自动下载课程文件。明确授权后才使用指定资料下载入口。notification-journal.sqlite3 是来源版本档案，随 Study/ 备份，不当缓存删除。
