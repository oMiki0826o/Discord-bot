"""
bot/mod/music/player.py

Modification():

- 管理單一 Guild 的音樂播放生命週期。
- 管理語音連線、佇列推進、閒置中斷與播放音量。
- 在播放前建立串流來源，並監控語音連線狀態。

本檔負責 Music Module 的 Guild 播放器 Runtime State。
"""

from __future__ import annotations

import asyncio
import logging
import re
import time

import discord

from bot.mod.music.queue import MusicQueue, LoopMode, QueueFullError
from bot.mod.music.song  import Song
from bot.mod.music.config import get, get_int

log = logging.getLogger("bot.music.player")

_URL_IN_ERROR_RE = re.compile(r"https?://\S+", re.IGNORECASE)


class ErrorAwarePCMVolumeTransformer(discord.PCMVolumeTransformer):
    """保留音量控制，同時讓 AudioPlayer 讀得到底層 FFmpeg 錯誤。"""

    @property
    def _current_error(self) -> Exception | None:
        return getattr(self.original, "_current_error", None)


class GuildPlayer:
    """
    單一 Discord 伺服器的音樂播放器。
    由 PlayerManager 建立，每個 Guild 只存在一個實例。
    """

    def __init__(self, bot: discord.Client, guild: discord.Guild) -> None:
        self.bot   = bot
        self.guild = guild
        self.queue = MusicQueue()

        # ── 可調整狀態 ──────────────────────
        self.volume: float = get("music.default_volume_percent", 50) / 100.0
        self.text_channel: discord.TextChannel | None = None

        # ── 內部狀態 ──────────────────────
        self._vc:          discord.VoiceClient | None = None
        self._idle_task:   asyncio.Task        | None = None
        self._play_lock    = asyncio.Lock()
        # True = _play_next 自行發送「正在播放」通知
        self._auto_notify: bool = False
        # 公開的「正在播放」訊息只保留當前一首。一併記錄
        # queue_id 可避免舊歌的 after callback 誤刪新歌訊息。
        self._now_playing_message: discord.Message | None = None
        self._now_playing_song_id: str | None = None
        self._manual_advance_song_id: str | None = None

        # ── 語音健康監控狀態 ──────────────────────
        self._watchdog_task:      asyncio.Task | None = None
        self._disconnected_since: float        | None = None

    # ── 連線管理 ──────────────────────

    async def connect(self, channel: discord.VoiceChannel) -> discord.VoiceClient:
        """
        連線至語音頻道；已連線則移動至新頻道。

        幽靈連接清理：self._vc 存在但 is_connected() 為 False 時，
        先強制 disconnect() 再重新連線，避免 ClientException。

        TimeoutError 轉換：channel.connect() 逾時時拋出 TimeoutError，
        其 str() 為空字串，直接顯示給使用者毫無意義，改為包裝成
        ConnectionError 並附上可讀說明。

        連接逾時秒數由 settings/*.json music.voice_connect_timeout 控制。
        """
        timeout = get_int("music.voice_connect_timeout", 30)

        if self._vc and self._vc.is_connected():
            if self._vc.channel.id != channel.id:
                try:
                    await self._vc.move_to(channel)
                except TimeoutError as exc:
                    raise ConnectionError(
                        f"移動語音頻道逾時（{timeout}s），請確認 Bot 網路連線"
                    ) from exc
                except discord.HTTPException as exc:
                    raise ConnectionError(f"移動語音頻道失敗：{exc}") from exc
            return self._vc

        # ── 清除幽靈連接 ──────────────────────
        if self._vc is not None:
            log.warning("[%s] 清除失效的語音連接", self.guild.name)
            try:
                await self._vc.disconnect(force=True)
            except (discord.ClientException, discord.HTTPException, OSError) as exc:
                log.debug("[%s] 清除失效語音連接失敗：%s", self.guild.name, exc)
            self._vc = None

        # ── 建立新連接 ──────────────────────
        try:
            self._vc = await channel.connect(self_deaf=True, timeout=timeout)
        except TimeoutError as exc:
            raise ConnectionError(
                f"連接語音頻道逾時（{timeout}s），請確認網路連線或稍後再試"
            ) from exc
        except RuntimeError as exc:
            if "davey library needed" in str(exc):
                raise ConnectionError(
                    "Bot 缺少 Discord 語音元件，請聯絡管理員完成安裝。"
                ) from exc
            raise ConnectionError(f"語音元件初始化失敗：{exc}") from exc
        except discord.ClientException as exc:
            raise ConnectionError(f"語音頻道連接失敗：{exc}") from exc

        self._start_watchdog()
        return self._vc

    async def disconnect(self) -> None:
        """中斷連線並完整清理狀態。"""
        self._cancel_idle_timer()
        self._cancel_watchdog()
        await self._delete_now_playing_message()
        self.queue.clear()
        self.queue.current = None
        if self._vc:
            self._vc.stop()
            await self._vc.disconnect(force=True)
            self._vc = None

    # ── 歌曲加入 ──────────────────────

    async def add_song(
        self,
        query:     str,
        requester: discord.Member,
        channel:   discord.TextChannel | None = None,
    ) -> Song:
        """
        解析單曲並加入佇列。
        若目前未播放，立即開始。
        """
        if channel:
            self.text_channel = channel

        was_active = self.is_active
        song       = await Song.from_query(query, requester)
        self.queue.add(song)

        if not was_active:
            async with self._play_lock:
                if not self.is_active:
                    self._auto_notify = False
                    await self._play_next()

        return song

    async def add_playlist(
        self,
        url:       str,
        requester: discord.Member,
        channel:   discord.TextChannel | None = None,
    ) -> tuple[list[Song], int]:
        """
        解析播放清單並批次加入佇列。
        回傳 (成功加入的歌曲清單, 跳過數量)。
        """
        if channel:
            self.text_channel = channel

        if self.queue.size >= self.queue.max_size:
            raise QueueFullError(f"播放佇列已滿（最多 {self.queue.max_size} 首）")

        was_active     = self.is_active
        songs, skipped = await Song.from_playlist(url, requester)

        available = max(0, self.queue.max_size - self.queue.size)
        accepted  = songs[:available]
        skipped  += len(songs) - len(accepted)

        for song in accepted:
            self.queue.add(song)

        if not was_active and accepted:
            async with self._play_lock:
                if not self.is_active:
                    self._auto_notify = False
                    await self._play_next()

        return accepted, skipped

    # ── 播放核心 ──────────────────────

    async def _play_next(self) -> None:
        """
        從佇列取出下一首並開始播放。
        佇列空時啟動閒置計時器；串流提取失敗時以迴圈跳過。
        """
        while True:
            finished_song = self.queue.current
            if finished_song is not None:
                await self._delete_now_playing_message(finished_song.queue_id)

            if not self._vc or not self._vc.is_connected():
                return

            song = self.queue.advance()
            if not song:
                self._start_idle_timer()
                return

            if not await self._start_song(song):
                continue

            if self._auto_notify and self.text_channel:
                from bot.mod.music.embeds import now_playing_embed
                from bot.mod.music.views import MusicControls
                try:
                    message = await self.text_channel.send(
                        embed=now_playing_embed(song, self.queue),
                        view=MusicControls(self),
                    )
                    await self.set_now_playing_message(message, song)
                except discord.HTTPException as exc:
                    log.warning("[%s] 無法發送自動通知：%s", self.guild.name, exc)
            return

    async def _start_song(self, song: Song, retry_attempt: int = 0) -> bool:
        """以最新串流 URL 啟動指定歌曲；擷取失敗時會重試同一首。"""
        if not self._vc or not self._vc.is_connected():
            return False

        max_retries = max(0, get_int("music.stream_retry_attempts", 2))
        try:
            raw_source = await song.create_source()
        except Exception as exc:
            if retry_attempt < max_retries:
                log.warning(
                    "[%s] 音訊串流擷取失敗，重試同一首 attempt=%d/%d error=%s",
                    self.guild.name, retry_attempt + 1, max_retries, type(exc).__name__,
                )
                await asyncio.sleep(0.5)
                return await self._start_song(song, retry_attempt + 1)
            log.error(
                "[%s] 無法載入音訊，已用盡重試，跳過此曲 error=%s",
                self.guild.name, self._safe_error(exc),
            )
            return False

        source = ErrorAwarePCMVolumeTransformer(raw_source, volume=self.volume)
        started_at = time.monotonic()

        def _after(error: Exception | None) -> None:
            asyncio.run_coroutine_threadsafe(
                self._handle_song_end(song, started_at, retry_attempt, error),
                self.bot.loop,
            )

        self._vc.play(source, after=_after)
        self._cancel_idle_timer()
        return True

    async def _handle_song_end(
        self,
        song: Song,
        started_at: float,
        retry_attempt: int,
        error: Exception | None,
    ) -> None:
        """FFmpeg 結束後區分正常播完、手動跳歌與串流失敗。"""
        current = self.queue.current
        if current is None or current.queue_id != song.queue_id:
            return

        manually_advanced = self._manual_advance_song_id == song.queue_id
        if manually_advanced:
            self._manual_advance_song_id = None

        elapsed = max(0.0, time.monotonic() - started_at)
        threshold = max(1, get_int("music.stream_premature_end_seconds", 8))
        if song.duration > 0:
            threshold = min(threshold, max(1, song.duration // 2))
        ended_prematurely = elapsed < threshold
        max_retries = max(0, get_int("music.stream_retry_attempts", 2))

        if not manually_advanced and (error is not None or ended_prematurely):
            if retry_attempt < max_retries:
                log.warning(
                    "[%s] 音訊串流異常結束，重新擷取 URL 重試同一首 "
                    "song=%s elapsed=%.2fs attempt=%d/%d error=%s",
                    self.guild.name, song.queue_id, elapsed,
                    retry_attempt + 1, max_retries,
                    self._safe_error(error) if error else "premature_eof",
                )
                await asyncio.sleep(0.5)
                if await self._start_song(song, retry_attempt + 1):
                    return
            else:
                log.error(
                    "[%s] 音訊串流重試用盡，跳過此曲 song=%s error=%s",
                    self.guild.name, song.queue_id,
                    self._safe_error(error) if error else "premature_eof",
                )

        self._auto_notify = True
        await self._play_next()

    @staticmethod
    def _safe_error(error: Exception) -> str:
        """移除錯誤內可能含簽名與 token 的媒體 URL。"""
        cleaned = _URL_IN_ERROR_RE.sub("<media-url>", str(error))
        return f"{type(error).__name__}: {cleaned[:500]}"

    async def set_now_playing_message(
        self,
        message: discord.Message,
        song: Song,
    ) -> None:
        """記錄當前公開播放 embed，並清理仍殘留的舊訊息。"""
        if self.current_song is None or self.current_song.queue_id != song.queue_id:
            try:
                await message.delete()
            except (discord.NotFound, discord.Forbidden, discord.HTTPException) as exc:
                log.debug("[%s] 清理過期播放通知失敗：%s", self.guild.name, exc)
            return
        if self._now_playing_message is not None and self._now_playing_message.id != message.id:
            await self._delete_now_playing_message()
        self._now_playing_message = message
        self._now_playing_song_id = song.queue_id

    async def _delete_now_playing_message(self, song_id: str | None = None) -> None:
        """刪除目前播放 embed；指定 song_id 時只刪除對應歌曲。"""
        if song_id is not None and song_id != self._now_playing_song_id:
            return

        message = self._now_playing_message
        self._now_playing_message = None
        self._now_playing_song_id = None
        if message is None:
            return
        try:
            await message.delete()
        except discord.NotFound:
            log.debug("[%s] 播放通知已不存在", self.guild.name)
        except (discord.Forbidden, discord.HTTPException) as exc:
            log.warning("[%s] 無法刪除已結束歌曲的通知：%s", self.guild.name, exc)

    # ── 播放控制 ──────────────────────

    def skip(self) -> None:
        if self._vc and (self._vc.is_playing() or self._vc.is_paused()):
            if self.queue.current is not None:
                self._manual_advance_song_id = self.queue.current.queue_id
            self._vc.stop()

    def pause(self) -> bool:
        if self._vc and self._vc.is_playing():
            self._vc.pause()
            return True
        return False

    def resume(self) -> bool:
        if self._vc and self._vc.is_paused():
            self._vc.resume()
            return True
        return False

    async def stop(self) -> None:
        """停止播放並清空佇列，之後依閒置逾時設定離開語音頻道。"""
        await self._delete_now_playing_message()
        self.queue.clear()
        self.queue.current = None
        self._manual_advance_song_id = None
        if self._vc:
            self._vc.stop()
            if self._vc.is_connected():
                self._start_idle_timer()

    def set_volume(self, volume: float) -> None:
        """設定音量（0.0 至 2.0），若正在播放則即時套用。"""
        self.volume = max(0.0, min(2.0, volume))
        if (
            self._vc
            and self._vc.source
            and isinstance(self._vc.source, discord.PCMVolumeTransformer)
        ):
            self._vc.source.volume = self.volume

    def set_loop(self, mode: LoopMode) -> None:
        self.queue.loop_mode = mode

    # ── 狀態屬性 ──────────────────────

    @property
    def is_playing(self) -> bool:
        return bool(self._vc and self._vc.is_playing())

    @property
    def is_paused(self) -> bool:
        return bool(self._vc and self._vc.is_paused())

    @property
    def is_connected(self) -> bool:
        return bool(self._vc and self._vc.is_connected())

    @property
    def is_active(self) -> bool:
        return self.is_playing or self.is_paused

    @property
    def current_song(self) -> Song | None:
        return self.queue.current

    @property
    def voice_channel(self) -> discord.VoiceChannel | None:
        return self._vc.channel if self._vc else None  # type: ignore[return-value]

    # ── 閒置計時器 ──────────────────────

    def _start_idle_timer(self) -> None:
        self._cancel_idle_timer()
        self._idle_task = asyncio.create_task(self._idle_disconnect())

    def _cancel_idle_timer(self) -> None:
        current = asyncio.current_task()
        if self._idle_task and self._idle_task is not current and not self._idle_task.done():
            self._idle_task.cancel()
        self._idle_task = None

    async def _idle_disconnect(self) -> None:
        timeout = get_int("music.idle_timeout_seconds", 180)
        await asyncio.sleep(timeout)
        log.info("[%s] 閒置 %ds，自動斷線", self.guild.name, timeout)

        message = str(
            get("music.idle_disconnect_message", "超過三分鐘沒事了，我先離開了")
        ).strip()
        if message and self.text_channel:
            try:
                await self.text_channel.send(message)
            except discord.HTTPException as exc:
                log.warning("[%s] 無法發送閒置離開通知：%s", self.guild.name, exc)

        await self.disconnect()

    # ── 語音健康監控 ──────────────────────

    def _start_watchdog(self) -> None:
        """連線成功後啟動健康監控迴圈。"""
        self._cancel_watchdog()
        self._disconnected_since = None
        self._watchdog_task = asyncio.create_task(self._voice_watchdog())

    def _cancel_watchdog(self) -> None:
        """停止健康監控迴圈（disconnect() 時呼叫）。"""
        current = asyncio.current_task()
        if self._watchdog_task and self._watchdog_task is not current and not self._watchdog_task.done():
            self._watchdog_task.cancel()
        self._watchdog_task      = None
        self._disconnected_since = None

    async def _voice_watchdog(self) -> None:
        """
        週期性檢查語音連線健康度。

        每隔 music.voice_health_check_interval_seconds 秒檢查一次
        is_connected()；一旦連續斷線超過
        music.voice_reconnect_grace_seconds 秒仍未恢復，視為
        discord.py 內部的自動重連已經失敗，主動強制清理連線，
        而非放任其無限期卡在 pending 狀態。
        """
        interval = get_int("music.voice_health_check_interval_seconds", 15)
        grace    = get_int("music.voice_reconnect_grace_seconds", 60)
        loop     = asyncio.get_event_loop()

        while True:
            await asyncio.sleep(interval)

            if self._vc is None:
                return  # 已被 disconnect() 清理，監控迴圈自然結束

            if self._vc.is_connected():
                self._disconnected_since = None
                continue

            now = loop.time()
            if self._disconnected_since is None:
                self._disconnected_since = now
                continue

            if now - self._disconnected_since < grace:
                continue

            # ── 超過寬限時間仍未恢復，視為連線已死 ──────────────────────
            log.warning(
                "[%s] 語音連線已斷開超過 %ds 仍未恢復，強制清理",
                self.guild.name, grace,
            )
            await self._notify_connection_lost()
            await self.disconnect()
            return

    async def _notify_connection_lost(self) -> None:
        """語音連線判定為已死時，於文字頻道通知使用者（有設定時才發送）。"""
        if not self.text_channel:
            return
        try:
            await self.text_channel.send("語音連線不穩定，已自動離開頻道，請重新使用 /play")
        except discord.HTTPException as exc:
            log.warning("[%s] 無法發送連線中斷通知：%s", self.guild.name, exc)
