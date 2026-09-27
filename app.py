import os, re, secrets, sqlite3
from datetime import datetime
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, send_from_directory
from werkzeug.security import generate_password_hash, check_password_hash

try:
    import stripe
except ImportError:
    stripe = None

BASE=os.path.dirname(os.path.abspath(__file__))
DB=os.path.join(BASE,'afterdark.db')
UPLOADS=os.path.join(BASE,'uploads')
os.makedirs(UPLOADS,exist_ok=True)
app=Flask(__name__)
app.secret_key=os.environ.get('AFTERDARK_SECRET',secrets.token_hex(32))
app.config['MAX_CONTENT_LENGTH']=8*1024*1024


def db():
    c=sqlite3.connect(DB); c.row_factory=sqlite3.Row; c.execute('PRAGMA foreign_keys=ON'); return c

def init_db():
    c=db(); c.executescript('''
    CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY AUTOINCREMENT,email TEXT UNIQUE NOT NULL,password_hash TEXT NOT NULL,role TEXT NOT NULL,created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS providers(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER UNIQUE NOT NULL REFERENCES users(id) ON DELETE CASCADE,name TEXT NOT NULL,category TEXT NOT NULL,location TEXT DEFAULT 'Birmingham',bio TEXT DEFAULT '',social TEXT DEFAULT '',aesthetics TEXT DEFAULT '',stripe_account_id TEXT DEFAULT '');
    CREATE TABLE IF NOT EXISTS services(id INTEGER PRIMARY KEY AUTOINCREMENT,provider_id INTEGER NOT NULL REFERENCES providers(id) ON DELETE CASCADE,name TEXT NOT NULL,price TEXT NOT NULL,duration TEXT DEFAULT '');
    CREATE TABLE IF NOT EXISTS bookings(id INTEGER PRIMARY KEY AUTOINCREMENT,customer_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,provider_id INTEGER NOT NULL REFERENCES providers(id) ON DELETE CASCADE,service_id INTEGER REFERENCES services(id) ON DELETE SET NULL,requested_date TEXT,message TEXT DEFAULT '',status TEXT DEFAULT 'pending',created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS reviews(id INTEGER PRIMARY KEY AUTOINCREMENT,customer_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,provider_id INTEGER NOT NULL REFERENCES providers(id) ON DELETE CASCADE,rating INTEGER NOT NULL,text TEXT DEFAULT '',created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS portfolio(id INTEGER PRIMARY KEY AUTOINCREMENT,provider_id INTEGER NOT NULL REFERENCES providers(id) ON DELETE CASCADE,filename TEXT NOT NULL,caption TEXT DEFAULT '',created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS directory_listings(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL,category TEXT NOT NULL,address TEXT NOT NULL,description TEXT DEFAULT '',status TEXT DEFAULT 'unclaimed');
    '''); c.commit(); c.close()

def seed_directory():
    rows=[
    ('Birmingham Ink Tattoo','Tattoo shop','74 Dalton St, Birmingham B4 7LX'),
    ('Tattoo Birmingham | Apex Ink','Tattoo shop','17c Vyse St, Birmingham B18 6LE'),
    ('Good Soul Tattoo Studio','Tattoo shop','51 Pershore Rd S, Cotteridge, Birmingham B30 3EG'),
    ('No Regrets Studios Birmingham','Tattoo shop','1st floor, 16 Regent Pl, Birmingham B1 3NJ'),
    ('Vela Body Piercing','Body piercing shop','Unit 4, Phenix Salon Suites, Snow Hill Queensway, Birmingham B4 6GA'),
    ('Matt Clarke Piercing','Body piercing shop','Outer Circle studio, 44 High St, Erdington, Birmingham B23 6RH'),
    ('The Goths Playground','Alternative shop','Gibb St, Deritend, Birmingham B9 4AT'),
    ('Coven & Co','Jewellery store','119 Floodgate St, Deritend, Birmingham B5 5SU')]
    c=db()
    if c.execute('SELECT COUNT(*) FROM directory_listings').fetchone()[0]==0:
        c.executemany('INSERT INTO directory_listings(name,category,address) VALUES(?,?,?)',rows); c.commit()
    c.close()

def user():
    uid=session.get('uid')
    if not uid:return None
    c=db(); x=c.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone(); c.close(); return x

def required(role=None):
    def deco(fn):
        @wraps(fn)
        def w(*a,**kw):
            u=user()
            if not u:return redirect(url_for('login'))
            if role and u['role']!=role:return redirect(url_for('home'))
            return fn(*a,**kw)
        return w
    return deco

def admin_ok():
    u=user(); return bool(u and u['email'].lower()==os.environ.get('AFTERDARK_ADMIN_EMAIL','admin@afterdark.local').lower())

@app.context_processor
def ctx():return {'me':user()}

@app.route('/')
def home():
    q=request.args.get('q','').strip(); a=request.args.get('aesthetic','').strip(); c=db()
    if q or a:
        term=q or a; p=c.execute('''SELECT p, p.name''') if False else c.execute('''SELECT p.*,COALESCE(AVG(r.rating),0) rating,COUNT(r.id) review_count FROM providers p LEFT JOIN reviews r ON r.provider_id=p.id WHERE (p.name LIKE ? OR p.category LIKE ? OR p.location LIKE ? OR p.aesthetics LIKE ?) GROUP BY p.id ORDER BY rating DESC''',(f'%{term}%',f'%{term}%',f'%{term}%',f'%{term}%')).fetchall()
    else:
        p=c.execute('''SELECT p.*,COALESCE(AVG(r.rating),0) rating,COUNT(r.id) review_count FROM providers p LEFT JOIN reviews r ON r.provider_id=p.id GROUP BY p.id ORDER BY p.id DESC''').fetchall()
    directory=c.execute("SELECT * FROM directory_listings WHERE status!='hidden' ORDER BY name").fetchall(); c.close()
    return render_template('home.html',providers=p,directory=directory,q=q,aesthetic=a)

@app.route('/signup',methods=['GET','POST'])
def signup():
    if request.method=='POST':
        email=request.form['email'].strip().lower(); pw=request.form['password']; role=request.form['role']; c=db()
        if len(pw)<8: flash('Use at least 8 characters.'); c.close(); return redirect(url_for('signup'))
        try:
            cur=c.execute('INSERT INTO users(email,password_hash,role,created_at) VALUES(?,?,?,?)',(email,generate_password_hash(pw),role,datetime.utcnow().isoformat())); uid=cur.lastrowid
            if role=='provider':c.execute('INSERT INTO providers(user_id,name,category,location,bio,social,aesthetics) VALUES(?,?,?,?,?,?,?)',(uid,request.form.get('name') or email.split('@')[0],request.form.get('category') or 'Alternative Creative','Birmingham',request.form.get('bio',''),request.form.get('social',''),request.form.get('aesthetics','Gothic')))
            c.commit()
        except sqlite3.IntegrityError:c.close(); flash('That email is already registered.'); return redirect(url_for('signup'))
        c.close(); session['uid']=uid; return redirect(url_for('dashboard' if role=='provider' else 'home'))
    return render_template('signup.html')

@app.route('/login',methods=['GET','POST'])
def login():
    if request.method=='POST':
        c=db(); u=c.execute('SELECT * FROM users WHERE email=?',(request.form['email'].strip().lower(),)).fetchone(); c.close()
        if u and check_password_hash(u['password_hash'],request.form['password']):session['uid']=u['id']; return redirect(url_for('dashboard' if u['role']=='provider' else 'home'))
        flash('Email or password not recognised.')
    return render_template('login.html')

@app.get('/logout')
def logout():session.clear(); return redirect(url_for('home'))

@app.route('/provider/<int:pid>')
def provider(pid):
    c=db(); p=c.execute('SELECT p.*,COALESCE(AVG(r.rating),0) rating,COUNT(r.id) review_count FROM providers p LEFT JOIN reviews r ON r.provider_id=p.id WHERE p.id=? GROUP BY p.id',(pid,)).fetchone()
    if not p:c.close(); return 'Not found',404
    services=c.execute('SELECT * FROM services WHERE provider_id=?',(pid,)).fetchall(); reviews=c.execute('SELECT r.*,u.email FROM reviews r JOIN users u ON u.id=r.customer_id WHERE r.provider_id=? ORDER BY r.id DESC',(pid,)).fetchall(); portfolio=c.execute('SELECT * FROM portfolio WHERE provider_id=? ORDER BY id DESC',(pid,)).fetchall(); c.close()
    return render_template('provider.html',p=p,services=services,reviews=reviews,portfolio=portfolio)

@app.route('/dashboard',methods=['GET','POST'])
@required('provider')
def dashboard():
    u=user(); c=db(); p=c.execute('SELECT * FROM providers WHERE user_id=?',(u['id'],)).fetchone()
    if request.method=='POST':
        c.execute('UPDATE providers SET name=?,category=?,location=?,bio=?,social=?,aesthetics=? WHERE id=?',(request.form['name'],request.form['category'],request.form['location'],request.form['bio'],request.form['social'],request.form['aesthetics'],p['id'])); c.commit(); flash('Profile saved.')
        p=c.execute('SELECT * FROM providers WHERE id=?',(p['id'],)).fetchone()
    services=c.execute('SELECT * FROM services WHERE provider_id=?',(p['id'],)).fetchall(); bookings=c.execute('SELECT b.*,s.name service,u.email customer_email FROM bookings b LEFT JOIN services s ON s.id=b.service_id JOIN users u ON u.id=b.customer_id WHERE b.provider_id=? ORDER BY b.id DESC',(p['id'],)).fetchall(); portfolio=c.execute('SELECT * FROM portfolio WHERE provider_id=? ORDER BY id DESC',(p['id'],)).fetchall(); stats=c.execute('SELECT (SELECT COUNT(*) FROM bookings WHERE provider_id=?) bookings,(SELECT COUNT(*) FROM reviews WHERE provider_id=?) reviews,(SELECT COUNT(*) FROM portfolio WHERE provider_id=?) portfolio',(p['id'],p['id'],p['id'])).fetchone(); c.close()
    return render_template('dashboard.html',p=p,services=services,bookings=bookings,portfolio=portfolio,stats=stats)

@app.post('/dashboard/service')
@required('provider')
def add_service():
    c=db(); p=c.execute('SELECT id FROM providers WHERE user_id=?',(user()['id'],)).fetchone(); c.execute('INSERT INTO services(provider_id,name,price,duration) VALUES(?,?,?,?)',(p['id'],request.form['name'],request.form['price'],request.form.get('duration',''))); c.commit(); c.close(); return redirect(url_for('dashboard'))

@app.post('/dashboard/service/<int:sid>/delete')
@required('provider')
def del_service(sid):
    c=db(); c.execute('DELETE FROM services WHERE id=? AND provider_id=(SELECT id FROM providers WHERE user_id=?)',(sid,user()['id'])); c.commit(); c.close(); return redirect(url_for('dashboard'))

@app.post('/dashboard/booking/<int:bid>')
@required('provider')
def update_booking(bid):
    c=db(); c.execute('UPDATE bookings SET status=? WHERE id=? AND provider_id=(SELECT id FROM providers WHERE user_id=?)',(request.form['status'],bid,user()['id'])); c.commit(); c.close(); return redirect(url_for('dashboard'))

@app.post('/provider/<int:pid>/book')
@required('customer')
def book(pid):
    c=db(); c.execute('INSERT INTO bookings(customer_id,provider_id,service_id,requested_date,message,created_at) VALUES(?,?,?,?,?,?)',(user()['id'],pid,request.form.get('service_id') or None,request.form.get('requested_date'),request.form.get('message',''),datetime.utcnow().isoformat())); c.commit(); c.close(); flash('Enquiry sent.'); return redirect(url_for('provider',pid=pid))

@app.post('/provider/<int:pid>/review')
@required('customer')
def review(pid):
    c=db(); c.execute('INSERT INTO reviews(customer_id,provider_id,rating,text,created_at) VALUES(?,?,?,?,?)',(user()['id'],pid,max(1,min(5,int(request.form['rating']))),request.form.get('text',''),datetime.utcnow().isoformat())); c.commit(); c.close(); flash('Review added.'); return redirect(url_for('provider',pid=pid))

@app.route('/account')
@required('customer')
def account():
    c=db(); bookings=c.execute('SELECT b.*,p.name provider_name,s.name service,s.price FROM bookings b JOIN providers p ON p.id=b.provider_id LEFT JOIN services s ON s.id=b.service_id WHERE b.customer_id=? ORDER BY b.id DESC',(user()['id'],)).fetchall(); c.close(); return render_template('account.html',bookings=bookings)

@app.post('/dashboard/upload')
@required('provider')
def upload():
    f=request.files.get('image');
    if not f or not f.filename:flash('Choose an image.'); return redirect(url_for('dashboard'))
    ext=f.filename.rsplit('.',1)[-1].lower() if '.' in f.filename else ''
    if ext not in {'png','jpg','jpeg','webp','gif'}:flash('Use PNG, JPG, WEBP or GIF.'); return redirect(url_for('dashboard'))
    name=secrets.token_hex(10)+'.'+ext; f.save(os.path.join(UPLOADS,name)); c=db(); p=c.execute('SELECT id FROM providers WHERE user_id=?',(user()['id'],)).fetchone(); c.execute('INSERT INTO portfolio(provider_id,filename,caption,created_at) VALUES(?,?,?,?)',(p['id'],name,request.form.get('caption',''),datetime.utcnow().isoformat())); c.commit(); c.close(); return redirect(url_for('dashboard'))

@app.get('/uploads/<path:name>')
def uploads(name):return send_from_directory(UPLOADS,name)

@app.route('/admin')
@required()
def admin():
    if not admin_ok():return 'Forbidden',403
    c=db(); counts=c.execute('SELECT (SELECT COUNT(*) FROM users) users,(SELECT COUNT(*) FROM providers) providers,(SELECT COUNT(*) FROM bookings) bookings,(SELECT COUNT(*) FROM directory_listings) listings').fetchone(); providers=c.execute('SELECT p.*,u.email FROM providers p JOIN users u ON u.id=p.user_id ORDER BY p.id DESC').fetchall(); listings=c.execute('SELECT * FROM directory_listings ORDER BY id DESC').fetchall(); bookings=c.execute('SELECT b.*,u.email customer_email,p.name provider_name FROM bookings b JOIN users u ON u.id=b.customer_id JOIN providers p ON p.id=b.provider_id ORDER BY b.id DESC').fetchall(); c.close(); return render_template('admin.html',counts=counts,providers=providers,listings=listings,bookings=bookings)

@app.post('/admin/listing/<int:lid>/invite')
@required()
def invite(lid):
    if not admin_ok():return 'Forbidden',403
    c=db(); c.execute("UPDATE directory_listings SET status='invited' WHERE id=?",(lid,)); c.commit(); c.close(); flash('Listing marked invited.'); return redirect(url_for('admin'))

@app.get('/connect/stripe')
@required('provider')
def connect_stripe():
    if stripe is None or not os.environ.get('STRIPE_SECRET_KEY'):flash('Stripe is not configured.'); return redirect(url_for('dashboard'))
    stripe.api_key=os.environ['STRIPE_SECRET_KEY']; c=db(); p=c.execute('SELECT * FROM providers WHERE user_id=?',(user()['id'],)).fetchone(); acct=stripe.Account.create(type='express',email=user()['email']); c.execute('UPDATE providers SET stripe_account_id=? WHERE id=?',(acct.id,p['id'])); c.commit(); c.close(); base=request.url_root.rstrip('/'); link=stripe.AccountLink.create(account=acct.id,refresh_url=base+'/dashboard',return_url=base+'/dashboard',type='account_onboarding'); return redirect(link.url)

@app.post('/booking/<int:bid>/checkout')
@required('customer')
def checkout(bid):
    if stripe is None or not os.environ.get('STRIPE_SECRET_KEY'):flash('Payments are not configured yet.'); return redirect(url_for('account'))
    stripe.api_key=os.environ['STRIPE_SECRET_KEY']; c=db(); b=c.execute('SELECT b.*,s.name service,s.price,p.stripe_account_id FROM bookings b LEFT JOIN services s ON s.id=b.service_id JOIN providers p ON p.id=b.provider_id WHERE b.id=? AND b.customer_id=?',(bid,user()['id'])).fetchone(); c.close()
    if not b or not b['price']:flash('This booking has no payable price.'); return redirect(url_for('account'))
    amount=int(float(re.sub(r'[^0-9.]','',b['price']))*100); params={'mode':'payment','line_items':[{'price_data':{'currency':'gbp','product_data':{'name':b['service'] or 'AFTERDARK booking'},'unit_amount':amount},'quantity':1}],'success_url':request.url_root.rstrip('/')+'/account?payment=success','cancel_url':request.url_root.rstrip('/')+'/account?payment=cancelled','metadata':{'booking_id':str(bid)}}
    if b['stripe_account_id']:params['payment_intent_data']={'application_fee_amount':int(amount*.12),'transfer_data':{'destination':b['stripe_account_id']}}
    return redirect(stripe.checkout.Session.create(**params).url)

@app.get('/health')
def health():return jsonify(ok=True,service='AFTERDARK Birmingham')

# Initialise the database when the app is imported by Gunicorn/Render.
# (Gunicorn does not execute the __main__ block.)
init_db()
seed_directory()

if __name__=='__main__':
    app.run(host='0.0.0.0',port=int(os.environ.get('PORT','5000')))
