import os
os.environ['MIRAGE_DB']='/tmp/mirage-test-'+str(os.getpid())+'.db'
os.environ['MIRAGE_ADMIN_PASSWORD']='test-password'
import app
def test_health(): assert app.app.test_client().get('/health').json['status']=='ok'
def test_login_required(): assert app.app.test_client().get('/').status_code==302
def test_login_dashboard():
 c=app.app.test_client();assert c.post('/login',data={'username':'admin','password':'test-password'}).status_code==302;assert c.get('/').status_code==200
def test_update_requires_login(): assert app.app.test_client().patch('/api/leads/1',json={'status':'won'}).status_code==302
