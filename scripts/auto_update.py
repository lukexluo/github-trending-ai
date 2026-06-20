#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GitHub Trending AI & Agent — 全自动更新脚本
每天 23:58 自动运行，获取最新 GitHub 数据并生成报告

使用方式：
  python3 scripts/auto_update.py

环境变量（可选）：
  GITHUB_TOKEN — GitHub 个人访问令牌，提高 API 限额

功能：
  1. 读取历史数据 (github-trending-ai-history.json)
  2. 通过 GitHub API 获取今日活跃 AI/Agent/LLM 项目
  3. 计算增量 (今日 - 昨日)
  4. 生成三个 HTML 文件：日期归档页、最新报告页、首页
  5. 更新历史记录文件
"""

import os
import sys
import json
import re
import time
import argparse
from datetime import datetime, timedelta
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from pathlib import Path
from html import escape

# ==================== 配置 ====================
BASE_DIR = Path(__file__).parent.parent.resolve()
HISTORY_FILE = BASE_DIR / "github-trending-ai-history.json"
OUTPUT_DIR = BASE_DIR

# GitHub API
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
API_BASE = "https://api.github.com"
HEADERS = {
    "Accept": "application/vnd.github.v3+json",
    "User-Agent": "GitHub-Trending-AI-Updater/1.0"
}
if GITHUB_TOKEN:
    HEADERS["Authorization"] = f"token {GITHUB_TOKEN}"

# 语言颜色映射
LANG_COLORS = {
    "Python": "#3572A5", "TypeScript": "#2b7489", "JavaScript": "#f1e05a",
    "Rust": "#dea584", "Go": "#00ADD8", "C++": "#f34b7d", "C#": "178600",
    "Java": "#b07219", "PHP": "#4F5D95", "Ruby": "#701516", "HTML": "#e34c26",
    "CSS": "#563d7c", "Swift": "#ffac45", "Kotlin": "#A97BFF", "Shell": "#89e051",
    "N/A": "#6b7280",
}

# 搜索关键词（用于发现新仓库）
SEARCH_KEYWORDS = ["AI", "agent", "LLM", "MCP", "codex", "automation", "chatbot"]

# ==================== API 工具函数 ====================

def api_call(endpoint, params=None, method="GET", retries=3, timeout=30):
    """调用 GitHub API，带重试机制，返回 JSON 或 None"""
    from urllib.parse import urlencode
    url = f"{API_BASE}{endpoint}"
    if params:
        query = urlencode(params)
        url = f"{url}?{query}"
    
    req = Request(url, headers=HEADERS, method=method)
    
    for attempt in range(1, retries + 1):
        try:
            with urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except HTTPError as e:
            if e.code == 403:
                print(f"  [API Error] {e.code} {e.reason} for {url}")
                print("  [Hint] Rate limit exceeded. Set GITHUB_TOKEN to increase quota.")
                return None
            elif e.code == 404:
                return None
            elif e.code in (502, 503, 504):
                if attempt < retries:
                    wait = 2 ** attempt
                    print(f"  [Retry {attempt}/{retries}] Server error {e.code}, waiting {wait}s...")
                    time.sleep(wait)
                    continue
            print(f"  [API Error] {e.code} {e.reason} for {url}")
            return None
        except Exception as e:
            if attempt < retries:
                wait = 2 ** attempt
                print(f"  [Retry {attempt}/{retries}] {e}, waiting {wait}s...")
                time.sleep(wait)
                continue
            print(f"  [Request Error] {e}")
            return None
    return None


def search_repos(query, per_page=30):
    """搜索 GitHub 仓库"""
    params = {
        "q": query,
        "sort": "stars",
        "order": "desc",
        "per_page": str(per_page)
    }
    data = api_call("/search/repositories", params)
    if data and "items" in data:
        return data["items"]
    return []


def get_repo(owner, repo):
    """获取单个仓库详细信息"""
    return api_call(f"/repos/{owner}/{repo}")


# ==================== 数据获取 ====================

def load_history():
    """读取历史数据"""
    if HISTORY_FILE.exists():
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[Warning] Failed to load history: {e}")
    return {}


def save_history(history):
    """保存历史数据"""
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)
    print(f"[Saved] {HISTORY_FILE}")


def infer_tags(name, description, lang):
    """根据仓库名称和描述推断标签"""
    tags = []
    text = f"{name} {description or ''}".lower()
    
    if "agent" in text:
        tags.append("agent")
    if any(k in text for k in ["ai", "llm", "gpt", "claude", "openai", "gemini"]):
        tags.append("AI")
    if "mcp" in text:
        tags.append("MCP")
    if "codex" in text:
        tags.append("codex")
    if any(k in text for k in ["coding", "code", "programming", "developer"]):
        tags.append("coding")
    if "memory" in text:
        tags.append("memory")
    if "skill" in text:
        tags.append("skill")
    if any(k in text for k in ["automation", "automate", "bot", "workflow"]):
        tags.append("automation")
    if not tags:
        tags.append("NEW")
    return tags


def fetch_today_data(today_str, history):
    """获取今日数据，返回排序后的仓库字典"""
    yesterday = (datetime.strptime(today_str, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
    
    # 收集所有已知仓库（从历史数据）
    known_repos = set()
    if yesterday in history:
        known_repos.update(history[yesterday].keys())
    for date, repos in history.items():
        known_repos.update(repos.keys())
    
    # 获取已知仓库的当前状态
    repo_data = {}
    
    # 限制 API 调用
    max_known = 50 if GITHUB_TOKEN else 15
    known_list = sorted(list(known_repos))[:max_known]
    
    print(f"[1/4] Fetching stats for {len(known_list)} known repos...")
    for i, full_name in enumerate(known_list, 1):
        parts = full_name.split("/")
        if len(parts) == 2:
            owner, repo = parts
            data = get_repo(owner, repo)
            if data:
                repo_data[full_name] = {
                    "stars": data.get("stargazers_count", 0),
                    "forks": data.get("forks_count", 0),
                    "language": data.get("language") or "N/A",
                    "description": data.get("description") or "AI/开源项目，值得关注。",
                    "owner": owner,
                    "repo": repo,
                }
        if i % 10 == 0:
            print(f"  ... {i}/{len(known_list)}")
        time.sleep(0.3)
    
    # 搜索新仓库
    print(f"[2/4] Searching for new repos...")
    for kw in SEARCH_KEYWORDS[:4]:  # 限制搜索次数
        query = f"{kw} pushed:>={yesterday} stars:>1"
        items = search_repos(query, per_page=15)
        for item in items:
            full_name = item.get("full_name", "")
            if full_name not in repo_data:
                repo_data[full_name] = {
                    "stars": item.get("stargazers_count", 0),
                    "forks": item.get("forks_count", 0),
                    "language": item.get("language") or "N/A",
                    "description": item.get("description") or "AI/开源项目，值得关注。",
                    "owner": item.get("owner", {}).get("login", ""),
                    "repo": item.get("name", ""),
                }
        time.sleep(1)
    
    # 计算增量
    print(f"[3/4] Calculating deltas...")
    today_data = {}
    for full_name, current in repo_data.items():
        prev_stars = 0
        prev_forks = 0
        if yesterday in history and full_name in history[yesterday]:
            prev_stars = history[yesterday][full_name].get("stars", 0)
            prev_forks = history[yesterday][full_name].get("forks", 0)
        
        delta_stars = current["stars"] - prev_stars
        delta_forks = current["forks"] - prev_forks
        
        tags = infer_tags(current["repo"], current["description"], current["language"])
        
        today_data[full_name] = {
            "stars": current["stars"],
            "forks": current["forks"],
            "language": current["language"],
            "description": current["description"],
            "owner": current["owner"],
            "repo": current["repo"],
            "delta_stars": delta_stars,
            "delta_forks": delta_forks,
            "tags": tags,
        }
    
    # 按增量排序
    sorted_data = dict(sorted(today_data.items(), key=lambda x: x[1]["delta_stars"], reverse=True))
    return sorted_data


# ==================== HTML 生成 ====================

def escape_attr(s):
    """HTML 属性转义"""
    return escape(str(s)) if s else ""


def format_number(n):
    """格式化数字（1.2k 等）"""
    if n >= 1000:
        return f"{n/1000:.1f}k"
    return str(n)


def generate_card(repo, rank, is_today=True):
    """生成单个仓库卡片 HTML"""
    full_name = f"{repo['owner']}/{repo['repo']}"
    url = f"https://github.com/{escape_attr(full_name)}"
    
    rank_class = ""
    if rank == 1:
        rank_class = " top1"
    elif rank == 2:
        rank_class = " top2"
    elif rank == 3:
        rank_class = " top3"
    
    tags_html = ""
    for tag in repo.get("tags", ["NEW"]):
        tag_class = f"tag-{tag.lower()}" if tag.lower() in ["ai", "agent", "coding", "new"] else ""
        tags_html += f'<span class="tag {tag_class}">{escape(tag)}</span>'
    
    lang = repo.get("language", "N/A")
    lang_color = LANG_COLORS.get(lang, "#6b7280")
    
    delta_stars_str = format_number(repo.get("delta_stars", 0))
    delta_forks_str = format_number(repo.get("delta_forks", 0))
    stars_str = format_number(repo["stars"])
    forks_str = format_number(repo["forks"])
    
    desc = escape(repo.get("description", "") or "AI/开源项目，值得关注。")
    
    tags_attr = " ".join(repo.get("tags", ["NEW"]))
    
    return f'''    <a href="{url}" target="_blank" class="card" data-tags="{escape_attr(tags_attr)}" data-lang="{escape_attr(lang)}" data-name="{escape_attr(repo['repo'])}">
        <div class="card-header">
            <div class="card-rank{rank_class}">{rank}</div>
            <div class="card-tags">{tags_html}</div>
        </div>
        <div class="card-name"><span class="owner">{escape(repo['owner'])}</span><span class="slash">/</span><span class="repo">{escape(repo['repo'])}</span></div>
        <div class="card-desc">{desc}</div>
        <div class="card-delta">
            <span class="delta-stars" style="color:var(--accent-green)">▲ +{delta_stars_str}</span>
            <span class="delta-forks">🔀 +{delta_forks_str}</span>
        </div>
        <div class="card-stats">
            <div class="stat stars"><svg fill="currentColor" viewBox="0 0 24 24"><path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z"/></svg><span class="stat-value">{stars_str}</span></div>
            <div class="stat forks"><svg fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M7 3a2 2 0 00-2 2v14a2 2 0 002 2h10a2 2 0 002-2V5a2 2 0 00-2-2H7z"/><path d="M12 12v.01"/></svg><span class="stat-value">{forks_str}</span></div>
            <div class="stat lang"><span class="lang-dot" style="background:{lang_color}"></span>{escape(lang)}</div>
        </div>
    </a>'''


def generate_report_page_html(today_str, today_data, history, is_archive=False):
    """生成报告页 HTML（日期归档或最新报告）"""
    
    # 取前 15 个作为今日增量
    today_items = list(today_data.items())[:15]
    
    # 取前 15 个作为本周增量（如果有多天数据，否则用今日数据）
    week_items = today_items  # 简化：本周 = 今日（后续可改进）
    
    today_cards = "\n".join(generate_card(repo, i+1, True) for i, (k, repo) in enumerate(today_items))
    week_cards = "\n".join(generate_card(repo, i+1, False) for i, (k, repo) in enumerate(week_items))
    
    # 计算统计数据
    total_repos = len(today_data)
    new_count = sum(1 for r in today_data.values() if r.get("delta_stars", 0) > 0)
    total_delta_stars = sum(r.get("delta_stars", 0) for r in today_data.values())
    langs = set(r.get("language", "N/A") for r in today_data.values())
    
    # 日期选择器选项
    all_dates = sorted(history.keys(), reverse=True)
    date_options = "\n".join(f'<option value="{d}"{" selected" if d == today_str else ""}>{d}</option>' for d in all_dates)
    if not date_options:
        date_options = f'<option value="{today_str}" selected>{today_str}</option>'
    
    # 生成标签筛选计数
    tag_counts = {}
    lang_counts = {}
    for repo in today_data.values():
        for tag in repo.get("tags", []):
            tag_counts[tag] = tag_counts.get(tag, 0) + 1
        lang = repo.get("language", "N/A")
        lang_counts[lang] = lang_counts.get(lang, 0) + 1
    
    # 构建筛选 chips
    chips_html = f'<button class="chip active" data-filter="all" onclick="setFilter(this, \'all\')">全部 <span class="count">{total_repos}</span></button>'
    for tag, count in sorted(tag_counts.items(), key=lambda x: -x[1])[:3]:
        chips_html += f'\n            <button class="chip" data-filter="{escape_attr(tag)}" onclick="setFilter(this, \'{escape_attr(tag)}\')">{escape(tag)} <span class="count">{count}</span></button>'
    for lang, count in sorted(lang_counts.items(), key=lambda x: -x[1])[:3]:
        chips_html += f'\n            <button class="chip" data-filter="{escape_attr(lang)}" onclick="setFilter(this, \'{escape_attr(lang)}\')">{escape(lang)} <span class="count">{count}</span></button>'
    
    title_prefix = f"{today_str} · 归档" if is_archive else "每日增量追踪"
    archive_title = f"GitHub Trending AI · {today_str} · 归档" if is_archive else "GitHub Trending AI & Agent — 每日增量追踪"
    
    html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{archive_title}</title>
    <meta name="description" content="{today_str} 每日追踪报告：GitHub 上新增 Star/Fork 最活跃的 AI、Agent、LLM 相关开源项目。">
    <meta name="keywords" content="GitHub Trending, AI, Agent, LLM, Open Source, {today_str}">
    <meta name="author" content="Kimi Work">
    <meta property="og:title" content="GitHub Trending AI · {today_str}">
    <meta property="og:description" content="{today_str} 每日追踪报告：GitHub 上新增 Star/Fork 最活跃的 AI、Agent、LLM 相关开源项目">
    <meta property="og:type" content="{'article' if is_archive else 'website'}">
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
    <style>
        :root {{
            --bg-primary: #0a0e1a; --bg-secondary: #111827; --bg-card: rgba(17, 24, 39, 0.85);
            --bg-card-hover: rgba(31, 41, 55, 0.9); --border: rgba(55, 65, 81, 0.5);
            --text-primary: #f3f4f6; --text-secondary: #9ca3af; --text-muted: #6b7280;
            --accent-cyan: #06b6d4; --accent-purple: #a855f7; --accent-pink: #ec4899;
            --accent-orange: #f97316; --accent-green: #10b981; --accent-yellow: #f59e0b;
            --gradient-1: linear-gradient(135deg, #06b6d4 0%, #a855f7 50%, #ec4899 100%);
            --shadow-lg: 0 8px 40px rgba(0, 0, 0, 0.5);
        }}
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif; background: var(--bg-primary); color: var(--text-primary); line-height: 1.6; min-height: 100vh; overflow-x: hidden; }}
        .bg-mesh {{ position: fixed; top: 0; left: 0; right: 0; bottom: 0; z-index: 0; pointer-events: none; background: radial-gradient(ellipse at 20% 20%, rgba(6, 182, 212, 0.08) 0%, transparent 50%), radial-gradient(ellipse at 80% 80%, rgba(168, 85, 247, 0.08) 0%, transparent 50%), radial-gradient(ellipse at 50% 50%, rgba(236, 72, 153, 0.05) 0%, transparent 60%); }}
        .bg-mesh::before {{ content: ''; position: absolute; top: -50%; left: -50%; width: 200%; height: 200%; background: url("data:image/svg+xml,%3Csvg width='60' height='60' viewBox='0 0 60 60' xmlns='http://www.w3.org/2000/svg'%3E%3Cg fill='none' fill-rule='evenodd'%3E%3Cg fill='%23374151' fill-opacity='0.15'%3E%3Cpath d='M36 34v-4h-2v4h-4v2h4v4h2v-4h4v-2h-4zm0-30V0h-2v4h-4v2h4v4h2V6h4V4h-4zM6 34v-4H4v4H0v2h4v4h2v-4h4v-2H6zM6 4V0H4v4H0v2h4v4h2V6h4V4H6z'/%3E%3C/g%3E%3C/g%3E%3C/svg%3E"); opacity: 0.4; animation: meshMove 120s linear infinite; }}
        @keyframes meshMove {{ 0% {{ transform: translate(0, 0); }} 100% {{ transform: translate(60px, 60px); }} }}
        .header {{ position: relative; z-index: 1; padding: 48px 24px 32px; text-align: center; background: linear-gradient(180deg, rgba(10,14,26,0.95) 0%, transparent 100%); }}
        .header-badge {{ display: inline-flex; align-items: center; gap: 8px; padding: 8px 20px; border-radius: 100px; background: rgba(6, 182, 212, 0.1); border: 1px solid rgba(6, 182, 212, 0.3); color: var(--accent-cyan); font-size: 13px; font-weight: 500; letter-spacing: 0.5px; text-transform: uppercase; margin-bottom: 20px; cursor: default; }}
        .header-badge .pulse {{ width: 8px; height: 8px; border-radius: 50%; background: var(--accent-cyan); box-shadow: 0 0 8px var(--accent-cyan); animation: pulse 2s ease-in-out infinite; }}
        @keyframes pulse {{ 0%, 100% {{ opacity: 1; transform: scale(1); }} 50% {{ opacity: 0.5; transform: scale(0.8); }} }}
        .header h1 {{ font-size: 42px; font-weight: 800; background: var(--gradient-1); -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text; margin-bottom: 12px; animation: fadeInUp 0.8s ease-out 0.1s both; }}
        .header p {{ color: var(--text-secondary); font-size: 16px; max-width: 560px; margin: 0 auto 24px; animation: fadeInUp 0.8s ease-out 0.2s both; }}
        .header-meta {{ display: flex; justify-content: center; gap: 24px; flex-wrap: wrap; animation: fadeInUp 0.8s ease-out 0.3s both; }}
        .meta-item {{ display: flex; align-items: center; gap: 6px; font-size: 13px; color: var(--text-muted); font-family: 'JetBrains Mono', monospace; }}
        .top-nav {{ position: relative; z-index: 1; display: flex; justify-content: center; gap: 12px; padding: 0 24px 16px; flex-wrap: wrap; animation: fadeInUp 0.8s ease-out 0.35s both; }}
        .top-nav a {{ display: flex; align-items: center; gap: 6px; padding: 8px 16px; border-radius: 10px; background: var(--bg-card); border: 1px solid var(--border); color: var(--text-secondary); font-size: 13px; font-weight: 500; text-decoration: none; transition: all 0.3s ease; }}
        .top-nav a:hover {{ background: var(--bg-card-hover); border-color: rgba(6, 182, 212, 0.4); color: var(--text-primary); transform: translateY(-2px); }}
        .date-selector {{ display: flex; justify-content: center; align-items: center; gap: 12px; padding: 0 24px 24px; position: relative; z-index: 1; animation: fadeInUp 0.8s ease-out 0.35s both; }}
        .date-selector select {{ padding: 10px 16px; border-radius: 10px; border: 1px solid var(--border); background: var(--bg-card); color: var(--text-primary); font-size: 14px; font-family: 'JetBrains Mono', monospace; cursor: pointer; outline: none; }}
        .filter-bar {{ position: relative; z-index: 1; max-width: 1200px; margin: 0 auto 24px; padding: 0 24px; display: flex; gap: 12px; flex-wrap: wrap; align-items: center; animation: fadeInUp 0.8s ease-out 0.38s both; }}
        .search-box {{ flex: 1; min-width: 200px; position: relative; }}
        .search-box input {{ width: 100%; padding: 12px 16px 12px 44px; border-radius: 12px; border: 1px solid var(--border); background: var(--bg-card); color: var(--text-primary); font-size: 14px; font-family: inherit; outline: none; transition: all 0.3s ease; }}
        .search-box input:focus {{ border-color: rgba(6, 182, 212, 0.5); box-shadow: 0 0 0 3px rgba(6, 182, 212, 0.1); }}
        .search-box input::placeholder {{ color: var(--text-muted); }}
        .search-box .search-icon {{ position: absolute; left: 14px; top: 50%; transform: translateY(-50%); color: var(--text-muted); pointer-events: none; }}
        .search-box .search-icon svg {{ width: 18px; height: 18px; }}
        .filter-chips {{ display: flex; gap: 8px; flex-wrap: wrap; }}
        .chip {{ padding: 8px 14px; border-radius: 10px; border: 1px solid var(--border); background: var(--bg-card); color: var(--text-secondary); font-size: 13px; font-weight: 500; cursor: pointer; transition: all 0.3s ease; font-family: inherit; white-space: nowrap; }}
        .chip:hover {{ background: var(--bg-card-hover); border-color: rgba(6, 182, 212, 0.4); color: var(--text-primary); }}
        .chip.active {{ background: var(--gradient-1); border-color: transparent; color: white; box-shadow: 0 4px 20px rgba(168, 85, 247, 0.3); }}
        .chip .count {{ display: inline-flex; align-items: center; justify-content: center; min-width: 18px; height: 18px; padding: 0 5px; border-radius: 100px; background: rgba(255,255,255,0.2); font-size: 10px; font-weight: 700; margin-left: 6px; }}
        .stats-panel {{ position: relative; z-index: 1; max-width: 1200px; margin: 0 auto 24px; padding: 0 24px; display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 12px; animation: fadeInUp 0.8s ease-out 0.4s both; }}
        .stat-card {{ background: var(--bg-card); border: 1px solid var(--border); border-radius: 14px; padding: 16px; text-align: center; transition: all 0.3s ease; }}
        .stat-card:hover {{ border-color: rgba(6, 182, 212, 0.3); transform: translateY(-2px); }}
        .stat-card .stat-value {{ font-size: 22px; font-weight: 700; font-family: 'JetBrains Mono', monospace; background: var(--gradient-1); -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text; }}
        .stat-card .stat-label {{ font-size: 12px; color: var(--text-muted); margin-top: 4px; text-transform: uppercase; letter-spacing: 0.5px; }}
        .tabs {{ position: relative; z-index: 1; display: flex; justify-content: center; gap: 8px; padding: 0 24px 32px; animation: fadeInUp 0.8s ease-out 0.42s both; }}
        .tab-btn {{ padding: 12px 28px; border-radius: 12px; border: 1px solid var(--border); background: var(--bg-card); color: var(--text-secondary); font-size: 14px; font-weight: 600; cursor: pointer; transition: all 0.3s ease; font-family: inherit; display: flex; align-items: center; gap: 8px; }}
        .tab-btn:hover {{ background: var(--bg-card-hover); border-color: rgba(6, 182, 212, 0.4); color: var(--text-primary); transform: translateY(-2px); }}
        .tab-btn.active {{ background: var(--gradient-1); border-color: transparent; color: white; box-shadow: 0 4px 20px rgba(168, 85, 247, 0.3); }}
        .tab-btn .count {{ display: inline-flex; align-items: center; justify-content: center; min-width: 22px; height: 22px; padding: 0 6px; border-radius: 100px; background: rgba(255,255,255,0.2); font-size: 11px; font-weight: 700; }}
        .content {{ position: relative; z-index: 1; max-width: 1200px; margin: 0 auto; padding: 0 24px 64px; }}
        .section {{ display: none; animation: fadeIn 0.6s ease-out; }}
        .section.active {{ display: block; }}
        @keyframes fadeIn {{ from {{ opacity: 0; transform: translateY(12px); }} to {{ opacity: 1; transform: translateY(0); }} }}
        @keyframes fadeInUp {{ from {{ opacity: 0; transform: translateY(20px); }} to {{ opacity: 1; transform: translateY(0); }} }}
        @keyframes fadeInDown {{ from {{ opacity: 0; transform: translateY(-10px); }} to {{ opacity: 1; transform: translateY(0); }} }}
        .section-title {{ display: flex; align-items: center; gap: 12px; margin-bottom: 24px; padding: 0 4px; }}
        .section-title h2 {{ font-size: 20px; font-weight: 700; color: var(--text-primary); }}
        .section-title .line {{ flex: 1; height: 1px; background: linear-gradient(90deg, var(--border), transparent); }}
        .section-title .badge {{ padding: 4px 12px; border-radius: 8px; font-size: 12px; font-weight: 600; background: rgba(6, 182, 212, 0.1); color: var(--accent-cyan); border: 1px solid rgba(6, 182, 212, 0.2); }}
        .section-title .badge.week {{ background: rgba(249, 115, 22, 0.1); color: var(--accent-orange); border: 1px solid rgba(249, 115, 22, 0.2); }}
        .cards-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(360px, 1fr)); gap: 20px; }}
        @media (max-width: 768px) {{ .cards-grid {{ grid-template-columns: 1fr; }} .header h1 {{ font-size: 28px; }} .filter-bar {{ flex-direction: column; align-items: stretch; }} .tabs {{ flex-wrap: wrap; }} .stats-panel {{ grid-template-columns: repeat(2, 1fr); }} }}
        .card {{ background: var(--bg-card); border: 1px solid var(--border); border-radius: 16px; padding: 24px; transition: all 0.4s cubic-bezier(0.4, 0, 0.2, 1); position: relative; overflow: hidden; backdrop-filter: blur(12px); cursor: pointer; text-decoration: none; display: block; }}
        .card::before {{ content: ''; position: absolute; top: 0; left: 0; right: 0; height: 3px; background: var(--gradient-1); opacity: 0; transition: opacity 0.3s ease; }}
        .card:hover {{ transform: translateY(-4px) scale(1.01); border-color: rgba(6, 182, 212, 0.3); box-shadow: var(--shadow-lg), 0 0 40px rgba(6, 182, 212, 0.08); background: var(--bg-card-hover); }}
        .card:hover::before {{ opacity: 1; }}
        .card.hidden {{ display: none; }}
        .card-header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px; min-height: 32px; }}
        .card-rank {{ display: flex; align-items: center; justify-content: center; width: 32px; height: 32px; border-radius: 10px; font-size: 13px; font-weight: 800; font-family: 'JetBrains Mono', monospace; background: rgba(6, 182, 212, 0.1); color: var(--accent-cyan); border: 1px solid rgba(6, 182, 212, 0.2); flex-shrink: 0; }}
        .card-rank.top1 {{ background: rgba(245, 158, 11, 0.15); color: var(--accent-yellow); border-color: rgba(245, 158, 11, 0.3); }}
        .card-rank.top2 {{ background: rgba(156, 163, 175, 0.15); color: #d1d5db; border-color: rgba(156, 163, 175, 0.3); }}
        .card-rank.top3 {{ background: rgba(249, 115, 22, 0.15); color: var(--accent-orange); border-color: rgba(249, 115, 22, 0.3); }}
        .card-tags {{ display: flex; gap: 4px; flex-wrap: nowrap; overflow: hidden; max-height: 28px; align-items: center; justify-content: flex-end; margin-left: 8px; }}
        .tag {{ padding: 2px 7px; border-radius: 6px; font-size: 10px; font-weight: 600; letter-spacing: 0.3px; text-transform: uppercase; white-space: nowrap; flex-shrink: 0; }}
        .tag-ai {{ background: rgba(168, 85, 247, 0.15); color: #c084fc; border: 1px solid rgba(168, 85, 247, 0.2); }}
        .tag-agent {{ background: rgba(6, 182, 212, 0.15); color: #67e8f9; border: 1px solid rgba(6, 182, 212, 0.2); }}
        .tag-coding {{ background: rgba(249, 115, 22, 0.15); color: #fb923c; border: 1px solid rgba(249, 115, 22, 0.2); }}
        .tag-new {{ background: rgba(16, 185, 129, 0.15); color: #34d399; border: 1px solid rgba(16, 185, 129, 0.2); }}
        .tag {{ background: rgba(107, 114, 128, 0.15); color: #9ca3af; border: 1px solid rgba(107, 114, 128, 0.2); }}
        .card-name {{ font-size: 17px; font-weight: 700; color: var(--text-primary); margin-bottom: 6px; display: flex; align-items: center; gap: 8px; word-break: break-all; }}
        .card-name .owner {{ color: var(--text-muted); font-weight: 500; }}
        .card-name .slash {{ color: var(--text-muted); opacity: 0.5; }}
        .card-name .repo {{ color: var(--accent-cyan); }}
        .card:hover .card-name .repo {{ color: #67e8f9; }}
        .card-desc {{ font-size: 13px; color: var(--text-secondary); line-height: 1.6; margin-bottom: 12px; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }}
        .card-delta {{ display: flex; gap: 16px; margin-bottom: 12px; padding: 8px 12px; border-radius: 8px; background: rgba(16, 185, 129, 0.05); border: 1px solid rgba(16, 185, 129, 0.1); }}
        .delta-stars {{ font-family: 'JetBrains Mono', monospace; font-size: 13px; font-weight: 700; }}
        .delta-forks {{ font-family: 'JetBrains Mono', monospace; font-size: 13px; color: var(--accent-cyan); font-weight: 600; }}
        .card-stats {{ display: flex; gap: 16px; padding-top: 14px; border-top: 1px solid var(--border); }}
        .stat {{ display: flex; align-items: center; gap: 6px; font-size: 13px; color: var(--text-muted); font-family: 'JetBrains Mono', monospace; }}
        .stat svg {{ width: 16px; height: 16px; opacity: 0.6; }}
        .stat.stars {{ color: var(--accent-yellow); }}
        .stat.forks {{ color: var(--accent-cyan); }}
        .stat.lang {{ color: var(--accent-purple); }}
        .stat-value {{ font-weight: 600; }}
        .lang-dot {{ width: 10px; height: 10px; border-radius: 50%; display: inline-block; }}
        .footer {{ position: relative; z-index: 1; text-align: center; padding: 32px 24px; border-top: 1px solid var(--border); color: var(--text-muted); font-size: 13px; }}
        .footer a {{ color: var(--accent-cyan); text-decoration: none; }}
        .footer a:hover {{ text-decoration: underline; }}
        ::-webkit-scrollbar {{ width: 8px; }}
        ::-webkit-scrollbar-track {{ background: var(--bg-primary); }}
        ::-webkit-scrollbar-thumb {{ background: #374151; border-radius: 4px; }}
        ::-webkit-scrollbar-thumb:hover {{ background: #4b5563; }}
        .empty-state {{ text-align: center; padding: 64px 24px; color: var(--text-muted); }}
        .empty-state svg {{ width: 64px; height: 64px; margin-bottom: 16px; opacity: 0.3; }}
        .empty-state h3 {{ font-size: 18px; color: var(--text-secondary); margin-bottom: 8px; }}
        .empty-state p {{ font-size: 14px; }}
    </style>
</head>
<body>
    <div class="bg-mesh"></div>
    <header class="header">
        <div class="header-badge"><span class="pulse"></span>Live Trending</div>
        <h1>GitHub Trending AI & Agent</h1>
        <p>基于 GitHub Search API 追踪 AI / Agent / LLM 关键词仓库，按新增 Star / Fork 排序（数据范围与 github.com/trending 不同）</p>
        <div class="header-meta">
            <div class="meta-item">📅 {today_str}</div>
            <div class="meta-item">⚡ 增量追踪</div>
        </div>
    </header>

    <nav class="top-nav">
        <a href="index.html">
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="width:14px;height:14px"><path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"></path><polyline points="9 22 9 12 15 12 15 22"></polyline></svg>
            首页
        </a>
        <a href="github-trending-ai.html">
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="width:14px;height:14px"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
            最新报告
        </a>
        <a href="https://github.com/trending" target="_blank">
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="width:14px;height:14px"><path d="M9 19c-5 1.5-5-2.5-7-3m14 6v-3.87a3.37 3.37 0 0 0-.94-2.61c3.14-.35 6.44-1.54 6.44-7A5.44 5.44 0 0 0 20 4.77 5.07 5.07 0 0 0 19.91 1S18.73.65 16 2.48a13.38 13.38 0 0 0-7 0C6.27.65 5.09 1 5.09 1A5.07 5.07 0 0 0 5 4.77a5.44 5.44 0 0 0-1.5 3.78c0 5.42 3.3 6.61 6.44 7A3.37 3.37 0 0 0 9 18.13V22"></path></svg>
            GitHub Trending
        </a>
    </nav>

    <div class="date-selector">
        <label>📅 历史日期:</label>
        <select id="dateSelect" onchange="window.location.href='github-trending-ai-'+this.value+'.html'">
            {date_options}
        </select>
    </div>

    <div class="filter-bar">
        <div class="search-box">
            <span class="search-icon">
                <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" /></svg>
            </span>
            <input type="text" id="searchInput" placeholder="搜索仓库名称、描述或语言..." oninput="applyFilters()">
        </div>
        <div class="filter-chips" id="filterChips">
            {chips_html}
        </div>
    </div>

    <div class="stats-panel" id="statsPanel">
        <div class="stat-card"><div class="stat-value">{total_repos}</div><div class="stat-label">项目总数</div></div>
        <div class="stat-card"><div class="stat-value">{new_count}</div><div class="stat-label">新增项目</div></div>
        <div class="stat-card"><div class="stat-value">{format_number(total_delta_stars)}</div><div class="stat-label">总新增 Star</div></div>
        <div class="stat-card"><div class="stat-value">{len(langs)}</div><div class="stat-label">语言种类</div></div>
    </div>

    <div class="tabs">
        <button class="tab-btn active" onclick="switchTab('today', this)">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
            今日增量
            <span class="count">{len(today_items)}</span>
        </button>
        <button class="tab-btn" onclick="switchTab('week', this)">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><rect x="3" y="4" width="18" height="18" rx="2" ry="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>
            本周增量
            <span class="count">{len(week_items)}</span>
        </button>
    </div>

    <main class="content">
        <div id="today" class="section active">
            <div class="section-title">
                <h2>今日增量排行</h2>
                <div class="line"></div>
                <span class="badge">新增 Star / Fork 统计</span>
            </div>
            <div class="cards-grid" id="todayGrid">
{today_cards}
            </div>
        </div>
        <div id="week" class="section">
            <div class="section-title">
                <h2>本周增量排行</h2>
                <div class="line"></div>
                <span class="badge week">本周汇总</span>
            </div>
            <div class="cards-grid" id="weekGrid">
{week_cards}
            </div>
        </div>
    </main>

    <footer class="footer">
        <p>数据来源 GitHub Search API · 增量 = 今日 - 昨日 · 每周日汇总本周</p>
        <p>生成时间 {today_str} · 由 Kimi Work 自动化生成</p>
    </footer>

    <script>
        function switchTab(tab, btn) {{
            document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            document.querySelectorAll('.section').forEach(s => s.classList.remove('active'));
            btn.classList.add('active');
            document.getElementById(tab).classList.add('active');
            applyFilters();
        }}
        let currentFilter = 'all';
        let searchQuery = '';
        function setFilter(el, filter) {{
            document.querySelectorAll('.chip').forEach(c => c.classList.remove('active'));
            el.classList.add('active');
            currentFilter = filter;
            applyFilters();
        }}
        function applyFilters() {{
            searchQuery = document.getElementById('searchInput').value.toLowerCase().trim();
            const activeSection = document.querySelector('.section.active');
            if (!activeSection) return;
            const grid = activeSection.querySelector('.cards-grid');
            const cards = grid.querySelectorAll('.card');
            let visibleCount = 0;
            cards.forEach(card => {{
                const tags = (card.dataset.tags || '').toLowerCase();
                const lang = (card.dataset.lang || '').toLowerCase();
                const name = (card.dataset.name || '').toLowerCase();
                const desc = card.querySelector('.card-desc')?.textContent.toLowerCase() || '';
                const matchesFilter = currentFilter === 'all' || tags.includes(currentFilter.toLowerCase()) || lang === currentFilter.toLowerCase();
                const matchesSearch = !searchQuery || name.includes(searchQuery) || desc.includes(searchQuery) || lang.includes(searchQuery) || tags.includes(searchQuery);
                if (matchesFilter && matchesSearch) {{
                    card.classList.remove('hidden');
                    visibleCount++;
                }} else {{
                    card.classList.add('hidden');
                }}
            }});
            let emptyState = grid.querySelector('.empty-state');
            if (visibleCount === 0) {{
                if (!emptyState) {{
                    emptyState = document.createElement('div');
                    emptyState.className = 'empty-state';
                    emptyState.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" /></svg><h3>未找到匹配项目</h3><p>请尝试其他搜索词或筛选条件</p>';
                    grid.appendChild(emptyState);
                }}
                emptyState.style.display = 'block';
            }} else if (emptyState) {{
                emptyState.style.display = 'none';
            }}
        }}
        async function loadHistory() {{
            try {{
                const resp = await fetch('github-trending-ai-history.json');
                const data = await resp.json();
                const dates = Object.keys(data).sort().reverse();
                const select = document.getElementById('dateSelect');
                select.innerHTML = '';
                dates.forEach(d => {{
                    const opt = document.createElement('option');
                    opt.value = d;
                    opt.textContent = d;
                    if (d === '{today_str}') opt.selected = true;
                    select.appendChild(opt);
                }});
            }} catch (e) {{}}
        }}
        loadHistory();
    </script>
</body>
</html>'''
    
    return html


def generate_index_html(today_str, history):
    """生成首页 HTML"""
    all_dates = sorted(history.keys(), reverse=True)
    days_count = len(all_dates)
    
    # 计算总项目数、总 Star 等
    total_repos = 0
    total_stars = 0
    total_forks = 0
    for date, repos in history.items():
        total_repos += len(repos)
        for name, data in repos.items():
            total_stars += data.get("stars", 0)
            total_forks += data.get("forks", 0)
    
    # 最新报告的归档项
    latest_archive = ""
    for d in all_dates[:7]:
        entry = history.get(d, {})
        count = len(entry)
        latest_archive += f'''        <a href="github-trending-ai-{d}.html" class="archive-item">
            <div class="date-icon">📅</div>
            <div class="info">
                <div class="date">{d}</div>
                <div class="desc">{count} 个项目 · 增量追踪</div>
            </div>
            <div class="arrow-icon">→</div>
        </a>
'''
    
    # 最新报告概览
    latest_date = all_dates[0] if all_dates else today_str
    latest_entry = history.get(latest_date, {})
    latest_count = len(latest_entry)
    latest_langs = len(set(r.get("language", "N/A") for r in latest_entry.values()))
    
    html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>GitHub Trending AI & Agent — 每日开源追踪</title>
    <meta name="description" content="每日追踪 GitHub 上 AI、Agent、LLM 相关最活跃开源项目，按增量自动排序归档。">
    <meta name="keywords" content="GitHub Trending, AI, Agent, LLM, Open Source, 开源项目, 每日追踪">
    <meta name="author" content="Kimi Work">
    <meta property="og:title" content="GitHub Trending AI & Agent — 每日开源追踪">
    <meta property="og:description" content="每日追踪 GitHub 上 AI、Agent、LLM 相关最活跃开源项目">
    <meta property="og:type" content="website">
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
    <style>
        :root {{
            --bg-primary: #0a0e1a; --bg-secondary: #111827; --bg-card: rgba(17, 24, 39, 0.85);
            --border: rgba(55, 65, 81, 0.5); --text-primary: #f3f4f6; --text-secondary: #9ca3af; --text-muted: #6b7280;
            --accent-cyan: #06b6d4; --accent-purple: #a855f7; --accent-pink: #ec4899; --accent-orange: #f97316;
            --accent-green: #10b981; --accent-yellow: #f59e0b;
            --gradient-1: linear-gradient(135deg, #06b6d4 0%, #a855f7 50%, #ec4899 100%);
            --shadow-lg: 0 8px 40px rgba(0, 0, 0, 0.5);
        }}
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif; background: var(--bg-primary); color: var(--text-primary); line-height: 1.6; min-height: 100vh; overflow-x: hidden; }}
        .bg-mesh {{ position: fixed; top: 0; left: 0; right: 0; bottom: 0; z-index: 0; pointer-events: none; background: radial-gradient(ellipse at 20% 20%, rgba(6, 182, 212, 0.08) 0%, transparent 50%), radial-gradient(ellipse at 80% 80%, rgba(168, 85, 247, 0.08) 0%, transparent 50%), radial-gradient(ellipse at 50% 50%, rgba(236, 72, 153, 0.05) 0%, transparent 60%); }}
        .bg-mesh::before {{ content: ''; position: absolute; top: -50%; left: -50%; width: 200%; height: 200%; background: url("data:image/svg+xml,%3Csvg width='60' height='60' viewBox='0 0 60 60' xmlns='http://www.w3.org/2000/svg'%3E%3Cg fill='none' fill-rule='evenodd'%3E%3Cg fill='%23374151' fill-opacity='0.15'%3E%3Cpath d='M36 34v-4h-2v4h-4v2h4v4h2v-4h4v-2h-4zm0-30V0h-2v4h-4v2h4v4h2V6h4V4h-4zM6 34v-4H4v4H0v2h4v4h2v-4h4v-2H6zM6 4V0H4v4H0v2h4v4h2V6h4V4H6z'/%3E%3C/g%3E%3C/g%3E%3C/svg%3E"); opacity: 0.4; animation: meshMove 120s linear infinite; }}
        @keyframes meshMove {{ 0% {{ transform: translate(0, 0); }} 100% {{ transform: translate(60px, 60px); }} }}
        .hero {{ position: relative; z-index: 1; padding: 64px 24px 48px; text-align: center; background: linear-gradient(180deg, rgba(10,14,26,0.95) 0%, transparent 100%); }}
        .hero-badge {{ display: inline-flex; align-items: center; gap: 8px; padding: 8px 20px; border-radius: 100px; background: rgba(6, 182, 212, 0.1); border: 1px solid rgba(6, 182, 212, 0.3); color: var(--accent-cyan); font-size: 13px; font-weight: 500; letter-spacing: 0.5px; text-transform: uppercase; margin-bottom: 24px; animation: fadeInDown 0.8s ease-out; }}
        .hero-badge .pulse {{ width: 8px; height: 8px; border-radius: 50%; background: var(--accent-cyan); box-shadow: 0 0 8px var(--accent-cyan); animation: pulse 2s ease-in-out infinite; }}
        @keyframes pulse {{ 0%, 100% {{ opacity: 1; transform: scale(1); }} 50% {{ opacity: 0.5; transform: scale(0.8); }} }}
        .hero h1 {{ font-size: 48px; font-weight: 800; background: var(--gradient-1); -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text; margin-bottom: 16px; animation: fadeInUp 0.8s ease-out 0.1s both; }}
        .hero p {{ color: var(--text-secondary); font-size: 18px; max-width: 600px; margin: 0 auto 32px; animation: fadeInUp 0.8s ease-out 0.2s both; }}
        .hero-actions {{ display: flex; justify-content: center; gap: 16px; flex-wrap: wrap; animation: fadeInUp 0.8s ease-out 0.3s both; }}
        .btn {{ display: inline-flex; align-items: center; gap: 8px; padding: 14px 28px; border-radius: 12px; font-size: 15px; font-weight: 600; text-decoration: none; transition: all 0.3s ease; cursor: pointer; border: none; font-family: inherit; }}
        .btn-primary {{ background: var(--gradient-1); color: white; box-shadow: 0 4px 20px rgba(168, 85, 247, 0.3); }}
        .btn-primary:hover {{ transform: translateY(-2px); box-shadow: 0 8px 30px rgba(168, 85, 247, 0.4); }}
        .btn-secondary {{ background: var(--bg-card); color: var(--text-primary); border: 1px solid var(--border); }}
        .btn-secondary:hover {{ background: rgba(31,41,55,0.9); border-color: rgba(6, 182, 212, 0.4); transform: translateY(-2px); }}
        .stats-overview {{ position: relative; z-index: 1; max-width: 1200px; margin: 0 auto 48px; padding: 0 24px; display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 16px; animation: fadeInUp 0.8s ease-out 0.4s both; }}
        .stat-card {{ background: var(--bg-card); border: 1px solid var(--border); border-radius: 16px; padding: 20px; text-align: center; transition: all 0.3s ease; backdrop-filter: blur(12px); }}
        .stat-card:hover {{ border-color: rgba(6, 182, 212, 0.3); transform: translateY(-2px); }}
        .stat-card .stat-icon {{ font-size: 24px; margin-bottom: 8px; }}
        .stat-card .stat-value {{ font-size: 26px; font-weight: 700; font-family: 'JetBrains Mono', monospace; background: var(--gradient-1); -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text; }}
        .stat-card .stat-label {{ font-size: 12px; color: var(--text-muted); margin-top: 4px; text-transform: uppercase; letter-spacing: 0.5px; }}
        .content {{ position: relative; z-index: 1; max-width: 1200px; margin: 0 auto; padding: 0 24px 64px; }}
        .section-title {{ display: flex; align-items: center; gap: 12px; margin-bottom: 24px; padding: 0 4px; }}
        .section-title h2 {{ font-size: 22px; font-weight: 700; color: var(--text-primary); }}
        .section-title .line {{ flex: 1; height: 1px; background: linear-gradient(90deg, var(--border), transparent); }}
        .section-title .badge {{ padding: 4px 12px; border-radius: 8px; font-size: 12px; font-weight: 600; background: rgba(6, 182, 212, 0.1); color: var(--accent-cyan); border: 1px solid rgba(6, 182, 212, 0.2); }}
        .latest-card {{ display: flex; align-items: center; gap: 24px; background: var(--bg-card); border: 1px solid var(--border); border-radius: 20px; padding: 32px; margin-bottom: 32px; transition: all 0.4s ease; text-decoration: none; color: inherit; backdrop-filter: blur(12px); position: relative; overflow: hidden; animation: fadeInUp 0.8s ease-out 0.5s both; }}
        .latest-card::before {{ content: ''; position: absolute; top: 0; left: 0; right: 0; height: 3px; background: var(--gradient-1); opacity: 0; transition: opacity 0.3s ease; }}
        .latest-card:hover {{ transform: translateY(-4px); border-color: rgba(6, 182, 212, 0.3); box-shadow: var(--shadow-lg), 0 0 40px rgba(6, 182, 212, 0.08); }}
        .latest-card:hover::before {{ opacity: 1; }}
        .latest-card .date-block {{ display: flex; flex-direction: column; align-items: center; justify-content: center; min-width: 80px; height: 80px; border-radius: 16px; background: var(--gradient-1); color: white; flex-shrink: 0; }}
        .latest-card .date-block .day {{ font-size: 28px; font-weight: 800; font-family: 'JetBrains Mono', monospace; line-height: 1; }}
        .latest-card .date-block .month {{ font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 1px; opacity: 0.9; }}
        .latest-card .info {{ flex: 1; }}
        .latest-card .info h3 {{ font-size: 20px; font-weight: 700; margin-bottom: 6px; }}
        .latest-card .info p {{ color: var(--text-secondary); font-size: 14px; margin-bottom: 12px; }}
        .latest-card .meta-tags {{ display: flex; gap: 8px; flex-wrap: wrap; }}
        .latest-card .meta-tag {{ padding: 4px 10px; border-radius: 6px; font-size: 11px; font-weight: 600; background: rgba(16, 185, 129, 0.1); color: #34d399; border: 1px solid rgba(16, 185, 129, 0.2); }}
        .latest-card .arrow {{ color: var(--accent-cyan); font-size: 24px; transition: transform 0.3s ease; }}
        .latest-card:hover .arrow {{ transform: translateX(4px); }}
        .archive-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 16px; animation: fadeInUp 0.8s ease-out 0.6s both; }}
        .archive-item {{ display: flex; align-items: center; gap: 16px; background: var(--bg-card); border: 1px solid var(--border); border-radius: 14px; padding: 20px; text-decoration: none; color: inherit; transition: all 0.3s ease; backdrop-filter: blur(12px); }}
        .archive-item:hover {{ background: rgba(31,41,55,0.9); border-color: rgba(6, 182, 212, 0.3); transform: translateY(-2px); }}
        .archive-item .date-icon {{ display: flex; align-items: center; justify-content: center; width: 44px; height: 44px; border-radius: 12px; background: rgba(6, 182, 212, 0.1); color: var(--accent-cyan); font-size: 18px; flex-shrink: 0; }}
        .archive-item .info {{ flex: 1; }}
        .archive-item .info .date {{ font-size: 15px; font-weight: 600; color: var(--text-primary); }}
        .archive-item .info .desc {{ font-size: 12px; color: var(--text-muted); margin-top: 2px; }}
        .archive-item .arrow-icon {{ color: var(--text-muted); transition: color 0.3s ease; }}
        .archive-item:hover .arrow-icon {{ color: var(--accent-cyan); }}
        .about-section {{ background: var(--bg-card); border: 1px solid var(--border); border-radius: 20px; padding: 32px; margin-top: 48px; animation: fadeInUp 0.8s ease-out 0.7s both; backdrop-filter: blur(12px); }}
        .about-section h3 {{ font-size: 18px; font-weight: 700; margin-bottom: 12px; }}
        .about-section p {{ color: var(--text-secondary); font-size: 14px; line-height: 1.7; margin-bottom: 12px; }}
        .about-section .features {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-top: 20px; }}
        .feature {{ display: flex; align-items: flex-start; gap: 12px; }}
        .feature .icon {{ font-size: 20px; }}
        .feature .text {{ font-size: 13px; color: var(--text-secondary); }}
        .feature .text strong {{ color: var(--text-primary); display: block; margin-bottom: 2px; }}
        .footer {{ position: relative; z-index: 1; text-align: center; padding: 32px 24px; border-top: 1px solid var(--border); color: var(--text-muted); font-size: 13px; }}
        .footer a {{ color: var(--accent-cyan); text-decoration: none; }}
        .footer a:hover {{ text-decoration: underline; }}
        ::-webkit-scrollbar {{ width: 8px; }}
        ::-webkit-scrollbar-track {{ background: var(--bg-primary); }}
        ::-webkit-scrollbar-thumb {{ background: #374151; border-radius: 4px; }}
        ::-webkit-scrollbar-thumb:hover {{ background: #4b5563; }}
        @keyframes fadeInUp {{ from {{ opacity: 0; transform: translateY(20px); }} to {{ opacity: 1; transform: translateY(0); }} }}
        @keyframes fadeInDown {{ from {{ opacity: 0; transform: translateY(-10px); }} to {{ opacity: 1; transform: translateY(0); }} }}
        @media (max-width: 768px) {{ .hero h1 {{ font-size: 32px; }} .hero p {{ font-size: 16px; }} .stats-overview {{ grid-template-columns: repeat(2, 1fr); }} .latest-card {{ flex-direction: column; align-items: flex-start; }} .latest-card .arrow {{ display: none; }} }}
        @media (max-width: 640px) {{ .archive-grid {{ grid-template-columns: 1fr; }} }}
    </style>
</head>
<body>
    <div class="bg-mesh"></div>
    <section class="hero">
        <div class="hero-badge"><span class="pulse"></span>自动更新</div>
        <h1>GitHub Trending AI & Agent</h1>
        <p>每日基于 GitHub Search API 追踪 AI / Agent / LLM 关键词仓库，按新增 Star / Fork 排序（数据范围与 github.com/trending 不同），自动归档、增量排序。</p>
        <div class="hero-actions">
            <a href="github-trending-ai.html" class="btn btn-primary">
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="width:18px;height:18px"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
                查看最新报告
            </a>
            <a href="https://github.com/trending" target="_blank" class="btn btn-secondary">
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="width:18px;height:18px"><path d="M9 19c-5 1.5-5-2.5-7-3m14 6v-3.87a3.37 3.37 0 0 0-.94-2.61c3.14-.35 6.44-1.54 6.44-7A5.44 5.44 0 0 0 20 4.77 5.07 5.07 0 0 0 19.91 1S18.73.65 16 2.48a13.38 13.38 0 0 0-7 0C6.27.65 5.09 1 5.09 1A5.07 5.07 0 0 0 5 4.77a5.44 5.44 0 0 0-1.5 3.78c0 5.42 3.3 6.61 6.44 7A3.37 3.37 0 0 0 9 18.13V22"></path></svg>
                GitHub Trending
            </a>
        </div>
    </section>

    <div class="stats-overview">
        <div class="stat-card">
            <div class="stat-icon">📅</div>
            <div class="stat-value">{days_count}</div>
            <div class="stat-label">追踪天数</div>
        </div>
        <div class="stat-card">
            <div class="stat-icon">📦</div>
            <div class="stat-value">{total_repos}</div>
            <div class="stat-label">收录项目</div>
        </div>
        <div class="stat-card">
            <div class="stat-icon">⭐</div>
            <div class="stat-value">{format_number(total_stars)}</div>
            <div class="stat-label">总 Star</div>
        </div>
        <div class="stat-card">
            <div class="stat-icon">🔀</div>
            <div class="stat-value">{format_number(total_forks)}</div>
            <div class="stat-label">总 Fork</div>
        </div>
    </div>

    <main class="content">
        <div class="section-title">
            <h2>最新报告</h2>
            <div class="line"></div>
            <span class="badge">Latest</span>
        </div>

        <a href="github-trending-ai.html" class="latest-card">
            <div class="date-block">
                <div class="day">{latest_date.split('-')[2]}</div>
                <div class="month">{latest_date[5:7]}月 {latest_date[:4]}</div>
            </div>
            <div class="info">
                <h3>{latest_date} 每日追踪报告</h3>
                <p>今日追踪 {latest_count} 个活跃项目。涵盖 Agent 框架、MCP 工具、AI 编码助手等方向。</p>
                <div class="meta-tags">
                    <span class="meta-tag">今日 {latest_count} 项</span>
                    <span class="meta-tag">{latest_langs} 种语言</span>
                </div>
            </div>
            <div class="arrow">→</div>
        </a>

        <div class="section-title">
            <h2>历史归档</h2>
            <div class="line"></div>
            <span class="badge">Archive</span>
        </div>

        <div class="archive-grid">
{latest_archive}
        </div>

        <div class="about-section">
            <h3>关于这个项目</h3>
            <p>本站点通过 GitHub Search API 追踪 AI 相关开源仓库，每天抓取 GitHub 上 AI、Agent、LLM 相关开源项目的增量数据，按新增 Star 和 Fork 排序，生成可阅读的追踪报告。</p>
            <div class="features">
                <div class="feature">
                    <div class="icon">⚡</div>
                    <div class="text"><strong>增量追踪</strong>对比昨日数据，只关注新增变化</div>
                </div>
                <div class="feature">
                    <div class="icon">🤖</div>
                    <div class="text"><strong>AI 聚焦</strong>专注 Agent、LLM、MCP 等前沿方向</div>
                </div>
                <div class="feature">
                    <div class="icon">📊</div>
                    <div class="text"><strong>自动归档</strong>按日保存，支持历史回溯对比</div>
                </div>
                <div class="feature">
                    <div class="icon">🔍</div>
                    <div class="text"><strong>实时筛选</strong>按标签、语言、关键词搜索项目</div>
                </div>
            </div>
        </div>
    </main>

    <footer class="footer">
        <p>数据来源 GitHub Search API · 增量 = 今日 - 昨日 · 自动归档</p>
        <p>生成时间 {today_str} · 由 Kimi Work 自动化生成</p>
    </footer>
</body>
</html>'''
    
    return html


# ==================== 主流程 ====================

def main():
    parser = argparse.ArgumentParser(description="GitHub Trending AI 自动化更新")
    parser.add_argument("--dry-run", action="store_true", help="仅打印日志，不写入文件")
    parser.add_argument("--date", type=str, help="指定日期 (YYYY-MM-DD)，默认今天")
    args = parser.parse_args()
    
    today_str = args.date or datetime.now().strftime("%Y-%m-%d")
    print(f"=" * 60)
    print(f"GitHub Trending AI 自动化更新")
    print(f"日期: {today_str}")
    print(f"Token: {'已配置' if GITHUB_TOKEN else '未配置 (API 限额较低)'}")
    print(f"=" * 60)
    
    # 1. 读取历史数据
    history = load_history()
    print(f"[Load] 历史记录: {len(history)} 天")
    
    # 2. 获取今日数据
    today_data = fetch_today_data(today_str, history)
    print(f"[Data] 获取到 {len(today_data)} 个项目")
    
    if not today_data:
        print("[Error] 未能获取到任何数据，跳过生成")
        return 1
    
    # 3. 更新历史数据（只保存 stars/forks 用于增量计算）
    history[today_str] = {
        name: {"stars": data["stars"], "forks": data["forks"]}
        for name, data in today_data.items()
    }
    
    # 4. 生成 HTML
    print(f"[4/4] Generating HTML files...")
    
    # 4a. 生成日期归档页
    archive_html = generate_report_page_html(today_str, today_data, history, is_archive=True)
    archive_path = OUTPUT_DIR / f"github-trending-ai-{today_str}.html"
    if not args.dry_run:
        with open(archive_path, "w", encoding="utf-8") as f:
            f.write(archive_html)
        print(f"  [Write] {archive_path.name}")
    else:
        print(f"  [DryRun] 将生成: {archive_path.name}")
    
    # 4b. 生成最新报告页（覆盖）
    latest_html = generate_report_page_html(today_str, today_data, history, is_archive=False)
    latest_path = OUTPUT_DIR / "github-trending-ai.html"
    if not args.dry_run:
        with open(latest_path, "w", encoding="utf-8") as f:
            f.write(latest_html)
        print(f"  [Write] {latest_path.name}")
    else:
        print(f"  [DryRun] 将生成: {latest_path.name}")
    
    # 4c. 生成首页
    index_html = generate_index_html(today_str, history)
    index_path = OUTPUT_DIR / "index.html"
    if not args.dry_run:
        with open(index_path, "w", encoding="utf-8") as f:
            f.write(index_html)
        print(f"  [Write] {index_path.name}")
    else:
        print(f"  [DryRun] 将生成: {index_path.name}")
    
    # 5. 保存历史数据
    if not args.dry_run:
        save_history(history)
    else:
        print(f"  [DryRun] 将更新: {HISTORY_FILE.name}")
    
    print(f"=" * 60)
    print(f"[Done] 自动化更新完成！")
    print(f"  日期归档: github-trending-ai-{today_str}.html")
    print(f"  最新报告: github-trending-ai.html")
    print(f"  首页: index.html")
    print(f"  历史记录: {HISTORY_FILE.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
