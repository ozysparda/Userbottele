"""Join grup via invite link: .joingc, .stopjgc, .gclink, .gclist."""
import asyncio
import random
import re

from telethon import events
from telethon.errors import (
    ChannelInvalidError,
    ChannelPrivateError,
    FloodWaitError,
    UsernameInvalidError,
    UsernameNotOccupiedError,
    UserPrivacyRestrictedError,
)

from core import helpers, store
from core.state import state

LINK_PATTERN = re.compile(
    r"(?:https?://)?t\.me/(?:joinchat|\+)\s*/?\s*([A-Za-z0-9_-]+)"
)

JOIN_FAILED_KEY = "gc_join_failed"
JOIN_STATS_KEY = "gc_join_stats"


def _extract_hashes(text):
    return list(set(LINK_PATTERN.findall(text)))


def _get_joined():
    return set(store.load("gc_joined", []))


def _save_joined(joined):
    store.save("gc_joined", list(joined))


def load():
    client = state.client

    @client.on(events.NewMessage(
        pattern=helpers.cmd("joingc", r"(?:\s+(\d+))?(?:\s+(\d+))?"),
        outgoing=True,
    ))
    async def joingc(event):
        state.stop["jgc"] = False

        count = int(event.pattern_match.group(1) or 20)
        cooldown = int(event.pattern_match.group(2) or 60)
        count = min(max(count, 1), 50)
        cooldown = min(max(cooldown, 20), 300)

        links = []

        if event.is_reply:
            reply = await event.get_reply_message()
            links = _extract_hashes(reply.text or "")
        else:
            parts = event.message.message.split()
            for p in parts:
                if LINK_PATTERN.match(p) or LINK_PATTERN.search(p):
                    links.extend(_extract_hashes(p))
            if not links:
                links = store.load("gc_links", [])

        if not links:
            await helpers.temp(event, helpers.wm(
                "❌ Tidak ada invite link.\n"
                "Cara pakai:\n"
                "1. Reply pesan berisi link → `.joingc 20`\n"
                "2. `.joingc 20 https://t.me/+abc ...`\n"
                "3. Simpan link ke `.gclink <link1> <link2> ...` dulu"
            ))
            await event.delete()
            return

        random.shuffle(links)
        joined = _get_joined()
        skipped = [h for h in links if h in joined]
        links = [h for h in links if h not in joined]

        if not links:
            await helpers.temp(event, helpers.wm(
                f"✅ Semua {len(skipped)} link sudah pernah dijoin."
            ))
            await event.delete()
            return

        to_join = links[:count]
        store.save("gc_links", links)

        await event.delete()
        progress = await event.respond(helpers.wm(
            f"🔄 **Mulai join {len(to_join)} GC** (cooldown {cooldown}s)"
        ))

        ok = 0
        fail = 0
        failed_list = []

        for i, h in enumerate(to_join):
            if state.stop.get("jgc"):
                await progress.edit(helpers.wm(
                    f"⏹ Dihentikan owner. Berhasil: {ok}, Gagal: {fail}"
                ))
                break

            url = f"https://t.me/+{h}"
            try:
                await client.join_chat(url)
                ok += 1
            except FloodWaitError as e:
                await asyncio.sleep(e.seconds + 5)
                try:
                    await client.join_chat(url)
                    ok += 1
                except Exception:
                    fail += 1
                    failed_list.append(h)
            except (
                UsernameInvalidError,
                UsernameNotOccupiedError,
                ChannelPrivateError,
                ChannelInvalidError,
                UserPrivacyRestrictedError,
            ) as e:
                fail += 1
                failed_list.append(h)
            except Exception:
                fail += 1
                failed_list.append(h)

            if (i + 1) % 5 == 0 or (i + 1) == len(to_join):
                try:
                    await progress.edit(helpers.wm(
                        f"⏳ Progress: {i+1}/{len(to_join)} | ✅ {ok} | ❌ {fail}"
                    ))
                except Exception:
                    pass

            if (i + 1) < len(to_join):
                await asyncio.sleep(cooldown)

        joined = _get_joined()
        for h in to_join:
            if h not in failed_list:
                joined.add(h)
        _save_joined(joined)

        result = f"✅ Join selesai: {ok} berhasil, {fail} gagal"
        if failed_list:
            result += f"\n❌ Gagal: {', '.join(failed_list[:10])}"
            if len(failed_list) > 10:
                result += f" (+{len(failed_list)-10} lainnya)"

        await progress.edit(helpers.wm(result))

        stats = store.load(JOIN_STATS_KEY, {"ok": 0, "fail": 0})
        stats["ok"] += ok
        stats["fail"] += fail
        store.save(JOIN_STATS_KEY, stats)

    @client.on(events.NewMessage(
        pattern=helpers.cmd("stopjgc"), outgoing=True,
    ))
    async def stopjgc(event):
        state.stop["jgc"] = True
        await helpers.temp(event, helpers.wm("⏹ Menghentikan join GC..."))
        await event.delete()

    @client.on(events.NewMessage(
        pattern=helpers.cmd("gclink", r"\s+(.+)"), outgoing=True,
    ))
    async def gclink(event):
        raw = event.pattern_match.group(1)
        hashes = _extract_hashes(raw)
        if not hashes:
            await helpers.temp(event, helpers.wm("❌ Tidak ditemukan link yang valid."))
            await event.delete()
            return
        old = store.load("gc_links", [])
        joined = _get_joined()
        new = [h for h in hashes if h not in joined]
        combined = list(dict.fromkeys(old + new))
        store.save("gc_links", combined)
        await helpers.temp(event, helpers.wm(
            f"📋 {len(new)} link baru ditambahkan. Total tersimpan: {len(combined)}"
        ))
        await event.delete()

    @client.on(events.NewMessage(
        pattern=helpers.cmd("gclist"), outgoing=True,
    ))
    async def gclist(event):
        links = store.load("gc_links", [])
        joined = _get_joined()
        pending = [h for h in links if h not in joined]
        done = [h for h in links if h in joined]
        stats = store.load(JOIN_STATS_KEY, {"ok": 0, "fail": 0})
        text = (
            f"**📋 Invite Link GC**\n"
            f"----------------------\n"
            f"📁 Total link: `{len(links)}`\n"
            f"✅ Sudah join: `{len(done)}`\n"
            f"⏳ Belum join: `{len(pending)}`\n"
            f"📊 Total berhasil: `{stats['ok']}`\n"
            f"❌ Total gagal: `{stats['fail']}`"
        )
        if pending:
            text += f"\n\n🔗 Contoh pending:\n" + "\n".join(
                f"`https://t.me/+{h}`" for h in pending[:5]
            )
        await event.respond(helpers.wm(text))
        await event.delete()

    @client.on(events.NewMessage(
        pattern=helpers.cmd("gcflush"), outgoing=True,
    ))
    async def gcflush(event):
        store.save("gc_links", [])
        _save_joined(set())
        store.save(JOIN_STATS_KEY, {"ok": 0, "fail": 0})
        await helpers.temp(event, helpers.wm("🗑 Semua data GC direset."))
        await event.delete()
