# -*- coding: utf-8 -*-
"""サーバーの死活監視（A2S）。

他人が建てたサーバーは中を覗けないが、A2S_INFO という標準のUDPクエリなら
外から「起きているか・何人いるか・どのマップか」が取れる。
サーバー一覧サイトが見ているのと同じ情報。

これを使う理由:
  ARK のゲーム内時間は**サーバーが動いている間しか進まない**。
  定期再起動やクラッシュで落ちていた分だけ、こちらの時計はズレる。
  落ちているのを見つけたら、その間だけ時計を止めれば自動で合い続ける。

（問い合わせ部分の作りは game-server-manager の core/a2s.py と同じ）
"""
from __future__ import annotations

import socket
import struct
import threading
import time

A2S_INFO = b"\xFF\xFF\xFF\xFFTSource Engine Query\x00"
DEFAULT_TIMEOUT = 3.0


class A2SError(Exception):
    pass


def _read_cstr(data, pos):
    end = data.index(b"\x00", pos)
    return data[pos:end].decode("utf-8", "replace"), end + 1


def info(host, port, timeout=DEFAULT_TIMEOUT):
    """A2S_INFO を投げてサーバー情報を返す。応答が無ければ A2SError。"""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(timeout)
    try:
        s.sendto(A2S_INFO, (host, port))
        data, _ = s.recvfrom(4096)
        if len(data) >= 5 and data[4:5] == b"A":     # チャレンジ要求
            s.sendto(A2S_INFO + data[5:9], (host, port))
            data, _ = s.recvfrom(4096)
    except (socket.timeout, OSError) as exc:
        raise A2SError("応答がありません（%s:%s）" % (host, port)) from exc
    finally:
        s.close()

    if len(data) < 6 or data[4:5] != b"I":
        raise A2SError("応答の形式が想定と違います")
    pos = 6                                          # ヘッダ4 + 'I' + protocol
    out = {}
    for key in ("name", "map", "folder", "game"):
        out[key], pos = _read_cstr(data, pos)
    try:
        out["app_id"] = struct.unpack_from("<H", data, pos)[0]
        pos += 2
        out["players"] = data[pos]
        out["max_players"] = data[pos + 1]
        out["bots"] = data[pos + 2]
    except (struct.error, IndexError):
        pass                                          # 人数まで読めなくても生死は分かる
    return out


def parse_address(text, default_port=27015):
    """'1.2.3.4:27015' / 'host 27015' / 'host' を (host, port) に。"""
    t = (text or "").strip()
    if not t:
        return None
    t = t.replace(",", " ").replace(":", " ")
    parts = [x for x in t.split() if x]
    if not parts:
        return None
    host = parts[0]
    port = default_port
    if len(parts) > 1:
        try:
            port = int(parts[1])
        except ValueError:
            return None
    if not 1 <= port <= 65535:
        return None
    return host, port


class Watcher(threading.Thread):
    """登録されたサーバーを順に叩いて、生死を覚えておくスレッド。

    get_targets() は [(キー, 'host:port'), ...] を返す関数。
    生死が変わったとき、落ちている間の秒数を on_hold(キー, 秒) で知らせる。
    """

    def __init__(self, get_targets, on_hold=None, interval=60.0):
        super().__init__(daemon=True)
        self.get_targets = get_targets
        self.on_hold = on_hold
        self.interval = float(interval)
        self._halt = threading.Event()
        self.state = {}          # キー -> 最後に見た結果
        self._last_seen = {}     # キー -> 最後に確認した時刻

    def stop(self):
        self._halt.set()

    def check_now(self, key, address):
        """1件だけその場で確認する（画面の「ためす」用）。"""
        addr = parse_address(address)
        if not addr:
            return {"ok": False, "why": "アドレスの書き方が違います（例 1.2.3.4:27015）"}
        try:
            d = info(*addr)
        except A2SError as e:
            return {"ok": False, "why": str(e), "online": False, "at": time.time()}
        except Exception as e:
            return {"ok": False, "why": "%s: %s" % (e.__class__.__name__, e),
                    "online": False, "at": time.time()}
        d.update({"ok": True, "online": True, "at": time.time()})
        return d

    def run(self):
        while not self._halt.is_set():
            for key, address in (self.get_targets() or []):
                if self._halt.is_set():
                    break
                res = self.check_now(key, address)
                prev = self.state.get(key)
                now = res.get("at") or time.time()
                # 落ちている間は、前回の確認からの時間だけ時計を止める
                if prev is not None and not res.get("online"):
                    gap = now - self._last_seen.get(key, now)
                    if gap > 0 and self.on_hold:
                        try:
                            self.on_hold(key, gap)
                        except Exception:
                            pass
                self._last_seen[key] = now
                self.state[key] = res
            self._halt.wait(max(10.0, self.interval))
