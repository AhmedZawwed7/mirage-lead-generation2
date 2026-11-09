"""Advanced feature routes ported from the original Mirage Hunter package."""
import os,re,time,uuid,smtplib,urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from email.message import EmailMessage
from flask import request,jsonify,render_template,redirect,session
import requests
from bs4 import BeautifulSoup
try:
    import phonenumbers
except ImportError:
    phonenumbers = None

COUNTRY_DATA={
 "SA":("السعودية",["الرياض","جدة","الدمام","مكة المكرمة","المدينة المنورة","الخبر","أبها","تبوك"]),
 "AE":("الإمارات",["دبي","أبوظبي","الشارقة","عجمان","العين","رأس الخيمة"]),
 "EG":("مصر",["القاهرة","الجيزة","الإسكندرية","المنصورة","طنطا","أسيوط","الغردقة"]),
 "KW":("الكويت",["مدينة الكويت","حولي","السالمية","الفروانية","الأحمدي"]),
 "QA":("قطر",["الدوحة","الريان","الوكرة","لوسيل"]),
 "BH":("البحرين",["المنامة","المحرق","الرفاع","مدينة عيسى"]),
 "OM":("عمان",["مسقط","صلالة","صحار","نزوى"]),
 "JO":("الأردن",["عمّان","إربد","الزرقاء","العقبة"]),
 "MA":("المغرب",["الدار البيضاء","الرباط","مراكش","طنجة","فاس"]),
 "TR":("تركيا",["إسطنبول","أنقرة","إزمير","أنطاليا"]),
 "GB":("بريطانيا",["لندن","مانشستر","برمنغهام","ليفربول"]),
 "US":("أمريكا",["نيويورك","لوس أنجلوس","شيكاغو","هيوستن"]),
 "DE":("ألمانيا",["برلين","ميونخ","هامبورغ","فرانكفورت"]),
 "FR":("فرنسا",["باريس","ليون","مرسيليا","نيس"]),
 "IT":("إيطاليا",["روما","ميلانو","نابولي","تورينو"]),
 "ES":("إسبانيا",["مدريد","برشلونة","فالنسيا","إشبيلية"]),
 "NL":("هولندا",["أمستردام","روتردام","أوترخت"]),
 "CA":("كندا",["تورونتو","فانكوفر","مونتريال","أوتاوا"]),
 "AU":("أستراليا",["سيدني","ملبورن","بريزبن","بيرث"]),
 "IN":("الهند",["مومباي","دلهي","بنغالور","حيدر آباد"]),
 "PK":("باكستان",["كراتشي","لاهور","إسلام آباد","راولبندي"]),
 "CN":("الصين",["شنغهاي","بكين","شينزين","قوانغتشو"]),
 "JP":("اليابان",["طوكيو","أوساكا","يوكوهاما"]),
 "ZA":("جنوب أفريقيا",["جوهانسبرغ","كيب تاون","ديربان"]),
 "NG":("نيجيريا",["لاغوس","أبوجا","كانو"])
}
COUNTRIES={k:v[0] for k,v in COUNTRY_DATA.items()}
MODIFIERS=["رقم الهاتف واتصل بنا","الموقع الرسمي بيانات التواصل","خدمات الشركات تواصل","contact phone official website"]
EXPANSIONS={"تنظيف":["خدمات تنظيف","شركة نظافة","cleaning services"],"مقاولات":["مقاولات عامة","إنشاءات","construction company"],"تسويق":["وكالة تسويق","digital marketing agency"],"عقارات":["شركة عقارية","real estate company"],"برمجة":["شركة برمجيات","software company"],"شحن":["شركة شحن ولوجستيات","logistics company"],"مطاعم":["مطاعم وشركات تموين","catering company"],"صيانة":["خدمات صيانة","maintenance services"]}
SKIP_DOMAINS=("facebook.com","instagram.com","linkedin.com","youtube.com","x.com","twitter.com","tiktok.com","wikipedia.org","yellowpages.","yelp.com","maps.google.")


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
        if section in ("whatsapp","email") and session.get("role") not in ("admin","manager"):
            return redirect("/leads")
        if section=="search" and session.get("role") not in ("admin","manager","researcher"):
            return redirect("/leads")
        c=db()
        batch_filter=request.args.get("batch",type=int)
        is_sales=session.get("role")=="sales"
        where=[];params=[]
        if batch_filter:where.append("batch_id=?");params.append(batch_filter)
        if is_sales:where.append("owner=?");params.append(session.get("user"))
        clause=(" WHERE "+" AND ".join(where)) if where else ""
        leads=c.execute("SELECT id,company,phone,email,city,country,status,website,batch_id,score,source,keyword FROM leads"+clause+" ORDER BY id DESC LIMIT 1000",params).fetchall()
        batches=c.execute("SELECT id,name,keyword,country,created,scanned,added FROM batches ORDER BY id DESC LIMIT 30").fetchall()
        scope=" WHERE owner=?" if is_sales else ""
        scope_params=(session.get("user"),) if is_sales else ()
        stats={"total":c.execute("SELECT COUNT(*) FROM leads"+scope,scope_params).fetchone()[0],
               "phone":c.execute("SELECT COUNT(*) FROM leads"+scope+(" AND" if scope else " WHERE")+" COALESCE(phone,'')<>''",scope_params).fetchone()[0],
               "email":c.execute("SELECT COUNT(*) FROM leads"+scope+(" AND" if scope else " WHERE")+" COALESCE(email,'')<>''",scope_params).fetchone()[0],
               "optout":c.execute("SELECT COUNT(*) FROM leads"+scope+(" AND" if scope else " WHERE")+" status='optout'",scope_params).fetchone()[0]}
        activities=[];tasks=[];wa_logs=[]
        if section=="activity":
            c.execute("CREATE TABLE IF NOT EXISTS wa_log(id INTEGER PRIMARY KEY,lead_id INTEGER,phone TEXT,ok INTEGER,note TEXT,created TEXT DEFAULT CURRENT_TIMESTAMP)")
            join_filter=" WHERE l.owner=?" if is_sales else ""
            activities=c.execute("SELECT a.id,a.actor,a.activity_type,a.note,a.created,l.company FROM activities a LEFT JOIN leads l ON l.id=a.lead_id"+join_filter+" ORDER BY a.id DESC LIMIT 150",scope_params).fetchall()
            tasks=c.execute("SELECT t.id,t.title,t.due_at,t.status,t.assigned_to,l.company FROM tasks t LEFT JOIN leads l ON l.id=t.lead_id"+join_filter+" ORDER BY t.id DESC LIMIT 100",scope_params).fetchall()
            wa_logs=c.execute("SELECT w.id,w.phone,w.ok,w.note,w.created,l.company FROM wa_log w LEFT JOIN leads l ON l.id=w.lead_id"+join_filter+" ORDER BY w.id DESC LIMIT 100",scope_params).fetchall()
        c.close()
        return render_template("features.html",section=section,leads=leads,stats=stats,countries=COUNTRIES,activities=activities,tasks=tasks,wa_logs=wa_logs,batches=batches,batch_filter=batch_filter)

    for section in ("search","leads","whatsapp","email","activity","statistics"):
        def view(s=section): return render_page(s)
        view.__name__="mirage_"+section
        app.add_url_rule("/"+section,endpoint=view.__name__,view_func=auth(view))

    def phone_digits(value):
        return re.sub(r"\D","",value or "")

    def normalize_phone(raw,region):
        if phonenumbers:
            try:
                parsed=phonenumbers.parse(raw,region or None)
                if phonenumbers.is_valid_number(parsed):
                    mobile=phonenumbers.number_type(parsed) in (phonenumbers.PhoneNumberType.MOBILE,phonenumbers.PhoneNumberType.FIXED_LINE_OR_MOBILE)
                    return phonenumbers.format_number(parsed,phonenumbers.PhoneNumberFormat.INTERNATIONAL),mobile
            except Exception:return "",False
            return "",False
        digits=phone_digits(raw)
        return ("+"+digits,False) if 9<=len(digits)<=15 else ("",False)

    def get_results(query,country,engine,lang,limit):
        if engine=="google_maps":
            key=os.getenv("SERPAPI_KEY")
            if not key:return []
            try:
                r=requests.get("https://serpapi.com/search.json",params={"engine":"google_maps","q":query,"api_key":key,"hl":"ar" if lang=="ar" else "en","gl":country.lower()},timeout=22)
                r.raise_for_status();data=r.json()
                return data.get("local_results") or data.get("places_results") or []
            except Exception:return []
        try:
            from ddgs import DDGS
            region=("xa-ar" if lang=="ar" else "xa-en") if country in ("SA","AE","KW","QA","BH","OM") else "wt-wt"
            try:return list(DDGS().text(query,backend=engine,region=region,max_results=min(40,max(10,limit))))
            except TypeError:return list(DDGS().text(query,region=region,max_results=min(40,max(10,limit))))
        except Exception:return []

    def extract_site(html,url,code,cities):
        soup=BeautifulSoup(html,"html.parser");strong=[];emails=[];has_wa=False
        for anchor in soup.find_all("a",href=True):
            href=anchor.get("href","").strip()
            if href.lower().startswith("tel:"):strong.append(urllib.parse.unquote(href[4:]))
            elif "wa.me/" in href or "api.whatsapp.com" in href:
                has_wa=True;match=re.search(r"(\d{8,15})",href)
                if match:strong.append("+"+match.group(1))
            elif href.lower().startswith("mailto:"):emails.append(href[7:].split("?")[0].strip().lower())
        text=" ".join(soup.stripped_strings)
        weak=re.findall(r"(?<![\w/])(\+?\d[\d\s().-]{7,17}\d)(?![\w/])",text)
        phones=[]
        for raw in strong+weak:
            number,mobile=normalize_phone(raw,code)
            if number and number not in [p[0] for p in phones]:phones.append((number,mobile,raw in strong))
        emails.extend(re.findall(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",html))
        emails=list(dict.fromkeys(e.lower() for e in emails if e and "example." not in e and "sentry" not in e and "noreply" not in e))
        meta=soup.find("meta",property="og:site_name");name=meta.get("content","") if meta else ""
        if not name and soup.title and soup.title.string:name=re.split(r"\s[|\-–—]\s",soup.title.string.strip())[0]
        city=next((c for c in cities if c and c.lower() in text.lower()),"")
        return {"phones":phones,"emails":emails,"name":name[:180],"city":city,"wa":has_wa}

    def contact_pages(html,base_url):
        soup=BeautifulSoup(html,"html.parser");host=urllib.parse.urlparse(base_url).hostname;found=[]
        hints=("contact","about","اتصل","تواصل","من نحن","اتصل بنا","contact-us")
        for anchor in soup.find_all("a",href=True):
            label=(anchor.get_text(" ",strip=True)+" "+anchor["href"]).lower()
            if any(h in label for h in hints):
                candidate=urllib.parse.urljoin(base_url,anchor["href"])
                if urllib.parse.urlparse(candidate).hostname==host and candidate not in found:found.append(candidate)
            if len(found)>=2:break
        return found

    def process_site(item,code,keyword,engine):
        url=item.get("website") or item.get("link") or item.get("href") or item.get("url") or ""
        if url and not url.startswith(("http://","https://")):url="https://"+url
        title=str(item.get("title") or item.get("name") or "شركة بدون اسم")[:180]
        raw_phone=str(item.get("phone") or item.get("phone_number") or "")
        address=str(item.get("address") or item.get("city") or "")[:180]
        city=next((c for c in COUNTRY_DATA.get(code,("",[],))[1] if c in address),address)
        email=str(item.get("email") or "").strip().lower();phone,mobile=normalize_phone(raw_phone,code) if raw_phone else ("",False)
        phones=[(phone,mobile,True)] if phone else [];has_wa=False;host=""
        if url and is_public_url(url) and robots_allowed(url):
            host=(urllib.parse.urlparse(url).hostname or "").lower().removeprefix("www.")
            html=safe_fetch(url)
            if html:
                data=extract_site(html,url,code,COUNTRY_DATA.get(code,("",[],))[1])
                if data["name"]:title=data["name"]
                phones.extend([p for p in data["phones"] if p[0] not in [x[0] for x in phones]])
                email=email or (data["emails"][0] if data["emails"] else "")
                city=city or data["city"];has_wa=data["wa"]
                if not phones:
                    for contact_url in contact_pages(html,url):
                        if not robots_allowed(contact_url):continue
                        sub=safe_fetch(contact_url)
                        if not sub:continue
                        more=extract_site(sub,contact_url,code,COUNTRY_DATA.get(code,("",[],))[1])
                        phones.extend([p for p in more["phones"] if p[0] not in [x[0] for x in phones]])
                        email=email or (more["emails"][0] if more["emails"] else "")
                        city=city or more["city"];has_wa=has_wa or more["wa"]
                        if phones:break
        if not phones and not email:return []
        phones.sort(key=lambda p:(not p[2],not p[1]));phones=phones[:3] or [("",False,False)]
        return [{"company":title,"phone":num,"email":email,"website":host,"country":COUNTRIES.get(code,code),"city":city,"keyword":keyword,"score":min(99,35+(25 if mobile else (10 if num else 0))+(18 if email else 0)+(14 if has_wa else 0)+(8 if city else 0)),"source":engine} for num,mobile,strong in phones]

    @app.post("/api/search/advanced")
    @auth
    @role_required("admin","manager","researcher")
    def advanced_search():
        b=request.get_json(silent=True) or {}
        keyword=str(b.get("keyword") or "").strip()
        countries=b.get("countries") or []
        if isinstance(countries,str):countries=[countries]
        countries=[x for x in countries if x in COUNTRIES]
        engines=[x for x in (b.get("engines") or ["duckduckgo"]) if x in ("google","google_maps","bing","brave","duckduckgo","yahoo","yandex","mojeek","startpage","wikipedia")]
        try:target=max(1,min(1000,int(b.get("target",100))))
        except (ValueError,TypeError):target=100
        lang=b.get("language") if b.get("language") in ("ar","en","both") else "ar"
        city_filter=str(b.get("city") or "").strip()
        widen=b.get("widen",True) is not False
        if not keyword or not countries or not engines:return jsonify(error="أدخل النشاط واختر دولة واحدة على الأقل ومحرك بحث."),400
        map_warning=""
        if "google_maps" in engines and not os.getenv("SERPAPI_KEY"):
            engines=[x for x in engines if x!="google_maps"]
            map_warning="Google Maps يحتاج SERPAPI_KEY؛ محركات الويب تعمل عبر DDGS بدون مفتاح."
        if not engines:return jsonify(error=map_warning or "لا يوجد محرك بحث متاح."),400

        c=db()
        batch=c.execute("INSERT INTO batches(name,keyword,country) VALUES(?,?,?)",(keyword+" | "+", ".join(COUNTRIES[x] for x in countries),keyword,", ".join(COUNTRIES[x] for x in countries))).lastrowid
        audit(c,"search.started","batch",batch,keyword+" | "+", ".join(countries));c.commit();c.close()

        keywords=[keyword]
        if widen:
            for term,alts in EXPANSIONS.items():
                if term in keyword:keywords.extend(alts)
        keywords=list(dict.fromkeys(keywords))
        languages=("ar","en") if lang=="both" else (lang,)
        query_plan=[]
        # Interleave countries so a bounded search still covers every selected market.
        max_city_slots=max([len([city_filter] if city_filter else COUNTRY_DATA[code][1][:4]) for code in countries] or [1])
        for city_index in range(max_city_slots):
            for code in countries:
                cities=[city_filter] if city_filter else COUNTRY_DATA[code][1][:4]
                if city_index>=len(cities):continue
                city_name=cities[city_index]
                for kw in keywords:
                    for language in languages:
                        modifier=MODIFIERS[0] if language=="ar" else MODIFIERS[-1]
                        query_plan.append((" ".join(x for x in (kw,city_name,COUNTRIES[code],modifier) if x),code,language,kw))
        max_queries=max(4,min(24,72//max(1,len(engines))))
        query_plan=query_plan[:max_queries]
        scanned=added=duplicates=0;seen_hosts=set();seen_phones=set();seen_emails=set()
        max_sites=min(1600,max(120,target*8))
        with ThreadPoolExecutor(max_workers=12) as pool:
            for query,code,language,kw in query_plan:
                if added>=target or scanned>=max_sites:break
                for engine in engines:
                    if added>=target or scanned>=max_sites:break
                    items=get_results(query,code,engine,language,30)
                    futures=[]
                    for item in items:
                        if scanned>=max_sites:break
                        url=item.get("website") or item.get("link") or item.get("href") or item.get("url") or ""
                        host=(urllib.parse.urlparse(url if "://" in url else "https://"+url).hostname or "").lower().removeprefix("www.") if url else ""
                        if host and (host in seen_hosts or any(host.endswith(x) for x in SKIP_DOMAINS)):continue
                        if host:seen_hosts.add(host)
                        scanned+=1;futures.append(pool.submit(process_site,item,code,kw,engine))
                    for future in as_completed(futures):
                        try:found=future.result()
                        except Exception:found=[]
                        for lead in found:
                            if added>=target:break
                            pn=phone_digits(lead["phone"]);em=lead["email"].lower();host=lead["website"].lower()
                            if (pn and pn in seen_phones) or (em and em in seen_emails):duplicates+=1;continue
                            c=db()
                            old=c.execute("""SELECT id FROM leads
                                WHERE (?<>'' AND REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(phone,'+',''),' ',''),'-',''),'(', ''),')',''),'.','')=?)
                                   OR (?<>'' AND lower(email)=?)
                                   OR (?<>'' AND lower(website)=?) LIMIT 1""",(pn,pn,em,em,host,host)).fetchone()
                            if old:duplicates+=1;c.close();continue
                            try:
                                c.execute("""INSERT INTO leads(company,phone,email,website,country,keyword,score,status,source,city,batch_id)
                                    VALUES(?,?,?,?,?,?,?,'new',?,?,?)""",
                                    (lead["company"],lead["phone"],lead["email"],lead["website"],lead["country"],lead["keyword"],lead["score"],lead["source"],lead["city"],batch))
                                c.commit();added+=1
                                if pn:seen_phones.add(pn)
                                if em:seen_emails.add(em)
                            except Exception:
                                c.rollback();duplicates+=1
                            finally:c.close()
        c=db();c.execute("UPDATE batches SET scanned=?,added=? WHERE id=?",(scanned,added,batch));c.commit();c.close()
        warning="؛ ".join(x for x in (map_warning,) if x)
        return jsonify(ok=True,batch_id=batch,scanned=scanned,added=added,duplicates=duplicates,target=target,countries=[COUNTRIES[x] for x in countries],engines=engines,warning=warning,note=("وصل البحث إلى الهدف المطلوب." if added>=target else "انتهت الاستعلامات المتاحة قبل الوصول للهدف؛ يمكنك بدء دفعة أخرى."))

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
