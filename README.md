# Minecraft Mod 版本检测工具 v2

一个学习 PCL2 模组匹配逻辑的 Minecraft 模组版本检测工具，支持 CurseForge 和 Modrinth 双平台。

## 功能特性

- ✅ **Hash 精确匹配**
  - CurseForge: MurmurHash2 算法
  - Modrinth: SHA1 算法
- ✅ **智能缓存机制**
  - 缓存有效期：6 小时
  - 减少重复 API 调用
- ✅ **并行查询优化**
  - 同时查询 CurseForge 和 Modrinth 两个平台
  - 提高查询效率
- ✅ **精确版本匹配**
  - 支持所有 Minecraft 版本格式（包括 26.1）
  - 检查项目是否支持目标版本，而非仅检查当前文件
- ✅ **项目版本支持检查**
  - 使用 Modrinth API: `GET /project/{id|slug}/version`
  - 获取项目所有版本，手动检查 `game_versions` 字段
  - 确保模组项目支持目标 Minecraft 版本
- ✅ **可配置的日志系统**
  - 支持 DEBUG/INFO/WARNING/ERROR/CRITICAL 级别
  - 日志文件自动保存到 `logs/` 目录

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置（可选）

编辑 `config.json` 文件：

```json
{
    "curseforge_api_key": "",  // CurseForge API 密钥（可选）
    "platform_priority": "modrinth",  // 平台优先级：modrinth 或 curseforge
    "thread_count": 5,  // 并行查询线程数
    "timeout_seconds": 5,  // API 请求超时时间（秒）
    "log_level": "INFO"  // 日志级别
}
```

### 3. 运行

```bash
python mod_version_checker_v2.py
```

### 4. 打包（可选）

```bash
# Windows
build_v2.bat

# 或手动打包
pyinstaller --onefile mod_version_checker_v2.py
```

## 输出说明

程序会生成 CSV 格式的检测报告，包含以下字段：

| 字段                   | 说明            |
| -------------------- | ------------- |
| mod\_name            | 模组名称          |
| current\_version     | 当前版本          |
| current\_mc\_version | 当前 MC 版本      |
| mod\_type            | 模组类型          |
| has\_match           | 是否有匹配         |
| match\_platform      | 匹配平台          |
| match\_version       | 匹配版本          |
| match\_mc\_versions  | 匹配版本支持的 MC 版本 |
| match\_mod\_loaders  | 匹配版本支持的加载器    |
| hash\_match          | 是否为 Hash 匹配   |
| status               | 状态            |

## 项目结构

```
.
├── mod_version_checker_v2.py    # 主程序
├── config.json                  # 配置文件
├── requirements.txt             # Python 依赖
├── build_v2.bat                 # 打包脚本
├── MinecraftModCheckerV2.spec   # PyInstaller 配置
├── LICENSE                      # 许可证
└── .gitignore                   # Git 忽略文件
```

## 技术栈

- **Python**: 3.13+
- **依赖库**:
  - requests - HTTP 请求
  - packaging - 版本解析
  - murmurhash - MurmurHash2 算法
  - pyinstaller - 打包工具

## 参考

- [PCL2 源代码](https://github.com/Hex-Dragon/PCL2)
- [Modrinth API 文档](https://docs.modrinth.com/)
- [CurseForge API 文档](https://docs.curseforge.com/)

## 许可证

CC0

## 更新日志

### v2.0.1 (2026-03-30)

- ✅ 修复加载器大小写匹配问题
- ✅ CSV 输出添加中文注释行
- ✅ 增强超时处理和日志记录

### v2.0.0 (2026-03-30)

- ✅ 实现 PCL2 风格的 Hash 精确匹配
- ✅ 支持 Modrinth 和 CurseForge 双平台
- ✅ 智能缓存机制
- ✅ 并行查询优化
- ✅ 项目版本支持检查

