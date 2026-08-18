# -*- coding: utf-8 -*-
"""ASA のサーバー情報を Epic Online Services から取る。

ASA は Steam のクエリ(A2S)を喋らないので、外から生死を見る手段が長らく無かった。
サーバー自身が Epic に登録しているセッション情報を読むのが正解。

**3つ揃わないと通らない**（2026-08-18に確認）:
  1. URL に `/wildcard` を挟む（ARK開発元 Studio Wildcard 専用の中継）。
     無印の /matchmaking/v1/... だと、権限があっても常に0件しか返らない。
  2. findSessions 権限のある ClientId。公開実装が使っている
     xyza7891muom... は権限を失っている(403)。ゲーム本体の exe から抜いたものを使う。
  3. デバイス認証で取った**ユーザートークン**。client_credentials のトークンだと
     policy_requires_user で弾かれる。

IPを1つ投げるだけで、そのマシンにあるサーバーが全部返る（クラスタ丸ごと取れる）。
"""
from __future__ import annotations

import base64
import json
import threading
import time
import urllib.parse
import urllib.request

API = "https://api.epicgames.dev"
DEPLOYMENT = "ad9a8feffb3b4b2ca315546f038c3ae2"
CLIENT_ID = "xyza7891qC5rMxf0e76B4lGe5qePQXNy"
CLIENT_SECRET = "14BiZqLRckVJ49d9fZY0/nUoyo+dQ2Z7k8urInugvH4"
TIMEOUT = 20


class EosError(Exception):
    pass


def _post(url, body, headers, raw=False, timeout=TIMEOUT):
    data = body if raw else urllib.parse.urlencode(body).encode()
    req = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        detail = e.read()[:200].decode("utf-8", "replace")
        raise EosError("HTTP %s %s" % (e.code, detail)) from e
    except Exception as e:
        raise EosError("%s: %s" % (e.__class__.__name__, e)) from e


class Client:
    """トークンを取って使い回す。1時間もつので毎回取り直さない。"""

    def __init__(self, client_id=CLIENT_ID, client_secret=CLIENT_SECRET,
                 deployment=DEPLOYMENT):
        self.client_id = client_id
        self.client_secret = client_secret
        self.deployment = deployment
        self._token = None
        self._expires = 0.0
        self._lock = threading.Lock()

    @property
    def _basic(self):
        raw = ("%s:%s" % (self.client_id, self.client_secret)).encode()
        return "Basic " + base64.b64encode(raw).decode()

    def _form_headers(self):
        return {"Authorization": self._basic,
                "Content-Type": "application/x-www-form-urlencoded"}

    def token(self, force=False):
        with self._lock:
            if not force and self._token and time.time() < self._expires - 120:
                return self._token
            # client_credentials -> デバイスID -> ユーザートークン の3段
            _post(API + "/auth/v1/oauth/token",
                  {"grant_type": "client_credentials",
                   "deployment_id": self.deployment}, self._form_headers())
            dev = _post(API + "/auth/v1/accounts/deviceid",
                        {"deviceModel": "PC"}, self._form_headers())
            got = _post(API + "/auth/v1/oauth/token",
                        {"grant_type": "external_auth",
                         "external_auth_type": "deviceid_access_token",
                         "external_auth_token": dev.get("access_token", ""),
                         "deployment_id": self.deployment,
                         "display_name": "User",
                         "nonce": "ArkBreedingTimer"}, self._form_headers())
            self._token = got["access_token"]
            self._expires = time.time() + float(got.get("expires_in") or 3600)
            return self._token

    def sessions_by_address(self, address):
        """そのIPにあるサーバーを全部返す。見つからなければ空リスト。"""
        body = {"criteria": [{"key": "attributes.ADDRESS_s", "op": "EQUAL",
                              "value": address}]}
        url = "%s/wildcard/matchmaking/v1/%s/filter" % (API, self.deployment)
        for attempt in (0, 1):
            try:
                res = _post(url, json.dumps(body).encode(),
                            {"Authorization": "Bearer " + self.token(force=bool(attempt)),
                             "Content-Type": "application/json",
                             "Accept": "application/json"}, raw=True)
            except EosError as e:
                if attempt == 0 and "401" in str(e):
                    continue          # トークン切れなら取り直して1回だけ再試行
                raise
            return [_summarize(s) for s in res.get("sessions", [])]
        return []


def _summarize(session):
    """使う項目だけ取り出す。"""
    a = session.get("attributes", {})
    bound = a.get("ADDRESSBOUND_s") or ""
    port = None
    if ":" in bound:
        try:
            port = int(bound.rsplit(":", 1)[1])
        except ValueError:
            port = None
    day = a.get("DAYTIME_s")
    try:
        day = int(day)
    except (TypeError, ValueError):
        day = None
    return {
        "name": a.get("CUSTOMSERVERNAME_s") or a.get("SESSIONNAME_s") or "",
        "map": a.get("MAPNAME_s") or "",
        "players": session.get("totalPlayers"),
        "max_players": (session.get("settings") or {}).get("maxPublicPlayers"),
        "port": port,
        "day": day,                    # ARK の「Day N」。増えた瞬間が日の変わり目
        "password": bool(a.get("SERVERPASSWORD_b")),
        "build": a.get("BUILDID_s"),
        "cluster": a.get("CLUSTERID_s"),
        "pve": a.get("SESSIONISPVE_l") == 1,
    }


def parse_address(text):
    """'1.2.3.4' / '1.2.3.4:7980' から (IP, ポート or None) を返す。"""
    t = (text or "").strip()
    if not t:
        return None, None
    t = t.replace(",", " ").replace(":", " ")
    parts = [x for x in t.split() if x]
    if not parts:
        return None, None
    port = None
    if len(parts) > 1:
        try:
            port = int(parts[1])
        except ValueError:
            port = None
    return parts[0], port
