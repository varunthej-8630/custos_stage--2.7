# alert_manager.py — Updated
# Changes:
#   - Telegram message now in simple plain English
#   - Time shown in 12hr format
#   - Describes what the person is doing in plain words
#   - Tamper message also uses 12hr time

import cv2, time, os, asyncio, threading, queue
from config import settings as config

try:
    import telegram  # type: ignore
    TELEGRAM_AVAILABLE = True
except ImportError:
    TELEGRAM_AVAILABLE = False
    from engine.logger import alert_logger
    alert_logger.warning('python-telegram-bot not installed.')

try:
    from plyer import notification  # type: ignore
    PLYER_AVAILABLE = True
except ImportError:
    PLYER_AVAILABLE = False

try:
    import pygame  # type: ignore
    pygame.mixer.init()
    PYGAME_AVAILABLE = True
except Exception:
    PYGAME_AVAILABLE = False


class AlertManager:
    def __init__(self):
        self.last_alert   = 0
        self.last_tamper  = 0
        self._running     = True
        self._send_queue  = queue.Queue()
        os.makedirs(config.SNAPSHOT_DIR, exist_ok=True)

        self._alarm_sound = None
        if PYGAME_AVAILABLE:
            self._alarm_sound = self._generate_beep()

        if TELEGRAM_AVAILABLE and config.TELEGRAM_TOKEN:
            self.bot = telegram.Bot(token=config.TELEGRAM_TOKEN)
            self._sender_thread = threading.Thread(
                target=self._sender_loop, daemon=False)
            self._sender_thread.start()
            from engine.logger import alert_logger
            alert_logger.info('Telegram bot ready.')
        else:
            self.bot = None
            from engine.logger import alert_logger
            alert_logger.info('No Telegram token — terminal alerts only.')

    # ── MAIN ALERT ────────────────────────────────────────────
    def check_and_send(self, frame, score, risk_engine):
        now = time.time()
        if now - self.last_alert < config.ALERT_COOLDOWN:
            return
        if not risk_engine.should_alert():
            return
        self.last_alert = now

        snap = self._save_snapshot(frame, score)
        msg  = self._build_message(score, risk_engine.event_log)
        
        from engine.logger import alert_logger
        alert_logger.info(f'Score={score:.0f} — queuing send')

        self._play_alarm()
        self._desktop_popup(score, risk_engine.event_log)

        if self.bot:
            self._send_queue.put(('photo', msg, snap))
        else:
            alert_logger.info(f'{msg}')

    # ── TAMPER ALERT ──────────────────────────────────────────
    def send_tamper_alert(self, pre_tamper_clip_path=None):
        now = time.time()
        if now - self.last_tamper < 30:
            return
        self.last_tamper = now

        now_str = time.strftime("%I:%M:%S %p")
        msg = (
            f'📵 Camera Tamper Detected!\n'
            f'━━━━━━━━━━━━━━━━━━━━\n'
            f'🕐 Time: {now_str}\n'
            f'⚠️ The camera is being blocked or covered\n'
            f'━━━━━━━━━━━━━━━━━━━━\n'
            f'SmartGuard 🛡'
        )
        from engine.logger import alert_logger
        alert_logger.warning('Camera tamper detected!')
        self._play_alarm(repeat=3)

        if self.bot:
            self._send_queue.put(('text', msg, None))
            if pre_tamper_clip_path and os.path.exists(pre_tamper_clip_path):
                self._send_queue.put(('video', msg, pre_tamper_clip_path))

    def shutdown(self):
        self._running = False

    # ── SENDER THREAD ─────────────────────────────────────────
    def _sender_loop(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        while self._running or not self._send_queue.empty():
            try:
                item = self._send_queue.get(timeout=1)
                kind, msg, payload = item
                try:
                    loop.run_until_complete(
                        self._send_with_timeout(kind, msg, payload))
                except RuntimeError:
                    pass
            except queue.Empty:
                continue
            except Exception:
                pass
        try:
            loop.close()
        except Exception:
            pass

    async def _send_with_timeout(self, kind, msg, payload):
        try:
            async def _do_send():
                async with self.bot:
                    if kind == 'photo':
                        # Send text first — instant notification
                        await self.bot.send_message(
                            chat_id=config.TELEGRAM_CHAT_ID,
                            text=msg)
                        from engine.logger import alert_logger
                        alert_logger.info('Telegram text sent instantly')
                        # Then send photo
                        if payload and os.path.exists(payload):
                            with open(payload, 'rb') as pf:
                                await self.bot.send_photo(
                                    chat_id=config.TELEGRAM_CHAT_ID,
                                    photo=pf,
                                    caption='📸 Alert snapshot')
                            alert_logger.info('Telegram photo sent')
                    elif kind == 'text':
                        await self.bot.send_message(
                            chat_id=config.TELEGRAM_CHAT_ID,
                            text=msg)
                        from engine.logger import alert_logger
                        alert_logger.info('Telegram text sent')
                    elif kind == 'video' and payload and os.path.exists(payload):
                        with open(payload, 'rb') as vf:
                            await self.bot.send_video(
                                chat_id=config.TELEGRAM_CHAT_ID,
                                video=vf,
                                caption=msg)
                        from engine.logger import alert_logger
                        alert_logger.info('Telegram video sent')

            await asyncio.wait_for(_do_send(), timeout=12.0)
        except asyncio.TimeoutError:
            from engine.logger import alert_logger
            alert_logger.warning('Telegram timeout (12s) — check internet.')
        except Exception as e:
            from engine.logger import alert_logger
            alert_logger.error(f'Telegram error: {e}')

    # ── OFFLINE ALERTS ────────────────────────────────────────
    def _generate_beep(self):
        try:
            import numpy as np
            sr   = 44100
            t    = np.linspace(0, 0.4, int(sr * 0.4))
            wave = (np.sin(2 * 3.14159 * 880 * t) * 32767).astype(np.int16)
            stereo = np.column_stack([wave, wave])
            return pygame.sndarray.make_sound(stereo)
        except Exception:
            return None

    def _play_alarm(self, repeat=2):
        if not PYGAME_AVAILABLE or not self._alarm_sound:
            return
        def _play():
            for _ in range(repeat):
                try:
                    self._alarm_sound.play()
                    time.sleep(0.5)
                except Exception:
                    pass
        threading.Thread(target=_play, daemon=True).start()

    def _desktop_popup(self, score, event_log):
        if not PLYER_AVAILABLE:
            return
        reason = 'Suspicious activity detected'
        for e in event_log:
            if 'HIGH'    in e:       reason = 'Person entered restricted area!'; break
            if 'CROUCH'  in e.upper(): reason = 'Person crouching in zone'; break
            if 'PACING'  in e.upper(): reason = 'Person pacing in zone'; break
            if 'linger'  in e:         reason = 'Person lingering too long'; break
        def _notify():
            try:
                notification.notify(
                    title=f'🚨 Alert — Risk Score: {score:.0f}/100',
                    message=reason, app_name='SmartGuard', timeout=8)
            except Exception:
                pass
        threading.Thread(target=_notify, daemon=True).start()

    # ── SNAPSHOT ──────────────────────────────────────────────
    def _save_snapshot(self, frame, score):
        ts   = time.strftime('%Y%m%d_%H%M%S')
        snap = f'{config.SNAPSHOT_DIR}/alert_{ts}.jpg'
        f    = frame.copy()
        h, w = f.shape[:2]
        cv2.rectangle(f, (0, 0), (w, h), (0, 0, 255), 8)
        cv2.putText(f, f'ALERT! RISK={score:.0f}',
                    (20, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.3, (0, 0, 255), 3)
        cv2.imwrite(snap, f, [cv2.IMWRITE_JPEG_QUALITY, 60])
        return snap

    # ── TELEGRAM MESSAGE — plain simple English ───────────────
    def _build_message(self, score, event_log):
        now_str = time.strftime("%I:%M:%S %p")  # 12hr e.g. 05:46:21 PM

        # Zone
        zone_info = 'Observation Area'
        for e in event_log:
            if 'HIGH' in e:
                zone_info = 'Restricted Area'
                break

        # What the person is doing in plain words
        actions = []
        for e in event_log:
            el = e.upper()
            if 'ENTERED HIGH' in el or 'HIGH ZONE' in el or 'RESTRICTED' in el:
                actions.append('entered a restricted area')
            elif 'PACING' in el:
                actions.append('walking back and forth repeatedly')
            elif 'CROUCH' in el:
                actions.append('crouching down in the zone')
            elif 'FROZE' in el:
                actions.append('stopped moving suddenly')
            elif 'CIRCLING' in el or 'RETURNED' in el:
                actions.append('keeps coming back to the same spot')
            elif 'ERRATIC' in el:
                actions.append('moving in an unusual way')
            elif 'RUNNING' in el:
                actions.append('running inside the zone')
            elif 'LINGER' in el:
                actions.append('standing in the zone for too long')
            elif 'TAMPER' in el:
                actions.append('camera is being blocked or covered')

        actions = list(dict.fromkeys(actions))

        # Risk level
        if score >= 80:
            level_icon = '🔴'
            level_text = 'High Risk'
        elif score >= 60:
            level_icon = '🟠'
            level_text = 'Medium Risk'
        else:
            level_icon = '🟡'
            level_text = 'Low Risk'

        # Build message
        msg  = f'{level_icon} Security Alert — {level_text}\n'
        msg += f'━━━━━━━━━━━━━━━━━━━━\n'
        msg += f'🕐 Time: {now_str}\n'
        msg += f'📍 Location: {zone_info}\n'
        msg += f'📊 Risk Score: {score:.0f} / 100\n'
        if actions:
            msg += f'━━━━━━━━━━━━━━━━━━━━\n'
            msg += f'👁 What is happening:\n'
            for a in actions:
                msg += f'  • Person is {a}\n'
        msg += f'━━━━━━━━━━━━━━━━━━━━\n'
        msg += f'SmartGuard 🛡'
        return msg