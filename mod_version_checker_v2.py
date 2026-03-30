"""
Minecraft Mod 版本检测工具 v2
参考 PCL2 的模组匹配逻辑重构

核心改进:
1. 使用 Hash 精确匹配 (CurseForge: MurmurHash2, Modrinth: SHA1)
2. 智能缓存机制 (6 小时缓存)
3. 并行查询优化 (同时查询两个平台)
4. 精确版本和加载器匹配
5. 批量 API 调用减少请求次数
"""

import os
import sys
import json
import csv
import zipfile
import re
import hashlib
import struct
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple, Set
from dataclasses import dataclass, field
from packaging import version as pkg_version
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


def get_base_path():
    """获取程序运行的基础路径（支持打包后的环境）"""
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent
    else:
        return Path(__file__).parent


BASE_DIR = get_base_path()
CONFIG_FILE = BASE_DIR / 'config.json'
LOG_DIR = BASE_DIR / 'logs'
CACHE_DIR = BASE_DIR / 'cache'

# 日志级别映射
LOG_LEVEL_MAP = {
    'DEBUG': logging.DEBUG,
    'INFO': logging.INFO,
    'WARNING': logging.WARNING,
    'WARN': logging.WARNING,
    'ERROR': logging.ERROR,
    'CRITICAL': logging.CRITICAL
}


def get_log_level_from_config():
    """从配置文件获取日志级别"""
    try:
        if CONFIG_FILE.exists():
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                config = json.load(f)
                log_level_str = config.get('log_level', 'INFO').upper()
                return LOG_LEVEL_MAP.get(log_level_str, logging.INFO)
        else:
            return logging.INFO
    except Exception as e:
        print(f"读取日志级别配置失败：{e}，使用默认级别 INFO")
        return logging.INFO


def setup_logger():
    """设置日志记录器"""
    LOG_DIR.mkdir(exist_ok=True)
    CACHE_DIR.mkdir(exist_ok=True)
    
    # 从配置获取日志级别
    log_level = get_log_level_from_config()
    
    logger = logging.getLogger('ModCheckerV2')
    logger.setLevel(logging.DEBUG)  # 记录器本身记录所有级别，由处理器过滤
    
    logger.handlers.clear()
    
    # 文件处理器 - 记录 DEBUG 及以上所有日志
    file_handler = logging.FileHandler(
        LOG_DIR / f'mod_checker_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log',
        encoding='utf-8'
    )
    file_handler.setLevel(logging.DEBUG)
    file_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)
    
    # 控制台处理器 - 使用配置文件中的日志级别
    console_handler = logging.StreamHandler()
    console_handler.setLevel(log_level)
    console_formatter = logging.Formatter('%(message)s')
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)
    
    return logger


logger = setup_logger()


# ============== PCL2 核心改进 1: Hash 计算 ==============

def calculate_murmurhash2(data: bytes) -> int:
    """
    计算 MurmurHash2 (CurseForge 使用)
    参考 PCL2 的 ModJava.vb 第 452-477 行
    """
    length = len(data)
    h = 1 ^ length  # 种子
    
    i = 0
    while i <= length - 4:
        k = (data[i] | 
             (data[i + 1] << 8) | 
             (data[i + 2] << 16) | 
             (data[i + 3] << 24))
        k = (k * 0x5BD1E995) & 0xFFFFFFFF
        k = k ^ (k >> 24)
        k = (k * 0x5BD1E995) & 0xFFFFFFFF
        h = (h * 0x5BD1E995) & 0xFFFFFFFF
        h = h ^ k
        i += 4
    
    remaining = length - i
    if remaining == 3:
        h = h ^ (data[i] | (data[i + 1] << 8))
        h = h ^ (data[i + 2] << 16)
        h = (h * 0x5BD1E995) & 0xFFFFFFFF
    elif remaining == 2:
        h = h ^ (data[i] | (data[i + 1] << 8))
        h = (h * 0x5BD1E995) & 0xFFFFFFFF
    elif remaining == 1:
        h = h ^ data[i]
        h = (h * 0x5BD1E995) & 0xFFFFFFFF
    
    h = h ^ (h >> 13)
    h = (h * 0x5BD1E995) & 0xFFFFFFFF
    h = h ^ (h >> 15)
    
    return h


def calculate_sha1(data: bytes) -> str:
    """计算 SHA1 (Modrinth 使用)"""
    return hashlib.sha1(data).hexdigest()


def get_file_hashes(file_path: str) -> Tuple[int, str]:
    """
    获取文件的 Hash 值
    返回：(CurseForge Hash, Modrinth Hash)
    """
    with open(file_path, 'rb') as f:
        content = f.read()
    
    # 过滤掉空白字符 (参考 PCL2)
    filtered_content = bytes([b for b in content if b not in (9, 10, 13, 32)])
    
    curseforge_hash = calculate_murmurhash2(filtered_content)
    modrinth_hash = calculate_sha1(content)
    
    return curseforge_hash, modrinth_hash


# ============== PCL2 核心改进 2: 智能缓存 ==============

class ModCache:
    """
    模组信息缓存 (参考 PCL2 的 LocalModCache)
    缓存有效期：6 小时
    """
    
    CACHE_VERSION = 1
    CACHE_FILE = CACHE_DIR / 'mod_cache.json'
    CACHE_DURATION = timedelta(hours=6)
    
    def __init__(self):
        self.cache_data = {
            'version': self.CACHE_VERSION,
            'entries': {},
            'last_updated': datetime.now().isoformat()
        }
        self.load_cache()
    
    def load_cache(self):
        """加载缓存"""
        try:
            if self.CACHE_FILE.exists():
                with open(self.CACHE_FILE, 'r', encoding='utf-8') as f:
                    self.cache_data = json.load(f)
                
                # 检查缓存版本
                if self.cache_data.get('version') != self.CACHE_VERSION:
                    logger.debug("缓存版本过期，重置缓存")
                    self.cache_data = {
                        'version': self.CACHE_VERSION,
                        'entries': {},
                        'last_updated': datetime.now().isoformat()
                    }
                else:
                    logger.debug(f"加载缓存成功，共 {len(self.cache_data['entries'])} 条记录")
        except Exception as e:
            logger.error(f"加载缓存失败：{e}")
            self.cache_data = {
                'version': self.CACHE_VERSION,
                'entries': {},
                'last_updated': datetime.now().isoformat()
            }
    
    def save_cache(self):
        """保存缓存"""
        try:
            self.cache_data['last_updated'] = datetime.now().isoformat()
            with open(self.CACHE_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.cache_data, f, indent=2, ensure_ascii=False)
            logger.debug("缓存已保存")
        except Exception as e:
            logger.error(f"保存缓存失败：{e}")
    
    def get_entry(self, cache_key: str) -> Optional[Dict]:
        """获取缓存条目"""
        entry = self.cache_data['entries'].get(cache_key)
        if entry:
            cached_time = datetime.fromisoformat(entry['cached_at'])
            if datetime.now() - cached_time < self.CACHE_DURATION:
                logger.debug(f"缓存命中：{cache_key}")
                return entry['data']
            else:
                logger.debug(f"缓存过期：{cache_key}")
                del self.cache_data['entries'][cache_key]
        return None
    
    def set_entry(self, cache_key: str, data: Dict):
        """设置缓存条目"""
        self.cache_data['entries'][cache_key] = {
            'cached_at': datetime.now().isoformat(),
            'data': data
        }
        logger.debug(f"缓存已设置：{cache_key}")
        self.save_cache()


# ============== 数据类 ==============

@dataclass
class ModInfo:
    """模组信息数据类"""
    name: str
    version: str
    mc_version: str
    mod_type: str  # Forge, Fabric, NeoForge, Quilt
    file_path: str
    file_name: str
    curseforge_hash: Optional[int] = None
    modrinth_hash: Optional[str] = None
    mod_id: Optional[str] = None  # 从配置文件提取的 modId


@dataclass
class PlatformMatch:
    """平台匹配结果"""
    platform: str  # CurseForge, Modrinth
    project_id: str
    project_name: str
    file_id: str
    file_name: str
    mod_version: str
    mc_versions: List[str]
    mod_loaders: List[str]
    release_date: str
    download_url: str
    hash_match: bool = True  # 是否为 Hash 精确匹配


@dataclass
class VersionCheckResult:
    """版本检查结果"""
    mod_name: str
    current_version: str
    current_mc_version: str
    mod_type: str
    file_path: str
    has_match: bool = False
    matches: List[PlatformMatch] = field(default_factory=list)
    best_match: Optional[PlatformMatch] = None
    status: str = '未检查'


# ============== PCL2 核心改进 3: 精确解析模组信息 ==============

def parse_mod_jar(file_path: str) -> Optional[ModInfo]:
    """
    解析 Mod JAR 文件，提取模组信息
    参考 PCL2 的 ModMod.vb 第 131-350 行
    """
    try:
        file_name = os.path.basename(file_path)
        
        with zipfile.ZipFile(file_path, 'r') as zf:
            namelist = zf.namelist()
            
            # 按优先级尝试不同的配置文件
            # 1. Fabric: fabric.mod.json
            if 'fabric.mod.json' in namelist:
                mod_info = parse_fabric_mod(zf, file_path, file_name)
                if mod_info:
                    return mod_info
            
            # 2. NeoForge: META-INF/neoforge.mods.toml
            if 'META-INF/neoforge.mods.toml' in namelist:
                mod_info = parse_neoforge_mod(zf, file_path, file_name)
                if mod_info:
                    return mod_info
            
            # 3. Forge: META-INF/mods.toml
            if 'META-INF/mods.toml' in namelist:
                mod_info = parse_forge_mod(zf, file_path, file_name)
                if mod_info:
                    return mod_info
            
            # 4. Legacy Forge: mcmod.info
            if 'mcmod.info' in namelist:
                mod_info = parse_legacy_forge_mod(zf, file_path, file_name)
                if mod_info:
                    return mod_info
            
            # 5. 尝试从 MANIFEST.MF 获取版本信息
            mod_info = parse_from_manifest(zf, file_path, file_name)
            if mod_info:
                return mod_info
        
        # 如果都失败了，返回基本信息
        return ModInfo(
            name=os.path.splitext(file_name)[0],
            version='Unknown',
            mc_version='Unknown',
            mod_type='Unknown',
            file_path=file_path,
            file_name=file_name
        )
        
    except Exception as e:
        logger.error(f"解析 {file_path} 失败：{e}")
        return None


def parse_fabric_mod(zf: zipfile.ZipFile, file_path: str, file_name: str) -> Optional[ModInfo]:
    """解析 Fabric 模组 (fabric.mod.json)"""
    try:
        with zf.open('fabric.mod.json') as f:
            data = json.load(f)
        
        # 检查 schemaVersion (参考 PCL2)
        if 'schemaVersion' not in data:
            return None
        
        name = data.get('name', 'Unknown')
        version = data.get('version', 'Unknown')
        
        # 获取 Minecraft 版本依赖
        depends = data.get('depends', {})
        mc_version = depends.get('minecraft', 'Unknown')
        
        # 获取 mod id
        mod_id = data.get('id', '')
        
        # 检测加载器类型
        mod_type = 'Fabric'
        if 'quilt' in data.get('groups', []):
            mod_type = 'Quilt'
        
        return ModInfo(
            name=name,
            version=version,
            mc_version=mc_version,
            mod_type=mod_type,
            file_path=file_path,
            file_name=file_name,
            mod_id=mod_id
        )
    except Exception as e:
        logger.debug(f"解析 Fabric 模组失败：{e}")
        return None


def parse_forge_mod(zf: zipfile.ZipFile, file_path: str, file_name: str) -> Optional[ModInfo]:
    """解析 Forge 模组 (mods.toml) - 参考 PCL2 第 201-288 行"""
    try:
        with zf.open('META-INF/mods.toml') as f:
            content = f.read().decode('utf-8')
        
        # 解析 TOML (简化版，参考 PCL2 的 TOML 解析逻辑)
        lines = []
        for line in content.replace('\r\n', '\n').replace('\r', '\n').split('\n'):
            # 去除注释
            if line.startswith('#'):
                continue
            elif '#' in line:
                line = line[:line.index('#')]
            
            line = line.strip()
            if line:
                lines.append(line)
        
        # 提取 mods 段落
        in_mods_section = False
        mod_data = {}
        
        for line in lines:
            if line.startswith('[mods]'):
                in_mods_section = True
                continue
            elif line.startswith('['):
                in_mods_section = False
                continue
            
            if in_mods_section and '=' in line:
                key, value = line.split('=', 1)
                key = key.strip()
                value = value.strip().strip('"\'')
                mod_data[key] = value
        
        if not mod_data.get('modId'):
            return None
        
        mod_id = mod_data.get('modId', 'Unknown')
        display_name = mod_data.get('displayName', mod_id)
        version = mod_data.get('version', 'Unknown')
        
        # 从依赖中提取 MC 版本
        mc_version = 'Unknown'
        for line in lines:
            if 'version' in line and '=' in line:
                key, value = line.split('=', 1)
                if 'minecraft' in key.lower():
                    mc_version = value.strip('[]"')
                    break
        
        return ModInfo(
            name=display_name,
            version=version,
            mc_version=mc_version,
            mod_type='Forge',
            file_path=file_path,
            file_name=file_name,
            mod_id=mod_id
        )
    except Exception as e:
        logger.debug(f"解析 Forge 模组失败：{e}")
        return None


def parse_neoforge_mod(zf: zipfile.ZipFile, file_path: str, file_name: str) -> Optional[ModInfo]:
    """解析 NeoForge 模组"""
    try:
        with zf.open('META-INF/neoforge.mods.toml') as f:
            content = f.read().decode('utf-8')
        
        # 解析逻辑与 Forge 相同
        lines = []
        for line in content.replace('\r\n', '\n').replace('\r', '\n').split('\n'):
            if line.startswith('#'):
                continue
            elif '#' in line:
                line = line[:line.index('#')]
            
            line = line.strip()
            if line:
                lines.append(line)
        
        in_mods_section = False
        mod_data = {}
        
        for line in lines:
            if line.startswith('[mods]'):
                in_mods_section = True
                continue
            elif line.startswith('['):
                in_mods_section = False
                continue
            
            if in_mods_section and '=' in line:
                key, value = line.split('=', 1)
                key = key.strip()
                value = value.strip().strip('"\'')
                mod_data[key] = value
        
        if not mod_data.get('modId'):
            return None
        
        mod_id = mod_data.get('modId', 'Unknown')
        display_name = mod_data.get('displayName', mod_id)
        version = mod_data.get('version', 'Unknown')
        
        mc_version = 'Unknown'
        for line in lines:
            if 'version' in line and '=' in line:
                key, value = line.split('=', 1)
                if 'minecraft' in key.lower():
                    mc_version = value.strip('[]"')
                    break
        
        return ModInfo(
            name=display_name,
            version=version,
            mc_version=mc_version,
            mod_type='NeoForge',
            file_path=file_path,
            file_name=file_name,
            mod_id=mod_id
        )
    except Exception as e:
        logger.debug(f"解析 NeoForge 模组失败：{e}")
        return None


def parse_legacy_forge_mod(zf: zipfile.ZipFile, file_path: str, file_name: str) -> Optional[ModInfo]:
    """解析旧版 Forge 模组 (mcmod.info)"""
    try:
        with zf.open('mcmod.info') as f:
            data = json.load(f)
        
        if isinstance(data, list):
            data = data[0]
        
        name = data.get('name', 'Unknown')
        version = data.get('version', 'Unknown')
        mc_version = data.get('mcversion', 'Unknown')
        mod_id = data.get('modid', '')
        
        return ModInfo(
            name=name,
            version=version,
            mc_version=mc_version,
            mod_type='Forge',
            file_path=file_path,
            file_name=file_name,
            mod_id=mod_id
        )
    except Exception as e:
        logger.debug(f"解析旧版 Forge 模组失败：{e}")
        return None


def parse_from_manifest(zf: zipfile.ZipFile, file_path: str, file_name: str) -> Optional[ModInfo]:
    """从 MANIFEST.MF 获取版本信息 (参考 PCL2 第 330-348 行)"""
    try:
        if 'META-INF/MANIFEST.MF' not in zf.namelist():
            return None
        
        with zf.open('META-INF/MANIFEST.MF') as f:
            content = f.read().decode('utf-8')
        
        # 查找 Implementation-Version
        version = None
        for line in content.split('\n'):
            line = line.replace(' :', ':').replace(': ', ':')
            if line.startswith('Implementation-Version:'):
                version = line.split(':', 1)[1].strip()
                break
        
        if version:
            return ModInfo(
                name=os.path.splitext(file_name)[0],
                version=version,
                mc_version='Unknown',
                mod_type='Unknown',
                file_path=file_path,
                file_name=file_name
            )
    except Exception as e:
        logger.debug(f"从 MANIFEST.MF 解析失败：{e}")
    
    return None


# ============== PCL2 核心改进 4: 批量 Hash 匹配 ==============

class ModPlatformMatcher:
    """
    模组平台匹配器
    参考 PCL2 的 ModMod.vb 第 638-865 行
    """
    
    def __init__(self, config: Dict, cache: ModCache):
        self.config = config
        self.cache = cache
        self.session = self._create_session()
        
        self.curseforge_api_key = config.get('curseforge_api_key', '')
        self.platform_priority = config.get('platform_priority', 'modrinth')
        self.timeout = config.get('timeout_seconds', 5)
        self.thread_count = config.get('thread_count', 5)  # 支持配置文件中的线程数设置
    
    def _create_session(self):
        """创建带重试的 HTTP 会话"""
        session = requests.Session()
        retry = Retry(
            total=3,
            backoff_factor=0.3,
            status_forcelist=[429, 500, 502, 503, 504]
        )
        adapter = HTTPAdapter(max_retries=retry)
        session.mount('http://', adapter)
        session.mount('https://', adapter)
        return session
    
    def match_mods_batch(self, mods: List[ModInfo], target_mc_versions: List[str], 
                        target_mod_loaders: List[str]) -> List[VersionCheckResult]:
        """
        批量匹配模组 (参考 PCL2 的并行查询逻辑)
        
        Args:
            mods: 模组信息列表
            target_mc_versions: 目标 MC 版本列表
            target_mod_loaders: 目标加载器列表 (Forge, Fabric, NeoForge, Quilt)
        
        Returns:
            版本检查结果列表
        """
        logger.info(f"开始批量匹配 {len(mods)} 个模组")
        logger.debug(f"目标 MC 版本：{target_mc_versions}")
        logger.debug(f"目标加载器：{target_mod_loaders}")
        
        results = []
        
        # 分组：有 Hash 的模组和无 Hash 的模组
        mods_with_hash = [m for m in mods if m.curseforge_hash and m.modrinth_hash]
        mods_without_hash = [m for m in mods if not m.curseforge_hash or not m.modrinth_hash]
        
        logger.info(f"有 Hash 的模组：{len(mods_with_hash)}, 无 Hash 的模组：{len(mods_without_hash)}")
        
        # 1. 优先处理有 Hash 的模组 (精确匹配)
        if mods_with_hash:
            logger.info("使用 Hash 精确匹配...")
            hash_results = self._match_by_hash_batch(mods_with_hash, target_mc_versions, target_mod_loaders)
            results.extend(hash_results)
        
        # 2. 处理无 Hash 的模组 (名称搜索)
        if mods_without_hash:
            logger.info("使用名称搜索匹配...")
            name_results = self._match_by_name_batch(mods_without_hash, target_mc_versions, target_mod_loaders)
            results.extend(name_results)
        
        return results
    
    def _match_by_hash_batch(self, mods: List[ModInfo], target_mc_versions: List[str],
                            target_mod_loaders: List[str]) -> List[VersionCheckResult]:
        """
        通过 Hash 批量匹配模组 (参考 PCL2 第 667-841 行)
        """
        results = []
        
        # 准备 Hash 列表
        curseforge_hashes = [m.curseforge_hash for m in mods if m.curseforge_hash]
        modrinth_hashes = [m.modrinth_hash for m in mods if m.modrinth_hash]
        
        # 并行查询两个平台
        with ThreadPoolExecutor(max_workers=min(2, self.thread_count)) as executor:
            # CurseForge 查询
            curseforge_future = executor.submit(
                self._query_curseforge_by_hash,
                curseforge_hashes, target_mc_versions, target_mod_loaders
            )
            
            # Modrinth 查询
            modrinth_future = executor.submit(
                self._query_modrinth_by_hash,
                modrinth_hashes, target_mc_versions, target_mod_loaders
            )
            
            # 等待结果
            curseforge_matches = curseforge_future.result()
            modrinth_matches = modrinth_future.result()
        
        # 合并结果 (CurseForge 优先，参考 PCL2 第 1246 行)
        for mod in mods:
            result = VersionCheckResult(
                mod_name=mod.name,
                current_version=mod.version,
                current_mc_version=mod.mc_version,
                mod_type=mod.mod_type,
                file_path=mod.file_path,
                matches=[]
            )
            
            # 添加 CurseForge 匹配
            if mod.curseforge_hash and mod.curseforge_hash in curseforge_matches:
                result.matches.extend(curseforge_matches[mod.curseforge_hash])
            
            # 添加 Modrinth 匹配
            if mod.modrinth_hash and mod.modrinth_hash in modrinth_matches:
                result.matches.extend(modrinth_matches[mod.modrinth_hash])
            
            # 选择最佳匹配
            if result.matches:
                result.has_match = True
                result.best_match = result.matches[0]  # 取第一个 (优先级最高的)
                result.status = f"找到匹配 ({result.best_match.platform})"
            else:
                result.status = "未找到匹配"
            
            results.append(result)
        
        return results
    
    def _query_curseforge_by_hash(self, hashes: List[int], target_mc_versions: List[str],
                                  target_mod_loaders: List[str]) -> Dict[int, List[PlatformMatch]]:
        """
        通过 Hash 查询 CurseForge (参考 PCL2 第 736-841 行)
        """
        if not hashes:
            return {}
        
        matches = {}
        
        try:
            # 批量查询指纹 (参考 PCL2 第 745-746 行)
            url = "https://api.curseforge.com/v1/fingerprints/432"
            headers = {'X-Api-Key': self.curseforge_api_key} if self.curseforge_api_key else {}
            payload = {'fingerprints': hashes}
            
            logger.debug(f"CurseForge 批量查询 {len(hashes)} 个指纹")
            response = self.session.post(url, json=payload, headers=headers, timeout=self.timeout)
            
            if response.status_code == 200:
                data = response.json()
                exact_matches = data.get('data', {}).get('exactMatches', [])
                
                logger.info(f"CurseForge 匹配到 {len(exact_matches)} 个结果")
                
                for match_data in exact_matches:
                    file_data = match_data.get('file', {})
                    file_hash = file_data.get('fileFingerprint')
                    project_id = file_data.get('modId')
                    
                    if not project_id:
                        continue
                    
                    # 检查版本和加载器匹配
                    game_versions = file_data.get('gameVersions', [])
                    mod_loaders = file_data.get('modLoaders', [])
                    
                    if not self._version_matches(game_versions, target_mc_versions):
                        continue
                    
                    if not self._loader_matches(mod_loaders, target_mod_loaders):
                        continue
                    
                    # 创建匹配结果
                    platform_match = PlatformMatch(
                        platform='CurseForge',
                        project_id=str(project_id),
                        project_name=match_data.get('file', {}).get('displayName', ''),
                        file_id=str(file_data.get('id', '')),
                        file_name=file_data.get('fileName', ''),
                        mod_version=file_data.get('displayName', ''),
                        mc_versions=[v for v in game_versions if re.match(r'^\d+\.\d+', v)],
                        mod_loaders=mod_loaders,
                        release_date=file_data.get('fileDate', ''),
                        download_url=file_data.get('downloadUrl', ''),
                        hash_match=True
                    )
                    
                    if file_hash not in matches:
                        matches[file_hash] = []
                    matches[file_hash].append(platform_match)
            else:
                logger.warning(f"CurseForge 查询失败：{response.status_code}")
        
        except Exception as e:
            logger.error(f"CurseForge Hash 查询异常：{e}")
        
        return matches
    
    def _query_modrinth_by_hash(self, hashes: List[str], target_mc_versions: List[str],
                               target_mod_loaders: List[str]) -> Dict[str, List[PlatformMatch]]:
        """
        通过 Hash 查询 Modrinth (参考 PCL2 第 668-734 行)
        """
        if not hashes:
            return {}
        
        matches = {}
        
        try:
            # 批量查询 Hash (参考 PCL2 第 673-674 行)
            url = "https://api.modrinth.com/v2/version_files"
            payload = {
                'hashes': hashes,
                'algorithm': 'sha1'
            }
            
            logger.debug(f"Modrinth 批量查询 {len(hashes)} 个 Hash")
            response = self.session.post(url, json=payload, timeout=self.timeout)
            
            if response.status_code == 200:
                data = response.json()
                
                logger.info(f"Modrinth 匹配到 {len(data)} 个结果")
                
                # 先收集所有 project_id，用于后续查询项目是否支持目标版本
                project_versions_map = {}  # project_id -> 该版本的数据
                for file_hash, version_data in data.items():
                    project_id = version_data.get('project_id')
                    if project_id:
                        if project_id not in project_versions_map:
                            project_versions_map[project_id] = []
                        project_versions_map[project_id].append((file_hash, version_data))
                
                # 对每个项目，检查是否有任意版本支持目标版本
                for project_id, version_list in project_versions_map.items():
                    # 查询项目的所有版本，检查是否支持目标版本
                    project_supports_target = self._check_project_supports_versions(
                        project_id, target_mc_versions, target_mod_loaders
                    )
                    
                    if not project_supports_target:
                        continue
                    
                    # 如果项目支持目标版本，则匹配所有该项目的文件
                    for file_hash, version_data in version_list:
                        game_versions = version_data.get('game_versions', [])
                        mod_loaders = version_data.get('loaders', [])
                        
                        # 获取文件信息
                        files = version_data.get('files', [])
                        if not files:
                            continue
                        
                        file_info = files[0]
                        
                        # 创建匹配结果
                        platform_match = PlatformMatch(
                            platform='Modrinth',
                            project_id=project_id,
                            project_name=version_data.get('name', ''),
                            file_id=version_data.get('id', ''),
                            file_name=file_info.get('filename', ''),
                            mod_version=version_data.get('version_number', ''),
                            mc_versions=game_versions,
                            mod_loaders=mod_loaders,
                            release_date=version_data.get('date_published', ''),
                            download_url=file_info.get('url', ''),
                            hash_match=True
                        )
                        
                        if file_hash not in matches:
                            matches[file_hash] = []
                        matches[file_hash].append(platform_match)
            else:
                logger.warning(f"Modrinth 查询失败：{response.status_code}")
        
        except Exception as e:
            logger.error(f"Modrinth Hash 查询异常：{e}")
        
        return matches
    
    def _check_project_supports_versions(self, project_id: str, target_mc_versions: List[str],
                                        target_mod_loaders: List[str]) -> bool:
        """
        检查项目是否有任意版本支持目标 MC 版本和加载器
        参考 Modrinth API: GET /project/{id|slug}/version
        
        获取项目所有版本，然后检查每个版本的 game_versions 字段
        """
        try:
            # 查询项目的所有版本（不使用 game_versions 参数过滤）
            url = f"https://api.modrinth.com/v2/project/{project_id}/version"
            params = {
                'include_changelog': 'false'  # 不需要 changelog，提高性能
            }
            
            logger.debug(f"正在查询项目 {project_id} 的版本... (target_mc_versions={target_mc_versions}, target_mod_loaders={target_mod_loaders})")
            response = self.session.get(url, params=params, timeout=self.timeout)
            
            if response.status_code != 200:
                logger.debug(f"查询项目 {project_id} 版本失败：{response.status_code}")
                return False
            
            all_versions = response.json()
            logger.debug(f"项目 {project_id} 共有 {len(all_versions)} 个版本")
            
            # 检查所有版本的 game_versions
            for version in all_versions:
                version_game_versions = version.get('game_versions', [])
                version_loaders = version.get('loaders', [])
                
                # 检查是否有版本支持任意目标版本
                for target_version in target_mc_versions:
                    if target_version in version_game_versions:
                        # 检查加载器是否匹配（大小写不敏感）
                        if not target_mod_loaders or any(loader.lower() in [vl.lower() for vl in version_loaders] for loader in target_mod_loaders):
                            logger.debug(f"项目 {project_id} 的版本 {version.get('version_number', 'N/A')} 支持 {target_version}")
                            return True
            
            logger.debug(f"项目 {project_id} 不支持任何目标版本")
            return False
            
        except requests.exceptions.Timeout:
            logger.warning(f"查询项目 {project_id} 版本超时（{self.timeout}秒）")
            return False
        except requests.exceptions.RequestException as e:
            logger.warning(f"查询项目 {project_id} 版本网络错误：{e}")
            return False
        except Exception as e:
            logger.debug(f"检查项目 {project_id} 版本支持失败：{e}")
            return False
    
    def _match_by_name_batch(self, mods: List[ModInfo], target_mc_versions: List[str],
                            target_mod_loaders: List[str]) -> List[VersionCheckResult]:
        """
        通过名称批量匹配模组 (备用方案)
        """
        results = []
        
        def check_single_mod(mod: ModInfo) -> VersionCheckResult:
            result = VersionCheckResult(
                mod_name=mod.name,
                current_version=mod.version,
                current_mc_version=mod.mc_version,
                mod_type=mod.mod_type,
                file_path=mod.file_path,
                matches=[]
            )
            
            # 尝试两个平台
            platforms = ['Modrinth', 'CurseForge'] if self.platform_priority == 'modrinth' else ['CurseForge', 'Modrinth']
            
            for platform in platforms:
                if platform == 'Modrinth':
                    match = self._search_modrinth_by_name(mod, target_mc_versions, target_mod_loaders)
                else:
                    match = self._search_curseforge_by_name(mod, target_mc_versions, target_mod_loaders)
                
                if match:
                    result.matches.append(match)
                    if not result.has_match:
                        result.has_match = True
                        result.best_match = match
                        result.status = f"找到匹配 ({platform})"
            
            if not result.has_match:
                result.status = "未找到匹配"
            
            return result
        
        # 并行处理 (使用配置文件中的线程数)
        with ThreadPoolExecutor(max_workers=self.thread_count) as executor:
            futures = {executor.submit(check_single_mod, mod): mod for mod in mods}
            
            for future in as_completed(futures):
                try:
                    result = future.result()
                    results.append(result)
                except Exception as e:
                    logger.error(f"名称匹配异常：{e}")
        
        return results
    
    def _search_modrinth_by_name(self, mod: ModInfo, target_mc_versions: List[str],
                                target_mod_loaders: List[str]) -> Optional[PlatformMatch]:
        """通过名称搜索 Modrinth"""
        try:
            # 搜索项目
            search_url = "https://api.modrinth.com/v2/search"
            params = {
                'query': mod.name,
                'limit': 5
            }
            
            response = self.session.get(search_url, params=params, timeout=self.timeout)
            if response.status_code != 200:
                return None
            
            data = response.json()
            hits = data.get('hits', [])
            
            if not hits:
                return None
            
            # 检查每个项目
            for hit in hits[:3]:
                project_id = hit.get('project_id')
                if not project_id:
                    continue
                
                # 获取版本列表
                version_url = f"https://api.modrinth.com/v2/project/{project_id}/version"
                version_response = self.session.get(version_url, timeout=self.timeout)
                
                if version_response.status_code != 200:
                    continue
                
                versions = version_response.json()
                
                # 检查每个版本
                for ver in versions[:10]:
                    game_versions = ver.get('game_versions', [])
                    loaders = ver.get('loaders', [])
                    
                    if not self._version_matches(game_versions, target_mc_versions):
                        continue
                    
                    if not self._loader_matches(loaders, target_mod_loaders):
                        continue
                    
                    # 找到匹配
                    files = ver.get('files', [])
                    if not files:
                        continue
                    
                    return PlatformMatch(
                        platform='Modrinth',
                        project_id=project_id,
                        project_name=hit.get('title', ''),
                        file_id=ver.get('id', ''),
                        file_name=files[0].get('filename', ''),
                        mod_version=ver.get('version_number', ''),
                        mc_versions=game_versions,
                        mod_loaders=loaders,
                        release_date=ver.get('date_published', ''),
                        download_url=files[0].get('url', ''),
                        hash_match=False
                    )
        except Exception as e:
            logger.debug(f"Modrinth 名称搜索失败：{e}")
        
        return None
    
    def _search_curseforge_by_name(self, mod: ModInfo, target_mc_versions: List[str],
                                  target_mod_loaders: List[str]) -> Optional[PlatformMatch]:
        """通过名称搜索 CurseForge"""
        try:
            headers = {'X-Api-Key': self.curseforge_api_key} if self.curseforge_api_key else {}
            
            # 搜索项目
            search_url = "https://api.curseforge.com/v1/mods/search"
            params = {
                'gameId': 432,
                'slug': mod.name.lower().replace(' ', '-')
            }
            
            response = self.session.get(search_url, params=params, headers=headers, timeout=self.timeout)
            if response.status_code != 200:
                return None
            
            data = response.json()
            mods_data = data.get('data', [])
            
            if not mods_data:
                return None
            
            # 检查第一个匹配的项目
            mod_data = mods_data[0]
            mod_id = mod_data.get('id')
            
            if not mod_id:
                return None
            
            # 获取文件列表
            files_url = f"https://api.curseforge.com/v1/mods/{mod_id}/files"
            params = {'gameVersion': target_mc_versions[0] if target_mc_versions else None}
            
            files_response = self.session.get(files_url, params=params, headers=headers, timeout=self.timeout)
            if files_response.status_code != 200:
                return None
            
            files_data = files_response.json()
            files = files_data.get('data', [])
            
            if not files:
                return None
            
            # 检查第一个文件
            file_data = files[0]
            game_versions = file_data.get('gameVersions', [])
            
            if not self._version_matches(game_versions, target_mc_versions):
                return None
            
            return PlatformMatch(
                platform='CurseForge',
                project_id=str(mod_id),
                project_name=mod_data.get('name', ''),
                file_id=str(file_data.get('id', '')),
                file_name=file_data.get('fileName', ''),
                mod_version=file_data.get('displayName', ''),
                mc_versions=[v for v in game_versions if re.match(r'^\d+\.\d+', v)],
                mod_loaders=[],
                release_date=file_data.get('fileDate', ''),
                download_url=file_data.get('downloadUrl', ''),
                hash_match=False
            )
        except Exception as e:
            logger.debug(f"CurseForge 名称搜索失败：{e}")
        
        return None
    
    def _version_matches(self, file_versions: List[str], target_versions: List[str]) -> bool:
        """
        检查版本是否匹配
        参考 PCL2 的版本匹配逻辑 (第 659-664 行)
        
        支持所有版本号格式，包括 26.1、1.21.11 等
        """
        if not target_versions:
            return True
        
        for target_ver in target_versions:
            for file_ver in file_versions:
                # 精确匹配（包括 26.1、1.21.11 等所有格式）
                if file_ver == target_ver:
                    return True
                
                # 主版本匹配 (例如 1.20.x 或 26.x)
                if '.' in target_ver:
                    main_ver = '.'.join(target_ver.split('.')[:2])
                    if file_ver.startswith(main_ver):
                        return True
        
        return False
    
    def _loader_matches(self, file_loaders: List[str], target_loaders: List[str]) -> bool:
        """
        检查加载器是否匹配
        """
        if not target_loaders:
            return True
        
        if not file_loaders:
            return True  # 没有指定加载器时认为匹配
        
        # 标准化加载器名称
        loader_map = {
            'forge': 'Forge',
            'fabric': 'Fabric',
            'neoforge': 'NeoForge',
            'quilt': 'Quilt',
            'liteloader': 'LiteLoader'
        }
        
        normalized_file_loaders = [loader_map.get(l.lower(), l) for l in file_loaders]
        normalized_target_loaders = [loader_map.get(l.lower(), l) for l in target_loaders]
        
        # 检查是否有交集
        return bool(set(normalized_file_loaders) & set(normalized_target_loaders))


# ============== 主功能函数 ==============

def scan_mods_folder(folder_path: str) -> List[ModInfo]:
    """扫描模组文件夹"""
    mods = []
    path = Path(folder_path)
    
    if not path.exists():
        logger.error(f"文件夹不存在：{folder_path}")
        return mods
    
    jar_files = list(path.glob('*.jar'))
    
    logger.info(f"发现 {len(jar_files)} 个模组文件")
    
    for jar_file in jar_files:
        logger.debug(f"正在解析：{jar_file.name}")
        mod_info = parse_mod_jar(str(jar_file))
        if mod_info:
            # 计算 Hash
            try:
                cf_hash, mr_hash = get_file_hashes(str(jar_file))
                mod_info.curseforge_hash = cf_hash
                mod_info.modrinth_hash = mr_hash
                logger.debug(f"  Hash: CF={cf_hash}, MR={mr_hash}")
            except Exception as e:
                logger.warning(f"  Hash 计算失败：{e}")
            
            mods.append(mod_info)
            logger.info(f"  ✓ {mod_info.name} v{mod_info.version} ({mod_info.mod_type})")
    
    return mods


def get_target_mod_loaders(mod_types: List[str]) -> List[str]:
    """
    获取目标加载器列表
    参考 PCL2 的 GetTargetModLoaders (第 866-874 行)
    """
    loaders = []
    
    if 'Forge' in mod_types:
        loaders.append('Forge')
    if 'NeoForge' in mod_types:
        loaders.append('NeoForge')
    if 'Fabric' in mod_types:
        loaders.append('Fabric')
    if 'Quilt' in mod_types:
        loaders.append('Quilt')
    
    # 如果没有指定加载器，允许所有类型
    if not loaders:
        loaders = ['Forge', 'NeoForge', 'Fabric', 'Quilt', 'LiteLoader']
    
    return loaders


def print_summary(results: List[VersionCheckResult]):
    """打印摘要信息"""
    total = len(results)
    has_matches = sum(1 for r in results if r.has_match)
    
    print("\n" + "="*80)
    print("检测结果摘要")
    print("="*80)
    print(f"总模组数：{total}")
    print(f"找到匹配的模组数：{has_matches}")
    print(f"未找到匹配的模组数：{total - has_matches}")
    print("="*80)
    
    if has_matches > 0:
        print("\n找到匹配的模组:")
        print("-"*80)
        for result in results:
            if result.has_match and result.best_match:
                match = result.best_match
                print(f"  - {result.mod_name}")
                print(f"    当前版本：{result.current_version} (MC {result.current_mc_version})")
                print(f"    匹配版本：{match.mod_version} (MC {', '.join(match.mc_versions[:3])})")
                print(f"    平台：{match.platform} {'[Hash]' if match.hash_match else '[名称]'}")
                print(f"    加载器：{', '.join(match.mod_loaders) if match.mod_loaders else '未知'}")
                print()
    
    if has_matches < total:
        print("\n未找到匹配的模组:")
        print("-"*80)
        for result in results:
            if not result.has_match:
                print(f"  - {result.mod_name} ({result.mod_type})")


def save_to_csv(results: List[VersionCheckResult], output_path: str):
    """将结果保存到 CSV"""
    if not results:
        logger.warning("没有结果需要保存")
        return
    
    fieldnames = [
        'mod_name', 'current_version', 'current_mc_version', 'mod_type',
        'has_match', 'match_platform', 'match_version', 'match_mc_versions',
        'match_mod_loaders', 'hash_match', 'status'
    ]
    # 字段说明：模组名称，当前版本，当前 MC 版本，模组类型，
    #          是否有匹配，匹配平台，匹配版本，匹配版本支持的 MC 版本，
    #          匹配版本支持的加载器，是否为 Hash 匹配，状态
    
    with open(output_path, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        
        # 添加中文注释行
        comments = {
            'mod_name': '模组名称',
            'current_version': '当前版本',
            'current_mc_version': '当前 MC 版本',
            'mod_type': '模组类型',
            'has_match': '是否有匹配',
            'match_platform': '匹配平台',
            'match_version': '匹配版本',
            'match_mc_versions': '匹配版本支持的 MC 版本',
            'match_mod_loaders': '匹配版本支持的加载器',
            'hash_match': '是否为 Hash 匹配',
            'status': '状态'
        }
        writer.writerow(comments)
        
        for result in results:
            row = {
                'mod_name': result.mod_name,
                'current_version': result.current_version,
                'current_mc_version': result.current_mc_version,
                'mod_type': result.mod_type,
                'has_match': result.has_match,
                'match_platform': result.best_match.platform if result.best_match else '',
                'match_version': result.best_match.mod_version if result.best_match else '',
                'match_mc_versions': ';'.join(result.best_match.mc_versions[:3]) if result.best_match else '',
                'match_mod_loaders': ';'.join(result.best_match.mod_loaders) if result.best_match else '',
                'hash_match': result.best_match.hash_match if result.best_match else False,
                'status': result.status
            }
            writer.writerow(row)
    
    logger.info(f"结果已保存到：{output_path}")
    print(f"\n结果已保存到：{output_path}")


def main():
    """主函数"""
    print("="*80)
    print("Minecraft Mod 版本检测工具 v2 (参考 PCL2 逻辑)")
    print("="*80)
    print(f"检测时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    # 加载配置
    config = load_config()
    logger.info(f"已加载配置文件：{CONFIG_FILE}")
    logger.info(f"平台优先级：{config.get('platform_priority', 'modrinth')}")
    
    # 初始化缓存
    cache = ModCache()
    
    # 获取模组文件夹路径
    mods_folder = input("请输入模组文件夹路径 (直接回车使用默认路径 './mods'): ").strip()
    if not mods_folder:
        mods_folder = './mods'
    
    if not os.path.exists(mods_folder):
        logger.warning(f"模组文件夹不存在，创建：{mods_folder}")
        os.makedirs(mods_folder, exist_ok=True)
    
    # 获取目标版本
    latest_mc_versions = get_version_input()
    logger.info(f"将检测以下 Minecraft 版本：{', '.join(latest_mc_versions[:5])}")
    
    # 扫描模组
    mods = scan_mods_folder(mods_folder)
    
    if not mods:
        logger.warning("未找到任何模组文件")
        print("未找到任何模组文件")
        return
    
    # 获取目标加载器
    all_mod_types = list(set(m.mod_type for m in mods))
    target_loaders = get_target_mod_loaders(all_mod_types)
    logger.info(f"目标加载器：{target_loaders}")
    
    # 创建匹配器
    matcher = ModPlatformMatcher(config, cache)
    
    # 批量匹配
    print(f"\n开始匹配 {len(mods)} 个模组...")
    results = matcher.match_mods_batch(mods, latest_mc_versions, target_loaders)
    
    # 打印摘要
    print_summary(results)
    
    # 保存结果
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    csv_filename = f'mod_update_report_{timestamp}.csv'
    save_to_csv(results, csv_filename)
    
    # 保存缓存
    cache.save_cache()
    
    logger.info("检测完成!")
    print("\n检测完成!")


def load_config() -> Dict:
    """加载配置文件"""
    DEFAULT_CONFIG = {
        'curseforge_api_key': '',
        'platform_priority': 'modrinth',
        'thread_count': 5,
        'timeout_seconds': 5,
        'log_level': 'INFO'
    }
    
    try:
        if CONFIG_FILE.exists():
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                config = json.load(f)
                for key, value in DEFAULT_CONFIG.items():
                    if key not in config:
                        config[key] = value
            logger.debug(f"配置文件加载成功：{CONFIG_FILE}")
            return config
        else:
            logger.warning("配置文件不存在，创建默认配置文件")
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(DEFAULT_CONFIG, f, indent=4, ensure_ascii=False)
            return DEFAULT_CONFIG
    except Exception as e:
        logger.error(f"加载配置文件失败：{e}，使用默认配置")
        return DEFAULT_CONFIG


def get_version_input() -> List[str]:
    """获取用户输入的版本列表"""
    print("\n请选择版本获取方式:")
    print("1. 自动获取最新 Minecraft 版本")
    print("2. 手动指定 Minecraft 版本")
    print("3. 使用常用版本列表 (1.21.11, 1.21.10, 1.21.9, 1.21, 1.20)")
    
    choice = input("\n请输入选项 (1/2/3，默认 1): ").strip()
    
    if choice == '2':
        print("\n请输入要检测的 Minecraft 版本，多个版本用逗号或空格分隔")
        version_str = input("输入版本：").strip()
        
        if not version_str:
            return ["1.21.11", "1.21.10", "1.21.9", "1.21", "1.20"]
        
        versions = [v.strip() for v in re.split(r'[,\s]+', version_str) if v.strip()]
        return versions if versions else ["1.21.11", "1.21.10", "1.21.9", "1.21", "1.20"]
    
    elif choice == '3':
        return ["1.21.11", "1.21.10", "1.21.9", "1.21", "1.20"]
    
    else:
        return get_latest_minecraft_versions()


def get_latest_minecraft_versions() -> List[str]:
    """获取最新的 Minecraft 版本"""
    try:
        logger.info("正在获取最新的 Minecraft 版本...")
        response = requests.get(
            "https://launchermeta.mojang.com/mc/game/version_manifest.json",
            timeout=10
        )
        response.raise_for_status()
        data = response.json()
        
        versions = []
        for v in data.get('versions', [])[:50]:
            if v['type'] == 'release':
                versions.append(v['id'])
        
        latest = versions[:1] if versions else []
        logger.info(f"获取到最新版本：{latest[0] if latest else '无'}")
        return latest
    except Exception as e:
        logger.error(f"获取 Minecraft 版本失败：{e}")
        return ["1.20", "1.19", "1.18"]


if __name__ == '__main__':
    main()
