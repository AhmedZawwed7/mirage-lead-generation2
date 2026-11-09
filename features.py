"""Advanced feature routes ported from the original Mirage Hunter package."""
import os,re,time,uuid,smtplib,urllib.parse
from email.message import EmailMessage
from flask import request,jsonify,render_template
import requests
from bs4 import BeautifulSoup

COUNTRIES={"SA":"السعودية","AE":"الإمارات","EG":"مصر","KW":"الكويت","QA":"قطر","BH":"البحرين","OM":"عمان","JO":"الأردن","MA":"المغرب","TR":"تركيا","GB":"بريطانيا","US":"أمريكا","DE":"ألمانيا","FR":"فرنسا","IT":"إيطاليا","ES":"إسبانيا","NL":"هولندا","CA":"كندا","AU":"أستراليا","IN":"الهند","PK":"باكستان","CN":"الصين","JP":"اليابان","ZA":"جنوب أفريقيا","NG":"نيجيريا"}

def register_features(app,db,auth,role_required,audit,safe_fetch,is_public_url,robots_allowed):
    sender={"obj":None}
    def init_wa():
        if sender["obj"]: return sender["obj"]
        from wa_sender import WaSender
        con=db()
        con.execute("CREATE TABLE IF NOT EXISTS wa_log(id INTEGER PRIMARY KEY,lead_id INTEGER,phone TEXT,ok INTEGER,note TEXT,created TEXT DEFAULT CURRENT_TIMESTAMP)")
        con.commit();con.close()
        def mark(i):
            c=db();c.execute("UPDATE leads SET status='contacted' WHERE id=? AND status<>'optout'",(i,));c.commit();c.close()
        def log(i,p,ok,n):
            c=db();c.execute("INSERT INTO wa_log(lead_id,phone,ok,note) VALUES(?,?,?,?)",(i,p,int(ok),n));c.commit();c.close()
        def today():
            c=db();n=c.execute("SELECT COUNT(*) FROM wa_log WHERE ok=1 AND date(created)=date('now','localtime')").fetchone()[0];c.close();return n
        sender["obj"]=WaSender(os.path.join(os.path.dirname(__file__),"instance","wa_profile"),mark,log,today)
        return sender["obj"]

    def render_page(section):
        c=db()
        leads=c.execute("SELECT id,company,phone,email,city,country,status,website FROM leads ORDER BY id DESC LIMIT 1000").fetchall()
        stats={"total":c.execute("SELECT COUNT(*) FROM leads").fetchone()[0],
               "phone":c.execute("SELECT COUNT(*) FROM leads WHERE COALESCE(phone,'')<>''").fetchone()[0],
               "email":c.execute("SELECT COUNT(*) FROM leads WHERE COALESCE(email,'')<>''").fetchone()[0],
               "optout":c.execute("SELECT COUNT(*) FROM leads WHERE status='optout'").fetchone()[0]}
        c.close()
        return render_template("features.html",section=section,leads=leads,stats=stats,countries=COUNTRIES)

    for section in ("search","leads","whatsapp","email","activity","statistics"):
        def view(s=section): return render_page(s)
        view.__name__="mirage_"+section
        app.add_url_rule("/"+section,endpoint=view.__name__,view_func=auth(view))

    def phone_digits(value):
        d=re.sub(r"\D","",value or "")
        return d if 8<=len(d)<=15 else ""

    def get_results(query,country,engine,lang,limit):
        key=os.getenv("SERPAPI_KEY")
        if engine not in ("google","bing","google_maps") or (not key and not (engine=="google" and os.getenv("GOOGLE_API_KEY") and os.getenv("GOOGLE_CX"))):
            try:
                from ddgs import DDGS
                region="xa-ar" if lang=="ar" else "wt-wt"
                return list(DDGS().text(query,backend=engine,region=region,max_results=min(100,limit)))
            except Exception:return []
        if engine=="google" and not key and os.getenv("GOOGLE_API_KEY") and os.getenv("GOOGLE_CX"):
            out=[]
            for start in range(1,min(91,limit)+1,10):
                try:
                    r=requests.get("https://www.googleapis.com/customsearch/v1",params={"key":os.getenv("GOOGLE_API_KEY"),"cx":os.getenv("GOOGLE_CX"),"q":query,"gl":country.lower(),"num":min(10,limit-len(out)),"start":start},timeout=18)
                    r.raise_for_status(); items=r.json().get("items",[])
                except Exception: break
                out.extend(items)
                if not items or len(out)>=limit: break
            return out
        if not key:return []
        out=[]; start=0
        for _ in range(min(10,max(1,(limit+9)//10))):
            params={"engine":engine,"q":query,"api_key":key,"gl":country.lower(),"hl":"ar" if lang=="ar" else "en","num":10}
            if engine=="google":params["start"]=start
            if engine=="bing":params["first"]=start+1
            if engine=="google_maps":params.pop("num",None)
            try:
                r=requests.get("https://serpapi.com/search.json",params=params,timeout=18);r.raise_for_status();data=r.json()
            except Exception:break
            items=(data.get("local_results") or data.get("places_results") or []) if engine=="google_maps" else (data.get("organic_results") or data.get("organic") or [])
            if not items:break
            out.extend(items)
            if engine=="google_maps" or len(out)>=limit:break
            start+=10
        return out[:limit]

    @app.post("/api/search/advanced")
    @auth
    @role_required("admin","manager","researcher")
    def advanced_search():
        b=request.get_json(silent=True) or {}
        keyword=str(b.get("keyword") or "").strip()
        countries=b.get("countries") or []
        if isinstance(countries,str):countries=[countries]
        countries=[x for x in countries if x in COUNTRIES]
        engines=[x for x in (b.get("engines") or ["google","google_maps","bing","duckduckgo"]) if x in ("google","google_maps","bing","brave","duckduckgo","yahoo","yandex","mojeek","startpage","wikipedia")]
        try:target=max(1,min(1000,int(b.get("target",100))))
        except (ValueError,TypeError):target=100
        lang="en" if b.get("language")=="en" else "ar"
        if not keyword or not countries or not engines:return jsonify(error="أدخل النشاط واختر دولة واحدة على الأقل ومصدر بحث."),400
        c=db();batch=c.execute("INSERT INTO batches(name,keyword,country) VALUES(?,?,?)",(keyword+" | "+", ".join(COUNTRIES[x] for x in countries),keyword,", ".join(countries))).lastrowid
        audit(c,"search.started","batch",batch,keyword+" | "+", ".join(countries));c.commit();c.close()
        scanned=added=duplicates=0;seen_p=set();seen_h=set();seen_e=set();errors=[]
        for country in countries:
            for engine in engines:
                if added>=target:break
                if engine=="google_maps" and not os.getenv("SERPAPI_KEY"):
                    errors.append(engine+" يحتاج SERPAPI_KEY");continue
                q=f"{keyword} {COUNTRIES[country]} شركة هاتف تواصل"
                for item in get_results(q,country,engine,lang,max(10,target-added)):
                    if added>=target:break
                    scanned+=1
                    url=item.get("website") or item.get("link") or item.get("href") or item.get("url") or ""
                    if url and not url.startswith(("http://","https://")):url="https://"+url
                    name=str(item.get("title") or item.get("name") or "شركة بدون اسم")[:180]
                    phone=str(item.get("phone") or item.get("phone_number") or "")
                    email="";city=str(item.get("address") or item.get("city") or "")[:160]
                    host=urllib.parse.urlparse(url).hostname or "";host=host.lower().removeprefix("www.")
                    if url and is_public_url(url) and robots_allowed(url):
                        html=safe_fetch(url)
                        if html:
                            soup=BeautifulSoup(html,"html.parser")
                            if name=="شركة بدون اسم" and soup.title and soup.title.string:name=soup.title.string.strip()[:180]
                            txt=" ".join(soup.stripped_strings)
                            if not phone:
                                phone=next((p for p in re.findall(r"(?<![\w/])(\+?\d[\d\s().-]{7,17}\d)(?![\w/])",txt) if phone_digits(p)),"")
                            email=next((e.lower() for e in re.findall(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",html) if "example." not in e.lower() and "sentry" not in e.lower()),"")
                    pn=phone_digits(phone);en=email.lower()
                    if not pn and not en and not host:continue
                    if (pn and pn in seen_p) or (en and en in seen_e) or (host and host in seen_h):duplicates+=1;continue
                    c=db()
                    old=c.execute("SELECT id FROM leads WHERE (?<>'' AND REPLACE(REPLACE(REPLACE(phone,'+',''),' ',''),'-','')=?) OR (?<>'' AND lower(email)=?) OR (?<>'' AND lower(website) LIKE ?) LIMIT 1",(pn,pn,en,en,host,"%"+host+"%")).fetchone()
                    if old:duplicates+=1;c.close();continue
                    score=min(99,35+(25 if pn else 0)+(18 if en else 0)+(8 if city else 0))
                    c.execute("INSERT INTO leads(company,phone,email,website,country,keyword,score,status,source) VALUES(?,?,?,?,?,?,?,'new',?)",(name,phone,email,host or url,COUNTRIES[country],keyword,score,"google_maps" if engine=="google_maps" else engine))
                    c.commit();c.close()
                    if pn:seen_p.add(pn)
                    if en:seen_e.add(en)
                    if host:seen_h.add(host)
                    added+=1
            if added>=target:break
        c=db();c.execute("UPDATE batches SET scanned=?,added=? WHERE id=?",(scanned,added,batch));c.commit();c.close()
        warning="؛ ".join(dict.fromkeys(errors))
        return jsonify(ok=True,batch_id=batch,scanned=scanned,added=added,duplicates=duplicates,target=target,countries=[COUNTRIES[x] for x in countries],engines=engines,warning=warning)

    @app.post("/api/email/test")
    @auth
    @role_required("admin","manager")
    def email_test():
        b=request.get_json(silent=True) or {}
        if any(not str(b.get(k,"")).strip() for k in ("host","port","username","password","from_email")):return jsonify(error="أكمل بيانات SMTP"),400
        try:
            cls=smtplib.SMTP_SSL if b.get("ssl") else smtplib.SMTP
            with cls(str(b["host"]).strip(),int(b["port"]),timeout=20) as s:
                if b.get("starttls") and not b.get("ssl"):s.starttls()
                s.login(b["username"],b["password"])
            return jsonify(ok=True,message="اتصال SMTP ناجح")
        except Exception as e:return jsonify(error="فشل SMTP: "+str(e)[:180]),502

    @app.post("/api/email/send")
    @auth
    @role_required("admin","manager")
    def email_send():
        b=request.get_json(silent=True) or {}
        if any(not str(b.get(k,"")).strip() for k in ("host","port","username","password","from_email","subject","body")):return jsonify(error="أكمل إعدادات SMTP والرسالة"),400
        try:ids=list(dict.fromkeys(int(x) for x in b.get("ids",[])))
        except (ValueError,TypeError):return jsonify(error="قائمة العملاء غير صالحة"),400
        if not ids:return jsonify(error="حدد العملاء أولاً"),400
        c=db();marks=",".join("?" for _ in ids)
        rows=c.execute(f"SELECT id,company,email,city FROM leads WHERE id IN ({marks}) AND COALESCE(email,'')<>'' AND status<>'optout'",ids).fetchall();c.close()
        if not rows:return jsonify(error="لا توجد عناوين صالحة أو أن العملاء أوقفوا التواصل"),400
        sent=0;failed=[]
        try:
            cls=smtplib.SMTP_SSL if b.get("ssl") else smtplib.SMTP
            with cls(str(b["host"]).strip(),int(b["port"]),timeout=25) as s:
                if b.get("starttls") and not b.get("ssl"):s.starttls()
                s.login(b["username"],b["password"])
                for row in rows:
                    try:
                        m=EmailMessage();m["From"]=str(b["from_email"]).strip();m["To"]=row["email"];m["Subject"]=str(b["subject"]).replace("{company}",row["company"] or "")
                        m.set_content(str(b["body"]).replace("{company}",row["company"] or "").replace("{city}",row["city"] or ""));s.send_message(m);sent+=1
                    except Exception as e:failed.append({"email":row["email"],"error":str(e)[:120]})
        except Exception as e:return jsonify(error="فشل اتصال SMTP: "+str(e)[:180]),502
        return jsonify(ok=True,sent=sent,failed=len(failed),errors=failed)

    @app.get("/api/wa/state")
    @auth
    @role_required("admin","manager")
    def wa_state():
        if os.getenv("VERCEL"):return jsonify(status="unavailable",note="WhatsApp Web يحتاج Chrome على جهاز محلي، ولا يعمل داخل Vercel Serverless.")
        try:return jsonify(init_wa().snapshot())
        except Exception as e:return jsonify(status="error",note=str(e)[:160]),503

    @app.post("/api/wa/connect")
    @auth
    @role_required("admin","manager")
    def wa_connect():
        if os.getenv("VERCEL"):return jsonify(error="شغّل نسخة Windows المحلية مع Chrome لربط QR.")
        try:w=init_wa()
        except Exception as e:return jsonify(error="ثبّت Playwright على جهازك: "+str(e)[:140]),503
        cfg={"min_delay":20,"max_delay":45,"batch_size":30,"batch_pause":5,"daily_cap":150}
        if not w.start([],cfg):return jsonify(error="جلسة WhatsApp تعمل بالفعل"),409
        return jsonify(ok=True)

    @app.post("/api/wa/attachment")
    @auth
    @role_required("admin","manager")
    def wa_attachment():
        if os.getenv("VERCEL"):return jsonify(error="المرفقات تعمل على النسخة المحلية فقط.")
        f=request.files.get("file")
        if not f or not f.filename:return jsonify(error="اختر ملفاً"),400
        data=f.read(16*1024*1024+1)
        if len(data)>16*1024*1024:return jsonify(error="الحد الأقصى 16MB"),413
        folder=os.path.abspath(os.path.join(os.path.dirname(__file__),"uploads"));os.makedirs(folder,exist_ok=True)
        ext=re.sub(r"[^A-Za-z0-9.]","",os.path.splitext(os.path.basename(f.filename))[1])[:12]
        path=os.path.join(folder,uuid.uuid4().hex+ext)
        with open(path,"wb") as out:out.write(data)
        return jsonify(ok=True,path=path,name=os.path.basename(f.filename))

    @app.post("/api/wa/start")
    @auth
    @role_required("admin","manager")
    def wa_start():
        if os.getenv("VERCEL"):return jsonify(error="مرسل WhatsApp يحتاج جهاز Windows محلي مع Chrome.")
        b=request.get_json(silent=True) or {}
        try:ids=list(dict.fromkeys(int(x) for x in b.get("ids",[])))
        except (ValueError,TypeError):return jsonify(error="قائمة العملاء غير صالحة"),400
        msg=str(b.get("message") or "").strip();attachment=b.get("attachment")
        root=os.path.abspath(os.path.join(os.path.dirname(__file__),"uploads"))
        if attachment and (not os.path.isfile(attachment) or os.path.commonpath([os.path.abspath(attachment),root])!=root):return jsonify(error="المرفق غير صالح"),400
        if not ids or (not msg and not attachment):return jsonify(error="حدد العملاء واكتب رسالة أو أرفق ملفاً"),400
        c=db();marks=",".join("?" for _ in ids);rows={r["id"]:dict(r) for r in c.execute(f"SELECT * FROM leads WHERE id IN ({marks})",ids)};c.close()
        items=[];seen=set()
        for i in ids:
            r=rows.get(i)
            if not r or r["status"]=="optout":continue
            p=phone_digits(r["phone"])
            if not p or p in seen:continue
            seen.add(p);items.append({"id":i,"phone":p,"text":msg.replace("{company}",r["company"] or "").replace("{city}",r.get("city","") or ""),"attachment":attachment})
        if not items:return jsonify(error="لا توجد أرقام صالحة ضمن المحدد"),400
        try:w=init_wa()
        except Exception as e:return jsonify(error="تعذر تشغيل WhatsApp: "+str(e)[:150]),503
        def num(k,d,lo,hi):
            try:return max(lo,min(hi,float(b.get(k,d))))
            except (ValueError,TypeError):return d
        mn=num("min_delay",20,10,600);cfg={"min_delay":mn,"max_delay":max(mn,num("max_delay",45,10,900)),"batch_size":int(num("batch_size",30,0,200)),"batch_pause":num("batch_pause",5,0,60),"daily_cap":int(num("daily_cap",150,1,1000))}
        if not w.start(items,cfg):return jsonify(error="هناك حملة إرسال تعمل بالفعل"),409
        return jsonify(ok=True,total=len(items))

    @app.post("/api/wa/stop")
    @auth
    @role_required("admin","manager")
    def wa_stop():
        if sender["obj"]:sender["obj"].halt()
        return jsonify(ok=True)
