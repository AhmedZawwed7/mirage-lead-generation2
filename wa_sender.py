"""Local WhatsApp Web sender. Never commit the generated wa_profile directory."""
import os,random,threading,time,urllib.parse
MIN_DELAY_FLOOR=10
class WaSender:
    def __init__(self,profile_dir,mark_contacted,log_result,sent_today):
        self.profile_dir=profile_dir;self.mark_contacted=mark_contacted;self.log_result=log_result;self.sent_today=sent_today
        self.lock=threading.Lock();self.stop=threading.Event();self.thread=None
        self.s={"status":"idle","sent":0,"failed":0,"total":0,"current":"","note":"","entries":[],"next_at":0}
    def running(self):return self.thread is not None and self.thread.is_alive()
    def snapshot(self):
        with self.lock:return dict(self.s)
    def start(self,items,cfg):
        if self.running():return False
        self.stop.clear()
        with self.lock:self.s={"status":"starting","sent":0,"failed":0,"total":len(items),"current":"","note":"","entries":[],"next_at":0}
        self.thread=threading.Thread(target=self._run,args=(items,cfg),daemon=True);self.thread.start();return True
    def halt(self):self.stop.set()
    def _run(self,items,cfg):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            with self.lock:self.s.update(status="error",note="ثبّت Playwright ثم نفّذ playwright install chromium")
            return
        try:
            os.makedirs(self.profile_dir,exist_ok=True)
            with sync_playwright() as p:
                try:ctx=p.chromium.launch_persistent_context(self.profile_dir,channel="chrome",headless=False)
                except Exception:ctx=p.chromium.launch_persistent_context(self.profile_dir,headless=False)
                page=ctx.pages[0] if ctx.pages else ctx.new_page()
                page.goto("https://web.whatsapp.com",wait_until="domcontentloaded")
                with self.lock:self.s["status"]="waiting_login"
                deadline=time.time()+300
                while time.time()<deadline and not self.stop.is_set():
                    if page.locator("#pane-side").count() or page.locator("#side").count():break
                    time.sleep(1)
                if self.stop.is_set():ctx.close();return
                if not (page.locator("#pane-side").count() or page.locator("#side").count()):
                    with self.lock:self.s.update(status="error",note="لم يتم مسح QR خلال 5 دقائق")
                    ctx.close();return
                if not items:
                    with self.lock:self.s.update(status="connected",note="تم ربط WhatsApp وحفظ الجلسة على هذا الجهاز")
                    ctx.close();return
                with self.lock:self.s["status"]="sending"
                sent_run=0;final="done"
                for i,item in enumerate(items):
                    if self.stop.is_set():final="stopped";break
                    if self.sent_today()>=cfg["daily_cap"]:final="daily_cap";break
                    phone=item["phone"];text=item.get("text","")
                    with self.lock:self.s.update(current=phone,index=i+1,status="sending")
                    url="https://web.whatsapp.com/send?phone="+phone+"&text="+urllib.parse.quote(text)
                    page.goto(url,wait_until="domcontentloaded",timeout=60000)
                    composer=page.locator('#main footer [contenteditable="true"]').first
                    try:
                        composer.wait_for(state="visible",timeout=45000)
                        time.sleep(1)
                        if text:
                            send=page.locator('#main [data-icon="send"]').last
                            if send.count():send.click(timeout=10000)
                            else:composer.press("Enter")
                        ok=True;note=""
                        if item.get("attachment"):
                            try:
                                menus=page.locator('[data-icon*="plus"], [data-icon*="attach"], [data-icon="clip"]')
                                if menus.count(): menus.last.click(timeout=4000)
                                inputs=page.locator('input[type="file"]')
                                accepts=inputs.evaluate_all("els => els.map(e => (e.accept || '').toLowerCase())")
                                if not accepts: raise RuntimeError("WhatsApp attachment input unavailable")
                                import mimetypes
                                mime=(mimetypes.guess_type(item["attachment"])[0] or "").lower()
                                is_media=mime.startswith(("image/","video/"))
                                candidates=[i for i,a in enumerate(accepts) if ("video" in a)==is_media and (is_media or not any(x in a for x in ("image","video","webp")))]
                                index=candidates[0] if candidates else len(accepts)-1
                                inputs.nth(index).set_input_files(item["attachment"],timeout=15000);time.sleep(2)
                                send=page.locator('#main [data-icon="send"]').last
                                send.wait_for(state="visible",timeout=15000);send.click(timeout=10000);time.sleep(2)
                            except Exception:ok=False;note="تعذر إرسال المرفق"
                    except Exception:ok=False;note="تعذر فتح المحادثة أو الرقم غير متاح"
                    self.log_result(item["id"],phone,ok,note)
                    if ok:self.mark_contacted(item["id"]);sent_run+=1
                    with self.lock:
                        self.s["sent" if ok else "failed"]+=1
                        self.s["entries"].append({"phone":phone,"ok":ok,"note":note})
                    if i<len(items)-1:
                        delay=random.uniform(cfg["min_delay"],cfg["max_delay"]) if ok else 3
                        if ok and cfg["batch_size"] and sent_run%cfg["batch_size"]==0:delay+=cfg["batch_pause"]*60
                        with self.lock:self.s.update(status="waiting",next_at=time.time()+delay)
                        end=time.time()+delay
                        while time.time()<end and not self.stop.is_set():time.sleep(1)
                with self.lock:self.s.update(status="stopped" if self.stop.is_set() else final,next_at=0)
                ctx.close()
        except Exception as e:
            with self.lock:self.s.update(status="error",note=str(e)[:200])
