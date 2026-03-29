# Minecraft Mod 版本检测工具

一个用于检测 Minecraft 模组是否支持最新版本的游戏的 Python 工具。
注：这个是ai生成的（满足我自己的需求）
## 功能特性

- ✅ 支持 Forge、Fabric、NeoForge 模组格式
- ✅ 支持手动指定或自动获取 Minecraft 版本
- ✅ 查询 CurseForge 和 Modrinth 平台的模组更新
- ✅ 多线程并发检测，大幅提升检测速度
- ✅ 检测模组是否存在指定 MC 版本
- ✅ 命令行实时显示检测进度
- ✅ 生成 CSV 格式的检测报告
- ✅ 支持自定义模组文件夹路径

## 安装

### 1. 安装 Python

确保已安装 Python 3.8 或更高版本。

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

## 使用方法

### 基本使用

1. 将需要检测的模组文件（.jar）放入 `mods` 文件夹
2. 运行程序：

```bash
python mod_version_checker.py
```

3. 按提示操作：
   - **选择版本获取方式**：
     - `1` - 自动获取最新 Minecraft 版本（默认）
     - `2` - 手动指定 Minecraft 版本
     - `3` - 使用常用版本列表
   - **选择检测模式**：
     - `1` - 顺序检测（适合少量模组）
     - `2` - 多线程检测（适合大量模组，速度更快，默认）
   - **设置线程数**（仅多线程模式）：输入 1-10 之间的数字，默认 5

### 指定模组文件夹

运行程序后，输入模组文件夹的完整路径，或直接回车使用默认的 `./mods` 文件夹。

### 使用示例

#### 示例 1：使用自动获取版本 + 多线程检测
```
请输入模组文件夹路径 (直接回车使用默认路径 './mods'): 
请选择版本获取方式:
1. 自动获取最新 Minecraft 版本
2. 手动指定 Minecraft 版本
3. 使用常用版本列表 (1.21.11, 1.21.10, 1.21.9, 1.21, 1.20)

请输入选项 (1/2/3，默认 1): 1

请选择检测模式:
1. 顺序检测 (适合少量模组)
2. 多线程检测 (适合大量模组，速度更快)
输入选项 (1/2，默认 2): 2
输入线程数 (默认 5，范围 1-10): 5
```

#### 示例 2：手动指定版本
```
请选择版本获取方式:
1. 自动获取最新 Minecraft 版本
2. 手动指定 Minecraft 版本
3. 使用常用版本列表 (1.21.11, 1.21.10, 1.21.9, 1.21, 1.20)

请输入选项 (1/2/3，默认 1): 2

请输入要检测的 Minecraft 版本，多个版本用逗号或空格分隔
例如：1.21.11, 1.21.10, 1.21.9 或 1.21.11 1.21.10 1.21.9
输入版本：1.21.11,1.21.10,1.21
将检测以下版本：1.21.11, 1.21.10, 1.21
```

## 输出说明

### 命令行输出

程序会在命令行实时显示：
- 当前检测的模组名称和版本
- 查询 CurseForge 和 Modrinth 的结果
- 检测完成后显示摘要信息

### CSV 报告

生成的 CSV 文件包含以下字段：
- `mod_name`: 模组名称
- `current_version`: 当前版本
- `current_mc_version`: 当前支持的 MC 版本
- `mod_type`: 模组类型 (Forge/Fabric/NeoForge)
- `has_update`: 是否存在指定版本 (True/False)
- `latest_mc_version`: 支持的 MC 版本
- `platform`: 检测平台 (CurseForge/Modrinth)
- `status`: 检测状态

## 注意事项

1. **网络连接**: 程序需要访问 CurseForge 和 Modrinth API，请确保网络连接正常
2. **CurseForge API**: 如果需要更准确的 CurseForge 搜索结果，可以设置环境变量 `CURSEFORGE_API_KEY`
3. **模组识别**: 程序通过解析 JAR 文件中的配置文件来识别模组信息，某些模组可能无法正确识别

## 支持的模组格式

### Fabric
- 配置文件：`fabric.mod.json`
- 识别字段：name, version, depends.minecraft

### Forge (1.13+)
- 配置文件：`META-INF/mods.toml`
- 识别字段：modId, displayName, version

### NeoForge
- 配置文件：`META-INF/neoforge.mods.toml`
- 识别字段：modId, displayName, version

### Legacy Forge (1.12 及以下)
- 配置文件：`mcmod.info`
- 识别字段：name, version, mcversion

## 故障排除

### 问题：无法获取 Minecraft 版本
**解决**: 检查网络连接，或程序会使用默认版本列表

### 问题：模组无法识别
**解决**: 确认模组文件格式正确，配置文件存在且格式正确

### 问题：API 查询失败
**解决**: 检查网络连接，稍后重试。CurseForge API 可能需要 API Key

## 许可证

CC0
