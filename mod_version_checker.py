import os
import sys
import json
import csv
import zipfile
import re
import requests
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, List, Tuple
from dataclasses import dataclass
from packaging import version
from concurrent.futures import ThreadPoolExecutor, as_completed


CONFIG_FILE = Path(__file__).parent / 'config.json'
DEFAULT_CONFIG = {
    'curseforge_api_key': '',
    'platform_priority': 'modrinth',
    'thread_count': 5,
    'timeout_seconds': 5
}


def load_config() -> Dict:
    """加载配置文件"""
    try:
        if CONFIG_FILE.exists():
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                config = json.load(f)
                for key, value in DEFAULT_CONFIG.items():
                    if key not in config:
                        config[key] = value
                return config
        else:
            print("配置文件不存在，创建默认配置文件...")
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(DEFAULT_CONFIG, f, indent=4, ensure_ascii=False)
            return DEFAULT_CONFIG
    except Exception as e:
        print(f"加载配置文件失败：{e}，使用默认配置")
        return DEFAULT_CONFIG


@dataclass
class ModInfo:
    """模组信息数据类"""
    name: str
    version: str
    mc_version: str
    mod_type: str  # Forge, Fabric, NeoForge
    file_path: str
    curseforge_id: Optional[str] = None
    modrinth_id: Optional[str] = None


@dataclass
class VersionInfo:
    """版本信息数据类"""
    latest_mc_version: str
    latest_mod_version: str
    platform: str  # CurseForge, Modrinth
    release_date: str
    download_url: str


def get_latest_minecraft_versions() -> List[str]:
    """获取最新的我的世界大版本（仅最新 1 个）"""
    try:
        print("正在获取最新的 Minecraft 版本...")
        response = requests.get(
            "https://launchermeta.mojang.com/mc/game/version_manifest.json",
            timeout=10
        )
        response.raise_for_status()
        data = response.json()
        
        versions = []
        for v in data.get('versions', [])[:50]:
            if v['type'] == 'release':
                ver = v['id']
                versions.append(ver)
        
        return versions[:1] if versions else []
    except Exception as e:
        print(f"获取 Minecraft 版本失败：{e}")
        return ["1.20", "1.19", "1.18", "1.17", "1.16"]


def get_version_input() -> List[str]:
    """获取用户手动输入的版本列表"""
    print("\n请选择版本获取方式:")
    print("1. 自动获取最新 Minecraft 版本")
    print("2. 手动指定 Minecraft 版本")
    print("3. 使用常用版本列表 (1.21.11, 1.21.10, 1.21.9, 1.21, 1.20)")
    
    choice = input("\n请输入选项 (1/2/3，默认 1): ").strip()
    
    if choice == '2':
        print("\n请输入要检测的 Minecraft 版本，多个版本用逗号或空格分隔")
        print("例如：1.21.11, 1.21.10, 1.21.9 或 1.21.11 1.21.10 1.21.9")
        version_str = input("输入版本：").strip()
        
        if not version_str:
            print("未输入版本，使用默认版本列表")
            return ["1.21.11", "1.21.10", "1.21.9", "1.21", "1.20"]
        
        versions = []
        for v in re.split(r'[,\s]+', version_str):
            v = v.strip()
            if v:
                versions.append(v)
        
        if versions:
            print(f"将检测以下版本：{', '.join(versions)}")
            return versions
        else:
            print("未输入有效版本，使用默认版本列表")
            return ["1.21.11", "1.21.10", "1.21.9", "1.21", "1.20"]
    
    elif choice == '3':
        print("使用常用版本列表")
        return ["1.21.11", "1.21.10", "1.21.9", "1.21", "1.20"]
    
    else:
        print("使用自动获取方式")
        return get_latest_minecraft_versions()


def parse_mod_jar(file_path: str) -> Optional[ModInfo]:
    """解析 Mod JAR 文件，提取模组信息"""
    try:
        with zipfile.ZipFile(file_path, 'r') as zf:
            mod_info = None
            
            if 'fabric.mod.json' in zf.namelist():
                mod_info = parse_fabric_mod(zf, file_path)
            elif 'META-INF/neoforge.mods.toml' in zf.namelist():
                mod_info = parse_neoforge_mod(zf, file_path)
            elif 'META-INF/mods.toml' in zf.namelist():
                mod_info = parse_forge_mod(zf, file_path)
            elif 'mcmod.info' in zf.namelist():
                mod_info = parse_legacy_forge_mod(zf, file_path)
            
            return mod_info
    except Exception as e:
        print(f"解析 {file_path} 失败：{e}")
        return None


def parse_fabric_mod(zf: zipfile.ZipFile, file_path: str) -> Optional[ModInfo]:
    """解析 Fabric 模组"""
    try:
        with zf.open('fabric.mod.json') as f:
            data = json.load(f)
        
        name = data.get('name', 'Unknown')
        version = data.get('version', 'Unknown')
        
        depends = data.get('depends', {})
        mc_version = depends.get('minecraft', 'Unknown')
        
        return ModInfo(
            name=name,
            version=version,
            mc_version=mc_version,
            mod_type='Fabric',
            file_path=file_path
        )
    except Exception as e:
        print(f"解析 Fabric 模组失败：{e}")
        return None


def parse_forge_mod(zf: zipfile.ZipFile, file_path: str) -> Optional[ModInfo]:
    """解析 Forge 模组 (mods.toml)"""
    try:
        with zf.open('META-INF/mods.toml') as f:
            content = f.read().decode('utf-8')
        
        mod_id_match = re.search(r'modId\s*=\s*"([^"]+)"', content)
        version_match = re.search(r'version\s*=\s*"([^"]+)"', content)
        
        mc_version_match = re.search(r'version\s*=\s*\[?([^,\]]+)', content)
        
        name_match = re.search(r'displayName\s*=\s*"([^"]+)"', content)
        
        mod_id = mod_id_match.group(1) if mod_id_match else 'Unknown'
        version = version_match.group(1) if version_match else 'Unknown'
        mc_version = mc_version_match.group(1) if mc_version_match else 'Unknown'
        name = name_match.group(1) if name_match else mod_id
        
        return ModInfo(
            name=name,
            version=version,
            mc_version=mc_version,
            mod_type='Forge',
            file_path=file_path
        )
    except Exception as e:
        print(f"解析 Forge 模组失败：{e}")
        return None


def parse_neoforge_mod(zf: zipfile.ZipFile, file_path: str) -> Optional[ModInfo]:
    """解析 NeoForge 模组"""
    try:
        with zf.open('META-INF/neoforge.mods.toml') as f:
            content = f.read().decode('utf-8')
        
        mod_id_match = re.search(r'modId\s*=\s*"([^"]+)"', content)
        version_match = re.search(r'version\s*=\s*"([^"]+)"', content)
        mc_version_match = re.search(r'version\s*=\s*\[?([^,\]]+)', content)
        name_match = re.search(r'displayName\s*=\s*"([^"]+)"', content)
        
        mod_id = mod_id_match.group(1) if mod_id_match else 'Unknown'
        version = version_match.group(1) if version_match else 'Unknown'
        mc_version = mc_version_match.group(1) if mc_version_match else 'Unknown'
        name = name_match.group(1) if name_match else mod_id
        
        return ModInfo(
            name=name,
            version=version,
            mc_version=mc_version,
            mod_type='NeoForge',
            file_path=file_path
        )
    except Exception as e:
        print(f"解析 NeoForge 模组失败：{e}")
        return None


def parse_legacy_forge_mod(zf: zipfile.ZipFile, file_path: str) -> Optional[ModInfo]:
    """解析旧版 Forge 模组 (mcmod.info)"""
    try:
        with zf.open('mcmod.info') as f:
            data = json.load(f)
        
        if isinstance(data, list):
            data = data[0]
        
        name = data.get('name', 'Unknown')
        version = data.get('version', 'Unknown')
        mc_version = data.get('mcversion', 'Unknown')
        
        return ModInfo(
            name=name,
            version=version,
            mc_version=mc_version,
            mod_type='Forge',
            file_path=file_path
        )
    except Exception as e:
        print(f"解析旧版 Forge 模组失败：{e}")
        return None


def search_curseforge_exists(mod_name: str, mc_version: str, api_key: str = '') -> bool:
    """在 CurseForge 上检查模组是否存在指定版本"""
    try:
        headers = {'X-Api-Key': api_key} if api_key else {}
        
        # 尝试多种搜索方式
        search_terms = [
            mod_name.lower().replace(' ', '-'),
            mod_name.lower().replace(' ', ''),
            mod_name.lower()
        ]
        
        for search_term in search_terms:
            try:
                response = requests.get(
                    f"https://api.curseforge.com/v1/mods/search",
                    params={'gameId': 432, 'slug': search_term},
                    headers=headers,
                    timeout=5
                )
                
                if response.status_code == 200:
                    data = response.json()
                    if data.get('data'):
                        mod = data['data'][0]
                        mod_id = mod['id']
                        
                        files_response = requests.get(
                            f"https://api.curseforge.com/v1/mods/{mod_id}/files",
                            params={'gameVersion': mc_version},
                            headers=headers,
                            timeout=5
                        )
                        
                        if files_response.status_code == 200:
                            files_data = files_response.json()
                            if files_data.get('data'):
                                return True
                        break
            except:
                continue
    except Exception as e:
        pass
    return False


def search_modrinth_exists(mod_name: str, mc_version: str, timeout: int = 5) -> bool:
    """在 Modrinth 上检查模组是否存在指定版本"""
    try:
        # 简化搜索，不使用 facets，直接搜索模组然后检查版本
        response = requests.get(
            "https://api.modrinth.com/v2/search",
            params={
                'query': mod_name,
                'limit': 5
            },
            timeout=timeout
        )
        
        if response.status_code == 200:
            data = response.json()
            if data.get('hits'):
                # 检查返回的模组是否包含指定版本
                for hit in data['hits'][:3]:  # 检查前 3 个结果
                    project_id = hit.get('project_id')
                    if project_id:
                        try:
                            version_response = requests.get(
                                f"https://api.modrinth.com/v2/project/{project_id}/version",
                                timeout=timeout
                            )
                            if version_response.status_code == 200:
                                versions_data = version_response.json()
                                if versions_data:
                                    # 检查是否有匹配的版本
                                    for version_info in versions_data[:10]:  # 检查最新 10 个版本
                                        game_versions = version_info.get('game_versions', [])
                                        if mc_version in game_versions:
                                            return True
                        except:
                            continue
    except Exception as e:
        pass
    return False


def scan_mods_folder(folder_path: str) -> List[ModInfo]:
    """扫描模组文件夹，获取所有模组信息"""
    mods = []
    path = Path(folder_path)
    
    if not path.exists():
        print(f"文件夹不存在：{folder_path}")
        return mods
    
    jar_files = list(path.glob('*.jar'))
    
    print(f"发现 {len(jar_files)} 个模组文件")
    
    for jar_file in jar_files:
        print(f"正在解析：{jar_file.name}")
        mod_info = parse_mod_jar(str(jar_file))
        if mod_info:
            mods.append(mod_info)
    
    return mods


def check_mod_updates(mod: ModInfo, latest_mc_versions: List[str], config: Dict) -> Dict:
    """检查模组是否存在指定版本"""
    result = {
        'mod_name': mod.name,
        'current_version': mod.version,
        'current_mc_version': mod.mc_version,
        'mod_type': mod.mod_type,
        'has_update': False,
        'latest_mc_version': None,
        'platform': None,
        'status': '未知'
    }
    
    api_key = config.get('curseforge_api_key', '')
    platform_priority = config.get('platform_priority', 'modrinth')
    timeout = config.get('timeout_seconds', 5)
    
    print(f"\n检查模组：{mod.name} (当前版本：{mod.version}, MC: {mod.mc_version})")
    
    for mc_version in latest_mc_versions:
        if platform_priority == 'modrinth':
            modrinth_exists = search_modrinth_exists(mod.name, mc_version, timeout)
            curseforge_exists = search_curseforge_exists(mod.name, mc_version, api_key) if not modrinth_exists else False
        else:
            curseforge_exists = search_curseforge_exists(mod.name, mc_version, api_key)
            modrinth_exists = search_modrinth_exists(mod.name, mc_version, timeout) if not curseforge_exists else False
        
        if curseforge_exists or modrinth_exists:
            result['has_update'] = True
            result['latest_mc_version'] = mc_version
            result['platform'] = 'CurseForge' if curseforge_exists else 'Modrinth'
            result['status'] = f'存在该版本 (支持 MC {mc_version})'
            break
    
    if not result['has_update']:
        result['status'] = '未找到匹配版本'
    
    return result


def check_mod_updates_parallel(mod: ModInfo, latest_mc_versions: List[str], config: Dict) -> Dict:
    """使用多线程检查模组是否存在指定版本"""
    result = {
        'mod_name': mod.name,
        'current_version': mod.version,
        'current_mc_version': mod.mc_version,
        'mod_type': mod.mod_type,
        'has_update': False,
        'latest_mc_version': None,
        'platform': None,
        'status': '未找到匹配版本'
    }
    
    api_key = config.get('curseforge_api_key', '')
    platform_priority = config.get('platform_priority', 'modrinth')
    timeout = config.get('timeout_seconds', 5)
    
    def check_single_version(mc_version: str) -> Optional[Tuple[str, str]]:
        """检查单个版本"""
        if platform_priority == 'modrinth':
            modrinth_exists = search_modrinth_exists(mod.name, mc_version, timeout)
            curseforge_exists = search_curseforge_exists(mod.name, mc_version, api_key) if not modrinth_exists else False
        else:
            curseforge_exists = search_curseforge_exists(mod.name, mc_version, api_key)
            modrinth_exists = search_modrinth_exists(mod.name, mc_version, timeout) if not curseforge_exists else False
        
        if curseforge_exists or modrinth_exists:
            platform = 'CurseForge' if curseforge_exists else 'Modrinth'
            return (mc_version, platform)
        return None
    
    print(f"检查模组：{mod.name} (当前版本：{mod.version}, MC: {mod.mc_version})")
    
    with ThreadPoolExecutor(max_workers=min(len(latest_mc_versions), 5)) as executor:
        future_to_version = {
            executor.submit(check_single_version, mc_ver): mc_ver 
            for mc_ver in latest_mc_versions
        }
        
        for future in as_completed(future_to_version):
            try:
                check_result = future.result()
                if check_result:
                    mc_version, platform = check_result
                    result['has_update'] = True
                    result['latest_mc_version'] = mc_version
                    result['platform'] = platform
                    result['status'] = f'存在该版本 (支持 MC {mc_version})'
                    break
            except Exception as e:
                pass
    
    return result


def save_to_csv(results: List[Dict], output_path: str):
    """将结果保存到 CSV 文件"""
    if not results:
        return
    
    fieldnames = [
        'mod_name', 'current_version', 'current_mc_version', 'mod_type',
        'has_update', 'latest_mc_version', 'platform', 'status'
    ]
    
    with open(output_path, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)
    
    print(f"\n结果已保存到：{output_path}")


def print_summary(results: List[Dict]):
    """打印摘要信息"""
    total = len(results)
    has_updates = sum(1 for r in results if r['has_update'])
    
    print("\n" + "="*80)
    print("检测结果摘要")
    print("="*80)
    print(f"总模组数：{total}")
    print(f"存在指定版本的模组数：{has_updates}")
    print(f"未找到匹配的模组数：{total - has_updates}")
    print("="*80)
    
    if has_updates > 0:
        print("\n存在指定版本的模组:")
        print("-"*80)
        for result in results:
            if result['has_update']:
                print(f"  • {result['mod_name']}")
                print(f"    当前版本：{result['current_version']} (MC {result['current_mc_version']})")
                print(f"    支持 MC 版本：{result['latest_mc_version']}")
                print(f"    平台：{result['platform']}")
                print()


def main():
    """主函数"""
    print("="*80)
    print("Minecraft Mod 版本检测工具")
    print("="*80)
    print(f"检测时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    config = load_config()
    print(f"已加载配置文件：{CONFIG_FILE}")
    print(f"平台优先级：{config.get('platform_priority', 'modrinth')}")
    if config.get('curseforge_api_key'):
        print("CurseForge API Key：已配置")
    else:
        print("CurseForge API Key：未配置（可能影响 CurseForge 搜索结果）")
    print()
    
    mods_folder = input("请输入模组文件夹路径 (直接回车使用默认路径 './mods'): ").strip()
    if not mods_folder:
        mods_folder = './mods'
    
    if not os.path.exists(mods_folder):
        print(f"创建默认模组文件夹：{mods_folder}")
        os.makedirs(mods_folder, exist_ok=True)
    
    latest_mc_versions = get_version_input()
    print(f"\n将检测以下 Minecraft 版本：{', '.join(latest_mc_versions[:5])}")
    if len(latest_mc_versions) > 5:
        print(f"等共 {len(latest_mc_versions)} 个版本")
    print()
    
    print("\n请选择检测模式:")
    print("1. 顺序检测 (适合少量模组)")
    print("2. 多线程检测 (适合大量模组，速度更快)")
    mode = input("输入选项 (1/2，默认 2): ").strip()
    use_parallel = mode != '1'
    
    if use_parallel:
        thread_count = input("输入线程数 (默认 5，范围 1-10): ").strip()
        try:
            max_workers = int(thread_count) if thread_count else config.get('thread_count', 5)
            max_workers = max(1, min(max_workers, 10))
        except:
            max_workers = config.get('thread_count', 5)
        print(f"使用 {max_workers} 个线程进行检测")
    
    mods = scan_mods_folder(mods_folder)
    
    if not mods:
        print("未找到任何模组文件")
        return
    
    results = []
    
    if use_parallel:
        print(f"\n开始多线程检测，共 {len(mods)} 个模组...")
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(check_mod_updates_parallel, mod, latest_mc_versions, config): mod 
                for mod in mods
            }
            
            for i, future in enumerate(as_completed(futures), 1):
                try:
                    result = future.result()
                    results.append(result)
                    print(f"[{i}/{len(mods)}] 完成检测：{result['mod_name']}")
                except Exception as e:
                    mod = futures[future]
                    print(f"[{i}/{len(mods)}] 检测失败 {mod.name}: {e}")
                    results.append({
                        'mod_name': mod.name,
                        'current_version': mod.version,
                        'current_mc_version': mod.mc_version,
                        'mod_type': mod.mod_type,
                        'has_update': False,
                        'latest_mc_version': None,
                        'platform': None,
                        'status': '检测失败'
                    })
    else:
        print(f"\n开始顺序检测，共 {len(mods)} 个模组...")
        for i, mod in enumerate(mods, 1):
            print(f"[{i}/{len(mods)}]", end=" ")
            result = check_mod_updates(mod, latest_mc_versions, config)
            results.append(result)
    
    print_summary(results)
    
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    csv_filename = f'mod_update_report_{timestamp}.csv'
    save_to_csv(results, csv_filename)
    
    print("\n检测完成!")


if __name__ == '__main__':
    main()
