import os,re,sqlite3,io,csv,ipaddress,socket,urllib.parse
from functools import wraps
from flask import Flask,request,session,redirect,url_for,render_template,jsonify,Response,flash
import requests
from bs4 import BeautifulSoup
try:
 from ddgs import DDGS
except ImportError: DDGS=None
ROOT=os.path.dirname(__file__);DB=os.getenv('MIRAGE_DB',os.path.join(ROOT,'instance','mirage.db'));os.makedirs(os.path.dirname(DB),exist_ok=True)
app=Flask(__name__);app.secret_key=os.getenv('SECRET_KEY','dev-secret-change-this-before-deploying-123');ADMIN=os.getenv('MIRAGE_ADMIN_USER','admin');PASSWORD=os.getenv('MIRAGE_ADMIN_PASSWORD','')
PHONE=re.compile(r'(?<![\\w/])(\\+?\\d[\\d\\s().-]{7,17}\\d)(?![\\w/])');EMAIL=re.compile(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Za-z]{2,}')
def db():
 c=sqlite3.connect(DB,timeout=20);c.row_factory=sqlite3.Row
 c.execute(\"CREATE TABLE IF NOT EXISTS leads(id INTEGER PRIMARY KEY,company TEXT,phone TEXT,email TEXT,website TEXT,country TEXT,keyword TEXT,score INTEGER DEFAULT 0,status TEXT DEFAULT 'new',owner TEXT DEFAULT '',created TEXT DEFAULT CURRENT_TIMESTAMP,UNIQUE(phone,website))\")
 c.execute(\"CREATE TABLE IF NOT EXISTS batches(id INTEGER PRIMARY KEY,name TEXT,keyword TEXT,country TEXT,created TEXT DEFAULT CURRENT_TIMESTAMP,scanned INTEGER DEFAULT 0,added INTEGER DEFAULT 0)\");c.commit();return c
def auth(f):
 @wraps(f)
 def w(*a,**k):
  if not session.get('user'):return redirect(url_for('login'))
  return f(*a,**k)
 return w
def public(url):
 try:
  p=urllib.parse.urlparse(url)
  if p.scheme not in ('http','https') or not p.hostname or p.username or p.password or (p.port and p.port not in (80,443)):return False
  return all(ipaddress.ip_address(x[4][0]).is_global for x in socket.getaddrinfo(p.hostname,None))
 except Exception:return False
def fetch(url):
 if not public(url):return ''
 try:
  r=requests.get(url,timeout=10,headers={'User-Agent':'MirageLeadResearch/1.0'},allow_redirects=False)
  if 300<=r.status_code<400:
   u=urllib.parse.urljoin(url,r.headers.get('Location',''))
   if not public(u):return ''
   r=requests.get(u,timeout=10,headers={'User-Agent':'MirageLeadResearch/1.0'},allow_redirects=False)
  return r.text[:1500000] if r.status_code==200 else ''
 except requests.RequestException:return ''
def discover(keyword,country,limit):
 if DDGS is None:return [],'مكتبة البحث غير مثبتة'
 try:results=list(DDGS().text(keyword+' '+country+' اتصل بنا',max_results=min(int(limit),50)))
 except Exception as e:return [],'فشل مزود البحث: '+type(e).__name__
 found=[]
 for item in results:
  url=item.get('href') or item.get('url')
  if not url or not public(url):continue
  soup=BeautifulSoup(fetch(url),'html.parser')
  for tag in soup(['script','style','noscript','svg']):tag.decompose()
  txt=' '.join(soup.stripped_strings);phones=[]
  for p in PHONE.findall(txt):
   digits=re.sub(r'\\D','',p)
   if 8<=len(digits)<=15 and p not in phones:phones.append(p)
  emails=[e.lower() for e in EMAIL.findall(txt) if 'example.' not in e.lower()]
  if not phones and not emails:continue
  name=soup.title.string.strip()[:180] if soup.title and soup.title.string else item.get('title','Company')
  found.append((name,phones[0] if phones else '',emails[0] if emails else '',url,country,keyword,min(100,35+30*bool(phones)+25*bool(emails))))
 return found,''
@app.get('/health')
def health():return jsonify(status='ok',app='Mirage Leads Hunter')
@app.route('/login',methods=['GET','POST'])
def login():
 if request.method=='POST':
  if PASSWORD and request.form.get('username')==ADMIN and request.form.get('password')==PASSWORD:session['user']=ADMIN;return redirect('/')
  flash('بيانات الدخول غير صحيحة أو لم يتم إعداد كلمة المرور.')
 return render_template('login.html')
@app.get('/logout')
def logout():session.clear();return redirect('/login')
@app.get('/')
@auth
def home():
 c=db();stats={k:c.execute(q).fetchone()[0] for k,q in {'total':'select count(*) from leads','new':\"select count(*) from leads where status='new'\",'contacted':\"select count(*) from leads where status='contacted'\",'qualified':\"select count(*) from leads where status='qualified'\"}.items()};leads=c.execute('select * from leads order by id desc limit 500').fetchall();c.close();return render_template('index.html',stats=stats,leads=leads,user=session['user'])
@app.post('/api/search')
@auth
def search():
 d=request.get_json(silent=True) or request.form;kw=(d.get('keyword') or '').strip();country=(d.get('country') or 'السعودية').strip()
 if not kw:return jsonify(error='اكتب كلمة البحث'),400
 c=db();bid=c.execute('insert into batches(name,keyword,country) values(?,?,?)',(kw+' - '+country,kw,country)).lastrowid;c.commit();c.close();rows,error=discover(kw,country,d.get('limit',25));c=db();added=0
 for x in rows:
  try:c.execute('insert into leads(company,phone,email,website,country,keyword,score) values(?,?,?,?,?,?,?)',x);added+=1
  except sqlite3.IntegrityError:pass
 c.execute('update batches set scanned=?,added=? where id=?',(len(rows),added,bid));c.commit();c.close();return jsonify(batch_id=bid,scanned=len(rows),added=added,error=error)
@app.patch('/api/leads/<int:i>')
@auth
def update(i):
 d=request.get_json(silent=True) or {};d={k:v for k,v in d.items() if k in ('status','owner')}
 if not d:return jsonify(error='no changes'),400
 if 'status' in d and d['status'] not in ('new','contacted','qualified','won','lost','optout'):return jsonify(error='invalid status'),400
 c=db();c.execute('update leads set '+','.join(k+'=?' for k in d)+' where id=?',(*d.values(),i));ok=c.total_changes;c.commit();c.close();return jsonify(ok=bool(ok))
@app.get('/api/leads.csv')
@auth
def export():
 c=db();rows=c.execute('select company,phone,email,website,country,keyword,score,status,owner from leads order by id desc').fetchall();c.close();o=io.StringIO();w=csv.writer(o);w.writerow(rows[0].keys() if rows else ['company','phone','email','website','country','keyword','score','status','owner'])
 for row in rows:w.writerow([("'"+v if isinstance(v,str) and v.startswith(('=','+','-','@')) else v) for v in row])
 return Response('\\ufeff'+o.getvalue(),mimetype='text/csv',headers={'Content-Disposition':'attachment; filename=mirage-leads.csv'})
if __name__=='__main__':app.run(host='127.0.0.1',port=int(os.getenv('PORT',5000)))
