#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
2026 GLaDOS 自动签到 (积分增强版)

功能：
- 全自动签到
- 精准获取当前积分 (Points)
- PushPlus 微信推送（包含积分、剩余天数、签到结果）
- 智能多域名切换 (优先 glados.cloud)
- 支持 Cookie-Editor 导出格式
"""

import requests
import json
import os
import sys
import time
from datetime import datetime
from urllib.parse import quote

# Fix Windows Unicode Output
if sys.platform.startswith('win'):
    sys.stdout.reconfigure(encoding='utf-8')

# ================= 配置 =================

# 域名优先级：Cloud 第一
DOMAINS = [
    "https://glados.cloud",
    "https://glados.rocks", 
    "https://glados.network",
]

# 会话与登录设备绑定，UA 必须与账号登录设备一致，否则签到返回 device-mismatch
# 默认 macOS Chrome；如账号在其他设备登录，用环境变量 GLADOS_UA 覆盖
HEADERS = {
    'User-Agent': os.environ.get('GLADOS_UA', 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'),
    'Content-Type': 'application/json;charset=UTF-8',
    'Accept': 'application/json, text/plain, */*',
}

# ================= 工具函数 =================

def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}")

def extract_cookie(raw: str):
    """提取 Cookie，支持 Cookie-Editor 冒号格式"""
    if not raw: return None
    raw = raw.strip()
    
    # Cookie-Editor 格式 (koa:sess=xxx; koa:sess.sig=yyy)
    if 'koa:sess=' in raw or 'koa:sess.sig=' in raw:
        return raw
        
    # JSON
    if raw.startswith('{'):
        try:
            return 'koa.sess=' + json.loads(raw).get('token')
        except: pass
        
    # JWT Token
    if raw.count('.') == 2 and '=' not in raw and len(raw) > 50:
        return 'koa:sess=' + raw
        
    # Standard
    return raw

def get_cookies():
    raw = os.environ.get("GLADOS_COOKIE", "")
    if not raw:
        log("❌ 未配置 GLADOS_COOKIE")
        return []
    
    # Split by enter or &
    sep = '\n' if '\n' in raw else '&'
    return [extract_cookie(c) for c in raw.split(sep) if c.strip()]

# ================= 核心逻辑 =================

class GLaDOS:
    def __init__(self, cookie):
        self.cookie = cookie
        self.domain = DOMAINS[0]
        self.email = "?"
        self.left_days = "?"
        self.points = "?"
        self.points_change = "?"
        self.exchange_info = ""
        self.plan = "?"
        
    def req(self, method, path, data=None):
        """带自动域名切换的请求"""
        for d in DOMAINS:
            try:
                url = f"{d}{path}"
                h = HEADERS.copy()
                h['Cookie'] = self.cookie
                h['Origin'] = d
                h['Referer'] = f"{d}/console/checkin"
                
                # 前端以 window.location.hostname 作为 token，必须与请求域名一致
                payload = data
                if isinstance(data, dict) and data.get('token') == '@hostname':
                    payload = dict(data, token=d.replace('https://', ''))

                if method == 'GET':
                    resp = requests.get(url, headers=h, timeout=10)
                else:
                    resp = requests.post(url, headers=h, json=payload, timeout=10)
                
                if resp.status_code == 200:
                    self.domain = d # Remember working domain
                    return resp.json()
            except Exception as e:
                log(f"⚠️ {d} 请求失败: {e}")
                continue
        return None

    def get_status(self):
        """获取状态：天数、邮箱"""
        res = self.req('GET', '/api/user/status')
        if res and 'data' in res:
            d = res['data']
            self.email = d.get('email', 'Unknown')
            self.left_days = str(d.get('leftDays', '?')).split('.')[0]
            return True
        return False

    def get_points(self):
        """获取积分、变化历史、兑换计划"""
        res = self.req('GET', '/api/user/points')
        if res and 'points' in res:
            # 当前积分
            self.points = str(res.get('points', '0')).split('.')[0]
            
            # 最近一次积分变化
            history = res.get('history', [])
            if history:
                last = history[0]
                change = str(last.get('change', '0')).split('.')[0]
                if not change.startswith('-'):
                    change = '+' + change
                self.points_change = change
            
            # 兑换计划
            plans = res.get('plans', {})
            pts = int(self.points)
            exchange_lines = []
            for plan_id, plan_data in plans.items():
                need = plan_data['points']
                days = plan_data['days']
                if pts >= need:
                    exchange_lines.append(f"✅ {need}分→{days}天 (可兑换)")
                else:
                    exchange_lines.append(f"❌ {need}分→{days}天 (差{need-pts}分)")
            self.exchange_info = "<br>".join(exchange_lines)
            return True
        return False

    def checkin(self):
        """执行签到（token 跟随请求域名，不一致会被判定为自动化）"""
        return self.req('POST', '/api/user/checkin', {'token': '@hostname'})

# ================= 主程序 =================

def pushplus(token, title, content):
    if not token: return
    try:
        url = "http://www.pushplus.plus/send"
        requests.get(url, params={'token': token, 'title': title, 'content': content, 'template': 'html'}, timeout=5)
        log("✅ PushPlus 推送成功")
    except:
        log("❌ PushPlus 推送失败")

def bark(base, title, content):
    """Bark 推送：base 形如 https://bark.example.com/你的device_key"""
    if not base: return
    try:
        base = base.rstrip('/')
        requests.get(f"{base}/{quote(title, safe='')}/{quote(content, safe='')}",
                     params={'group': 'GLaDOS', 'isArchive': '1'}, timeout=10)
        log("✅ Bark 推送成功")
    except Exception as e:
        log(f"❌ Bark 推送失败: {e}")

def main():
    log("🚀 2026 GLaDOS Checkin Starting...")
    cookies = get_cookies()
    if not cookies: sys.exit(1)
    
    results = []
    plain_results = []
    success_cnt = 0
    
    for i, cookie in enumerate(cookies, 1):
        g = GLaDOS(cookie)
        
        # 1. Checkin
        res = g.checkin()
        msg = res.get('message', 'Failure') if res else "Network Error"
        
        # 2. Get Info (Refresh data)
        g.get_status()
        g.get_points()
        
        # 3. Log
        ok = bool(res) and "automated" not in msg.lower() and res.get('code') != 4
        status_icon = "✅" if ok else "⚠️"
        log(f"用户: {g.email} | 积分: {g.points} | 天数: {g.left_days} | 结果: {msg}")
        
        if ok: success_cnt += 1
        
        if res and res.get('code') == 4 and res.get('reason') == 'device-mismatch':
            log(f"⚠️ 会话绑定在 {res.get('loginDevice', '?')} 设备上，请设置 GLADOS_UA 为该设备的浏览器 UA，或重新登录 GLaDOS 后更新 Cookie")
        
        # 4. Result Formatting
        results.append(f"""
<div style="border:2px solid #333; padding:15px; margin-bottom:15px; border-radius:10px; background:#fff;">
    <h3 style="margin:0 0 15px 0; color:#333; border-bottom:2px solid #333; padding-bottom:8px;">👤 {g.email}</h3>
    <p style="margin:8px 0; color:#000; font-size:16px;"><b>当前积分:</b> <span style="color:#e74c3c; font-size:22px; font-weight:bold;">{g.points}</span> <span style="color:#27ae60; font-weight:bold;">({g.points_change})</span></p>
    <p style="margin:8px 0; color:#000; font-size:16px;"><b>剩余天数:</b> <span style="font-weight:bold;">{g.left_days} 天</span></p>
    <p style="margin:8px 0; color:#000; font-size:16px;"><b>签到结果:</b> {msg}</p>
    <div style="margin-top:15px; padding:12px; background:#f0f0f0; border-radius:8px; border:1px solid #ccc;">
        <p style="margin:0 0 8px 0; color:#333; font-weight:bold; font-size:15px;">🎁 兑换选项:</p>
        <p style="margin:0; color:#000; font-size:14px; line-height:1.8;">{g.exchange_info}</p>
    </div>
</div>
""")

    plain_results.append(f"{g.email}\n积分 {g.points} ({g.points_change}) | 剩余 {g.left_days} 天\n{msg}")

    # Push
    ptoken = os.environ.get("PUSHPLUS_TOKEN")
    if ptoken:
        # Get first user's points for title
        first_points = "多账户"
        if len(cookies) == 1:
            # Re-parse log to find points? Or just use last object
            # Ideally store objects. Using simplified approach:
            pass 
        
        title = f"GLaDOS签到: 成功{success_cnt}/{len(cookies)}"
        content = "".join(results)
        content += f"<br><small>时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</small>"
        pushplus(ptoken, title, content)

    burl = os.environ.get("BARK_URL")
    if burl:
        bark(burl, f"GLaDOS签到: 成功{success_cnt}/{len(cookies)}", "\n\n".join(plain_results))

if __name__ == '__main__':
    main()
