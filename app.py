from flask import Flask, render_template, request, jsonify, session, redirect, url_for, send_from_directory, abort, Response
import base64
from functools import wraps
import re
import shutil
from werkzeug.utils import secure_filename
from flask_admin import Admin, AdminIndexView
from flask_sqlalchemy import SQLAlchemy
from flask_admin.contrib import sqla
from datetime import datetime, timedelta
from sqlalchemy import text, or_
import json
import os
import time
import random
import uuid
from flask_socketio import SocketIO, emit, join_room
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from dotenv import load_dotenv

# Loading environment variables from .env file
load_dotenv()

# ===== PATH =====
BASE_DIR = os.path.abspath(os.path.dirname(__file__))

# ===== APP =====
app = Flask(__name__, template_folder='templates')
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY') or 'dev-only-change-me'
ADMIN_NICKNAMES = {n.strip() for n in os.environ.get('ADMIN_NICKNAMES', '').split(',') if n.strip()}
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(BASE_DIR, 'tag.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.config['UPLOAD_FOLDER'] = os.path.join(BASE_DIR, 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 60 * 1024 * 1024
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)

socketio = SocketIO(app, cors_allowed_origins="*")

db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# ===== MODELS =====
class City(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    slug = db.Column(db.String(50), unique=True)

class Location(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    city_id = db.Column(db.Integer, db.ForeignKey('city.id'))
    city = db.relationship('City', backref='locations')
    theme = db.Column(db.String(50))
    photos = db.Column(db.Text)
    approved = db.Column(db.Boolean, default=False)

class Suggestion(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    type = db.Column(db.String(20))
    city = db.Column(db.String(100))
    title = db.Column(db.String(200))
    description = db.Column(db.Text)
    themes = db.Column(db.Text, nullable=True)  # JSON list
    user_id = db.Column(db.String(50))
    nickname = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class SuggestionPhoto(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    location_title = db.Column(db.String(200))
    city = db.Column(db.String(100))
    filename = db.Column(db.String(200))
    user_id = db.Column(db.String(50))
    status = db.Column(db.String(20), default='pending')

class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    telegram_username = db.Column(db.String(120), unique=True, nullable=True)
    telegram_id = db.Column(db.String(50), unique=True, nullable=True)
    nickname = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(128))
    avatar = db.Column(db.Text, nullable=True)  # Base64 encoded image
    is_confirmed = db.Column(db.Boolean, default=False)
    verification_code = db.Column(db.String(6), nullable=True)
    verification_expires = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

class PrivateMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    receiver_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    message = db.Column(db.Text, nullable=False)
    file_url = db.Column(db.String(500), nullable=True)  # Path to uploaded file
    file_type = db.Column(db.String(50), nullable=True)  # 'image', 'file', etc.
    file_name = db.Column(db.String(255), nullable=True)  # Original filename
    location = db.Column(db.Text, nullable=True)  # JSON string of location data
    kind = db.Column(db.String(20), default='text')
    payload = db.Column(db.Text, nullable=True)  # JSON for rich messages
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    sender = db.relationship('User', foreign_keys=[sender_id], backref='sent_messages')
    receiver = db.relationship('User', foreign_keys=[receiver_id], backref='received_messages')

class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    city_slug = db.Column(db.String(50))
    user_id = db.Column(db.String(50))
    nickname = db.Column(db.String(100))
    message = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class SavedLocation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    location_id = db.Column(db.Integer, db.ForeignKey('location.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user = db.relationship('User', backref='saved_locations')
    location = db.relationship('Location', backref='saved_by')

class FavoriteLocation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    title = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user = db.relationship('User', backref='favorite_locations')
    __table_args__ = (db.UniqueConstraint('user_id', 'title', name='uix_user_location'),)

class FriendRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    receiver_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    status = db.Column(db.String(20), default='pending')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    sender = db.relationship('User', foreign_keys=[sender_id], backref='sent_friend_requests')
    receiver = db.relationship('User', foreign_keys=[receiver_id], backref='received_friend_requests')
    __table_args__ = (db.UniqueConstraint('sender_id', 'receiver_id', name='uix_sender_receiver'),)


class Review(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    place_key = db.Column(db.String(300), nullable=False, index=True)
    rating = db.Column(db.Integer, nullable=False)
    text = db.Column(db.Text)
    media = db.Column(db.Text)  # JSON list [{"url":..., "type": "image"|"video"}]
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user = db.relationship('User', backref='reviews')
    __table_args__ = (db.UniqueConstraint('user_id', 'place_key', name='uix_review_user_place'),)

class Collection(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    title = db.Column(db.String(120), nullable=False)
    description = db.Column(db.String(500))
    privacy = db.Column(db.String(10), default='private')  # public | private | friends
    collaborative = db.Column(db.Boolean, default=False)
    token = db.Column(db.String(40), unique=True, default=lambda: uuid.uuid4().hex)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    owner = db.relationship('User', foreign_keys=[owner_id], backref='collections')

class CollectionItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    collection_id = db.Column(db.Integer, db.ForeignKey('collection.id'), nullable=False)
    place_key = db.Column(db.String(300), nullable=False)  # "<city>::<title>"
    title = db.Column(db.String(200), nullable=False)
    city = db.Column(db.String(80))
    description = db.Column(db.Text)
    photo = db.Column(db.String(500))
    lat = db.Column(db.Float)
    lon = db.Column(db.Float)
    added_by = db.Column(db.Integer, db.ForeignKey('user.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    collection = db.relationship('Collection', backref=db.backref(
        'items', cascade='all, delete-orphan', order_by='CollectionItem.created_at'))
    __table_args__ = (db.UniqueConstraint('collection_id', 'place_key', name='uix_collection_place'),)

class CollectionMember(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    collection_id = db.Column(db.Integer, db.ForeignKey('collection.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    status = db.Column(db.String(10), default='invited')  # invited | member
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    collection = db.relationship('Collection', backref=db.backref('members', cascade='all, delete-orphan'))
    user = db.relationship('User')
    __table_args__ = (db.UniqueConstraint('collection_id', 'user_id', name='uix_collection_member'),)

class CollectionShare(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    collection_id = db.Column(db.Integer, db.ForeignKey('collection.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    collection = db.relationship('Collection', backref=db.backref('shares', cascade='all, delete-orphan'))
    __table_args__ = (db.UniqueConstraint('collection_id', 'user_id', name='uix_collection_share'),)

class Plan(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    creator_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    place_key = db.Column(db.String(300))
    title = db.Column(db.String(200), nullable=False)
    city = db.Column(db.String(80))
    photo = db.Column(db.String(500))
    when_text = db.Column(db.String(40))
    note = db.Column(db.String(500))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    creator = db.relationship('User')

class PlanInvite(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    plan_id = db.Column(db.Integer, db.ForeignKey('plan.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    status = db.Column(db.String(10), default='pending')  # pending | going | maybe | declined
    plan = db.relationship('Plan', backref=db.backref('invites', cascade='all, delete-orphan'))
    user = db.relationship('User')
    __table_args__ = (db.UniqueConstraint('plan_id', 'user_id', name='uix_plan_user'),)



# ===== ADMIN =====
def is_admin_user():
    """Admin = nickname listed in ADMIN_NICKNAMES (.env). If the list is empty,
    the very first registered user is the admin."""
    if not current_user.is_authenticated:
        return False
    if ADMIN_NICKNAMES:
        return current_user.nickname in ADMIN_NICKNAMES
    first = User.query.order_by(User.id).first()
    return bool(first and first.id == current_user.id)

def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not is_admin_user():
            abort(403)
        return f(*args, **kwargs)
    return wrapper

class SecureModelView(sqla.ModelView):
    def is_accessible(self):
        return is_admin_user()

    def inaccessible_callback(self, name, **kwargs):
        abort(403)

class SecureIndexView(AdminIndexView):
    def is_accessible(self):
        return is_admin_user()

    def inaccessible_callback(self, name, **kwargs):
        abort(403)

@app.errorhandler(403)
def forbidden(e):
    if request.path.startswith('/api/'):
        return jsonify({'error': 'forbidden'}), 403
    return (
        '<meta charset="utf-8"><body style="font-family:system-ui;background:#1a1a1a;color:#eee;padding:40px">'
        '<h2>403 — нет доступа</h2>'
        '<p>Войдите под ником администратора. Ник задаётся в файле <code>miniapp/.env</code> строкой '
        '<code>ADMIN_NICKNAMES=ваш_ник</code> (после изменения перезапустите сайт). '
        'Если строка пустая, администратором считается первый зарегистрированный пользователь.</p>'
        '<p><a style="color:#ffb6d9" href="/login">Войти</a> · <a style="color:#ffb6d9" href="/">На главную</a></p></body>'
    ), 403

@app.context_processor
def inject_admin():
    try:
        return {'is_admin': is_admin_user()}
    except Exception:
        return {'is_admin': False}

admin = Admin(app, name='THEARCGO Admin', index_view=SecureIndexView())
admin.add_view(SecureModelView(City, db.session))
admin.add_view(SecureModelView(Location, db.session))
admin.add_view(SecureModelView(Suggestion, db.session))
admin.add_view(SecureModelView(SuggestionPhoto, db.session))
admin.add_view(SecureModelView(User, db.session))
admin.add_view(SecureModelView(PrivateMessage, db.session))
admin.add_view(SecureModelView(Message, db.session))
admin.add_view(SecureModelView(FavoriteLocation, db.session))
admin.add_view(SecureModelView(FriendRequest, db.session))
admin.add_view(SecureModelView(Review, db.session))
admin.add_view(SecureModelView(Collection, db.session))
admin.add_view(SecureModelView(Plan, db.session))



# ===== HELPERS =====
def parse_themes(val):
    if not val:
        return ['popular']
    try:
        parsed = json.loads(val)
        if isinstance(parsed, list):
            return parsed
        if isinstance(parsed, str):
            return [parsed]
    except Exception:
        pass
    return [t.strip() for t in str(val).split(',') if t.strip()]

def parse_photos(val, city_slug=None):
    """photos may be a JSON list or a comma-separated list of file names."""
    if not val:
        return []
    try:
        parsed = json.loads(val)
        items = parsed if isinstance(parsed, list) else [parsed]
    except Exception:
        items = [p.strip() for p in str(val).split(',') if p.strip()]
    result = []
    for p in items:
        if p.startswith('/') or p.startswith('http'):
            result.append(p)
        elif city_slug:
            result.append(f'/static/photos/{city_slug}/{p}')
        else:
            result.append(p)
    return result

_TRANSLIT = dict(zip('абвгдеёжзийклмнопрстуфхцчшщъыьэюя',
    ['a','b','v','g','d','e','e','zh','z','i','y','k','l','m','n','o','p','r','s','t','u','f','h','c','ch','sh','sch','','y','','e','yu','ya']))

def slugify(name):
    out = ''.join(_TRANSLIT.get(ch, ch) for ch in name.strip().lower())
    out = re.sub(r'[^a-z0-9]+', '-', out).strip('-')
    return out or f'city-{int(time.time())}'


# ===== API =====
# ===== SOCIAL HELPERS =====
ALLOWED_MEDIA = {
    'jpg': 'image', 'jpeg': 'image', 'png': 'image', 'webp': 'image', 'gif': 'image',
    'mp4': 'video', 'mov': 'video', 'webm': 'video',
}
MSG_KINDS = {'text', 'place', 'collection', 'plan', 'drop', 'collab_invite', 'plan_reply'}


def iso(dt):
    return dt.isoformat() + 'Z' if dt else None


def user_brief(u):
    return {'id': u.id, 'nickname': u.nickname, 'avatar': f'/avatar/{u.id}' if u.avatar else None}


def friend_ids_of(uid):
    rows = FriendRequest.query.filter(
        FriendRequest.status == 'accepted',
        or_(FriendRequest.sender_id == uid, FriendRequest.receiver_id == uid),
    ).all()
    return {r.receiver_id if r.sender_id == uid else r.sender_id for r in rows}


def are_friends(a, b):
    return b in friend_ids_of(a)


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _safe_url(u):
    u = str(u or '').strip()[:500]
    return u if (u.startswith('/') and not u.startswith('//')) or u.startswith('http://') or u.startswith('https://') else ''


def clean_place(p):
    """Whitelist the fields of a place sent by the browser."""
    if not isinstance(p, dict):
        return None
    title = str(p.get('title') or '').strip()[:200]
    if not title:
        return None
    city = str(p.get('city') or p.get('_city') or '').strip()[:80]
    photos = p.get('photos')
    photo = p.get('photo') or (photos[0] if isinstance(photos, list) and photos else '')
    return {
        'key': f'{city}::{title}', 'city': city, 'title': title,
        'desc': str(p.get('desc') or '')[:500], 'photo': _safe_url(photo),
        'lat': _num(p.get('lat')), 'lon': _num(p.get('lon')),
    }


def save_upload(file, subdir, max_mb=30):
    ext = os.path.splitext(file.filename or '')[1].lower().lstrip('.')
    if ext not in ALLOWED_MEDIA:
        return None, 'Поддерживаются фото (jpg, png, webp, gif) и видео (mp4, mov, webm)'
    file.stream.seek(0, os.SEEK_END)
    size = file.stream.tell()
    file.stream.seek(0)
    if size > max_mb * 1024 * 1024:
        return None, f'Файл больше {max_mb} МБ'
    name = f'{uuid.uuid4().hex}.{ext}'
    folder = os.path.join(BASE_DIR, 'uploads', subdir)
    os.makedirs(folder, exist_ok=True)
    file.save(os.path.join(folder, name))
    return {'url': f'/uploads/{subdir}/{name}', 'type': ALLOWED_MEDIA[ext]}, None


def remove_uploaded(url):
    if url and url.startswith('/uploads/'):
        path = os.path.normpath(os.path.join(BASE_DIR, url.lstrip('/')))
        if path.startswith(os.path.join(BASE_DIR, 'uploads')) and os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass


def message_preview(m):
    kind = m.kind or ('place' if m.location else 'text')
    return {
        'place': '📍 Место', 'collection': '🗂 Коллекция', 'plan': "📅 Let's Go",
        'drop': '💧 DROP', 'collab_invite': '🤝 Совместная подборка', 'plan_reply': m.message or '',
    }.get(kind) or (('📎 ' + (m.file_name or 'Файл')) if m.file_url and not m.message else (m.message or ''))


def serialize_message(m):
    payload = None
    if m.payload:
        try:
            payload = json.loads(m.payload)
        except Exception:
            payload = None
    return {
        'id': m.id, 'sender_id': m.sender_id, 'receiver_id': m.receiver_id,
        'message': m.message, 'file_url': m.file_url, 'file_type': m.file_type, 'file_name': m.file_name,
        'location': json.loads(m.location) if m.location else None,
        'kind': m.kind or ('place' if m.location else 'text'), 'payload': payload,
        'created_at': iso(m.created_at), 'sender_nickname': m.sender.nickname,
    }


def create_message(sender_id, receiver_id, text='', kind='text', payload=None,
                   file_url=None, file_type=None, file_name=None, location=None):
    msg = PrivateMessage(
        sender_id=sender_id, receiver_id=receiver_id, message=text or '',
        kind=kind, payload=json.dumps(payload, ensure_ascii=False) if payload else None,
        file_url=file_url, file_type=file_type, file_name=file_name,
        location=json.dumps(location, ensure_ascii=False) if location else None,
        is_read=False,
    )
    db.session.add(msg)
    db.session.commit()
    data = serialize_message(msg)
    try:
        for uid in {sender_id, receiver_id}:
            socketio.emit('new_private_message', data, to=str(uid))
    except Exception as exc:  # sockets are only a speed-up, the chat also polls over HTTP
        print('[SOCKET] push failed:', exc)
    return data


# ===== API =====
@socketio.on('connect')
def on_connect():
    if current_user.is_authenticated:
        join_room(str(current_user.id))


@socketio.on('join')
def on_join(data=None):
    if current_user.is_authenticated:
        join_room(str(current_user.id))


@socketio.on('private_message')
def handle_private_message(data):
    """Kept for old clients; the chat page now sends over HTTP (/api/send_message)."""
    if not current_user.is_authenticated or not isinstance(data, dict):
        return
    try:
        rid = int(data.get('receiver_id'))
    except (TypeError, ValueError):
        return
    if rid == current_user.id or not User.query.get(rid):
        return
    text = str(data.get('message') or '')[:4000]
    if text or data.get('file_url'):
        create_message(current_user.id, rid, text=text)


@app.route('/avatar/<int:uid>')
def avatar(uid):
    u = User.query.get_or_404(uid)
    m = re.match(r'data:(image/(?:png|jpeg|webp|gif));base64,(.+)$', u.avatar or '', re.S)
    if not m:
        abort(404)
    try:
        data = base64.b64decode(m.group(2))
    except Exception:
        abort(404)
    resp = Response(data, mimetype=m.group(1))
    resp.headers['Cache-Control'] = 'private, max-age=120'
    return resp


@app.route('/api/send_message', methods=['POST'])
@login_required
def api_send_message():
    d = request.get_json(silent=True) or {}
    try:
        rid = int(d.get('receiver_id'))
    except (TypeError, ValueError):
        return jsonify({'error': 'receiver_id required'}), 400
    if rid == current_user.id:
        return jsonify({'error': 'cannot message yourself'}), 400
    if not User.query.get(rid):
        return jsonify({'error': 'user not found'}), 404
    kind = d.get('kind') or 'text'
    if kind not in ('text', 'place', 'drop'):
        return jsonify({'error': 'bad kind'}), 400
    text = str(d.get('message') or '').strip()[:4000]
    payload = None
    file_url = file_type = file_name = None
    if kind in ('place', 'drop'):
        place = clean_place(d.get('place'))
        if not place:
            return jsonify({'error': 'place required'}), 400
        payload = {'place': place}
        if kind == 'drop':
            payload['teaser'] = str(d.get('teaser') or '')[:200]
            text = text or 'DROP 💧'
        else:
            text = text or f"Отправил(а) место: {place['title']}"
    else:
        file_url = d.get('file_url')
        if file_url:
            if not str(file_url).startswith('/uploads/chat_files/'):
                return jsonify({'error': 'bad file'}), 400
            file_type = str(d.get('file_type') or 'file')[:50]
            file_name = str(d.get('file_name') or '')[:255]
    if not text and not file_url:
        return jsonify({'error': 'empty message'}), 400
    return jsonify(create_message(current_user.id, rid, text=text, kind=kind, payload=payload,
                                  file_url=file_url, file_type=file_type, file_name=file_name))


# 🔹 ADDING A CITY FROM THE WEB


@app.route('/api/add-city', methods=['POST'])
@admin_required
def add_city():
    if not request.is_json:
        return jsonify({'error': 'Expected JSON'}), 400

    data = request.get_json(silent=True)
    name = data.get('name')
    slug = data.get('slug')

    if not name or not slug:
        return jsonify({'error': 'name and slug required'}), 400

    if City.query.filter_by(slug=slug).first():
        return jsonify({'error': 'city already exists'}), 400

    city = City(name=name, slug=slug)
    db.session.add(city)
    db.session.commit()

    return jsonify({'status': 'ok'})

# 🔹 SUGGESTIONS
@app.route('/api/suggest', methods=['POST'])
def suggest():
    if not request.is_json:
        return jsonify({'error': 'Expected JSON'}), 400

    data = request.get_json(silent=True)

    suggestion = Suggestion(
        type=data.get('type'),
        city=data.get('city'),
        title=data.get('title'),
        description=data.get('description'),
        themes=json.dumps(data.get('themes') or [], ensure_ascii=False),
        user_id=data.get('user_id'),
        nickname=data.get('nickname')
    )

    db.session.add(suggestion)
    db.session.commit()

    return jsonify({'status': 'ok'})

# 🔹 BRANCHES (chain locations with several addresses)
@app.route('/api/branches')
def get_branches():
    path = os.path.join(BASE_DIR, 'static', 'branches.json')
    try:
        with open(path, encoding='utf8') as f:
            groups = json.load(f)
    except Exception:
        return jsonify([])
    return jsonify([
        {
            'city': g['city'], 'title': g['title'], 'name': g.get('name', g['title']),
            'branches': [
                {'address': b['address'], 'note': b.get('note', ''), 'lat': b.get('lat'), 'lon': b.get('lon')}
                for b in g['branches']
            ],
        } for g in groups
    ])

# 🔹 CITIES
@app.route('/api/cities')
def get_cities():
    cities = City.query.all()
    return jsonify([{'name': c.name, 'slug': c.slug} for c in cities])

# 🔹 LOCATIONS
@app.route('/api/locations/<city_slug>')
def get_locations(city_slug):
    city = City.query.filter_by(slug=city_slug).first()
    if not city:
        return jsonify([])

    locations = Location.query.filter_by(city_id=city.id, approved=True).all()

    return jsonify([
        {
            'title': l.title,
            'desc': l.description or '',
            'themes': parse_themes(l.theme),
            'photos': parse_photos(l.photos, city_slug)
        } for l in locations
    ])

@app.route('/api/save_location/<int:location_id>', methods=['POST'])
@login_required
def save_location(location_id):
    location = Location.query.get(location_id)
    if not location:
        return jsonify({'error': 'Location not found'}), 404

    existing = SavedLocation.query.filter_by(user_id=current_user.id, location_id=location_id).first()
    if existing:
        return jsonify({'success': True, 'saved': True, 'message': 'Already saved'})

    saved = SavedLocation(user_id=current_user.id, location_id=location_id)
    db.session.add(saved)
    db.session.commit()
    return jsonify({'success': True, 'saved': True})

@app.route('/api/unsave_location/<int:location_id>', methods=['POST'])
@login_required
def unsave_location(location_id):
    saved = SavedLocation.query.filter_by(user_id=current_user.id, location_id=location_id).first()
    if saved:
        db.session.delete(saved)
        db.session.commit()
    return jsonify({'success': True, 'saved': False})

@app.route('/api/check_saved/<int:location_id>')
@login_required
def check_saved(location_id):
    saved = SavedLocation.query.filter_by(user_id=current_user.id, location_id=location_id).first()
    return jsonify({'saved': bool(saved)})

@app.route('/api/saved_locations')
@login_required
def get_saved_locations():
    saved = SavedLocation.query.filter_by(user_id=current_user.id).all()
    locations = []
    for s in saved:
        loc = s.location
        locations.append({
            'id': loc.id,
            'title': loc.title,
            'desc': loc.description or '',
            'city': loc.city.name,
            'themes': parse_themes(loc.theme),
            'photos': parse_photos(loc.photos, loc.city.slug if loc.city else None)
        })
    return jsonify(locations)

@app.route('/api/favorite_locations', methods=['GET'])
@login_required
def get_favorite_locations():
    favorites = FavoriteLocation.query.filter_by(user_id=current_user.id).all()
    return jsonify([f.title for f in favorites])

@app.route('/api/favorite_locations', methods=['POST'])
@login_required
def add_favorite_location():
    data = request.get_json(silent=True) or {}
    title = data.get('title')
    if not title:
        return jsonify({'error': 'title required'}), 400

    existing = FavoriteLocation.query.filter_by(user_id=current_user.id, title=title).first()
    if not existing:
        fav = FavoriteLocation(user_id=current_user.id, title=title)
        db.session.add(fav)
        db.session.commit()
    return jsonify({'success': True})

@app.route('/api/favorite_locations', methods=['DELETE'])
@login_required
def delete_favorite_location():
    data = request.get_json(silent=True) or {}
    title = data.get('title')
    if not title:
        return jsonify({'error': 'title required'}), 400

    existing = FavoriteLocation.query.filter_by(user_id=current_user.id, title=title).first()
    if existing:
        db.session.delete(existing)
        db.session.commit()
    return jsonify({'success': True})


@app.route('/api/search_users')
@login_required
def search_users():
    query = request.args.get('q', '').strip()
    if not query:
        return jsonify([])
    search_term = f'%{query}%'
    users = User.query.filter(
        User.id != current_user.id,
        or_(User.nickname.ilike(search_term), User.telegram_username.ilike(search_term)),
    ).limit(15).all()
    fids = friend_ids_of(current_user.id)
    pending = {r.receiver_id for r in FriendRequest.query.filter_by(sender_id=current_user.id, status='pending')}
    return jsonify([
        {'id': u.id, 'name': u.telegram_username or u.nickname, 'nickname': u.nickname,
         'avatar': f'/avatar/{u.id}' if u.avatar else None,
         'is_friend': u.id in fids, 'requested': u.id in pending}
        for u in users
    ])


@app.route('/api/friend_request', methods=['POST'])
@login_required
def friend_request():
    data = request.get_json(silent=True) or {}
    try:
        friend_id = int(data.get('friend_id'))
    except (TypeError, ValueError):
        return jsonify({'error': 'friend_id required'}), 400
    if friend_id == current_user.id:
        return jsonify({'error': 'cannot add yourself'}), 400
    if not User.query.get(friend_id):
        return jsonify({'error': 'user not found'}), 404
    reverse = FriendRequest.query.filter_by(sender_id=friend_id, receiver_id=current_user.id).first()
    if reverse:
        reverse.status = 'accepted'
        db.session.commit()
        return jsonify({'success': True, 'status': 'accepted'})
    existing = FriendRequest.query.filter_by(sender_id=current_user.id, receiver_id=friend_id).first()
    if not existing:
        existing = FriendRequest(sender_id=current_user.id, receiver_id=friend_id)
        db.session.add(existing)
        db.session.commit()
    return jsonify({'success': True, 'status': existing.status})


@app.route('/api/friends')
@login_required
def api_friends():
    fids = friend_ids_of(current_user.id)
    friends = User.query.filter(User.id.in_(fids)).order_by(User.nickname).all() if fids else []
    incoming = FriendRequest.query.filter_by(receiver_id=current_user.id, status='pending').all()
    outgoing = FriendRequest.query.filter_by(sender_id=current_user.id, status='pending').all()
    return jsonify({
        'friends': [user_brief(u) for u in friends],
        'incoming': [dict(user_brief(r.sender), request_id=r.id) for r in incoming],
        'outgoing': [r.receiver_id for r in outgoing],
    })


@app.route('/api/friend_request/respond', methods=['POST'])
@login_required
def friend_request_respond():
    data = request.get_json(silent=True) or {}
    req = FriendRequest.query.filter_by(id=data.get('request_id'), receiver_id=current_user.id, status='pending').first()
    if not req:
        return jsonify({'error': 'request not found'}), 404
    if data.get('accept'):
        req.status = 'accepted'
    else:
        db.session.delete(req)
    db.session.commit()
    return jsonify({'success': True})


@app.route('/api/friends/<int:friend_id>', methods=['DELETE'])
@login_required
def api_unfriend(friend_id):
    FriendRequest.query.filter(
        or_(
            (FriendRequest.sender_id == current_user.id) & (FriendRequest.receiver_id == friend_id),
            (FriendRequest.sender_id == friend_id) & (FriendRequest.receiver_id == current_user.id),
        )
    ).delete(synchronize_session=False)
    db.session.commit()
    return jsonify({'success': True})


@app.route('/api/chat_list')
@login_required
def get_chat_list():
    uid = current_user.id
    msgs = PrivateMessage.query.filter(
        or_(PrivateMessage.sender_id == uid, PrivateMessage.receiver_id == uid)
    ).order_by(PrivateMessage.id.desc()).all()
    chats, unread = {}, {}
    for m in msgs:
        other = m.receiver_id if m.sender_id == uid else m.sender_id
        if m.receiver_id == uid and m.is_read is False:
            unread[other] = unread.get(other, 0) + 1
        if other not in chats:
            chats[other] = m
    users = {u.id: u for u in User.query.filter(User.id.in_(list(chats))).all()} if chats else {}
    result = []
    for other, m in chats.items():
        u = users.get(other)
        if not u:
            continue
        result.append({
            'id': u.id, 'nickname': u.nickname, 'avatar': f'/avatar/{u.id}' if u.avatar else None,
            'last_message': message_preview(m), 'last_message_time': iso(m.created_at),
            'has_file': bool(m.file_url), 'unread': unread.get(other, 0), 'last_id': m.id,
        })
    result.sort(key=lambda x: x['last_id'], reverse=True)
    return jsonify(result)


@app.route('/api/unread_count')
@login_required
def unread_count():
    n = PrivateMessage.query.filter_by(receiver_id=current_user.id, is_read=False).count()
    return jsonify({'unread': n})


@app.route('/api/messages/<int:user_id>')
@login_required
def get_messages(user_id):
    after = request.args.get('after', type=int, default=0)
    messages = PrivateMessage.query.filter(
        ((PrivateMessage.sender_id == current_user.id) & (PrivateMessage.receiver_id == user_id)) |
        ((PrivateMessage.sender_id == user_id) & (PrivateMessage.receiver_id == current_user.id)),
        PrivateMessage.id > after,
    ).order_by(PrivateMessage.id).all()
    unread = [m for m in messages if m.receiver_id == current_user.id and m.is_read is False]
    for m in unread:
        m.is_read = True
    if unread:
        db.session.commit()
    return jsonify([serialize_message(m) for m in messages])




@app.route('/api/suggest/photos', methods=['POST'])
def photo_suggest():
    files = request.files.getlist('photos')
    location = request.form.get('location')
    city = request.form.get('city')
    user_id = request.form.get('user_id')

    if not files or not location or not city or not user_id:
        return jsonify({'error': 'photos, location, city and user_id required'}), 400

    photos_dir = os.path.join(BASE_DIR, 'uploads', 'photos_pending')
    os.makedirs(photos_dir, exist_ok=True)

    for file in files:
        if file and file.filename:
            ext = os.path.splitext(file.filename)[1] or '.jpg'
            filename = f"{user_id}_{int(time.time())}_{uuid.uuid4().hex}{ext}"
            file.save(os.path.join(photos_dir, filename))

            photo = SuggestionPhoto(
                location_title=location,
                city=city,
                filename=filename,
                user_id=user_id,
                status='pending'
            )
            db.session.add(photo)

    db.session.commit()
    return jsonify({'success': True})


@app.route('/api/upload_file', methods=['POST'])
@login_required
def upload_file():
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400
    file = request.files['file']
    if not file or file.filename == '':
        return jsonify({'error': 'No selected file'}), 400
    file.stream.seek(0, os.SEEK_END)
    if file.stream.tell() > 50 * 1024 * 1024:
        return jsonify({'error': 'Файл больше 50 МБ'}), 400
    file.stream.seek(0)

    uploads_dir = os.path.join(BASE_DIR, 'uploads', 'chat_files')
    os.makedirs(uploads_dir, exist_ok=True)
    original = file.filename
    safe = secure_filename(original) or 'file'
    filename = f"{current_user.id}_{int(time.time())}_{uuid.uuid4().hex[:8]}_{safe}"
    file.save(os.path.join(uploads_dir, filename))
    ext = os.path.splitext(filename)[1].lower().lstrip('.')
    file_type = 'image' if ALLOWED_MEDIA.get(ext) == 'image' else 'file'
    return jsonify({
        'success': True, 'file_url': f'/uploads/chat_files/{filename}',
        'file_type': file_type, 'file_name': original,
    })


@app.route('/uploads/<path:filename>')
def uploaded_file(filename):
    ext = os.path.splitext(filename)[1].lower().lstrip('.')
    resp = send_from_directory(app.config['UPLOAD_FOLDER'], filename)
    resp.headers['X-Content-Type-Options'] = 'nosniff'
    if ext not in ALLOWED_MEDIA:  # never let the browser render uploaded html/svg/js
        resp.headers['Content-Disposition'] = 'attachment'
    return resp



# ===== REVIEWS =====
def serialize_review(r, uid=None):
    try:
        media = json.loads(r.media or '[]')
    except Exception:
        media = []
    return {
        'id': r.id, 'user': user_brief(r.user), 'rating': r.rating, 'text': r.text or '',
        'media': media, 'created_at': iso(r.created_at), 'mine': uid is not None and r.user_id == uid,
    }


@app.route('/api/reviews')
def api_reviews():
    key = (request.args.get('place_key') or '').strip()
    rows = Review.query.filter_by(place_key=key).order_by(Review.created_at.desc()).all()
    uid = current_user.id if current_user.is_authenticated else None
    avg = round(sum(r.rating for r in rows) / len(rows), 1) if rows else None
    return jsonify({'avg': avg, 'count': len(rows), 'reviews': [serialize_review(r, uid) for r in rows]})


@app.route('/api/reviews', methods=['POST'])
@login_required
def api_review_save():
    key = (request.form.get('place_key') or '').strip()[:300]
    if not key:
        return jsonify({'error': 'place_key required'}), 400
    try:
        rating = int(request.form.get('rating'))
    except (TypeError, ValueError):
        return jsonify({'error': 'Поставьте оценку от 1 до 10'}), 400
    if not 1 <= rating <= 10:
        return jsonify({'error': 'Оценка от 1 до 10'}), 400
    text = (request.form.get('text') or '').strip()[:2000]

    new_media = []
    for f in request.files.getlist('media')[:4]:
        if f and f.filename:
            item, err = save_upload(f, 'reviews')
            if err:
                for m in new_media:
                    remove_uploaded(m['url'])
                return jsonify({'error': err}), 400
            new_media.append(item)

    review = Review.query.filter_by(user_id=current_user.id, place_key=key).first()
    if review:
        review.rating = rating
        review.text = text
        if new_media or request.form.get('remove_media') == '1':
            try:
                for m in json.loads(review.media or '[]'):
                    remove_uploaded(m.get('url'))
            except Exception:
                pass
            review.media = json.dumps(new_media)
    else:
        review = Review(user_id=current_user.id, place_key=key, rating=rating, text=text,
                        media=json.dumps(new_media))
        db.session.add(review)
    db.session.commit()
    return jsonify({'success': True, 'review': serialize_review(review, current_user.id)})


@app.route('/api/reviews/<int:rid>', methods=['DELETE'])
@login_required
def api_review_delete(rid):
    r = Review.query.get_or_404(rid)
    if r.user_id != current_user.id and not is_admin_user():
        abort(403)
    try:
        for m in json.loads(r.media or '[]'):
            remove_uploaded(m.get('url'))
    except Exception:
        pass
    db.session.delete(r)
    db.session.commit()
    return jsonify({'success': True})


# ===== COLLECTIONS =====
PRIVACY = ('public', 'private', 'friends')


def can_edit_collection(c, user):
    if not user:
        return False
    if c.owner_id == user.id:
        return True
    return bool(c.collaborative and any(m.user_id == user.id and m.status == 'member' for m in c.members))


def can_view_collection(c, user):
    if c.privacy == 'public':
        return True
    if not user:
        return False
    if c.owner_id == user.id or any(m.user_id == user.id for m in c.members) \
            or any(s.user_id == user.id for s in c.shares):
        return True
    return c.privacy == 'friends' and are_friends(c.owner_id, user.id)


def _cur_user():
    return current_user if current_user.is_authenticated else None


def serialize_item(i):
    return {'place_key': i.place_key, 'title': i.title, 'city': i.city, 'desc': i.description or '',
            'photo': i.photo or '', 'lat': i.lat, 'lon': i.lon}


def serialize_collection(c, full=False):
    user = _cur_user()
    d = {
        'id': c.id, 'title': c.title, 'description': c.description or '', 'privacy': c.privacy,
        'collaborative': bool(c.collaborative), 'token': c.token, 'url': f'/c/{c.token}',
        'owner': user_brief(c.owner), 'count': len(c.items),
        'cover': next((i.photo for i in c.items if i.photo), None),
        'is_owner': bool(user and user.id == c.owner_id), 'can_edit': can_edit_collection(c, user),
    }
    if full:
        d['items'] = [serialize_item(i) for i in c.items]
        d['members'] = [{'user': user_brief(m.user), 'status': m.status} for m in c.members]
    return d


@app.route('/api/collections')
@login_required
def api_collections():
    uid = current_user.id
    key = request.args.get('place_key')

    def pack(c):
        d = serialize_collection(c)
        if key:
            d['has'] = any(i.place_key == key for i in c.items)
        return d

    mine = Collection.query.filter_by(owner_id=uid).order_by(Collection.created_at.desc()).all()
    joined, invited = [], []
    for m in CollectionMember.query.filter_by(user_id=uid).all():
        (joined if m.status == 'member' else invited).append(m.collection)
    return jsonify({'mine': [pack(c) for c in mine], 'joined': [pack(c) for c in joined],
                    'invited': [serialize_collection(c) for c in invited]})


@app.route('/api/collections/saved')
@login_required
def api_collections_saved():
    """Place keys/titles the user has put into any of his collections (for the star icons)."""
    uid = current_user.id
    cols = Collection.query.filter_by(owner_id=uid).all()
    cols += [m.collection for m in CollectionMember.query.filter_by(user_id=uid, status='member')]
    keys, titles = set(), set()
    for c in cols:
        for i in c.items:
            keys.add(i.place_key)
            titles.add(i.title)
    return jsonify({'keys': sorted(keys), 'titles': sorted(titles)})


@app.route('/api/collections/public')
def api_collections_public():
    cols = Collection.query.filter_by(privacy='public').order_by(Collection.created_at.desc()).limit(60).all()
    return jsonify([serialize_collection(c) for c in cols if c.items])


@app.route('/api/collections', methods=['POST'])
@login_required
def api_collection_create():
    d = request.get_json(silent=True) or {}
    title = str(d.get('title') or '').strip()[:120]
    if not title:
        return jsonify({'error': 'Введите название'}), 400
    privacy = d.get('privacy') if d.get('privacy') in PRIVACY else 'private'
    c = Collection(owner_id=current_user.id, title=title, description=str(d.get('description') or '')[:500],
                   privacy=privacy, collaborative=bool(d.get('collaborative')))
    db.session.add(c)
    db.session.commit()
    return jsonify({'success': True, 'collection': serialize_collection(c)})


@app.route('/api/collections/<int:cid>')
def api_collection_get(cid):
    c = Collection.query.get_or_404(cid)
    if not can_view_collection(c, _cur_user()):
        abort(403)
    return jsonify(serialize_collection(c, full=True))


@app.route('/api/collections/<int:cid>', methods=['PATCH'])
@login_required
def api_collection_update(cid):
    c = Collection.query.get_or_404(cid)
    if c.owner_id != current_user.id:
        abort(403)
    d = request.get_json(silent=True) or {}
    if 'title' in d:
        title = str(d['title']).strip()[:120]
        if not title:
            return jsonify({'error': 'Введите название'}), 400
        c.title = title
    if 'description' in d:
        c.description = str(d['description'] or '')[:500]
    if d.get('privacy') in PRIVACY:
        c.privacy = d['privacy']
    if 'collaborative' in d:
        c.collaborative = bool(d['collaborative'])
    if d.get('reset_link'):
        c.token = uuid.uuid4().hex
    db.session.commit()
    return jsonify({'success': True, 'collection': serialize_collection(c, full=True)})


@app.route('/api/collections/<int:cid>', methods=['DELETE'])
@login_required
def api_collection_delete(cid):
    c = Collection.query.get_or_404(cid)
    if c.owner_id != current_user.id:
        abort(403)
    db.session.delete(c)
    db.session.commit()
    return jsonify({'success': True})


@app.route('/api/collections/<int:cid>/items', methods=['POST'])
@login_required
def api_collection_add_item(cid):
    c = Collection.query.get_or_404(cid)
    if not can_edit_collection(c, current_user):
        abort(403)
    d = request.get_json(silent=True) or {}
    place = clean_place(d.get('place'))
    if not place:
        return jsonify({'error': 'place required'}), 400
    if not any(i.place_key == place['key'] for i in c.items):
        db.session.add(CollectionItem(
            collection_id=c.id, place_key=place['key'], title=place['title'], city=place['city'],
            description=place['desc'], photo=place['photo'], lat=place['lat'], lon=place['lon'],
            added_by=current_user.id))
        db.session.commit()
    return jsonify({'success': True, 'count': len(c.items)})


@app.route('/api/collections/<int:cid>/items', methods=['DELETE'])
@login_required
def api_collection_remove_item(cid):
    c = Collection.query.get_or_404(cid)
    if not can_edit_collection(c, current_user):
        abort(403)
    key = str((request.get_json(silent=True) or {}).get('place_key') or '')
    item = CollectionItem.query.filter_by(collection_id=c.id, place_key=key).first()
    if item:
        db.session.delete(item)
        db.session.commit()
    return jsonify({'success': True, 'count': len(c.items)})


@app.route('/api/collections/<int:cid>/invite', methods=['POST'])
@login_required
def api_collection_invite(cid):
    c = Collection.query.get_or_404(cid)
    if c.owner_id != current_user.id:
        abort(403)
    try:
        uid = int((request.get_json(silent=True) or {}).get('user_id'))
    except (TypeError, ValueError):
        return jsonify({'error': 'user_id required'}), 400
    if uid not in friend_ids_of(current_user.id):
        return jsonify({'error': 'Приглашать в совместную подборку можно только друзей'}), 400
    c.collaborative = True
    member = CollectionMember.query.filter_by(collection_id=c.id, user_id=uid).first()
    if not member:
        db.session.add(CollectionMember(collection_id=c.id, user_id=uid, status='invited'))
    db.session.commit()
    create_message(current_user.id, uid, text=f'Приглашает в совместную подборку «{c.title}»', kind='collab_invite',
                   payload={'collection_id': c.id, 'title': c.title, 'owner': current_user.nickname})
    return jsonify({'success': True})


@app.route('/api/collections/<int:cid>/respond', methods=['POST'])
@login_required
def api_collection_respond(cid):
    member = CollectionMember.query.filter_by(collection_id=cid, user_id=current_user.id).first_or_404()
    if (request.get_json(silent=True) or {}).get('accept'):
        member.status = 'member'
    else:
        db.session.delete(member)
    db.session.commit()
    return jsonify({'success': True})


@app.route('/api/collections/<int:cid>/send', methods=['POST'])
@login_required
def api_collection_send(cid):
    c = Collection.query.get_or_404(cid)
    if not can_view_collection(c, current_user):
        abort(403)
    ids = [int(x) for x in ((request.get_json(silent=True) or {}).get('receiver_ids') or []) if str(x).isdigit()][:30]
    sent = 0
    for rid in dict.fromkeys(ids):
        if rid == current_user.id or not User.query.get(rid):
            continue
        # owner/editors may grant access to a non-public collection by sending it
        if c.privacy != 'public' and can_edit_collection(c, current_user) \
                and not CollectionShare.query.filter_by(collection_id=c.id, user_id=rid).first():
            db.session.add(CollectionShare(collection_id=c.id, user_id=rid))
            db.session.commit()
        create_message(current_user.id, rid, text=f'Коллекция «{c.title}»', kind='collection', payload={
            'id': c.id, 'token': c.token, 'title': c.title, 'description': c.description or '',
            'count': len(c.items), 'cover': next((i.photo for i in c.items if i.photo), None),
            'owner': c.owner.nickname})
        sent += 1
    return jsonify({'success': True, 'sent': sent})


@app.route('/collections')
@login_required
def collections_page():
    return render_template('collections.html')


@app.route('/c/<token>')
def public_collection(token):
    c = Collection.query.filter_by(token=token).first_or_404()
    viewer = _cur_user()
    allowed = can_view_collection(c, viewer)
    return render_template(
        'collection_public.html', c=c, items=c.items if allowed else [], allowed=allowed,
        reason=('friends' if c.privacy == 'friends' else 'private') if not allowed else None,
        viewer=viewer, share_url=request.url_root.rstrip('/') + f'/c/{c.token}',
        pts=[{'lat': i.lat, 'lon': i.lon, 'title': i.title} for i in (c.items if allowed else []) if i.lat and i.lon])


# ===== PLANS / LET'S GO =====
@app.route('/api/letsgo', methods=['POST'])
@login_required
def api_letsgo():
    d = request.get_json(silent=True) or {}
    place = clean_place(d.get('place'))
    if not place:
        return jsonify({'error': 'place required'}), 400
    ids = [int(x) for x in (d.get('friend_ids') or []) if str(x).isdigit()][:30]
    if not ids:
        return jsonify({'error': 'Выберите друзей'}), 400
    friends = friend_ids_of(current_user.id)
    ids = [i for i in dict.fromkeys(ids) if i in friends]
    if not ids:
        return jsonify({'error': "Let's Go можно предложить только друзьям. Сначала добавьте друзей."}), 400
    when = str(d.get('when') or '')[:40]
    note = str(d.get('note') or '')[:500]
    plan = Plan(creator_id=current_user.id, place_key=place['key'], title=place['title'], city=place['city'],
                photo=place['photo'], when_text=when, note=note)
    db.session.add(plan)
    db.session.flush()
    for i in ids:
        db.session.add(PlanInvite(plan_id=plan.id, user_id=i))
    db.session.commit()
    for i in ids:
        create_message(current_user.id, i, text=f"Let's Go: {place['title']}", kind='plan', payload={
            'plan_id': plan.id, 'place': place, 'when': when, 'note': note,
            'creator': current_user.nickname, 'letsgo': True})
    return jsonify({'success': True, 'plan_id': plan.id, 'sent': len(ids)})


def _plan_dict(plan, uid):
    return {
        'id': plan.id, 'title': plan.title, 'city': plan.city, 'photo': plan.photo, 'when': plan.when_text,
        'note': plan.note, 'creator': user_brief(plan.creator),
        'invites': [{'user': user_brief(i.user), 'status': i.status} for i in plan.invites],
        'my_status': next((i.status for i in plan.invites if i.user_id == uid), None),
    }


@app.route('/api/plans/<int:pid>')
@login_required
def api_plan_get(pid):
    plan = Plan.query.get_or_404(pid)
    if plan.creator_id != current_user.id and not any(i.user_id == current_user.id for i in plan.invites):
        abort(403)
    return jsonify(_plan_dict(plan, current_user.id))


@app.route('/api/plans/<int:pid>/respond', methods=['POST'])
@login_required
def api_plan_respond(pid):
    plan = Plan.query.get_or_404(pid)
    status = (request.get_json(silent=True) or {}).get('status')
    if status not in ('going', 'maybe', 'declined'):
        return jsonify({'error': 'bad status'}), 400
    inv = PlanInvite.query.filter_by(plan_id=pid, user_id=current_user.id).first_or_404()
    inv.status = status
    db.session.commit()
    label = {'going': '✓', 'maybe': '?', 'declined': '✕'}[status]
    create_message(current_user.id, plan.creator_id, text=f'{label}: {plan.title}', kind='plan_reply',
                   payload={'plan_id': plan.id, 'status': status, 'title': plan.title})
    return jsonify({'success': True, 'plan': _plan_dict(plan, current_user.id)})




# ===== MODERATION =====
@app.route('/moderation')
@admin_required
def moderation():
    return render_template('admin.html')

@app.route('/api/admin/suggested-cities')
@admin_required
def admin_suggested_cities():
    items = Suggestion.query.filter_by(type='city').order_by(Suggestion.created_at).all()
    return jsonify([{'id': s.id, 'name': s.city, 'user_nickname': s.nickname or ''} for s in items])

@app.route('/api/admin/suggested-places')
@admin_required
def admin_suggested_places():
    items = Suggestion.query.filter_by(type='place').order_by(Suggestion.created_at).all()
    return jsonify([{'id': s.id, 'title': s.title, 'city': s.city, 'description': s.description or '',
                     'user_nickname': s.nickname or ''} for s in items])

@app.route('/api/admin/approve-city/<int:sid>', methods=['POST'])
@admin_required
def admin_approve_city(sid):
    s = Suggestion.query.filter_by(id=sid, type='city').first_or_404()
    name = (s.city or '').strip()
    slug = slugify(name)
    if name and not City.query.filter_by(slug=slug).first():
        db.session.add(City(name=name, slug=slug))
    db.session.delete(s)
    db.session.commit()
    return jsonify({'success': True})

@app.route('/api/admin/reject-city/<int:sid>', methods=['POST'])
@admin_required
def admin_reject_city(sid):
    s = Suggestion.query.filter_by(id=sid, type='city').first_or_404()
    db.session.delete(s)
    db.session.commit()
    return jsonify({'success': True})

@app.route('/api/admin/approve-place/<int:sid>', methods=['POST'])
@admin_required
def admin_approve_place(sid):
    s = Suggestion.query.filter_by(id=sid, type='place').first_or_404()
    city = City.query.filter_by(slug=(s.city or '').strip()).first() or City.query.filter_by(name=(s.city or '').strip()).first()
    if not city:
        name = (s.city or '').strip()
        if not name:
            return jsonify({'success': False, 'error': 'city not found'}), 400
        base = slugify(name) or 'city'
        slug, n = base, 2
        while City.query.filter_by(slug=slug).first():
            slug, n = f'{base}-{n}', n + 1
        city = City(name=name, slug=slug)
        db.session.add(city)
        db.session.flush()

    photos = []
    pending = SuggestionPhoto.query.filter_by(location_title=s.title, city=s.city, status='pending').all()
    if pending:
        dest = os.path.join(BASE_DIR, 'static', 'photos', city.slug)
        os.makedirs(dest, exist_ok=True)
        for p in pending:
            src = os.path.join(BASE_DIR, 'uploads', 'photos_pending', p.filename)
            if os.path.exists(src):
                fname = secure_filename(p.filename)
                shutil.move(src, os.path.join(dest, fname))
                photos.append(f'/static/photos/{city.slug}/{fname}')
            p.status = 'approved'

    db.session.add(Location(
        title=s.title, description=s.description, city_id=city.id,
        theme=s.themes or json.dumps([]), photos=json.dumps(photos), approved=True))
    db.session.delete(s)
    db.session.commit()
    return jsonify({'success': True})

@app.route('/api/admin/reject-place/<int:sid>', methods=['POST'])
@admin_required
def admin_reject_place(sid):
    s = Suggestion.query.filter_by(id=sid, type='place').first_or_404()
    for p in SuggestionPhoto.query.filter_by(location_title=s.title, city=s.city, status='pending').all():
        path = os.path.join(BASE_DIR, 'uploads', 'photos_pending', p.filename)
        if os.path.exists(path):
            os.remove(path)
        p.status = 'rejected'
    db.session.delete(s)
    db.session.commit()
    return jsonify({'success': True})

# ===== SITE =====
@app.route("/")
@login_required
def index():
    return render_template("index.html")

@app.route("/profile")
@login_required
def profile():
    return render_template("profile.html")

@app.route("/login", methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if current_user.is_authenticated:
            logout_user()

        nickname = request.form.get('nickname', '').strip()
        user = User.query.filter_by(nickname=nickname).first()
        if user:
            login_user(user)
            session.permanent = True
            next_page = request.args.get('next')
            return redirect(next_page) if next_page else redirect(url_for('index'))
        return render_template("login.html", error="Nickname not found")
    return render_template("login.html")

@app.route("/register", methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    if request.method == 'POST':
        nickname = request.form.get('nickname', '').strip()

        if not nickname:
            return render_template('register.html', error='Nickname is required')

        if User.query.filter_by(nickname=nickname).first():
            return render_template('register.html', error='Nickname already in use')

        user = User(
            telegram_username=None,
            nickname=nickname,
            is_confirmed=True
        )
        db.session.add(user)
        db.session.commit()

        login_user(user)
        session.permanent = True
        return redirect(url_for('index'))

    return render_template('register.html')

@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route("/delete-account", methods=["POST"])
@login_required
def delete_account():
    user_id = current_user.id
    logout_user()

    PrivateMessage.query.filter(
        (PrivateMessage.sender_id == user_id) | (PrivateMessage.receiver_id == user_id)
    ).delete(synchronize_session=False)
    User.query.filter_by(id=user_id).delete(synchronize_session=False)
    db.session.commit()
    return redirect(url_for('register'))

@app.route("/update-profile", methods=["POST"])
@login_required
def update_profile():
    data = request.get_json(silent=True) or {}
    nickname = data.get('nickname')
    avatar = data.get('avatar')

    if nickname is not None:
        nickname = nickname.strip()
        if not nickname:
            return jsonify({"success": False, "error": "Nickname cannot be empty"}), 400

        existing = User.query.filter(
            User.nickname == nickname,
            User.id != current_user.id,
        ).first()
        if existing:
            return jsonify({"success": False, "error": "Nickname already in use"}), 400

        current_user.nickname = nickname

    if avatar is not None:
        current_user.avatar = avatar

    db.session.commit()
    return jsonify({
        "success": True,
        "nickname": current_user.nickname,
        "avatar": current_user.avatar,
    })

def migrate_user_verification_schema():
    with db.engine.begin() as conn:
        if conn.engine.url.drivername.startswith('sqlite'):
            existing = {r[1] for r in conn.execute(text('PRAGMA table_info("user")')).fetchall()}
            if 'is_confirmed' not in existing:
                conn.execute(text('ALTER TABLE "user" ADD COLUMN is_confirmed BOOLEAN DEFAULT 0'))
            if 'verification_code' not in existing:
                conn.execute(text('ALTER TABLE "user" ADD COLUMN verification_code VARCHAR(6)'))
            if 'verification_expires' not in existing:
                conn.execute(text('ALTER TABLE "user" ADD COLUMN verification_expires DATETIME'))
            if 'avatar' not in existing:
                conn.execute(text('ALTER TABLE "user" ADD COLUMN avatar TEXT'))
            if 'telegram_username' not in existing:
                conn.execute(text('ALTER TABLE "user" ADD COLUMN telegram_username VARCHAR(120)'))
            if 'telegram_id' not in existing:
                conn.execute(text('ALTER TABLE "user" ADD COLUMN telegram_id VARCHAR(50)'))

            sg_existing = {r[1] for r in conn.execute(text('PRAGMA table_info("suggestion")')).fetchall()}
            if sg_existing and 'themes' not in sg_existing:
                conn.execute(text('ALTER TABLE "suggestion" ADD COLUMN themes TEXT'))

            # Migration for PrivateMessage
            pm_existing = {r[1] for r in conn.execute(text('PRAGMA table_info("private_message")')).fetchall()}
            if 'file_url' not in pm_existing:
                conn.execute(text('ALTER TABLE "private_message" ADD COLUMN file_url VARCHAR(500)'))
            if 'file_type' not in pm_existing:
                conn.execute(text('ALTER TABLE "private_message" ADD COLUMN file_type VARCHAR(50)'))
            if 'file_name' not in pm_existing:
                conn.execute(text('ALTER TABLE "private_message" ADD COLUMN file_name VARCHAR(255)'))
            if 'location' not in pm_existing:
                conn.execute(text('ALTER TABLE "private_message" ADD COLUMN location TEXT'))
            if 'kind' not in pm_existing:
                conn.execute(text('ALTER TABLE "private_message" ADD COLUMN kind VARCHAR(20) DEFAULT \'text\''))
            if 'payload' not in pm_existing:
                conn.execute(text('ALTER TABLE "private_message" ADD COLUMN payload TEXT'))
            if 'is_read' not in pm_existing:
                conn.execute(text('ALTER TABLE "private_message" ADD COLUMN is_read BOOLEAN DEFAULT 1'))


@app.route("/chats")
@login_required
def chats():
    return render_template("chats.html")

# ===== RUN =====
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))  
    
    with app.app_context():
        db.create_all()
        print("[OK] Database is ready")
        
        # Add Moscow if not exists
        moscow = City.query.filter_by(slug='moscow').first()
        if not moscow:
            moscow = City(name='Москва', slug='moscow')
            db.session.add(moscow)
            db.session.commit()

        # Add Saint Petersburg if not exists
        spb = City.query.filter_by(slug='spb').first()
        if not spb:
            spb = City(name='Санкт-Петербург', slug='spb')
            db.session.add(spb)
            db.session.commit()

        # Add Novosibirsk if not exists
        novosibirsk = City.query.filter_by(slug='novosibirsk').first()
        if not novosibirsk:
            novosibirsk = City(name='Новосибирск', slug='novosibirsk')
            db.session.add(novosibirsk)
            db.session.commit()
        
        # Add Moscow locations if not exist
        locations_data = [
            {
                'title': 'Хлебзавод',
                'description': 'Креативное пространство на территории бывшего хлебозавода.',
                'theme': 'culture',
                'photos': 'hlebz1.jpg,hlebz2.jpg,hlebz3.jpg,hlebz4.jpg',
                'city_id': moscow.id
            },
            {
                'title': 'Naberezhnye',
                'description': 'Современный комплекс на набережной.',
                'theme': 'leisure',
                'photos': 'nabber1.jpg,nabber2.jpg,nabber3.jpg,nabber4.jpg,nabber5.jpg,nabber6.jpg,nabber7.png,nabber8.jpg,nabber9.jpg',
                'city_id': moscow.id
            },
            {
                'title': 'Завод Арма',
                'description': 'Адрес: Нижний Сусальный переулок, 5 (метро «Курская», «Чкаловская»)',
                'theme': 'industrial',
                'photos': 'arma1.jpg,arma2.jpg,arma3.jpg',
                'city_id': moscow.id
            },
            {
                'title': 'Humbl Cookies',
                'description': 'Уютная кофейня с выпечкой и печеньем ручной работы в Петербурге.',
                'theme': 'food',
                'photos': '',
                'city_id': spb.id
            },
            {
                'title': 'The Buddy Cafe',
                'description': 'Небольшое кафе в Петербурге с атмосферой для встреч и лёгких закусок.',
                'theme': 'food',
                'photos': '',
                'city_id': spb.id
            },
            {
                'title': 'Nobody Knows i Suppose',
                'description': 'Атмосферный бар в Новосибирске с нишевой концепцией и авторской музыкой.',
                'theme': json.dumps(['нишевые', 'бары']),
                'photos': json.dumps(['/static/photos/novosibirsk/restDv4.jpg']),
                'city_id': novosibirsk.id
            }
        ]
        
        for loc_data in locations_data:
            location = Location.query.filter_by(title=loc_data['title'], city_id=loc_data['city_id']).first()
            if not location:
                location = Location(
                    title=loc_data['title'],
                    description=loc_data['description'],
                    city_id=loc_data['city_id'],
                    theme=loc_data['theme'],
                    photos=loc_data['photos'],
                    approved=True
                )
                db.session.add(location)
        db.session.commit()
        
        print("Cities:", City.query.count())
        migrate_user_verification_schema() 

    # Look up coordinates for branch addresses in the background (needs internet, ~2 min, once)
    try:
        import geocoder
        geocoder.run_in_background()
    except Exception as exc:
        print('[GEOCODER] not started:', exc)

    print(f"[SERVER] http://0.0.0.0:{port}/")
    print(f"[ADMIN] http://0.0.0.0:{port}/admin/")

    socketio.run(app, host="0.0.0.0", port=port, debug=True)
