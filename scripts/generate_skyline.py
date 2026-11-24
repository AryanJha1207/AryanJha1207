#!/usr/bin/env python3
"""
Generates assets/skyline.svg: an animated 3D contribution skyline where a spider
web-swings across your active days and towers rise behind it.

The output uses the approved ARYZEN NEX card styling (glass frame, Rajdhani labels,
gradient stats) via restyle(); the spider and tower animation is unchanged.

Data comes from the GitHub GraphQL API (contribution calendar + repo languages),
so the picture changes whenever you commit. Pure standard library, no installs.

Usage (the GitHub Action does this for you):
    GH_TOKEN=... GH_USER=AryanJha1207 python scripts/generate_skyline.py
Options:
    --out PATH          output file (default assets/skyline.svg)
    --from-json PATH    read a saved GraphQL response instead of calling the API
    --allow-sample      if the API is unreachable, draw sample data (never used by the Action)
"""
import argparse, datetime as dt, json, math, os, random, re, sys, urllib.request

USER = os.environ.get("GH_USER", "AryanJha1207")
TOKEN = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") or ""

COLS, ROWS = 36, 7
CW, DXS, DYS = 16, 10, 9
PITCH, RDX, RDY = 25, 14, 18
X0, YFRONT = 57, 410
W, H = 1100, 530
HEIGHTS = [22, 46, 68, 92]
# top, front, side  (cool -> hot as activity rises)
PAL = [
    ("#5f93c9", "#2f609a", "#1b3c63", "b"),
    ("#86c4ff", "#3f87d9", "#21548f", "b"),
    ("#ff8a8d", "#d9283a", "#85121f", "r"),
    ("#ffb3b5", "#ff3b44", "#a8161f", "r"),
]
GLOW = {"r": "#ff3b3f", "b": "#4d9fff"}
RING = {"r": "#ff7a7e", "b": "#8cc8ff"}
LANG_COLORS = ["#4d9fff", "#e62429", "#8e6bbf", "#2a3349"]

QUERY = """
query($login:String!){
  user(login:$login){
    contributionsCollection{ contributionCalendar{ totalContributions weeks{ contributionDays{ contributionCount date weekday } } } }
    repositories(first:100, ownerAffiliations:OWNER, isFork:false){
      nodes{ languages(first:8, orderBy:{field:SIZE, direction:DESC}){ edges{ size node{ name } } } }
    }
  }
}"""


# --------------------------------------------------------------------------- data
def fetch():
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": QUERY, "variables": {"login": USER}}).encode(),
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json", "User-Agent": "skyline-generator"},
    )
    with urllib.request.urlopen(req, timeout=40) as r:
        payload = json.load(r)
    if "errors" in payload or not payload.get("data", {}).get("user"):
        raise RuntimeError(f"GraphQL error: {payload.get('errors') or 'user not found'}")
    return payload["data"]["user"]


def sample_user():
    rng = random.Random(11)
    weeks = []
    day = dt.date.today() - dt.timedelta(days=53 * 7)
    for _ in range(53):
        days = []
        for wd in range(7):
            p = 0.3 + 0.2 * math.sin(len(weeks) / 3.1) + (0.12 if 0 < wd < 6 else -0.18)
            n = rng.choice([1, 2, 3, 5, 8]) if rng.random() < p else 0
            days.append({"contributionCount": n, "date": str(day), "weekday": wd})
            day += dt.timedelta(days=1)
        weeks.append({"contributionDays": days})
    total = sum(d["contributionCount"] for w in weeks for d in w["contributionDays"])
    langs = [("JavaScript", 38), ("Python", 27), ("Java", 20), ("HTML", 15)]
    repos = [{"languages": {"edges": [{"size": s, "node": {"name": n}} for n, s in langs]}}]
    return {"contributionsCollection": {"contributionCalendar": {"totalContributions": total, "weeks": weeks}},
            "repositories": {"nodes": repos}}


def analyse(user):
    cal = user["contributionsCollection"]["contributionCalendar"]
    weeks = cal["weeks"]
    flat = [d for w in weeks for d in w["contributionDays"]]
    counts = [d["contributionCount"] for d in flat]
    # streaks (today may still be empty, so it does not break the current streak)
    cur, i = 0, len(counts) - 1
    if i >= 0 and counts[i] == 0:
        i -= 1
    while i >= 0 and counts[i] > 0:
        cur += 1
        i -= 1
    longest = run = 0
    for c in counts:
        run = run + 1 if c > 0 else 0
        longest = max(longest, run)
    # grid: last COLS weeks
    grid = {}
    last = weeks[-COLS:]
    nz = sorted(d["contributionCount"] for w in last for d in w["contributionDays"] if d["contributionCount"] > 0)

    def level(n):
        if not nz:
            return 0
        q = lambda f: nz[min(len(nz) - 1, int(f * len(nz)))]
        return 0 if n <= q(.25) else 1 if n <= q(.5) else 2 if n <= q(.75) else 3

    for ci, w in enumerate(last):
        for d in w["contributionDays"]:
            if d["contributionCount"] > 0:
                grid[(ci + (COLS - len(last)), d["weekday"])] = level(d["contributionCount"])
    # languages
    sizes = {}
    for repo in user["repositories"]["nodes"]:
        for e in repo["languages"]["edges"]:
            sizes[e["node"]["name"]] = sizes.get(e["node"]["name"], 0) + e["size"]
    tot = sum(sizes.values()) or 1
    top = sorted(sizes.items(), key=lambda kv: -kv[1])[:3]
    langs = [(n, round(100 * s / tot)) for n, s in top]
    other = max(0, 100 - sum(p for _, p in langs))
    return {"total": cal["totalContributions"], "current": cur, "longest": longest, "grid": grid, "langs": langs, "other": other}


# --------------------------------------------------------------------------- drawing
def origin(c, r):
    k = ROWS - 1 - r
    return X0 + c * PITCH + k * RDX, YFRONT - k * RDY


def gcenter(c, r):
    x, y = origin(c, r)
    return x + CW / 2 + DXS / 2, y - DYS / 2


def load_fonts():
    return ""   # the original fonts are replaced by restyle()


def card_fonts():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "skyline_fonts.json")
    fonts = json.load(open(path))
    css = ""
    for fam, weights in fonts.items():
        for w, data in weights.items():
            css += f"@font-face{{font-family:{fam};font-weight:{w};src:url(data:font/ttf;base64,{data}) format('truetype')}}"
    css += "text{font-family:RJ,sans-serif;font-weight:600}.mc{font-family:MC,sans-serif;font-weight:400}"
    return css


def restyle(s, info, stamp):
    """Turn build()'s output into the approved card styling. Mirrors the approved sample skyline exactly."""
    sample = bool(info.get("sample"))
    s = re.sub(r'<style>.*?</style>', '', s, flags=re.S)
    i = s.index('<rect x="1" y="1" width="1098" height="528"')
    body = s[i:]
    od = re.search(r'<defs>(.*?)</defs>', s, re.S).group(1)
    od = re.sub(r'<linearGradient id="g".*?</linearGradient>', '', od, count=1, flags=re.S)
    od = re.sub(r'<clipPath id="pane">.*?</clipPath>', '', od, flags=re.S)
    body = re.sub(r'<rect x="1" y="1" width="1098" height="528"[^>]*/>\n', '', body, 1)
    body = re.sub(r'<circle cx="(34|53|72)" cy="27"[^>]*/>\n', '', body)
    body = re.sub(r'<text x="550.0" y="31"[^>]*>.*?</text>\n', '', body)
    body = re.sub(r'<text x="1066" y="31"[^>]*>LIVE</text>\n', '', body)
    body = re.sub(r'<circle cx="1022" cy="27".*?</circle>\n', '', body, flags=re.S)
    body = re.sub(r'<line x1="1" y1="52" x2="1099" y2="52"[^>]*/>\n', '', body)
    body = body.replace('<rect x="24" y="72" width="1052" height="434" rx="10" fill="#04060b" stroke="#1b2540"/>', '<rect x="24" y="72" width="1052" height="434" rx="20" fill="#050a18" fill-opacity=".8" stroke="url(#bd)" stroke-opacity=".5" stroke-width="1.6"/>')
    body = body.replace('ACTIVITY.SKYLINE', 'ACTIVITY SKYLINE')
    body = body.replace('font-size="46" letter-spacing="1" fill="#f2f5fb"', 'font-size="26" fill="url(#gn)"')
    body = body.replace('fill="#4d9fff">ACTIVITY SKYLINE', 'fill="#ffffff" font-weight="700">ACTIVITY SKYLINE').replace('font-size="11" letter-spacing="2.5" fill="#ffffff"', 'font-size="15" letter-spacing="6" fill="#ffffff"')
    body = body.replace('font-size="11"', 'font-size="13.5"').replace('font-size="12"', 'font-size="14"').replace('font-size="13"', 'font-size="14"')
    old = 'M18,1 H1082 A17,17 0 0 1 1099,18 V512 A17,17 0 0 1 1082,529 H18 A17,17 0 0 1 1,512 V18 A17,17 0 0 1 18,1 Z'
    assert old in body
    body = body.replace(old, 'M31,3 H1069 A28,28 0 0 1 1097,31 V499 A28,28 0 0 1 1069,527 H31 A28,28 0 0 1 3,499 V31 A28,28 0 0 1 31,3 Z')

    def rep(a, b):
        nonlocal body
        assert a in body, a
        body = body.replace(a, b)
    rep('font-size="15" letter-spacing="6" fill="#ffffff" font-weight="700">ACTIVITY SKYLINE', 'font-size="24" letter-spacing="6" fill="#ffffff" font-weight="700">ACTIVITY SKYLINE')
    rep('<text x="1056" y="96" text-anchor="end" font-size="13.5" letter-spacing="2.5" fill="#e62429">', '<text x="1056" y="96" text-anchor="end" font-size="20" letter-spacing="2.5" fill="#ff5a5f">')
    body = re.sub(r'<text x="1056" y="113"[^>]*>[^<]*</text>\n?', '', body)   # sync stamp lives in the title instead, clear of the spider path
    nums = [("--" if sample else f"{info['total']:,}"), ("--" if sample else str(info["current"])), ("--" if sample else str(info["longest"]))]
    for (x, lab), num in zip(((44, 'CONTRIBUTIONS / 12 MO'), (244, 'CURRENT STREAK'), (444, 'LONGEST STREAK')), nums):
        nx = {44: 44, 244: 330, 444: 580}[x]
        shown = "SYNC PENDING" if sample else num
        rep(f'<text class="disp" x="{x}" y="150" font-size="26" fill="url(#gn)">{num}</text>', f'<text x="{nx}" y="148" font-size="32" font-weight="700" letter-spacing="1" fill="url(#gn)">{shown}</text>')
        rep(f'<text x="{x}" y="170" font-size="13.5" letter-spacing="2" fill="#6b7488">{lab}</text>', f'<text x="{nx}" y="176" font-size="19" letter-spacing="2" fill="#aab6d0">{lab}</text>')
    if sample:
        rep('font-size="14" letter-spacing="1.5" fill="#8b93a7">LANGUAGE MIX APPEARS AFTER FIRST SYNC', 'font-size="20" letter-spacing="1.5" fill="#aab6d0">SAMPLE DATA. REAL ACTIVITY AFTER FIRST SYNC')
    else:
        body = re.sub(r'font-size="14" letter-spacing="1.5" fill="#8b93a7">', 'font-size="20" letter-spacing="1.5" fill="#aab6d0">', body, count=1)
    rep('<text x="892" y="488" text-anchor="end" font-size="13.5" letter-spacing="1.5" fill="#5b6478">LESS', '<text x="892" y="488" text-anchor="end" font-size="19" letter-spacing="1.5" fill="#aab6d0">LESS')
    rep('<text x="972" y="488" font-size="13.5" letter-spacing="1.5" fill="#5b6478">MORE', '<text x="972" y="488" font-size="19" letter-spacing="1.5" fill="#aab6d0">MORE')

    bd = ('<linearGradient id="bd" gradientUnits="userSpaceOnUse" x1="0" y1="0" x2="1100" y2="0"><stop offset="0" stop-color="#ff2d33"/><stop offset=".5" stop-color="#7a3fb4"/><stop offset="1" stop-color="#2f8cff"/></linearGradient>\n'
          '<linearGradient id="gn" x1="0" x2="1"><stop offset="0" stop-color="#ff4a4f"/><stop offset="1" stop-color="#3da5ff"/></linearGradient>\n'
          '<linearGradient id="base" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#070c1a"/><stop offset="1" stop-color="#03060f"/></linearGradient>\n'
          '<radialGradient id="gr" cx="0" cy=".15" r=".62"><stop offset="0" stop-color="#d4141e" stop-opacity=".42"/><stop offset="1" stop-color="#d4141e" stop-opacity="0"/></radialGradient>\n'
          '<radialGradient id="gb" cx="1" cy=".25" r=".62"><stop offset="0" stop-color="#1673ff" stop-opacity=".34"/><stop offset="1" stop-color="#1673ff" stop-opacity="0"/></radialGradient>\n'
          '<filter id="bl" x="-5%" y="-10%" width="110%" height="120%"><feGaussianBlur stdDeviation="5"/></filter>\n'
          '<filter id="bl2" x="-20%" y="-40%" width="140%" height="180%"><feGaussianBlur stdDeviation="3"/></filter>')
    shell = ('<rect x="3" y="3" width="1094" height="524" rx="28" fill="url(#base)"/>'
             '<rect x="3" y="3" width="1094" height="524" rx="28" fill="url(#gr)"/><rect x="3" y="3" width="1094" height="524" rx="28" fill="url(#gb)"/>'
             '<rect x="3" y="3" width="1094" height="524" rx="28" fill="none" stroke="url(#bd)" stroke-width="5" opacity=".75" filter="url(#bl)"/>'
             '<rect x="3" y="3" width="1094" height="524" rx="28" fill="none" stroke="url(#bd)" stroke-width="3.5"/>')
    clip = '<clipPath id="pane"><rect x="24" y="72" width="1052" height="434" rx="20"/></clipPath>'
    if sample:
        label = f"Animated 3D contribution skyline for {USER}: a spider swings across every active day and a tower rises on each square after it leaves. Sample data until the first sync."
        title = f"Activity skyline for {USER} (sample data)"
    else:
        label = f"Animated 3D contribution skyline for {USER}: a spider swings across every active day and a tower rises on each square after it leaves. {stamp.capitalize()}."
        title = f"Activity skyline for {USER}. {stamp.capitalize()}"
    head = (f'<svg xmlns="http://www.w3.org/2000/svg" width="1100" height="530" viewBox="0 0 1100 530" role="img" aria-label="{label}">'
            f'<title>{title}</title><style>{card_fonts()}</style><defs>{bd}{clip}{od}</defs>')
    return head + shell + body


def build(info, stamp):
    grid = info["grid"]
    rng = random.Random(3)
    route = []                      # snake order: column by column, alternating direction
    for c in range(COLS):
        rows = sorted(r for (cc, r) in grid if cc == c)
        if c % 2:
            rows.reverse()
        route += [(c, r) for r in rows]
    n_act = len(route)

    LEAD, STAY, EXIT, HOLD, FADE = 0.8, 0.07, 0.7, 3.8, 0.9
    SWING_MIN = 58                  # px; longer jumps swing on a web thread, shorter ones are hops

    def spos(c, r):
        x, y = gcenter(c, r)
        return x, y - 7

    pos = [spos(*cell) for cell in route]
    exit_pt = (pos[-1][0] + 130, -70) if pos else (0, 0)
    targets = pos + [exit_pt]
    flights = []
    for j in range(n_act):
        dist = math.hypot(targets[j + 1][0] - targets[j][0], targets[j + 1][1] - targets[j][1])
        if j == n_act - 1:
            flights.append(EXIT)
        elif dist >= SWING_MIN:
            flights.append(min(0.34, max(0.16, 0.10 + dist / 900)))
        else:
            flights.append(min(0.22, max(0.11, 0.07 + dist / 800)))
    ta, tl = [], []
    t = LEAD
    for j in range(n_act):
        ta.append(t)
        tl.append(t + STAY)
        t = tl[j] + flights[j]
    D = (tl[-1] + flights[-1] + HOLD) if n_act else 6.0

    kt = lambda v: f"{max(0.0, min(1.0, v / D)):.4f}"
    ks = lambda ts: ";".join(kt(v) for v in ts)

    # towers rise the instant the spider leaves their square, never before it has been there
    rise = {cell: tl[j] for j, cell in enumerate(route)}
    land = {cell: ta[j] for j, cell in enumerate(route)}
    for cell in route:
        assert land[cell] <= rise[cell] <= land[cell] + STAY + 1e-9, cell

    o = []
    a = o.append
    a(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-label="Animated 3D contribution skyline for {USER}: a spider swings across every active day and a tower rises on each square after it leaves">')
    a(f'<title>Activity skyline for {USER}</title><defs>')
    a(f'<linearGradient id="g" gradientUnits="userSpaceOnUse" x1="0" y1="0" x2="{W}" y2="0"><stop offset="0" stop-color="#e62429"/><stop offset=".5" stop-color="#3b1d5c"/><stop offset="1" stop-color="#4d9fff"/></linearGradient>')
    a(f'<linearGradient id="g2" gradientUnits="userSpaceOnUse" x1="24" y1="0" x2="{W-24}" y2="0"><stop offset="0" stop-color="#ff4d52"/><stop offset="1" stop-color="#4d9fff"/></linearGradient>')
    a('<linearGradient id="sw" x1="0" x2="1" y1="0" y2="0"><stop offset="0" stop-color="#bcd8ff" stop-opacity="0"/><stop offset=".5" stop-color="#d8e8ff" stop-opacity=".34"/><stop offset="1" stop-color="#bcd8ff" stop-opacity="0"/></linearGradient>')
    a('<radialGradient id="orb"><stop offset="0" stop-color="#ffffff" stop-opacity=".95"/><stop offset=".35" stop-color="#9cc8ff" stop-opacity=".5"/><stop offset="1" stop-color="#4d9fff" stop-opacity="0"/></radialGradient>')
    for k, cc in GLOW.items():
        a(f'<radialGradient id="gl{k}"><stop offset="0" stop-color="{cc}" stop-opacity=".75"/><stop offset="1" stop-color="{cc}" stop-opacity="0"/></radialGradient>')
    a('<radialGradient id="halo"><stop offset="0" stop-color="#ff3b3f" stop-opacity=".6"/><stop offset="1" stop-color="#ff3b3f" stop-opacity="0"/></radialGradient>')
    a('<radialGradient id="bgR" cx=".2" cy="1" r=".7"><stop offset="0" stop-color="#e62429" stop-opacity=".16"/><stop offset="1" stop-color="#e62429" stop-opacity="0"/></radialGradient>')
    a('<radialGradient id="bgB" cx=".85" cy="1" r=".7"><stop offset="0" stop-color="#4d9fff" stop-opacity=".16"/><stop offset="1" stop-color="#4d9fff" stop-opacity="0"/></radialGradient>')
    a(f'<clipPath id="pane"><rect x="24" y="72" width="{W-48}" height="434" rx="10"/></clipPath></defs>')
    a(f'<style>{load_fonts()}</style>')
    a(f'<rect x="1" y="1" width="{W-2}" height="{H-2}" rx="18" fill="#05070d" stroke="url(#g)" stroke-width="2"/>')
    for i, cc in enumerate(("#ff5f57", "#febc2e", "#28c840")):
        a(f'<circle cx="{34+i*19}" cy="27" r="5.5" fill="{cc}"/>')
    a(f'<text x="{W/2}" y="31" text-anchor="middle" font-size="13" fill="#8b93a7">{USER.lower()}@github ~ $ ./activity --live</text>')
    a(f'<text x="{W-34}" y="31" text-anchor="end" font-size="12" letter-spacing="2" fill="#8fb8ff">LIVE</text>')
    a(f'<circle cx="{W-78}" cy="27" r="4" fill="#e62429"><animate attributeName="opacity" values="1;.25;1" dur="1.6s" repeatCount="indefinite"/></circle>')
    a(f'<line x1="1" y1="52" x2="{W-1}" y2="52" stroke="#1b2540"/>')
    a(f'<rect x="24" y="72" width="{W-48}" height="434" rx="10" fill="#04060b" stroke="#1b2540"/>')

    # background: glows, web corner, dust
    a('<g clip-path="url(#pane)">')
    a(f'<rect x="24" y="72" width="{W-48}" height="434" fill="url(#bgR)"/><rect x="24" y="72" width="{W-48}" height="434" fill="url(#bgB)"/>')
    cx0, cy0 = W - 24, 72
    ang = [math.radians(v) for v in (92, 112, 132, 152, 172, 192)]
    for an in ang:
        a(f'<line x1="{cx0}" y1="{cy0}" x2="{cx0+math.cos(an)*330:.1f}" y2="{cy0+math.sin(an)*330:.1f}" stroke="#16213a" stroke-width=".9"/>')
    for rad in (60, 120, 190, 270):
        for i in range(len(ang) - 1):
            p1 = (cx0 + math.cos(ang[i]) * rad, cy0 + math.sin(ang[i]) * rad)
            p2 = (cx0 + math.cos(ang[i + 1]) * rad, cy0 + math.sin(ang[i + 1]) * rad)
            m = (cx0 + math.cos((ang[i] + ang[i + 1]) / 2) * rad * .86, cy0 + math.sin((ang[i] + ang[i + 1]) / 2) * rad * .86)
            a(f'<path d="M{p1[0]:.1f},{p1[1]:.1f} Q{m[0]:.1f},{m[1]:.1f} {p2[0]:.1f},{p2[1]:.1f}" fill="none" stroke="#16213a" stroke-width=".9"/>')
    for _ in range(46):
        x, y = rng.uniform(40, W - 40), rng.uniform(84, 250)
        a(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{rng.uniform(.7,1.6):.1f}" fill="#7f8fc0"><animate attributeName="opacity" values=".1;.8;.1" dur="{rng.uniform(2.4,5.2):.1f}s" begin="-{rng.uniform(0,4):.1f}s" repeatCount="indefinite"/></circle>')
    a('</g>')
    # route progress line along the top of the pane
    if n_act:
        a(f'<g clip-path="url(#pane)"><rect x="24" y="72" width="0" height="2.5" fill="url(#g2)"><animate attributeName="width" values="0;0;{W-48};{W-48};0" keyTimes="{ks([0, ta[0], tl[-1], D-FADE, D])}" dur="{D:.2f}s" repeatCount="indefinite"/></rect></g>')

    # HUD
    a('<text x="44" y="96" font-size="11" letter-spacing="2.5" fill="#4d9fff">ACTIVITY.SKYLINE</text>')
    a(f'<text x="{W-44}" y="96" text-anchor="end" font-size="11" letter-spacing="2.5" fill="#e62429">SPIDER-SENSE: SCANNING</text>')
    a(f'<text x="{W-44}" y="113" text-anchor="end" font-size="11" letter-spacing="1.5" fill="#5b6478">{stamp}</text>')
    dash = info.get("sample")  # never show made-up numbers
    stats = (("--" if dash else f"{info['total']:,}", "CONTRIBUTIONS / 12 MO"),
             ("--" if dash else str(info["current"]), "CURRENT STREAK"),
             ("--" if dash else str(info["longest"]), "LONGEST STREAK"))
    for i, (num, lab) in enumerate(stats):
        x = 44 + i * 200
        a(f'<text class="disp" x="{x}" y="150" font-size="46" letter-spacing="1" fill="#f2f5fb">{num}</text>')
        a(f'<text x="{x}" y="170" font-size="11" letter-spacing="2" fill="#6b7488">{lab}</text>')

    # ground tiles (a landing lights the square it touches)
    for r in range(ROWS):
        for c in range(COLS):
            x, y = origin(c, r)
            pts = f"{x},{y} {x+CW},{y} {x+CW+DXS},{y-DYS} {x+DXS},{y-DYS}"
            if (c, r) in land:
                tt = land[(c, r)]
                flash = "#3a78c8" if PAL[grid[(c, r)]][3] == "b" else "#c2303f"
                a(f'<polygon points="{pts}" fill="#0d1322" stroke="#162038" stroke-width=".6"><animate attributeName="fill" values="#0d1322;#0d1322;{flash};#0d1322;#0d1322" keyTimes="{ks([0, tt, tt+.05, tt+.5, D])}" dur="{D:.2f}s" repeatCount="indefinite"/></polygon>')
            else:
                a(f'<polygon points="{pts}" fill="#0d1322" stroke="#162038" stroke-width=".6"/>')

    # spider + thread timeline
    T, op_t, op_v = [], [0], [0]
    if n_act:
        sx0, sy0 = pos[0]
        T += [(0, sx0, -50, sx0, -50), (LEAD, sx0, sy0, sx0, sy0)]
        ease = lambda u: 0.5 - 0.5 * math.cos(math.pi * u)
        for j in range(n_act):
            sx, sy = targets[j]
            tx, ty = targets[j + 1]
            t0, t1 = tl[j], tl[j] + flights[j]
            dist = math.hypot(tx - sx, ty - sy)
            T.append((t0, sx, sy, sx, sy))
            if dist >= SWING_MIN or j == n_act - 1:
                Hh = min(150, 62 + 0.35 * dist)
                ax, ay = (sx + tx) / 2, min(sy, ty) - Hh
                th_s, th_t = math.atan2(sy - ay, sx - ax), math.atan2(ty - ay, tx - ax)
                rs, rt = math.hypot(sx - ax, sy - ay), math.hypot(tx - ax, ty - ay)
                op_t.append(t0); op_v.append(1)
                for u in (0.12, 0.25, 0.4, 0.55, 0.7, 0.85, 1.0):
                    e = ease(u)
                    th = th_s + (th_t - th_s) * e
                    rr = rs + (rt - rs) * e
                    px, py = (tx, ty) if u == 1.0 else (ax + rr * math.cos(th), ay + rr * math.sin(th))
                    k = min(1.0, u / 0.12)
                    T.append((t0 + u * (t1 - t0), px, py, sx + (ax - sx) * k, sy + (ay - sy) * k))
                op_t.append(t1); op_v.append(0)
            else:                                   # quick hop with a small arc, no thread
                amp = min(30, 9 + 0.22 * dist)
                for u in (0.25, 0.5, 0.75, 1.0):
                    T.append((t0 + u * (t1 - t0), sx + (tx - sx) * u, sy + (ty - sy) * u - amp * 4 * u * (1 - u), sx + (tx - sx) * u, sy + (ty - sy) * u))
        T.append((D, T[-1][1], T[-1][2], T[-1][3], T[-1][4]))
        op_t.append(D); op_v.append(0)

    # glows
    for (c, r), lvl in sorted(grid.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        gx, gy = gcenter(c, r)
        tr = rise[(c, r)]
        hue = PAL[lvl][3]
        a(f'<ellipse cx="{gx:.1f}" cy="{gy:.1f}" rx="24" ry="10" fill="url(#gl{hue})" opacity="0"><animate attributeName="opacity" values="0;0;.9;.5;.5;0" keyTimes="{ks([0, tr, tr+.2, tr+.8, D-FADE, D])}" dur="{D:.2f}s" repeatCount="indefinite"/></ellipse>')
    # towers, back row to front row; the top face flashes white as the tower pops up
    for r in range(ROWS):
        for c in range(COLS):
            if (c, r) not in grid:
                continue
            lvl = grid[(c, r)]
            top, front, side, _ = PAL[lvl]
            h = HEIGHTS[lvl]
            x, y = origin(c, r)
            tr = rise[(c, r)]
            a(f'<g transform="translate({x} {y})"><g transform="scale(1 0)">')
            a(f'<animateTransform attributeName="transform" type="scale" values="1 0;1 0;1 1.2;1 1;1 1;1 0" keyTimes="{ks([0, tr, tr+.16, tr+.3, D-FADE, D])}" dur="{D:.2f}s" repeatCount="indefinite"/>')
            a(f'<polygon points="0,0 {CW},0 {CW},{-h} 0,{-h}" fill="{front}"/>')
            a(f'<polygon points="{CW},0 {CW+DXS},{-DYS} {CW+DXS},{-h-DYS} {CW},{-h}" fill="{side}"/>')
            a(f'<polygon points="0,{-h} {CW},{-h} {CW+DXS},{-h-DYS} {DXS},{-h-DYS}" fill="{top}" stroke="#ffffff" stroke-opacity=".28" stroke-width=".6">'
              f'<animate attributeName="fill" values="{top};{top};#ffffff;{top};{top}" keyTimes="{ks([0, tr, tr+.04, tr+.45, D])}" dur="{D:.2f}s" repeatCount="indefinite"/></polygon>')
            a('</g></g>')
    # web trail between consecutive towers: appears with the tower the spider just left
    for j in range(1, len(route)):
        (c1, r1), (c2, r2) = route[j - 1], route[j]
        x1, y1 = origin(c1, r1)
        x2, y2 = origin(c2, r2)
        p1 = (x1 + CW / 2 + DXS / 2, y1 - HEIGHTS[grid[(c1, r1)]] - DYS / 2)
        p2 = (x2 + CW / 2 + DXS / 2, y2 - HEIGHTS[grid[(c2, r2)]] - DYS / 2)
        if math.hypot(p1[0] - p2[0], p1[1] - p2[1]) > 170:
            continue
        tr = rise[(c2, r2)]
        a(f'<line x1="{p1[0]:.1f}" y1="{p1[1]:.1f}" x2="{p2[0]:.1f}" y2="{p2[1]:.1f}" stroke="#cfe0ff" stroke-width=".8" opacity="0"><animate attributeName="opacity" values="0;0;.55;.32;.32;0" keyTimes="{ks([0, tr+.1, tr+.35, tr+1.3, D-FADE, D])}" dur="{D:.2f}s" repeatCount="indefinite"/></line>')
    # landing shockwaves
    for cell, tt in land.items():
        hue = PAL[grid[cell]][3]
        gx, gy = gcenter(*cell)
        kw = ks([0, tt, tt + .55, D])
        a(f'<ellipse cx="{gx:.1f}" cy="{gy:.1f}" rx="4" ry="1.7" fill="none" stroke="{RING[hue]}" stroke-width="1.6" opacity="0">'
          f'<animate attributeName="rx" values="4;4;38;38" keyTimes="{kw}" dur="{D:.2f}s" repeatCount="indefinite"/>'
          f'<animate attributeName="ry" values="1.7;1.7;15;15" keyTimes="{kw}" dur="{D:.2f}s" repeatCount="indefinite"/>'
          f'<animate attributeName="opacity" values="0;0;.9;0;0" keyTimes="{ks([0, tt, tt+.01, tt+.55, D])}" dur="{D:.2f}s" repeatCount="indefinite"/></ellipse>')
    # finale: a light band sweeps across the finished skyline
    if n_act:
        tf = tl[-1] + flights[-1] * 0.4 + 0.5
        a(f'<g clip-path="url(#pane)"><polygon points="0,220 110,220 60,450 -50,450" fill="url(#sw)"><animateTransform attributeName="transform" type="translate" values="-160 0;-160 0;1200 0;1200 0" keyTimes="{ks([0, tf, tf+2.4, D])}" dur="{D:.2f}s" repeatCount="indefinite"/></polygon></g>')
    # thread (soft glow under + bright core) and spider
    if n_act:
        col = lambda i: ";".join(f"{e[i]:.1f}" for e in T)
        tk = ks([e[0] for e in T])
        for width, colr, op in ((6, "#7fb2ff", .22), (1.5, "#eaf1ff", 1)):
            a(f'<line x1="0" y1="0" x2="0" y2="0" stroke="{colr}" stroke-width="{width}" stroke-linecap="round" opacity="0">'
              f'<animate attributeName="x1" values="{col(3)}" keyTimes="{tk}" dur="{D:.2f}s" repeatCount="indefinite"/>'
              f'<animate attributeName="y1" values="{col(4)}" keyTimes="{tk}" dur="{D:.2f}s" repeatCount="indefinite"/>'
              f'<animate attributeName="x2" values="{col(1)}" keyTimes="{tk}" dur="{D:.2f}s" repeatCount="indefinite"/>'
              f'<animate attributeName="y2" values="{col(2)}" keyTimes="{tk}" dur="{D:.2f}s" repeatCount="indefinite"/>'
              f'<animate attributeName="opacity" calcMode="discrete" values="{";".join(str(op*v) for v in op_v)}" keyTimes="{ks(op_t)}" dur="{D:.2f}s" repeatCount="indefinite"/></line>')
        a('<g>')
        a(f'<animateTransform attributeName="transform" type="translate" values="{";".join(f"{e[1]:.1f} {e[2]:.1f}" for e in T)}" keyTimes="{tk}" dur="{D:.2f}s" repeatCount="indefinite"/>')
        a('<g transform="scale(1.45)"><circle r="20" fill="url(#halo)"/>')
        for sx_ in (-1, 1):
            for k_, ly in enumerate((-1, -0.35, 0.3, 0.95)):
                yy = ly * 6
                ex = sx_ * (11 + (1.5 if k_ in (1, 2) else 0))
                ey = yy * 1.7 + (-3 if k_ == 0 else 3 if k_ == 3 else 0)
                a(f'<polyline points="{sx_*2.5},{yy*.5:.1f} {sx_*7},{yy-3:.1f} {ex:.1f},{ey:.1f}" fill="none" stroke="#ff3b3f" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/>')
        a('<ellipse cx="0" cy="3" rx="3.4" ry="5" fill="#ff3b3f"/><circle cx="0" cy="-3.5" r="2.4" fill="#ff3b3f"/>')
        a('<circle cx="-.9" cy="-4" r=".7" fill="#fff"/><circle cx=".9" cy="-4" r=".7" fill="#fff"/></g></g>')

    # orbiting light on the card border
    rr_ = 18
    path = (f"M{rr_},1 H{W-rr_} A{rr_-1},{rr_-1} 0 0 1 {W-1},{rr_} V{H-rr_} A{rr_-1},{rr_-1} 0 0 1 {W-rr_},{H-1} "
            f"H{rr_} A{rr_-1},{rr_-1} 0 0 1 1,{H-rr_} V{rr_} A{rr_-1},{rr_-1} 0 0 1 {rr_},1 Z")
    a(f'<g><circle r="13" fill="url(#orb)"/><circle r="2.4" fill="#fff"/><animateMotion dur="15s" begin="1s" repeatCount="indefinite" path="{path}"/></g>')

    # language bar + legend
    bx, bw = X0, 985
    segs = [(p, LANG_COLORS[i]) for i, (_, p) in enumerate(info["langs"])] + [(info["other"], LANG_COLORS[3])]
    tot = sum(p for p, _ in segs) or 1
    cx = bx
    for p, cc in segs:
        w = bw * p / tot
        a(f'<rect x="{cx:.1f}" y="462" width="{w:.1f}" height="4" fill="{cc}"/>')
        cx += w
    txt = "  /  ".join(f"{n.upper()} {p}" for n, p in info["langs"]) or "LANGUAGE MIX APPEARS AFTER FIRST SYNC"
    a(f'<text x="{bx}" y="488" font-size="12" letter-spacing="1.5" fill="#8b93a7">{txt}</text>')
    lx = bx + bw - 4 * 17 - 74
    a(f'<text x="{lx-8}" y="488" text-anchor="end" font-size="11" letter-spacing="1.5" fill="#5b6478">LESS</text>')
    for i, cc in enumerate(("#111827", PAL[0][1], PAL[1][1], PAL[3][1])):
        a(f'<rect x="{lx+i*17}" y="477" width="12" height="12" rx="3" fill="{cc}"/>')
    a(f'<text x="{lx+4*17+4}" y="488" font-size="11" letter-spacing="1.5" fill="#5b6478">MORE</text>')
    a('</svg>')
    return "\n".join(o), n_act, n_act, D


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="assets/skyline.svg")
    ap.add_argument("--from-json")
    ap.add_argument("--allow-sample", action="store_true")
    args = ap.parse_args()

    sample = False
    if args.from_json:
        user = json.load(open(args.from_json))
        user = user.get("data", {}).get("user", user)
    else:
        try:
            if not TOKEN:
                raise RuntimeError("no GH_TOKEN / GITHUB_TOKEN in the environment")
            user = fetch()
        except Exception as exc:  # never overwrite real data with sample data unless asked
            if not args.allow_sample:
                sys.exit(f"could not fetch contributions: {exc}")
            print(f"warning: {exc}; drawing sample data", file=sys.stderr)
            user, sample = sample_user(), True

    info = analyse(user)
    info["sample"] = sample
    if sample:
        info["langs"], info["other"] = [], 100
    stamp = "SAMPLE DATA / AWAITING FIRST SYNC" if sample else f"SYNCED {dt.datetime.now(dt.timezone.utc):%Y-%m-%d} / @{USER.upper()}"
    svg, n_act, M, D = build(info, stamp)
    svg = restyle(svg, info, stamp)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(svg)
    print(f"wrote {args.out}: {n_act} active days, {M} stops, {D:.1f}s loop, {len(svg)//1024} KB")


if __name__ == "__main__":
    main()
