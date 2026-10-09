"""敏感词过滤：事中防线唯一的实体。

实现是前缀树（Trie）：把词库建成树之后，判断一条文本是否命中只需要沿树走，
代价与文本长度成正比，与词库大小基本无关。早期版本用的是朴素子串匹配
（每个词都去文本里 find 一次），词库十几条时够用，词库变大就会线性变慢。

词库来源（10-02 起）：数据库 sensitive_word 表是唯一权威源，由
services/wordlist_service.py 读出后调 set_words() 注入本模块；
sensitive_words.txt 退位为"建库种子"（表为空时导入一次）。本模块保持
纯同步：命中判定在 WS/REST 热路径上，不能因为查库引入 await。

铁律：只在后端拦截。前端提示仅作体验优化，不能作为安全边界。
消息、频道帖子、评论三处共用 hit_sensitive，保证拦截口径一致。
"""
from __future__ import annotations

import os

WORD_FILE = os.path.join(os.path.dirname(__file__), "..", "..", "sensitive_words.txt")

# 词表与前缀树都是进程内缓存：改完词库文件要调用 reload_words() 才会生效
_WORDS: tuple[str, ...] | None = None
_TRIE: dict | None = None

# 前缀树里用来标记"到这里是一个完整的词"的键。词条都是中文，不会和它冲突
_END = "$"


def _build_trie(words: tuple[str, ...]) -> dict:
    """把词表建成前缀树。

    结构用嵌套字典表示：键是字符，值是子节点；节点的 ``"$"`` 键存在即表示
    从根走到这里构成一个完整词条。用字典而不是自定义节点类，少一层间接，
    也少写一堆样板代码。
    """
    root: dict = {}
    for word in words:
        node = root
        for ch in word:
            node = node.setdefault(ch, {})
        node[_END] = True
    return root


def load_words() -> list[str]:
    """读取词库，建立前缀树，返回词表。

    跳过空行与 ``#`` 开头的注释行。这里必须显式跳过注释：早期版本没有跳，
    而词库第 2 行恰好是一个单独的 ``#``，结果它被当成词条加载，
    凡是含 ``#`` 的消息（比如"C# 怎么学"）都会被判为敏感词拦掉。

    文件缺失时返回空列表而不抛异常——词库缺失不该让整个服务起不来。
    """
    global _WORDS, _TRIE
    if _WORDS is None:
        path = os.path.abspath(WORD_FILE)
        words: list[str] = []
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                for line in f:
                    word = line.strip()
                    if word and not word.startswith("#"):
                        words.append(word)
        _WORDS = tuple(words)
        _TRIE = _build_trie(_WORDS)
    return list(_WORDS)


def _ensure_loaded() -> dict:
    """取前缀树；尚未加载时先加载。"""
    if _TRIE is None:
        load_words()
    return _TRIE  # type: ignore[return-value]


def hit_sensitive(text: str) -> str | None:
    """返回命中的敏感词；未命中返回 None。

    判定规则：从左到右逐字符作为起点，沿前缀树尽量往下走，记下这一起点上
    能匹配到的最长词；一旦某个起点有命中就返回，不再往后找。

    之所以在每个起点取最长匹配，是为了让提示更准确——文本里出现"代开发票"时
    应该提示"代开发票"，而不是被更短的"开票"抢先命中。

    只返回第一个命中的词，够调用方拼一句提示文案了。不做变体还原
    （拆字、拼音、繁简混用都能绕过），词表也刻意只收多字词，避免单字误伤。
    """
    if not text:
        return None
    trie = _ensure_loaded()
    length = len(text)
    for start in range(length):
        node = trie
        matched: str | None = None
        for i in range(start, length):
            node = node.get(text[i])
            if node is None:
                break
            if node.get(_END):
                matched = text[start : i + 1]
        if matched is not None:
            return matched
    return None


def reload_words() -> None:
    """词库文件改动后调用，重建词表与前缀树，无需重启服务。

    （仅用于 DB 不可用时的文件回退路径；正常运行走 set_words）"""
    global _WORDS, _TRIE
    _WORDS = None
    _TRIE = None
    load_words()


def set_words(words: list[str]) -> None:
    """外部（wordlist_service）注入词表并重建前缀树。

    管理端增删敏感词后，本实例直接调用，其他实例经总线控制帧
    收到同样的刷新指令——每个进程各自换上新树，替换是整体式的，
    不存在"半新半旧"的中间态。空词表是合法输入（拦截全部关闭）。
    """
    global _WORDS, _TRIE
    _WORDS = tuple(dict.fromkeys(w.strip() for w in words if w and w.strip()))
    _TRIE = _build_trie(_WORDS)


def get_words() -> list[str]:
    """当前生效的词表快照（仅供展示/排错，判定不依赖它）。"""
    _ensure_loaded()
    return list(_WORDS or ())
