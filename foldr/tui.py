"""
foldr.tui
~~~~~~~~~
All interactive TUI screens for FOLDR v4.

Ghost border fix
----------------
The old confirm_dialog had ghost content bleeding to the right of the box
because vlen(strip(content)) was measuring the BOX content without counting
the left padding offset. Fixed: put() now always writes a FULL terminal-width
row: left_blank + box_content + right_blank, where right_blank uses the
correct formula: w - box_c - vlen(strip(box_content)).
"""
from __future__ import annotations
import sys, time, threading
from pathlib import Path

from foldr.term import (
    Screen, read_key, term_wh, strip, vlen, truncate, pad_to, centre,
    box_top, box_bot, box_sep, box_row, pbar, SPINNER,
    cat_fg, cat_icon, op_icon, fmt_size,
    RESET, BOLD, DIM,
    BWHT, FG_DIM, FG_MUTED, FG_BRIGHT,
    bg256, fg256,
    BG_BASE, BG_PANEL, BG_HEADER, BG_SEL, BG_MODAL,
    ACCENT, ACCENT2, COL_OK, COL_WARN, COL_ERR, COL_BORD, COL_BORD2,
    K_UP, K_DOWN, K_LEFT, K_RIGHT, K_ENTER, K_ESC,
    K_PGUP, K_PGDN, K_HOME, K_END, K_TAB, K_CC,
)

# ── Chrome helpers ─────────────────────────────────────────────────────────────
def _bg(scr:Screen, w:int, h:int)->None:
    row = BG_BASE+" "*w+RESET
    for r in range(h): scr.fill(r, row)

def _header(scr:Screen, w:int, title:str, tag:str="", tag_col:str="")->None:
    logo = ACCENT+BOLD+" FOLDR "+RESET
    sep  = FG_MUTED+" | "+RESET
    t    = " "+FG_DIM+title+RESET if title else ""
    right= (("  "+(tag_col or FG_DIM)+tag+RESET+"  ") if tag else "")
    pad  = " "*max(0, w - vlen(strip(logo+sep+t)) - vlen(strip(right)) - 1)
    scr.fill(0, BG_HEADER+logo+sep+t+pad+right+RESET)

def _footer(scr:Screen, w:int, row:int, hints:list[tuple[str,str]])->None:
    bg    = bg256(232)
    parts = []
    for k, desc in hints:
        parts.append(bg+ACCENT+BOLD+" "+k+" "+RESET+bg+FG_DIM+" "+desc+"  "+RESET)
    line = "".join(parts)
    fill = " "*max(0, w-vlen(strip(line)))
    scr.fill(row, bg+line+fill+RESET)


# ── confirm_dialog ─────────────────────────────────────────────────────────────
def confirm_dialog(
    scr: Screen,
    title: str,
    body_lines: list[str],
    yes_label: str = " Confirm ",
    no_label:  str = " Cancel  ",
    danger:    bool = False,
) -> bool:
    """
    Blocking modal confirmation dialog.

    Ghost-fix
    ---------
    Every row the dialog occupies is written as a FULL terminal-width
    string:  [left_blank][box_row][right_blank]
    Both blanks use BG_MODAL so no background content bleeds through.
    The right_blank width is: w - box_c - vlen(pure_box_content)
    where pure_box_content is strip()ped to remove ANSI codes before
    measuring, giving the true visual column width.
    """
    w, h   = scr.w, scr.h
    border = COL_ERR if danger else COL_BORD2

    body_w  = max((vlen(strip(l)) for l in body_lines), default=30)
    box_w   = min(w-4, max(52, body_w+10))
    box_h   = len(body_lines)+7
    box_r   = max(1, (h-box_h)//2)
    box_c   = max(0, (w-box_w)//2)

    sel = 0  # 0=Cancel (safe default)

    def put(r:int, raw_content:str)->None:
        """
        Write one dialog row, padded to the full terminal width.
        raw_content = the box row content (with ANSI codes).
        Visual width of raw_content is computed after stripping codes.
        """
        left       = BG_MODAL+" "*box_c
        right_len  = max(0, w - box_c - vlen(strip(raw_content)))
        right      = BG_MODAL+" "*right_len+RESET
        scr.fill(r, left+raw_content+right)

    def blank_row(r:int)->None:
        scr.fill(r, BG_MODAL+" "*w+RESET)

    while True:
        blank_row(box_r-1)
        put(box_r, box_top(box_w, title, col=border, tcol=ACCENT2+BOLD))
        put(box_r+1, border+"║"+RESET+BG_MODAL+" "*(box_w-2)+border+"║"+RESET)

        for i, bl in enumerate(body_lines):
            inner = box_w-4
            line  = pad_to(truncate(bl, inner), inner)
            put(box_r+2+i, border+"║"+RESET+BG_MODAL+"  "+line+"  "+border+"║"+RESET)

        sep_r = box_r+2+len(body_lines)
        put(sep_r,   box_sep(box_w, col=border))
        put(sep_r+1, border+"║"+RESET+BG_MODAL+" "*(box_w-2)+border+"║"+RESET)

        # Buttons — Cancel left, Confirm right
        yes_c   = COL_ERR if danger else COL_OK
        no_bg   = BG_SEL  if sel==0 else BG_MODAL
        yes_bg  = BG_MODAL
        no_txt  = no_bg+FG_BRIGHT+BOLD+f"  {no_label}  "+RESET
        yes_txt = yes_bg+(yes_c+BOLD if sel==1 else FG_DIM)+f"  {yes_label}  "+RESET

        # Calculate gap between buttons to right-align Confirm
        gap = max(2, box_w-4 - vlen(strip(no_txt)) - vlen(strip(yes_txt)))
        put(sep_r+2,
            border+"║"+RESET+BG_MODAL+"  "+no_txt+" "*gap+yes_txt+"  "+border+"║"+RESET)

        hint = centre(FG_MUTED+"<- -> select   Enter confirm   Esc cancel"+RESET, box_w-4)
        put(sep_r+3, border+"║"+RESET+BG_MODAL+"  "+hint+"  "+border+"║"+RESET)
        put(sep_r+4, box_bot(box_w, col=border))
        blank_row(sep_r+5)

        scr.flush()
        k = read_key()
        if not k: continue

        if k in (K_LEFT, K_RIGHT, K_TAB, "h", "l"): sel = 1-sel
        elif k == K_ENTER:  return sel==1
        elif k in ("y","Y"):     return True
        elif k in ("n","N",K_ESC,K_CC,"q","Q"): return False


# ── mode_picker ────────────────────────────────────────────────────────────────
def mode_picker()->str:
    """First-run: ask user TUI or CLI. Returns 'tui' or 'cli'."""
    scr = Screen(); scr.enter(); sel=0
    try:
        while True:
            scr.resize(); w,h=scr.w,scr.h
            _bg(scr,w,h)
            _header(scr,w,"First Run Setup")
            lines=[
                "",ACCENT+BOLD+"  Choose your preferred output mode"+RESET,"",
                FG_DIM+"  Saved to ~/.foldr/prefs.json. Change with: foldr config --mode tui|cli"+RESET,"",
            ]
            top=max(2,(h-14)//2)
            for i,l in enumerate(lines): scr.fill(top+i, BG_BASE+l+RESET)
            r=top+len(lines)
            def btn(label:str,desc:str,is_sel:bool,row:int)->None:
                bw=min(60,w-4); lc=max(0,(w-bw)//2)
                arrow=ACCENT+" > " if is_sel else "   "
                bg=BG_SEL if is_sel else BG_PANEL
                dc=FG_BRIGHT if is_sel else FG_DIM
                line=bg+arrow+BOLD+label+RESET+bg+FG_MUTED+"  -  "+RESET+dc+desc+RESET
                scr.fill(row," "*lc+pad_to(line,lc+bw)+RESET)
            btn("TUI Mode","interactive screens, progress bars, history browser",sel==0,r)
            scr.fill(r+1,"")
            btn("CLI Mode","plain text, works in pipes and scripts",sel==1,r+2)
            scr.fill(r+3,"")
            scr.fill(r+4,centre(FG_MUTED+"Up/Down select   Enter confirm"+RESET,w))
            _footer(scr,w,h-1,[("Up/Down","select"),("Enter","confirm")])
            scr.flush()
            k=read_key()
            if not k: continue
            if k in (K_UP,"k"):   sel=0
            if k in (K_DOWN,"j"): sel=1
            if k==K_TAB:          sel=1-sel
            if k==K_ENTER:        return "tui" if sel==0 else "cli"
            if k in (K_ESC,K_CC): return "tui"
    finally:
        scr.exit()


# ── PreviewScreen ──────────────────────────────────────────────────────────────
class PreviewScreen:
    """Scrollable preview + 2-step confirm. Returns True = execute."""
    def __init__(self, records:list, base:Path, dry_run:bool):
        self.records  = records
        self.base     = base
        self.dry_run  = dry_run
        self.cursor   = 0
        self.scroll   = 0
        self._cats: dict[str,int] = {}
        for r in records: self._cats[r.category]=self._cats.get(r.category,0)+1
        self._sorted_cats = sorted(self._cats.items(), key=lambda x:-x[1])
        self._show_help   = False

    def run(self)->bool:
        scr=Screen(); scr.enter()
        try:    return self._loop(scr)
        finally: scr.exit()

    def _layout(self,w:int,h:int)->dict:
        n_cats  = len(self._sorted_cats)
        stats_h = min(n_cats+3,10)
        dry_h   = 1 if self.dry_run else 0
        fixed   = 1+1+1+stats_h+dry_h+1
        list_h  = max(5,h-fixed)
        return dict(
            list_top=2, list_h=list_h, inner=list_h-2,
            detail=2+list_h,
            stats_top=2+list_h+1, stats_h=stats_h,
            dry_row=2+list_h+1+stats_h,
            footer=h-1,
        )

    def _loop(self,scr:Screen)->bool:
        while True:
            scr.resize(); w,h=scr.w,scr.h; L=self._layout(w,h)
            self._draw(scr,w,h,L)
            k=read_key()
            if not k: continue
            if self._show_help: self._show_help=False; continue
            n=len(self.records); inner=L["inner"]
            if k in (K_UP,"k"):     self.cursor=max(0,self.cursor-1)
            elif k in (K_DOWN,"j"): self.cursor=min(n-1,self.cursor+1)
            elif k==K_PGUP:         self.cursor=max(0,self.cursor-inner)
            elif k==K_PGDN:         self.cursor=min(n-1,self.cursor+inner)
            elif k==K_HOME:         self.cursor=0
            elif k==K_END:          self.cursor=max(0,n-1)
            elif k=="?":            self._show_help=True
            elif k in (K_ENTER,"y","Y") and not self.dry_run:
                ok=confirm_dialog(
                    scr," Confirm Move ",[
                        "",
                        f"  Move {ACCENT+BOLD}{n}{RESET} files from {ACCENT}{self.base.name}/{RESET}",
                        f"  into {ACCENT+BOLD}{len(self._cats)}{RESET} category folders.",
                        "",
                        f"  {FG_MUTED}Reversible with:  {ACCENT}foldr undo{RESET}","",
                    ],
                    yes_label=" Move Files ",no_label=" Cancel     ",
                )
                return ok
            elif k in ("n","N",K_ESC,K_CC,"q","Q"):
                return False
            if self.cursor<self.scroll: self.scroll=self.cursor
            elif self.cursor>=self.scroll+inner: self.scroll=self.cursor-inner+1

    def _draw(self,scr:Screen,w:int,h:int,L:dict)->None:
        _bg(scr,w,h)
        tag="preview only -- no files will move" if self.dry_run else "review & confirm"
        _header(scr,w,"Preview",tag,FG_MUTED)
        n=len(self.records); inner=L["inner"]; lt=L["list_top"]
        scr.fill(lt, BG_PANEL+box_top(w,f" {n} files ",col=COL_BORD,tcol=ACCENT+BOLD)+RESET)
        for i in range(inner):
            ai=self.scroll+i; rr=lt+1+i
            if ai<n:
                r=self.records[ai]; is_sel=(ai==self.cursor)
                dest=Path(r.destination).parent.name
                col=cat_fg(r.category); ico=cat_icon(r.category)
                inner_w=w-4
                fname=truncate(r.filename,max(20,inner_w//3))
                content=pad_to(fname,max(20,inner_w//3))+FG_MUTED+" -> "+RESET+col+ico+" "+dest+"/"+RESET+FG_MUTED+" ["+r.category+"]"+RESET
                body=truncate(content,inner_w-2)
                if is_sel:
                    scr.fill(rr,BG_PANEL+COL_BORD+"║"+RESET+BG_SEL+ACCENT+"> "+RESET+BG_SEL+FG_BRIGHT+pad_to(strip(body),inner_w-2)+RESET+BG_PANEL+COL_BORD+"║"+RESET)
                else:
                    scr.fill(rr,BG_PANEL+COL_BORD+"║"+RESET+BG_PANEL+"  "+body+" "*max(0,inner_w-vlen(strip(body))-2)+BG_PANEL+COL_BORD+"║"+RESET)
            else:
                scr.fill(rr,BG_PANEL+COL_BORD+"║"+BG_PANEL+" "*(w-2)+COL_BORD+"║"+RESET)
        # Scrollbar
        if n>inner:
            sb_h=max(1,inner*inner//n); sb_pos=int(self.scroll/max(1,n-inner)*(inner-sb_h))
            for i in range(inner):
                rr=lt+1+i
                ch=ACCENT+"#" if sb_pos<=i<sb_pos+sb_h else FG_MUTED+"|"
                row=scr._back[rr]
                suffix=COL_BORD+"║"+RESET
                if row.endswith(suffix): scr.fill(rr,row[:-len(suffix)]+ch+RESET+suffix)
        scr.fill(lt+inner+1,BG_PANEL+box_bot(w,col=COL_BORD)+RESET)
        # Detail strip
        if self.records:
            r=self.records[self.cursor]; dest=Path(r.destination).parent.name; col=cat_fg(r.category)
            line=FG_MUTED+"  sel: "+RESET+col+BOLD+r.filename+RESET+FG_MUTED+" -> "+RESET+col+dest+"/"+RESET+FG_MUTED+"  ["+r.category+"]"+RESET
            scr.fill(L["detail"],bg256(233)+pad_to(line,w)+RESET)
        # Category breakdown
        st=L["stats_top"]; total=max(1,n); bar_w=max(10,(w-40)//2)
        scr.fill(st,BG_PANEL+box_top(w," breakdown ",col=COL_BORD,tcol=FG_DIM+BOLD)+RESET)
        max_rows=L["stats_h"]-2
        for i,(cat,cnt) in enumerate(self._sorted_cats[:max_rows]):
            col=cat_fg(cat); pct=cnt/total; fill=max(1,int(pct*bar_w))
            bar=col+"#"*fill+COL_BORD+"-"*(bar_w-fill)+RESET
            scr.fill(st+1+i,BG_PANEL+f"  {col}{cat_icon(cat)}{RESET}  {FG_DIM}{pad_to(cat,16)}{RESET}  {bar}  {ACCENT}{cnt:>4}{RESET}  {FG_MUTED}{pct*100:4.1f}%{RESET}")
        scr.fill(st+L["stats_h"]-1,BG_PANEL+box_bot(w,col=COL_BORD)+RESET)
        if self.dry_run:
            scr.fill(L["dry_row"],bg256(232)+centre(COL_WARN+BOLD+"  preview mode -- no files will be moved  "+RESET,w)+RESET)
        if self.dry_run: hints=[("Up/Down","scroll"),("Q/Esc","exit")]
        else:            hints=[("Up/Down","scroll"),("Enter/Y","confirm"),("N/Esc","cancel"),("?","help")]
        _footer(scr,w,L["footer"],hints)
        if self._show_help: self._draw_help(scr,w,h)
        scr.flush()

    def _draw_help(self,scr:Screen,w:int,h:int)->None:
        lines=[ACCENT+BOLD+"  Keyboard Reference"+RESET,"",
               f"  {ACCENT}Up/k{RESET}      scroll up",
               f"  {ACCENT}Down/j{RESET}    scroll down",
               f"  {ACCENT}PgUp/PgDn{RESET} fast scroll",
               f"  {ACCENT}Home/End{RESET}  first/last","",
               f"  {COL_OK}Enter/Y{RESET}   confirm move",
               f"  {COL_ERR}N/Esc{RESET}     cancel","",
               f"  {FG_MUTED}Press any key to close{RESET}"]
        bw=min(50,w-4); bh=len(lines)+4; br=max(1,(h-bh)//2); bc=max(0,(w-bw)//2); pad=" "*bc
        scr.fill(br,pad+box_top(bw," Help ",col=COL_BORD2,tcol=ACCENT+BOLD))
        for i,l in enumerate(lines):
            iw=bw-4
            scr.fill(br+1+i,pad+COL_BORD2+"║"+RESET+BG_MODAL+"  "+pad_to(truncate(l,iw),iw)+"  "+COL_BORD2+"║"+RESET)
        scr.fill(br+1+len(lines),pad+box_bot(bw,col=COL_BORD2))


# ── ExecutionScreen ────────────────────────────────────────────────────────────
class ExecutionScreen:
    """Context manager: shows live progress while organizing."""
    def __init__(self,total:int,base:Path):
        self.total=total; self.base=base; self.done=0
        self.log:list[tuple[str,str,str]]=[]
        self._scr=Screen(); self._start=time.monotonic(); self._lock=threading.Lock()
    def __enter__(self): self._scr.enter(); return self
    def __exit__(self,*_): self._scr.exit()
    def update(self,filename:str,dest:str,category:str)->None:
        with self._lock: self.done+=1; self.log.append((category,filename,dest))
        self._draw()
    def _draw(self)->None:
        scr=self._scr; scr.resize(); w,h=scr.w,scr.h
        elapsed=time.monotonic()-self._start; pct=self.done/max(1,self.total)
        _bg(scr,w,h); _header(scr,w,"Organizing files")
        pb_w=max(10,w-24); bar=pbar(pct,pb_w)
        rate=self.done/max(0.01,elapsed); eta=max(0,(self.total-self.done)/max(0.01,rate))
        scr.fill(2,BG_PANEL+f"  {bar}  {ACCENT+BOLD}{pct*100:.0f}%{RESET}  {FG_DIM}{self.done}/{self.total}{RESET}")
        scr.fill(3,BG_PANEL+f"  {FG_MUTED}elapsed {elapsed:.1f}s  eta ~{eta:.0f}s{RESET}")
        scr.fill(4,BG_PANEL+COL_BORD+"─"*w+RESET)
        log_h=h-7
        scr.fill(5,BG_PANEL+box_top(w," recent moves ",col=COL_BORD,tcol=FG_DIM+BOLD)+RESET)
        with self._lock: visible=self.log[-(log_h):]
        for i,(cat,fname,dest) in enumerate(visible):
            col=cat_fg(cat); ico=cat_icon(cat)
            scr.fill(6+i,BG_PANEL+f"  {FG_MUTED}{ico}{RESET}  {FG_DIM}{pad_to(cat,16)}{RESET}  {FG_BRIGHT}{truncate(fname,38)}{RESET}  {FG_MUTED}->{RESET}  {col}{dest}/{RESET}")
        scr.fill(6+log_h,BG_PANEL+box_bot(w,col=COL_BORD)+RESET)
        _footer(scr,w,h-1,[])
        scr.flush()


# ── HistoryScreen ──────────────────────────────────────────────────────────────
class HistoryScreen:
    """Browse all history entries, undo any one."""
    def __init__(self,entries:list[dict]):
        self.entries=entries; self.cursor=0; self.scroll=0
        self._mode="list"; self._detail_scroll=0

    def run(self)->tuple[str|None,str|None]:
        scr=Screen(); scr.enter()
        try:    return self._loop(scr)
        finally: scr.exit()

    def _loop(self,scr:Screen)->tuple[str|None,str|None]:
        n=len(self.entries)
        while True:
            scr.resize(); w,h=scr.w,scr.h; inner=h-4
            if self._mode=="list":
                self._draw_list(scr,w,h,inner)
                k=read_key()
                if not k: continue
                if k in (K_UP,"k"):     self.cursor=max(0,self.cursor-1)
                elif k in (K_DOWN,"j"): self.cursor=min(max(0,n-1),self.cursor+1)
                elif k==K_PGUP:         self.cursor=max(0,self.cursor-inner)
                elif k==K_PGDN:         self.cursor=min(max(0,n-1),self.cursor+inner)
                elif k in (K_ENTER,"d","D") and n: self._mode="detail"; self._detail_scroll=0
                elif k in ("u","U") and n:
                    e=self.entries[self.cursor]
                    if e.get("op_type")=="dedup":
                        confirm_dialog(scr," Cannot Undo ",["","  Dedup deletes files permanently.","  Cannot be restored.",""],yes_label=" OK ",no_label=" OK ")
                        continue
                    body=["",f"  Restore {ACCENT+BOLD}{e.get('total_files',0)}{RESET} files",f"  from operation {ACCENT}{e.get('id','?')}{RESET}",f"  in {FG_DIM}{Path(e.get('base','?')).name}/{RESET}","",f"  {FG_MUTED}Files moved elsewhere will be skipped.{RESET}",""]
                    ok=confirm_dialog(scr," Undo Operation ",body,yes_label=" Undo ",no_label=" Cancel ",danger=True)
                    if ok: return "undo",e.get("id")
                elif k in (K_ESC,K_CC,"q","Q"): return None,None
                if self.cursor<self.scroll: self.scroll=self.cursor
                elif self.cursor>=self.scroll+inner: self.scroll=self.cursor-inner+1
            else:
                e=self.entries[self.cursor]
                recs=e.get("records",[])
                if not recs and e.get("path"):
                    import json
                    try:
                        full=json.loads(Path(e["path"]).read_text())
                        e["records"]=full.get("records",[]); e["_full"]=True; recs=e["records"]
                    except Exception: pass
                self._draw_detail(scr,w,h,e,recs)
                k=read_key()
                if not k: continue
                if k in (K_UP,"k"):   self._detail_scroll=max(0,self._detail_scroll-1)
                elif k in (K_DOWN,"j"): self._detail_scroll+=1
                elif k==K_PGUP: self._detail_scroll=max(0,self._detail_scroll-10)
                elif k==K_PGDN: self._detail_scroll+=10
                elif k in (K_ESC,"q","Q",K_ENTER,"b","B"): self._mode="list"

    def _draw_list(self,scr:Screen,w:int,h:int,inner:int)->None:
        _bg(scr,w,h); n=len(self.entries)
        _header(scr,w,"History","all operations",FG_MUTED)
        scr.fill(1,BG_PANEL+box_top(w,f" {n} operations ",col=COL_BORD,tcol=FG_DIM+BOLD)+RESET)
        for i in range(inner):
            ai=self.scroll+i; rr=2+i
            if ai<n:
                e=self.entries[ai]; is_sel=(ai==self.cursor)
                ts=e.get("timestamp","")[:16].replace("T"," "); base=Path(e.get("base","?")).name
                tot=e.get("total_files",0); eid=e.get("id","?"); ot=e.get("op_type","organize")
                oc={"organize":ACCENT,"dedup":COL_ERR,"undo":COL_WARN}.get(ot,FG_DIM)
                row=f"  {oc}{op_icon(ot)}{RESET}  {FG_MUTED}{ts}{RESET}  {FG_BRIGHT}{pad_to(base,22)}{RESET}  {FG_DIM}{tot:>3} files{RESET}  {FG_MUTED}{eid}{RESET}"
                if is_sel:
                    scr.fill(rr,BG_PANEL+COL_BORD+"║"+RESET+BG_SEL+ACCENT+"> "+RESET+BG_SEL+FG_BRIGHT+pad_to(strip(row),w-5)+RESET+BG_PANEL+COL_BORD+"║"+RESET)
                else:
                    scr.fill(rr,BG_PANEL+COL_BORD+"║"+RESET+BG_PANEL+row+" "*max(0,w-vlen(strip(row))-4)+BG_PANEL+COL_BORD+"║"+RESET)
            else:
                scr.fill(rr,BG_PANEL+COL_BORD+"║"+BG_PANEL+" "*(w-2)+COL_BORD+"║"+RESET)
        scr.fill(2+inner,BG_PANEL+box_bot(w,col=COL_BORD)+RESET)
        _footer(scr,w,h-1,[("Up/Down","navigate"),("Enter","details"),("U","undo"),("Q","quit")])
        scr.flush()

    def _draw_detail(self,scr:Screen,w:int,h:int,e:dict,recs:list)->None:
        _bg(scr,w,h)
        eid=e.get("id","?"); tot=e.get("total_files",0); ts=e.get("timestamp","")[:19].replace("T"," ")
        _header(scr,w,f"Detail: {eid}")
        scr.fill(1,BG_PANEL+f"  {FG_MUTED}{ts}  ·  {RESET}{ACCENT+BOLD}{tot}{RESET}{FG_DIM} files  ·  {Path(e.get('base','?')).name}/{RESET}")
        scr.fill(2,BG_PANEL+COL_BORD+"─"*w+RESET)
        inner=h-5; lines=[]
        for r in recs:
            col=cat_fg(r.get("category","")); ico=cat_icon(r.get("category",""))
            dest=Path(r.get("destination","")).parent.name
            lines.append(f"  {FG_MUTED}{ico}{RESET}  {FG_BRIGHT}{pad_to(r.get('filename',''),36)}{RESET}  {FG_MUTED}->{RESET}  {col}{dest}/{RESET}")
        self._detail_scroll=min(self._detail_scroll,max(0,len(lines)-inner))
        for i in range(inner):
            idx=self._detail_scroll+i
            scr.fill(3+i,BG_PANEL+(lines[idx] if idx<len(lines) else "")+RESET)
        scr.fill(3+inner,BG_PANEL+COL_BORD+"─"*w+RESET)
        _footer(scr,w,h-1,[("Up/Down","scroll"),("B/Esc","back")])
        scr.flush()


# ── WatchScreen ────────────────────────────────────────────────────────────────
class WatchScreen:
    def __init__(self,base:Path,dry_run:bool):
        self.base=base; self.dry_run=dry_run
        self._log:list[tuple[str,str,str,str]]=[]
        self._lock=threading.Lock(); self._start=time.monotonic(); self._stop=threading.Event()
        self._scr=Screen()
    def add_event(self,filename:str,dest:str,category:str)->None:
        with self._lock:
            ts=time.strftime("%H:%M:%S"); self._log.append((ts,category,filename,dest))
            if len(self._log)>500: self._log=self._log[-500:]
    def run_blocking(self)->None:
        self._scr.enter()
        try:
            while not self._stop.is_set():
                self._draw(); time.sleep(0.25)
        finally:
            self._scr.exit()
    def stop(self)->None: self._stop.set()
    def _draw(self)->None:
        scr=self._scr; scr.resize(); w,h=scr.w,scr.h
        elapsed=int(time.monotonic()-self._start); count=len(self._log)
        _bg(scr,w,h)
        tag="preview only" if self.dry_run else "live organizing"
        _header(scr,w,"Watch Mode",tag,COL_WARN if self.dry_run else COL_OK)
        scr.fill(1,BG_PANEL+f"  {FG_MUTED}uptime {elapsed}s  ·  {RESET}{ACCENT+BOLD}{count}{RESET}{FG_DIM} files organized{RESET}")
        scr.fill(2,BG_PANEL+COL_BORD+"─"*w+RESET)
        scr.fill(3,bg256(232)+FG_MUTED+f"  {'TIME':<10}  {'CATEGORY':<16}  {'FILE':<38}  DEST"+RESET)
        log_h=h-6
        scr.fill(4,BG_PANEL+box_top(w,col=COL_BORD)+RESET)
        with self._lock: visible=self._log[-(log_h):]
        for i,(ts,cat,fname,dest) in enumerate(visible):
            col=cat_fg(cat); ico=cat_icon(cat)
            scr.fill(5+i,BG_PANEL+f"  {FG_MUTED}{ts:<10}{RESET}  {col}{pad_to(ico+' '+cat,16)}{RESET}  {FG_BRIGHT}{truncate(fname,38)}{RESET}  {FG_MUTED}->{RESET}  {col}{dest}/{RESET}")
        scr.fill(5+log_h,BG_PANEL+box_bot(w,col=COL_BORD)+RESET)
        _footer(scr,w,h-1,[("Ctrl+C","stop watching")])
        scr.flush()
