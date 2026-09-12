"""Utilitas: kalkulator (.calc), hapus pesan (.del), translate (.tr)."""
import asyncio
import ast
import json
import math
import operator
import re
import urllib.parse
import urllib.request

from telethon import events

from core import helpers
from core.state import state

LANG = {
    "id": "Indonesia", "en": "Inggris", "ms": "Melayu", "ar": "Arab",
    "ja": "Jepang", "ko": "Korea", "zh": "Tionghoa", "fr": "Prancis",
    "de": "Jerman", "es": "Spanyol", "pt": "Portugis", "ru": "Rusia",
    "hi": "Hindi", "th": "Thailand", "tr": "Turki", "it": "Italia",
    "nl": "Belanda", "vi": "Vietnam",
}

_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}

_FUNCS = {
    "sqrt": math.sqrt, "log": math.log, "log10": math.log10, "log2": math.log2,
    "exp": math.exp, "abs": abs, "round": round,
    "floor": math.floor, "ceil": math.ceil,
    "sin": math.sin, "cos": math.cos, "tan": math.tan,
    "degrees": math.degrees, "radians": math.radians,
    "pi": math.pi, "e": math.e, "tau": math.tau,
}


def _safe_eval(node):
    if isinstance(node, ast.Expression):
        return _safe_eval(node.body)
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        left = _safe_eval(node.left)
        right = _safe_eval(node.right)
        if type(node.op) is ast.Pow and abs(right) > 1000000:
            raise ValueError("jangkauan terlalu besar")
        return _OPS[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_safe_eval(node.operand))
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _FUNCS:
        args = [_safe_eval(a) for a in node.args]
        return _FUNCS[node.func.id](*args)
    if isinstance(node, ast.Name) and node.id in _FUNCS:
        return _FUNCS[node.id]
    raise ValueError("ekspresi tidak valid")


def safe_calc(expr):
    return _safe_eval(ast.parse(expr, mode="eval"))


def _fmt(result):
    if isinstance(result, float):
        if result == int(result) and abs(result) < 1e15:
            return str(int(result))
        return f"{result:.6f}".rstrip("0").rstrip(".")
    return str(result)


def _translate(text, target):
    url = (
        "https://translate.googleapis.com/translate_a/single?"
        "client=gtx&dt=t&sl=auto&tl=" + urllib.parse.quote(target) +
        "&q=" + urllib.parse.quote(text)
    )
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode())
    return "".join(seg[0] for seg in data[0])


async def translate(text, target):
    """Translate via Google, fallback ke Gemini kalau Google rate-limit/gagal."""
    try:
        return await asyncio.to_thread(_translate, text, target)
    except Exception:
        from modules.ai import ask_gemini

        lang_name = LANG.get(target, target)
        prompt = (
            f"Terjemahkan teks berikut ke bahasa {lang_name}. "
            f"Balas HANYA hasil terjemahan, tanpa ditambah kata lain:\n\n{text}"
        )
        result = await ask_gemini(prompt)
        if result.startswith("❌"):
            raise RuntimeError("gemini gagal")
        return result


def load():
    client = state.client

    @client.on(events.NewMessage(pattern=helpers.cmd("calc", r"\s+"), outgoing=True))
    async def calc(event):
        expr = event.message.message.split(None, 1)[1].strip()
        expr = (expr.replace(",", "")
                    .replace("\u00d7", "*")
                    .replace("\u00f7", "/")
                    .replace("pi", "pi"))
        try:
            result = _fmt(safe_calc(expr))
        except Exception:
            await helpers.temp(event, helpers.wm("❌ Ekspresi tidak valid."))
            await event.delete()
            return
        await event.respond(helpers.wm(f"🧮 `{expr}` = **{result}**"))
        await event.delete()

    @client.on(events.NewMessage(pattern=helpers.cmd("del"), outgoing=True))
    async def del_msg(event):
        reply = await event.get_reply_message()
        try:
            await event.message.delete()
        except Exception:
            pass
        if reply:
            try:
                await reply.delete()
            except Exception:
                await helpers.temp(event, helpers.wm("❌ Gak bisa hapus pesan itu."))

    @client.on(events.NewMessage(pattern=helpers.cmd("tr", r"(?:\s+.*)?"), outgoing=True))
    async def tr(event):
        args = event.message.message.split()[1:]
        target = "id"
        text = ""
        if args and re.fullmatch(r"[a-z]{2,5}", args[0].lower()):
            target = args.pop(0).lower()
        if args:
            text = " ".join(args)
        else:
            reply = await event.get_reply_message()
            if reply:
                text = reply.message
        text = text.strip()
        if not text:
            await helpers.temp(event, helpers.wm("❌ Pakai: `.tr id <teks>` atau reply pesan."))
            await event.delete()
            return
        try:
            result = await translate(text, target)
        except Exception:
            await helpers.temp(event, helpers.wm("❌ Gagal translate."))
            await event.delete()
            return
        await event.respond(helpers.wm(f"🌐 `{target}`\n{result}"))
        await event.delete()


