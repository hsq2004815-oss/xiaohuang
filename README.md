# 小黄 / XiaoHuang

小黄是一个 Windows 桌面 AI 语音助手原型，目标是逐步发展为本地桌面 Agent。

## 当前能力

- 语音唤醒：openWakeWord / STT 文本唤醒路径
- 本地语音识别：FunASR / SenseVoiceSmall，独立 STT server
- 大模型回复：DeepSeek API，可回退本地规则回复
- 语音播报：edge-tts
- 桌面浮窗：PySide6 透明音波状态 UI
- Web 控制面板：启动、停止、重启、状态查看、文本对话历史
- 诊断能力：日志目录打开、诊断 TXT 导出、启动失败诊断、启动前检查
- Runtime Event Stream：记录关键运行事件，辅助排查问题

## 当前阶段

当前项目已经不是 V0.1 音频链路 Demo，而是 V1.5 系列 Windows 桌面 AI 助手原型。

近期关键能力包括：

- PySide6 透明语音浮窗
- GPU STT server 配置
- 控制面板诊断导出
- Runtime Event Stream
- 启动失败诊断
- 启动前检查
- 文本对话历史持久化：当前选中对话通过 `conversation_id` 明确传给后端，普通 LLM 会话仍沿用旧 `session_id` 逻辑
- LLM 配置安全摘要：控制面板可显示 `config_path`、provider/model、key 是否存在，不显示真实 API key
- 对话清理：支持清空单个对话消息，也支持一键清除所有本地对话历史和绑定任务记录

## 下一步方向

下一阶段建议继续收敛控制面板代码边界，避免把对话历史、Multica 绑定、LLM 配置诊断继续塞进单个 web service。

此前 V1.4-A Local Command Router MVP 的方向仍成立：

V1.4-A Local Command Router MVP

目标是让小黄通过语音执行少量安全白名单工具，例如：

- 打开日志目录
- 运行启动前检查
- 导出诊断信息
- 查看当前状态
- 打开控制面板

第一阶段不开放任意 shell、不做文件删除、不让大模型自由执行系统命令。

## 本地运行提示

项目主要在 Windows + Python 3.10 环境下开发。

常用路径示例：

```powershell
cd E:\Projects\xiaohuang
$env:PYTHONPATH="E:\Projects\xiaohuang\src"
$env:PYTHONDONTWRITEBYTECODE="1"
```

常用验证：

```powershell
& "F:\for_xiaohuang\conda310\python.exe" -m compileall -q src scripts tests
& "F:\for_xiaohuang\conda310\python.exe" -m unittest discover -s tests
& "F:\for_xiaohuang\conda310\python.exe" scripts\voice_overlay.py --help
& "F:\for_xiaohuang\conda310\python.exe" scripts\control_panel_web.py --help
```

## 注意

不要提交本地运行文件、日志、录音、TTS 输出、模型缓存和密钥文件。

本地对话历史数据库位于 `data/conversations/`，属于运行数据，不提交。
