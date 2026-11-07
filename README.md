# DOL_translation

《大航海时代 Online》日服的实验性原位中文替换工具。直接在游戏生成字形前替换文本，不依赖 OCR。可选本地模型或 DeepSeek API 自动翻译任务。

**这不是全程汉化成品。** 未收录的文字仍显示原文。它目前实现的是“读到文字 → 本地精确匹配 → 在原对话框生成中文”，以及词库热更新和漏译记录。

## 当前能力与验证边界

- 32 位原生模块，在字形生成前替换选项和对话正文。
- JSON 补译编译为 UTF-16 二进制词库；后台约每秒检查更新。
- 未命中的日文在本机去重记录；单独启动任务自动翻译后，可选择本地模型或 DeepSeek API。
- DLL 不在加载入口中自动安装钩子；加载器明确调用安装函数。
- 检查客户端 SHA-256 和目标函数前导字节，版本不符时拒绝安装。
- 不修改游戏 EXE 或资源文件。模块仅对当前游戏进程生效，重启后需要重新加载。

开发过程已在一个日服客户端验证了选项、船只重造/解体说明正文的中文显示；测试记录也曾出现“只翻译三个选项”的覆盖不足情况，因此**不能用词库数量证明汉化覆盖率**。本仓库是整理后的可复现实现，还需要更多内容和长期稳定性验证。

当前只支持以下客户端指纹：

| 项目 | 值 |
| --- | --- |
| 主模块 | `GVOnline.bin`（x86） |
| 版本线索 | 12.038 |
| SHA-256 | `ef9aa7a832c5ecf874238f2e4b5d185cdb6c8d26b14cba7102d98dbfc82116ae` |
| 字形生成函数 RVA | `0x663a50` |

更新游戏后不要直接改哈希来绕过检查；需要重新定位函数并核对调用约定。

## 使用发行包

从本仓库 Releases 下载运行压缩包，解压到独立目录。无需放进游戏安装目录。

1. 正常启动游戏并登录。
2. 双击 `加载汉化.cmd`，在 Windows UAC 窗口确认权限。
3. 关闭并重新打开 NPC 对话或菜单，查看中文。
4. 每次重启游戏后重新加载一次。若已安装另一份/旧版模块，先退出游戏再切换。

`停用汉化.cmd` 关闭本次进程的翻译；重新打开对话后生效。模块固定驻留以防止仍在执行的回调被卸载，完全退出游戏才会移除它。

## 任务自动翻译（实验性）

1. 运行 DeepSeek 模式前，双击 `设置DeepSeek密钥.cmd`，输入自己的 API 密钥。密钥使用 Windows 当前账户加密，文件不应分享。
2. 本地模式需要安装并启动 Ollama：分别执行 `ollama pull demonbyron/HY-MT1.5-1.8B` 或 `ollama pull qwen2.5:7b`。混元模型需要较新版本 Ollama。
3. 启动并登录游戏，双击 `启动任务自动翻译.cmd`，选择 DeepSeek、混元 1.8B 或 Qwen 7B，并保持窗口打开。DeepSeek 模式使用 `deepseek-flash`，关闭思考模式，调用费用由 API 账户承担。
4. 打开任务详情，等待后台完成翻译，然后关闭并重新打开窗口。已有缓存会直接匹配，自动译文保存在 `dictionaries/supplement-000-auto.json`；人工词库优先。重新打开未必触发新的显示日志，翻译失败时可能需要重启游戏和自动翻译程序。

**隐私与准确性：**任务识别仅基于文字长度、换行和前后顺序，无法可靠区分任务与其他文字，DeepSeek 模式可能上传符合条件的聊天或玩家名称；本地模式不调用 DeepSeek。原始日志及自动词库可能含个人信息，默认不进入 Git 或发行包。机器译文可能误译地名、数量和条件，任务标题关联也可能出错。首次翻译后不会自动刷新已排版页面。

本工具会向游戏加载 DLL 并设置一个原生函数钩子，可能与客户端或其他模块不兼容、造成闪退。它不包含登录、自动操作或修改服务器数据的逻辑。

## 词库和持续补译

发行包只附基础验证词条及本项目的公开补译。**不附带私人自动缓存、第三方汉化词库或游戏文件。** 玩家名、尚未收录的剧情等可能保持日文。

编辑 `dictionaries/supplement-*.json`，例如：

```json
{
  "船型式とは？": "什么是船型？",
  "次の質問へ": "查看其他问题"
}
```

安装 Python 3.10+ 后运行 `更新词库.cmd`，或：

```powershell
.\scripts\Update.ps1 -Python python
```

同一会话内无需重启游戏；等待约一秒，再重新打开对话。**已经生成的旧文字不会自动重新排版。** DLL 升级仍需重启游戏。

漏译在 `bin/missing-text.jsonl`（源码构建时为 `build/bin/missing-text.jsonl`）中记录，可能包含 NPC 文本、菜单、玩家聊天和名字。日志保存在本机；使用 DeepSeek 自动翻译时，筛选出的文字会发送到 DeepSeek。发布前不要直接提交日志。队列繁忙时允许丢弃记录，以免阻塞显示。每次会话最多记录 10,000 个不同文本。

词库使用精确匹配。游戏可能拆行、添加冒号或展开变量；完整段落译文不一定能命中最终显示片段。工具会生成冒号变体，但不会进行不受控的模糊替换。

## 从源码构建

需要 Windows、Visual Studio 2022 或更新版本的 C++ 工具（含 x86 编译器与 Windows SDK）、Python 3.10+。无需额外 Python 包。MinHook v1.3.4 源码已随仓库附带。

```powershell
.\build.ps1 -Python python
```

脚本自动寻找 Visual Studio 和 SDK，执行 Python 测试、32 位调用约定/日志/热更新测试、DLL 宿主保护测试，输出 `build/bin`。构建过程不会连接游戏。

如需从自己持有的 JSON 词库导入基础译文，仅在本地操作：

```powershell
python tools/import_private_dictionary.py --input X:\local\dictionary.json --output dictionaries/private-base.json
.\build.ps1 -BaseDictionary "$PWD\dictionaries\private-base.json"
```

基础词库受编译时摘要约束，修改后必须重新构建 DLL；日常补译请使用可热更新的 `supplement-*.json`。私有词库默认被 Git 忽略；若自制发行包包含其他人的译文，分发前需要确认相应权利。

构建运行压缩包：

```powershell
python tools/package.py
```

## 实现结构

```text
src/                  原生字形钩子、后台记录、热更新、显式加载器
dictionaries/         基础验证词库与本项目补译
tools/dictionary.py   JSON → UTF-16 二进制，校验及原子发布
scripts/              加载、停用、更新入口
tests/                独立词库测试；原生测试位于 localizer.cpp 的测试分支
third_party/minhook/  固定版本依赖及原始许可证
docs/architecture.md  调用路径、文件格式与限制
```

源代码采用 MIT 许可证；MinHook 使用其原始 BSD 许可证，见 `THIRD_PARTY_NOTICES.md`。游戏及第三方译文的权利不属于本项目许可证范围。
