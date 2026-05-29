from __future__ import annotations

import base64
import hashlib
import os
import re
import tempfile
from typing import Literal, Optional

import httpx
from bs4 import BeautifulSoup
from pydantic import BaseModel

# Playwright 可执行文件路径，优先使用本地已安装的 headless shell
_PLAYWRIGHT_EXE = (
    r"C:\Users\Lenovo\AppData\Local\ms-playwright"
    r"\chromium_headless_shell-1187\chrome-win\headless_shell.exe"
)


class FetchResult(BaseModel):
    url: str
    status: Literal["fetched", "failed", "empty"]
    failure_reason: Optional[str] = None
    title: Optional[str] = None
    raw_text: Optional[str] = None
    content_hash: Optional[str] = None
    http_status: Optional[int] = None


def _clean_html(html: str) -> tuple[str | None, str]:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "nav", "footer", "aside"]):
        tag.decompose()
    title = soup.title.get_text(" ", strip=True) if soup.title else None
    text = soup.get_text(separator="\n", strip=True)
    text = re.sub(r"\n{2,}", "\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return title, text.strip()


def _fetch_with_playwright(url: str, timeout: float = 20.0) -> FetchResult:
    """Render page with headless Chromium, extract visible text."""
    try:
        import os
        from pathlib import Path
        from playwright.sync_api import sync_playwright

        exe = _PLAYWRIGHT_EXE if Path(_PLAYWRIGHT_EXE).exists() else None
        launch_kwargs: dict = {"headless": True}
        if exe:
            launch_kwargs["executable_path"] = exe

        with sync_playwright() as p:
            browser = p.chromium.launch(**launch_kwargs)
            try:
                page = browser.new_page(
                    viewport={"width": 1280, "height": 800},
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0.0.0 Safari/537.36"
                    ),
                )
                page.goto(url, wait_until="domcontentloaded", timeout=int(timeout * 1000))
                # 等待初始渲染
                page.wait_for_timeout(2000)
                # 滚动触发懒加载内容（定价页常见）
                page.evaluate("window.scrollTo(0, document.body.scrollHeight / 2)")
                page.wait_for_timeout(1000)
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(1500)
                html = page.content()
                final_url = page.url
            finally:
                browser.close()

        title, raw_text = _clean_html(html)
        text_length = len(raw_text)
        if text_length < 200:
            return FetchResult(
                url=final_url,
                status="empty",
                failure_reason="pw_parse_empty",
                title=title,
                raw_text=raw_text,
            )
        content_hash = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()[:16]
        return FetchResult(
            url=final_url,
            status="fetched",
            title=title,
            raw_text=raw_text,
            content_hash=content_hash,
        )
    except Exception as e:
        return FetchResult(url=url, status="failed", failure_reason=f"playwright_error:{e!s:.80}")


def _vision_enabled() -> bool:
    """Vision fallback requires VISION_API_KEY (and optionally VISION_BASE_URL + VISION_MODEL)."""
    return bool(os.getenv("VISION_API_KEY"))


def _fetch_with_vision(url: str, screenshot_png: bytes) -> FetchResult:
    """Send a Playwright screenshot to a Vision LLM and extract page text.

    Env vars:
      VISION_API_KEY   — required (Moonshot / OpenAI / any OpenAI-compat key)
      VISION_BASE_URL  — optional, default https://api.moonshot.cn/v1
      VISION_MODEL     — optional, default moonshot-v1-8k-vision-preview
    """
    try:
        from openai import OpenAI

        api_key = os.environ["VISION_API_KEY"]
        base_url = os.getenv("VISION_BASE_URL", "https://api.moonshot.cn/v1")
        model = os.getenv("VISION_MODEL", "moonshot-v1-8k-vision-preview")

        image_b64 = base64.b64encode(screenshot_png).decode("utf-8")
        image_url = f"data:image/png;base64,{image_b64}"

        client = OpenAI(api_key=api_key, base_url=base_url)
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你是一名网页内容提取助手。请将截图中的所有可见文字完整提取出来，"
                        "保留结构（标题、价格、功能列表等），不要添加任何解释或评论。"
                        "直接输出提取到的文字内容。"
                    ),
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": image_url}},
                        {"type": "text", "text": "请提取该网页截图中的所有文字内容。"},
                    ],
                },
            ],
            max_tokens=2048,
        )
        raw_text = (resp.choices[0].message.content or "").strip()
        if len(raw_text) < 200:
            return FetchResult(url=url, status="empty", failure_reason="vision_too_short", raw_text=raw_text)
        content_hash = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()[:16]
        return FetchResult(
            url=url,
            status="fetched",
            raw_text=raw_text,
            content_hash=content_hash,
            title=None,
        )
    except Exception as e:
        return FetchResult(url=url, status="failed", failure_reason=f"vision_error:{e!s:.80}")


def _fetch_with_playwright_and_vision(url: str, timeout: float = 20.0) -> FetchResult:
    """Playwright render → if empty, screenshot → Vision LLM fallback."""
    try:
        import os as _os
        from pathlib import Path
        from playwright.sync_api import sync_playwright

        exe = _PLAYWRIGHT_EXE if Path(_PLAYWRIGHT_EXE).exists() else None
        launch_kwargs: dict = {"headless": True}
        if exe:
            launch_kwargs["executable_path"] = exe

        with sync_playwright() as p:
            browser = p.chromium.launch(**launch_kwargs)
            try:
                page = browser.new_page(
                    viewport={"width": 1280, "height": 800},
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0.0.0 Safari/537.36"
                    ),
                )
                page.goto(url, wait_until="domcontentloaded", timeout=int(timeout * 1000))
                page.wait_for_timeout(2000)
                page.evaluate("window.scrollTo(0, document.body.scrollHeight / 2)")
                page.wait_for_timeout(1000)
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(1500)
                html = page.content()
                final_url = page.url
                # 截图供 Vision fallback 使用
                screenshot_png: bytes = page.screenshot(full_page=True)
            finally:
                browser.close()

        title, raw_text = _clean_html(html)
        if len(raw_text) >= 200:
            content_hash = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()[:16]
            return FetchResult(url=final_url, status="fetched", title=title,
                               raw_text=raw_text, content_hash=content_hash)

        # 文字太少 → Vision fallback
        if _vision_enabled():
            vision_result = _fetch_with_vision(final_url, screenshot_png)
            if vision_result.status == "fetched":
                vision_result.title = title  # 保留 HTML title（如果有）
                return vision_result

        return FetchResult(url=final_url, status="empty", failure_reason="pw_parse_empty",
                           title=title, raw_text=raw_text)
    except Exception as e:
        return FetchResult(url=url, status="failed", failure_reason=f"playwright_error:{e!s:.80}")


def _make_result(url: str, response_url: str, http_status: int, html: str) -> FetchResult:
    try:
        title, raw_text = _clean_html(html)
    except Exception:
        return FetchResult(url=response_url, status="failed", failure_reason="unknown", http_status=http_status)

    text_length = len(raw_text)
    if text_length < 200:
        return FetchResult(url=response_url, status="empty", failure_reason="parse_empty",
                           title=title, raw_text=raw_text, http_status=http_status)
    if text_length < 500:
        return FetchResult(url=response_url, status="empty", failure_reason="too_short",
                           title=title, raw_text=raw_text, http_status=http_status)

    content_hash = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()[:16]
    return FetchResult(url=response_url, status="fetched", title=title, raw_text=raw_text,
                       content_hash=content_hash, http_status=http_status)


def fetch(url: str, timeout: float = 15.0) -> FetchResult:
    """Fetch and clean a URL. Falls back to Playwright for JS-rendered pages."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    try:
        with httpx.Client(follow_redirects=True, timeout=timeout, headers=headers) as client:
            response = client.get(url)
    except (httpx.TimeoutException, httpx.ConnectError, httpx.NetworkError):
        # 网络超时直接走 Playwright（含 Vision fallback）
        return _fetch_with_playwright_and_vision(url, timeout=timeout)
    except Exception:
        return FetchResult(url=url, status="failed", failure_reason="unknown")

    if response.status_code == 403 or response.status_code == 429:
        # 反爬拒绝，用浏览器 UA 重试（含 Vision fallback）
        return _fetch_with_playwright_and_vision(url, timeout=timeout)

    if response.status_code < 200 or response.status_code >= 300:
        return FetchResult(
            url=str(response.url),
            status="failed",
            failure_reason="non_200",
            http_status=response.status_code,
        )

    result = _make_result(url, str(response.url), response.status_code, response.text)

    # empty 时用 Playwright 二次渲染（含 Vision fallback）
    if result.status == "empty":
        pw_result = _fetch_with_playwright_and_vision(url, timeout=timeout)
        if pw_result.status == "fetched":
            return pw_result

    return result
