---
name: moodle-study-light
description: 在独立的 Moodle 学习项目中核读学校变化，按课程教学、维护真实学习记录和考试练习；适用于日常学习消息，不用于触发开发咨询的学校同步。
---

# Moodle 学习轻量模式

定位用户指定项目后读取其 AGENTS.md；技能安装目录不是个人学习目录。只使用本项目本人资料与连接。

每条学习消息含追问，使用 tools/study/light.py turn，已知课程加 --course。它实时检查学校、保存每个观察到的来源版本，返回全课程待审与本科上下文。项目开发咨询不触发学校访问。context 只是本轮补读入口；缓存须用户明确接受。

先核读 notifications 中全课程 pending；turn/review 提供原文，大项用 source/bundle 分页，实际核对教师身份与媒体，合并真实结论后按 event_id 和 hash 确认。失败、不可见、无法查看的媒体保持待确认。确认一页后从 offset 0 继续，不能略过其他课程或历史版本。

教学保留课程画像、教师方法、实际教学位置、题设限定和原页证据。上下文的 more/inline:false/truncated_fields 都有补读入口，不能当完整审阅。真实独立作答才建立掌握证据。

按需读取：[工作流](docs/WORKFLOW.md)处理队列和分页；[工具协议](docs/TOOLS.md)处理作答、复习、媒体与活动状态；[考试流程](docs/EXAM_PREP.md)处理模拟卷与批改。保留同日复习预算及本人授权边界，不附加邮件、学校写入或公开发布。
