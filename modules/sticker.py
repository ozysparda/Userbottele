"""Kirim pesan reply jadi kartu stiker: foto profil + nama + text chat.

Pakai Pillow untuk render kartu quote ala Telegram (stiker statis WebP).
Perintah: .sticker / .stk (reply ke pesan teks).
"""
import asyncio
import io
import os

from telethon import events
from telethon.tl.types import (
    DocumentAttributeFilename,
    DocumentAttributeSticker,
    InputMediaUploadedDocument,
    InputStickerSetEmpty,
)

from core import helpers

try:
    from PIL import Image, ImageDraw, ImageFont
    _PIL_OK = True
except Exception:
    _PIL_OK = False

WIDTH = 512
PAD = 28
AVATAR = 72
RADIUS = 26
FOL_BG = (31, 36, 41, 255)
ACCENT = (86, 156, 214, 255)
TEXT_COLOR = (238, 242, 245, 255)
NAME_COLOR = (107, 194, 245, 255)


def _font_path(bold=False):
    if os.name == "nt":
        cands = [
            r"C:\Windows\Fonts\arialbd.ttf" if bold else r"C:\Windows\Fonts\arial.ttf",
            r"C:\Windows\Fonts\segoeuib.ttf" if bold else r"C:\Windows\Fonts\segoeui.ttf",
        ]
    else:
        cands = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        ]
    for c in cands:
        if os.path.exists(c):
            return c
    return None


def _font(size, bold=False):
    p = _font_path(bold)
    if p:
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            pass
    try:
        return ImageFont.load_default(size)
    except Exception:
        return ImageFont.load_default()


def _wrap(draw, text, font, max_w):
    words = text.split()
    lines, cur = [], ""
    for w in words:
        test = (cur + " " + w).strip()
        if draw.textlength(test, font=font) <= max_w:
            cur = test
        else:
            if cur:
                lines.append(cur)
            cur = w
            while len(cur) > 1 and draw.textlength(cur, font=font) > max_w:
                cut = len(cur) - 1
                while cut > 1 and draw.textlength(cur[:cut], font=font) > max_w:
                    cut -= 1
                lines.append(cur[:cut])
                cur = cur[cut:].strip()
    if cur:
        lines.append(cur)
    return lines


def _circular(im, size):
    im = im.convert("RGBA").resize((size, size), Image.LANCZOS)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size - 1, size - 1), fill=255)
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(im, (0, 0), mask)
    return out


async def _load_avatar(client, user_id):
    try:
        photos = await client.get_profile_photos(user_id, limit=1)
        if not photos:
            return None
        raw = await client.download_media(photos[0], file=bytes)
        return Image.open(io.BytesIO(raw)).convert("RGBA")
    except Exception:
        return None


def _default_avatar(initial):
    im = Image.new("RGBA", (AVATAR, AVATAR), ACCENT)
    d = ImageDraw.Draw(im)
    d.text((AVATAR // 2, AVATAR // 2), (initial or "?").upper()[:1],
           font=_font(40, True), fill=(255, 255, 255, 255),
           anchor="mm")
    return im


def _render(name, text, avatar_im):
    size_l = 26
    font_name = _font(26, True)
    font_msg = _font(26)
    tmp = Image.new("RGBA", (WIDTH, 200), (0, 0, 0, 0))
    draw = ImageDraw.Draw(tmp)
    name_w = draw.textlength(name, font=font_name) if name else 0
    name_txt = name if name_w <= WIDTH - 2 * PAD - AVATAR - 16 else name[:20] + "…"

    draw_w = WIDTH - 2 * PAD - AVATAR - 16
    text = " ".join(text.split())[:700]
    lines = _wrap(draw, text, font_msg, draw_w)
    if len(lines) > 9:
        lines = lines[:9]
        lines[-1] = lines[-1][:60] + "…"

    line_h = int(size_l * 1.35)
    img_h = PAD + max(AVATAR, line_h) + 14 + line_h * len(lines) + PAD
    img_h = max(img_h, 200)
    card = Image.new("RGBA", (WIDTH, img_h), (0, 0, 0, 0))
    d = ImageDraw.Draw(card)
    d.rounded_rectangle((0, 0, WIDTH - 1, img_h - 1), radius=RADIUS, fill=FOL_BG)
    d.rounded_rectangle((2, 2, WIDTH - 3, img_h - 3), radius=RADIUS, outline=(54, 62, 70, 255), width=1)
    d.line((PAD, PAD + AVATAR + 12, WIDTH - PAD, PAD + AVATAR + 12), fill=(54, 62, 70, 255), width=1)

    av = avatar_im or _default_avatar(name[:1])
    card.paste(av, (PAD, PAD), av)
    d.text((PAD + AVATAR + 16, PAD + AVATAR // 2 - size_l // 2), name_txt,
           font=font_name, fill=NAME_COLOR)

    y = PAD + AVATAR + 28
    for ln in lines:
        d.text((PAD, y), ln, font=font_msg, fill=TEXT_COLOR)
        y += line_h

    SCALE = 512
    if card.width > SCALE or card.height > SCALE:
        ratio = min(SCALE / card.width, SCALE / card.height)
        card = card.resize(
            (max(1, int(card.width * ratio)), max(1, int(card.height * ratio))),
            Image.LANCZOS,
        )
    canvas = Image.new("RGBA", (SCALE, SCALE), (0, 0, 0, 0))
    canvas.paste(
        card,
        ((SCALE - card.width) // 2, (SCALE - card.height) // 2),
        card,
    )
    return canvas


def load():
    client = helpers.state.client

    @client.on(events.NewMessage(pattern=helpers.cmd(("sticker", "stk")), outgoing=True))
    async def make_sticker(event):
        if not _PIL_OK:
            await helpers.temp(event, helpers.wm("❌ Pillow belum terpasang (install: `pip install pillow`)."))
            await event.delete()
            return
        reply = await event.get_reply_message()
        if not reply:
            await helpers.temp(event, helpers.wm("❌ Reply ke pesan teks yang mau jadi stiker."))
            await event.delete()
            return
        text = (reply.message or (reply.sticker and "🖼 Stiker") or "📎 Media").strip()
        if not text:
            await helpers.temp(event, helpers.wm("❌ Tidak ada teks untuk dijadikan stiker."))
            await event.delete()
            return

        sender = None
        if reply.sender_id:
            try:
                sender = reply.sender or await client.get_entity(reply.sender_id)
            except Exception:
                sender = None
        if sender:
            first = getattr(sender, "first_name", None) or ""
            last = getattr(sender, "last_name", None) or ""
            name = f"{first} {last}".strip() or getattr(sender, "username", None) or str(reply.sender_id)
        else:
            name = f"User {reply.sender_id}"

        av = await _load_avatar(client, reply.sender_id) if reply.sender_id else None
        note = await event.respond(helpers.wm("🖼️ Membuat stiker..."))
        try:
            img = await asyncio.to_thread(_render, name, text, av)
            buf = io.BytesIO()
            img.convert("RGBA").save(buf, format="WEBP")
            buf.seek(0)
            uploaded = await client.upload_file(buf, file_name="sticker.webp")
            media = InputMediaUploadedDocument(
                file=uploaded,
                mime_type="image/webp",
                attributes=[
                    DocumentAttributeSticker(
                        alt="",
                        stickerset=InputStickerSetEmpty(),
                        mask=False,
                    ),
                    DocumentAttributeFilename("sticker.webp"),
                ],
                force_file=False,
            )
            await client.send_media(event.chat_id, media)
            try:
                await note.delete()
            except Exception:
                pass
        except Exception as e:
            await event.respond(helpers.wm(f"❌ Gagal buat stiker: {e}"))
        await event.delete()